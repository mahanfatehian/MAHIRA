from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any

from core import fsrs


@dataclass(frozen=True)
class SchedulerTuning:
    """Learner-controlled knobs applied on top of the pure FSRS model.

    The defaults reproduce MAHIRA's original behaviour exactly, so a caller
    that passes no tuning (tests, previews, legacy paths) schedules the same
    intervals it always did.
    """

    target_retention: float = fsrs.DEFAULT_REQUEST_RETENTION
    interval_fuzz: bool = True


DEFAULT_TUNING = SchedulerTuning()

# Fields the state classes use for their primary key. Vocab/grammar/sentence/
# listening states each name theirs differently.
_ID_FIELDS = ("vocab_id", "grammar_id", "sentence_id", "listening_id", "id")


def _item_key(state: Any) -> int:
    """A stable per-item number, so two cards never share the same fuzz."""
    key = 0
    for name in _ID_FIELDS:
        value = getattr(state, name, None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            key = value
            break
    mode = getattr(state, "practice_mode", None)
    if isinstance(mode, str) and mode:
        # Production and dictation share a vocab_id but schedule independently,
        # so they must not receive identical fuzz.
        key = key * 31 + (sum(ord(ch) for ch in mode) % 97)
    return key


def tuning_from_settings(value: Any) -> SchedulerTuning:
    """Build tuning from an AppSettings-like object.

    Tolerates None and partially-populated objects so the scheduler keeps
    working when settings are unavailable (e.g. during migration or in tests).
    """
    if value is None:
        return DEFAULT_TUNING
    try:
        retention = float(
            getattr(value, "target_retention", DEFAULT_TUNING.target_retention)
        )
    except (TypeError, ValueError):
        retention = DEFAULT_TUNING.target_retention
    fuzz = getattr(value, "interval_fuzz", DEFAULT_TUNING.interval_fuzz)
    return SchedulerTuning(
        target_retention=retention,
        interval_fuzz=bool(fuzz),
    )


def schedule_next(
    state: Any,
    rating: int,
    *,
    now: int | None = None,
    tuning: SchedulerTuning | None = None,
) -> Any:
    """
    Advance an SRS state by one review using the FSRS-4.5 memory model.

    Works for any of the three frozen state dataclasses (VocabState /
    GrammarState / SentenceState) -- they share the scheduling fields
    (ease, interval_days, reps, lapses, due_at, last_review_at, stability,
    difficulty), so a single scheduler keeps vocab, grammar and sentences on
    identical, correct logic.

    rating: 0=Again, 1=Hard, 2=Good, 3=Easy

    The returned state carries the updated FSRS stability/difficulty (the real
    drivers) plus a derived `ease` and `interval_days` so legacy readers keep
    working. On Again the item re-enters a 10-minute relearning step.
    """
    now = int(time.time()) if now is None else int(now)
    tuning = DEFAULT_TUNING if tuning is None else tuning

    last_review_at = getattr(state, "last_review_at", None)
    elapsed_days = 0.0
    if last_review_at:
        elapsed_days = max(0.0, (now - float(last_review_at)) / 86400.0)

    # Pull the current memory model, lazily migrating legacy items that predate
    # the FSRS upgrade (stability/difficulty not yet recorded).
    stability = getattr(state, "stability", None)
    difficulty = getattr(state, "difficulty", None)
    reps = int(getattr(state, "reps", 0) or 0)

    if stability is None:
        stability = fsrs.stability_from_interval(getattr(state, "interval_days", 0.0), reps)
    if difficulty is None and reps > 0:
        difficulty = fsrs.difficulty_from_ease(getattr(state, "ease", 2.5))

    result = fsrs.schedule(
        rating=rating,
        stability=stability,
        difficulty=difficulty,
        elapsed_days=elapsed_days,
        request_retention=tuning.target_retention,
    )

    is_again = int(rating) <= 0
    lapses = int(getattr(state, "lapses", 0) or 0) + (1 if is_again else 0)
    new_reps = reps + 1  # monotonic review counter; reps > 0 means "seen"

    interval = float(result.interval_days)
    due_in_seconds = int(result.due_in_seconds)
    # interval_days == 0 is the relearning step, which must stay exact.
    if interval > 0.0 and tuning.interval_fuzz:
        interval = fsrs.apply_fuzz(
            interval,
            seed=_item_key(state) * 7919 + int(rating) * 31 + new_reps,
        )
        interval = max(1.0, interval)
        due_in_seconds = int(round(interval * fsrs.SECONDS_PER_DAY))

    return replace(
        state,
        ease=fsrs.ease_from_difficulty(result.difficulty),
        interval_days=interval,
        reps=new_reps,
        lapses=lapses,
        due_at=now + due_in_seconds,
        last_review_at=now,
        stability=float(result.stability),
        difficulty=float(result.difficulty),
    )
