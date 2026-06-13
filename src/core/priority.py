# src/core/priority.py
"""
Unified, always-on recall priority.

This is the single source of truth for "how urgently should this item be
reviewed right now". It is deterministic, needs no training, and is applied to
EVERY selection (the ML model only nudges the ordering once it has data -- it
is never a gate). That guarantees the app targets weak/forgotten material from
the very first review, not only after the model warms up.

The dominant signal is FSRS retrievability R(t): the probability the learner
would recall the item at this instant. Low R == about to be forgotten == high
priority. On top of that we layer overdue pressure and per-item weakness
signals (lapses, low accuracy, low ratings, reliance on tips, skips, slow
responses, FSRS difficulty). Never-seen items get a fixed coverage priority so
new material is steadily and reliably introduced.

Priorities are returned in [0, 1] (higher = review sooner).
"""

from __future__ import annotations

import time
from typing import Optional

from core import fsrs

# --- term weights (relative importance) ---------------------------------
W_RECALL = 2.6     # forgetting risk (1 - retrievability) -- the main driver
W_OVERDUE = 0.9    # how far past due
W_DUE_BONUS = 0.4  # flat bump once an item is actually due
W_UNSEEN = 1.7     # coverage priority for never-reviewed items
W_ACCURACY = 2.0   # historical wrong-answer rate
W_RATING = 1.2     # low self/effective ratings
W_SKIP = 1.6       # tendency to skip (a strong "I don't know this" signal)
W_TIP = 0.5        # reliance on meaning tips
W_HELPER = 0.4     # reliance on gender/translation helpers
W_LAPSE = 0.8      # number of past failures
W_DIFFICULTY = 0.6  # FSRS difficulty
W_SLOW = 0.25      # slow responses
W_RECENT = 0.8     # damping: just reviewed -> don't show again immediately

# Normaliser keeps the typical score range inside [0, 1].
_NORM = 6.5

# An item reviewed within this window is damped to avoid back-to-back repeats.
_RECENT_HOURS = 2.0


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def recall_probability(
    *,
    now: float,
    last_review_at: Optional[float],
    stability: Optional[float],
    interval_days: float,
    reps: int,
) -> Optional[float]:
    """
    FSRS retrievability right now, or None for a never-reviewed item.

    Legacy items (reviewed before FSRS, so no stability stored) get a stability
    derived from their interval, so retrievability is still meaningful.
    """
    if reps <= 0 or not last_review_at:
        return None

    s = stability
    if s is None or s <= 0:
        s = max(fsrs._MIN_STABILITY, interval_days if interval_days and interval_days > 0 else 1.0)

    elapsed_days = max(0.0, (now - float(last_review_at)) / 86400.0)
    return fsrs.retrievability(elapsed_days, s)


def compute_priority(
    *,
    now: Optional[float] = None,
    due_at: float,
    last_review_at: Optional[float],
    stability: Optional[float],
    difficulty: Optional[float],
    interval_days: float,
    reps: float,
    lapses: float,
    total_reviews: float,
    avg_rating: float,
    accuracy: float,
    tip_rate: float,
    helper_rate: float,
    skip_rate: float,
    response_ms: float,
    extra_penalty: float = 0.0,
) -> float:
    """Return review priority in [0, 1]; higher means review sooner."""
    now = time.time() if now is None else float(now)

    is_unseen = total_reviews <= 0 or reps <= 0

    overdue_days = max(0.0, (now - due_at) / 86400.0)
    is_due = due_at <= now

    low_rating_pressure = _clip((3.0 - avg_rating) / 3.0)
    weak_accuracy = _clip(1.0 - accuracy)
    slow_pressure = _clip(response_ms / 20000.0)

    d = difficulty if difficulty is not None else fsrs.difficulty_from_ease(2.5)
    difficulty_pressure = _clip((d - 1.0) / 9.0)

    score = 0.0

    if is_unseen:
        # Guaranteed, steady coverage for new material.
        score += W_UNSEEN
    else:
        r = recall_probability(
            now=now,
            last_review_at=last_review_at,
            stability=stability,
            interval_days=interval_days,
            reps=int(reps),
        )
        if r is not None:
            score += (1.0 - r) * W_RECALL
        score += _clip(overdue_days / 7.0) * W_OVERDUE
        if is_due:
            score += W_DUE_BONUS

    score += weak_accuracy * W_ACCURACY
    score += low_rating_pressure * W_RATING
    score += _clip(skip_rate) * W_SKIP
    score += _clip(tip_rate) * W_TIP
    score += _clip(helper_rate) * W_HELPER
    score += _clip(lapses / 5.0) * W_LAPSE
    score += difficulty_pressure * W_DIFFICULTY
    score += slow_pressure * W_SLOW
    score += float(extra_penalty)

    if last_review_at:
        hours_since = (now - float(last_review_at)) / 3600.0
        if hours_since < _RECENT_HOURS:
            score -= W_RECENT

    return _clip(score / _NORM)


def is_unseen(*, reps: float, total_reviews: float) -> bool:
    return total_reviews <= 0 or reps <= 0
