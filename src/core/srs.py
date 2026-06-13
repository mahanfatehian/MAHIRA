from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from core import fsrs


def schedule_next(state: Any, rating: int, *, now: int | None = None) -> Any:
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
    )

    is_again = int(rating) <= 0
    lapses = int(getattr(state, "lapses", 0) or 0) + (1 if is_again else 0)
    new_reps = reps + 1  # monotonic review counter; reps > 0 means "seen"

    return replace(
        state,
        ease=fsrs.ease_from_difficulty(result.difficulty),
        interval_days=float(result.interval_days),
        reps=new_reps,
        lapses=lapses,
        due_at=now + int(result.due_in_seconds),
        last_review_at=now,
        stability=float(result.stability),
        difficulty=float(result.difficulty),
    )
