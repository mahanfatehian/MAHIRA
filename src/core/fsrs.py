# src/core/fsrs.py
"""
FSRS-4.5 memory model (Free Spaced Repetition Scheduler).

This is the "state of the art" core that powers MAHIRA's selection engine.
Unlike SM-2 (which only tracks an interval), FSRS models each item with two
latent variables:

  - stability  (S): days for recall probability to fall from 1.0 to the
                    target retention (0.9). Bigger S = more durable memory.
  - difficulty (D): 1..10, how hard the item is for this learner.

From those it computes *retrievability* R(t) -- the probability you would
recall the item right now, t days after the last review. R is the signal we
use to trigger reviews "exactly when you are about to forget":

    R(t, S) = (1 + FACTOR * t / S) ** DECAY

The scheduler picks the next interval as the time at which R decays to the
requested retention (default 0.9).

This module is intentionally pure (no DB, no Qt, no clock side effects beyond
an injectable `now`) so it is trivially unit-testable. Grades use MAHIRA's
0..3 convention (0=Again, 1=Hard, 2=Good, 3=Easy); internally they map to the
FSRS 1..4 convention.

Default parameters are the published FSRS-4.5 defaults. They are global and
tunable; a future job can optimise them per-user from the review log.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# FSRS-4.5 power forgetting curve constants.
DECAY: float = -0.5
FACTOR: float = 0.9 ** (1.0 / DECAY) - 1.0  # ~= 0.2345679 (so R == 0.9 when t == S)

# Published FSRS-4.5 default weights (19 parameters).
DEFAULT_PARAMS: tuple[float, ...] = (
    0.4197,  # w0  initial stability: Again
    1.1869,  # w1  initial stability: Hard
    3.0412,  # w2  initial stability: Good
    15.2441,  # w3  initial stability: Easy
    7.1434,  # w4  initial difficulty base
    0.6477,  # w5  initial difficulty exponent
    1.0007,  # w6  difficulty change per grade
    0.0674,  # w7  difficulty mean-reversion weight
    1.6597,  # w8  stability-on-recall scale
    0.1712,  # w9  stability-on-recall: stability penalty exponent
    1.1178,  # w10 stability-on-recall: retrievability factor
    2.0225,  # w11 post-lapse stability scale
    0.0904,  # w12 post-lapse: difficulty penalty exponent
    0.3025,  # w13 post-lapse: stability factor exponent
    2.1214,  # w14 post-lapse: retrievability factor
    0.2498,  # w15 hard penalty (grade == Hard)
    2.9466,  # w16 easy bonus (grade == Easy)
    0.4891,  # w17 (short-term; unused by the long-term scheduler here)
    0.6468,  # w18 (short-term; unused by the long-term scheduler here)
)

# Target probability of recall when an item next becomes due.
DEFAULT_REQUEST_RETENTION: float = 0.9

# Minimum stability (days) to avoid divide-by-zero / runaway intervals.
_MIN_STABILITY: float = 0.1

# When a card is failed (Again) it re-enters a short relearning step instead of
# waiting a full day, so the learner sees it again in the same session.
RELEARN_STEP_SECONDS: int = 10 * 60

SECONDS_PER_DAY: int = 86_400


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class MemoryState:
    """Latent memory parameters for a single item."""

    stability: float
    difficulty: float


@dataclass(frozen=True)
class Scheduled:
    """Result of scheduling a review."""

    stability: float
    difficulty: float
    interval_days: float  # 0.0 means a sub-day relearning step
    due_in_seconds: int


def retrievability(elapsed_days: float, stability: float) -> float:
    """Probability of recall `elapsed_days` after the last review."""
    if stability <= 0:
        return 0.0
    elapsed_days = max(0.0, float(elapsed_days))
    return (1.0 + FACTOR * elapsed_days / stability) ** DECAY


def interval_for_retention(stability: float, request_retention: float = DEFAULT_REQUEST_RETENTION) -> float:
    """Days until retrievability decays from 1.0 to `request_retention`."""
    request_retention = _clamp(request_retention, 0.5, 0.99)
    stability = max(_MIN_STABILITY, float(stability))
    return (stability / FACTOR) * (request_retention ** (1.0 / DECAY) - 1.0)


# Interval fuzz. Cards introduced on the same day otherwise stay locked
# together for the life of the deck, so every Lektion's reviews land as one
# spike. These are the FSRS/Anki fuzz bands: a widening window around the
# exact interval, expressed as (start_days, end_days, factor).
_FUZZ_BANDS: tuple[tuple[float, float, float], ...] = (
    (2.5, 7.0, 0.15),
    (7.0, 20.0, 0.10),
    (20.0, math.inf, 0.05),
)

# Intervals below this are left exact: nudging a 1-2 day interval is the
# difference between "tomorrow" and "skipped a day".
FUZZ_MIN_INTERVAL_DAYS: float = 2.5


def fuzz_bounds(interval_days: float) -> tuple[float, float]:
    """Inclusive day range `interval_days` may be nudged into."""
    interval_days = max(0.0, float(interval_days))
    if interval_days < FUZZ_MIN_INTERVAL_DAYS:
        return (interval_days, interval_days)
    delta = 1.0
    for start, end, factor in _FUZZ_BANDS:
        delta += factor * max(0.0, min(interval_days, end) - start)
    lower = max(2.0, float(round(interval_days - delta)))
    upper = max(lower, float(round(interval_days + delta)))
    return (lower, upper)


def _mix(value: int) -> int:
    """Stable, well-distributed scramble of an integer.

    Deliberately not `hash()`: Python salts string hashing per process, and a
    fuzz that changed between runs would make the interval preview on a rating
    button disagree with the interval that review actually schedules.
    """
    mask = 0xFFFFFFFFFFFFFFFF
    x = (int(value) & mask) ^ 0x9E3779B97F4A7C15
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & mask
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & mask
    return x ^ (x >> 31)


def apply_fuzz(interval_days: float, *, seed: int) -> float:
    """Spread an interval within its fuzz band, deterministically.

    The same `seed` always yields the same interval, so this is safe to call
    from a preview and from the real review that follows it.
    """
    lower, upper = fuzz_bounds(interval_days)
    span = int(upper - lower) + 1
    if span <= 1:
        return float(lower)
    return float(lower + (_mix(seed) % span))


def _grade(rating: int) -> int:
    """Map MAHIRA rating 0..3 (Again/Hard/Good/Easy) to FSRS grade 1..4."""
    try:
        r = int(rating)
    except Exception:
        r = 0
    return int(_clamp(r, 0, 3)) + 1


def init_stability(params: tuple[float, ...], grade: int) -> float:
    return max(_MIN_STABILITY, params[grade - 1])


def init_difficulty(params: tuple[float, ...], grade: int) -> float:
    d = params[4] - math.exp(params[5] * (grade - 1)) + 1.0
    return _clamp(d, 1.0, 10.0)


def _next_difficulty(params: tuple[float, ...], difficulty: float, grade: int) -> float:
    # Linear change away from "Good" (grade 3), then mean-revert toward the
    # easiest baseline so difficulty does not drift unbounded.
    delta = -params[6] * (grade - 3)
    nxt = difficulty + delta
    reverted = params[7] * init_difficulty(params, 4) + (1.0 - params[7]) * nxt
    return _clamp(reverted, 1.0, 10.0)


def _stability_after_recall(
    params: tuple[float, ...], difficulty: float, stability: float, r: float, grade: int
) -> float:
    hard_penalty = params[15] if grade == 2 else 1.0
    easy_bonus = params[16] if grade == 4 else 1.0
    growth = (
        math.exp(params[8])
        * (11.0 - difficulty)
        * (stability ** -params[9])
        * (math.exp((1.0 - r) * params[10]) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    return max(_MIN_STABILITY, stability * (1.0 + growth))


def _stability_after_lapse(
    params: tuple[float, ...], difficulty: float, stability: float, r: float
) -> float:
    post = (
        params[11]
        * (difficulty ** -params[12])
        * (((stability + 1.0) ** params[13]) - 1.0)
        * math.exp((1.0 - r) * params[14])
    )
    # A lapse must never increase stability.
    return max(_MIN_STABILITY, min(post, stability))


def schedule(
    *,
    rating: int,
    stability: float | None,
    difficulty: float | None,
    elapsed_days: float,
    request_retention: float = DEFAULT_REQUEST_RETENTION,
    params: tuple[float, ...] = DEFAULT_PARAMS,
) -> Scheduled:
    """
    Advance the FSRS memory model by one review.

    `stability`/`difficulty` are None for an item that has never been reviewed
    (first exposure); in that case the initial-state formulas are used.
    `elapsed_days` is the real time since the last review (ignored on first
    exposure).
    """
    grade = _grade(rating)
    first_review = stability is None or difficulty is None or stability <= 0

    if first_review:
        new_s = init_stability(params, grade)
        new_d = init_difficulty(params, grade)
    else:
        s = max(_MIN_STABILITY, float(stability))
        d = _clamp(float(difficulty), 1.0, 10.0)
        r = retrievability(elapsed_days, s)
        new_d = _next_difficulty(params, d, grade)
        if grade == 1:  # Again / lapse
            new_s = _stability_after_lapse(params, d, s, r)
        else:
            new_s = _stability_after_recall(params, d, s, r, grade)

    if grade == 1:
        # Relearning step: show again within the session, but keep the updated
        # (lowered) memory model so long-term scheduling stays accurate.
        return Scheduled(
            stability=new_s,
            difficulty=new_d,
            interval_days=0.0,
            due_in_seconds=RELEARN_STEP_SECONDS,
        )

    interval = interval_for_retention(new_s, request_retention)
    interval = max(1.0, interval)  # successful reviews are at least one day out
    return Scheduled(
        stability=new_s,
        difficulty=new_d,
        interval_days=interval,
        due_in_seconds=int(round(interval * SECONDS_PER_DAY)),
    )


def difficulty_from_ease(ease: float | None) -> float:
    """
    Derive an FSRS difficulty from a legacy SM-2 ease factor, for migrating
    items reviewed before the FSRS upgrade. Higher ease == easier == lower D.
    """
    try:
        e = float(ease)
    except Exception:
        return 5.0
    # SM-2 ease typically lives in [1.3, ~3.0]; map onto difficulty [10, 1].
    span = (e - 1.3) / (3.0 - 1.3)
    return _clamp(10.0 - span * 9.0, 1.0, 10.0)


def ease_from_difficulty(difficulty: float | None) -> float:
    """Inverse mapping, kept so legacy `ease` columns stay meaningful for display."""
    try:
        d = float(difficulty)
    except Exception:
        return 2.5
    span = (10.0 - _clamp(d, 1.0, 10.0)) / 9.0
    return _clamp(1.3 + span * (3.0 - 1.3), 1.3, 3.0)


def stability_from_interval(interval_days: float | None, reps: int) -> float | None:
    """
    Derive a starting stability for a legacy item that has been reviewed but has
    no stability recorded yet. Unseen items (reps <= 0) return None so the next
    review initialises them properly.
    """
    try:
        reps = int(reps)
    except Exception:
        reps = 0
    if reps <= 0:
        return None
    try:
        iv = float(interval_days)
    except Exception:
        iv = 0.0
    return max(_MIN_STABILITY, iv if iv > 0 else 1.0)
