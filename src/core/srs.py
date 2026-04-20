from __future__ import annotations

import time
from dataclasses import replace

from db.repo import VocabState


def schedule_next(state: VocabState, rating: int) -> VocabState:
    """Simple SM-2-ish scheduler.

    rating: 0=Again, 1=Hard, 2=Good, 3=Easy

    FIX: Hard must *shorten* interval (old code incorrectly made it longer).
    """
    if rating not in (0, 1, 2, 3):
        raise ValueError("rating must be 0..3")

    now = int(time.time())
    s = replace(state, last_review_at=now)

    # Again
    if rating == 0:
        ease = max(1.3, s.ease - 0.2)
        return replace(
            s,
            ease=ease,
            lapses=s.lapses + 1,
            reps=max(0, s.reps - 1),
            interval_days=0.0,
            due_at=now + 10 * 60,  # 10 minutes
        )

    reps = s.reps + 1

    # First reps: fixed short steps
    if reps == 1:
        interval = 1.0
    elif reps == 2:
        interval = 3.0
    else:
        # Hard should shorten, Easy should lengthen.
        mult = {1: 0.8, 2: 1.0, 3: 1.3}[rating]
        interval = max(1.0, s.interval_days * s.ease * mult)

    # Ease adjustment
    if rating == 1:
        ease = max(1.3, s.ease - 0.15)
    elif rating == 3:
        ease = max(1.3, s.ease + 0.10)
    else:
        ease = max(1.3, s.ease)

    due_at = now + int(interval * 86400)
    return replace(s, ease=ease, reps=reps, interval_days=interval, due_at=due_at)
