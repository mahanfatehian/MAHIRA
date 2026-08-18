"""The recall priority must keep ranking the worst cards against each other.

_NORM was pinned at 6.5 while the term weights grew to sum to 11.25. Every raw
score past 6.5 clipped to exactly 1.0, so the most at-risk items - the ones the
module exists to surface - all tied. rank_* breaks ties on (priority,
-original_index), so ordering among them collapsed to database id order.
"""

from __future__ import annotations


import pytest

from core import priority
from core.priority import compute_priority

NOW = 1_800_000_000


def _card(**overrides) -> float:
    base = dict(
        reps=5,
        lapses=1,
        due_at=NOW - 86400,
        last_review_at=NOW - 5 * 86400,
        total_reviews=5,
        avg_rating=2.0,
        accuracy=0.7,
        tip_rate=0.1,
        helper_rate=0.0,
        skip_rate=0.0,
        response_ms=4000,
        stability=8.0,
        difficulty=5.0,
        interval_days=8.0,
        now=NOW,
    )
    base.update(overrides)
    return compute_priority(**base)


def _worst(**overrides) -> dict:
    base = dict(
        reps=8,
        lapses=6,
        due_at=NOW - 60 * 86400,
        last_review_at=NOW - 80 * 86400,
        total_reviews=8,
        avg_rating=0.3,
        accuracy=0.05,
        tip_rate=0.9,
        helper_rate=0.8,
        skip_rate=0.7,
        response_ms=18000,
        stability=0.8,
        difficulty=9.8,
        interval_days=0.8,
        now=NOW,
    )
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# The normaliser
# --------------------------------------------------------------------------

def test_the_normaliser_covers_every_weight():
    """Derived, not hardcoded, so adding a term cannot silently re-break this."""
    reachable = (
        priority.W_RECALL
        + priority.W_OVERDUE
        + priority.W_DUE_BONUS
        + priority.W_ACCURACY
        + priority.W_RATING
        + priority.W_SKIP
        + priority.W_TIP
        + priority.W_HELPER
        + priority.W_LAPSE
        + priority.W_DIFFICULTY
        + priority.W_SLOW
        + priority.W_EXTRA
    )
    assert priority._NORM == pytest.approx(reachable)


def test_the_unseen_branch_cannot_exceed_the_normaliser():
    assert priority.W_UNSEEN <= priority._MAX_RECALL_SCORE


# --------------------------------------------------------------------------
# No saturation
# --------------------------------------------------------------------------

def test_a_realistically_terrible_card_is_below_the_ceiling():
    assert compute_priority(**_worst()) < 1.0


def test_two_differently_bad_cards_are_distinguishable():
    bad = compute_priority(
        **_worst(lapses=4, accuracy=0.2, skip_rate=0.3, avg_rating=0.9)
    )
    worse = compute_priority(**_worst(lapses=20, accuracy=0.0, skip_rate=1.0, avg_rating=0.0))
    assert worse > bad


def test_the_worst_cards_do_not_collapse_to_one_value():
    scores = {
        compute_priority(**_worst(lapses=n, accuracy=max(0.0, 0.3 - n / 40)))
        for n in range(1, 20)
    }
    assert len(scores) > 10, "priority is still flattening the top of the range"


# --------------------------------------------------------------------------
# Monotonicity along each axis of "worse"
# --------------------------------------------------------------------------

def test_more_lapses_never_lowers_priority():
    scores = [_card(lapses=n) for n in range(0, 12)]
    assert scores == sorted(scores)


def test_lower_accuracy_never_lowers_priority():
    scores = [_card(accuracy=a / 20) for a in range(20, -1, -1)]
    assert scores == sorted(scores)


def test_more_overdue_never_lowers_priority():
    scores = [_card(due_at=NOW - d * 86400) for d in range(0, 30)]
    assert scores == sorted(scores)


def test_more_skipping_never_lowers_priority():
    scores = [_card(skip_rate=s / 10) for s in range(0, 11)]
    assert scores == sorted(scores)


def test_lower_stability_never_lowers_priority():
    scores = [_card(stability=s) for s in (60.0, 30.0, 12.0, 6.0, 2.0, 0.5)]
    assert scores == sorted(scores)


def test_higher_difficulty_never_lowers_priority():
    scores = [_card(difficulty=d) for d in range(1, 11)]
    assert scores == sorted(scores)


# --------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------

@pytest.mark.parametrize("lapses", [0, 3, 50, 5000])
@pytest.mark.parametrize("accuracy", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("skip_rate", [0.0, 1.0])
def test_priority_always_stays_in_range(lapses, accuracy, skip_rate):
    value = _card(lapses=lapses, accuracy=accuracy, skip_rate=skip_rate)
    assert 0.0 <= value <= 1.0


def test_an_extra_penalty_still_cannot_escape_the_range():
    value = compute_priority(**_worst(), extra_penalty=priority.W_EXTRA)
    assert 0.0 <= value <= 1.0


def test_a_healthy_card_still_ranks_below_a_struggling_one():
    healthy = _card(
        lapses=0,
        accuracy=1.0,
        avg_rating=3.0,
        tip_rate=0.0,
        due_at=NOW + 20 * 86400,
        stability=90.0,
        difficulty=1.5,
    )
    assert healthy < compute_priority(**_worst())


def test_an_unseen_item_still_gets_its_coverage_priority():
    unseen = compute_priority(
        reps=0,
        lapses=0,
        due_at=NOW,
        last_review_at=None,
        total_reviews=0,
        avg_rating=2.0,
        accuracy=0.55,
        tip_rate=0.0,
        helper_rate=0.0,
        skip_rate=0.0,
        response_ms=0.0,
        stability=None,
        difficulty=None,
        interval_days=0.0,
        now=NOW,
    )
    assert 0.0 < unseen < 1.0
