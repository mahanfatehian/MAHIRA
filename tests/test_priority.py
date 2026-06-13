"""Always-on recall priority: forgotten/weak items must outrank fresh ones."""

from core import priority

NOW = 1_000_000.0
DAY = 86_400.0


def _base(**over):
    d = dict(
        now=NOW,
        due_at=NOW,
        last_review_at=NOW,
        stability=10.0,
        difficulty=5.0,
        interval_days=10.0,
        reps=3,
        lapses=0,
        total_reviews=3,
        avg_rating=2.0,
        accuracy=0.8,
        tip_rate=0.0,
        helper_rate=0.0,
        skip_rate=0.0,
        response_ms=2000.0,
    )
    d.update(over)
    return d


def test_priority_in_unit_range():
    assert 0.0 <= priority.compute_priority(**_base()) <= 1.0


def test_unseen_item_has_meaningful_priority():
    p = priority.compute_priority(**_base(reps=0, total_reviews=0, last_review_at=None))
    assert p > 0.2


def test_overdue_forgotten_item_outranks_fresh_item():
    forgotten = priority.compute_priority(
        **_base(
            due_at=NOW - 10 * DAY,
            last_review_at=NOW - 12 * DAY,
            stability=2.0,
            difficulty=8.0,
            reps=3,
            lapses=2,
            avg_rating=1.0,
            accuracy=0.4,
        )
    )
    fresh = priority.compute_priority(
        **_base(
            due_at=NOW + 5 * DAY,
            last_review_at=NOW,
            stability=40.0,
            difficulty=2.0,
            reps=6,
            lapses=0,
            avg_rating=3.0,
            accuracy=0.97,
        )
    )
    assert forgotten > fresh


def test_lower_retrievability_raises_priority():
    """Same item, more time elapsed (lower recall prob) => higher priority."""
    soon = priority.compute_priority(
        **_base(last_review_at=NOW - 1 * DAY, due_at=NOW - 1 * DAY, stability=10.0)
    )
    later = priority.compute_priority(
        **_base(last_review_at=NOW - 40 * DAY, due_at=NOW - 30 * DAY, stability=10.0)
    )
    assert later > soon


def test_recently_reviewed_item_is_damped():
    """An item reviewed minutes ago should not immediately rank high again."""
    just_now = priority.compute_priority(
        **_base(last_review_at=NOW - 60, due_at=NOW - 60, stability=1.0)
    )
    a_week = priority.compute_priority(
        **_base(last_review_at=NOW - 7 * DAY, due_at=NOW - 6 * DAY, stability=1.0)
    )
    assert a_week > just_now


def test_skips_and_errors_increase_priority():
    clean = priority.compute_priority(**_base(skip_rate=0.0, accuracy=0.9))
    messy = priority.compute_priority(**_base(skip_rate=0.8, accuracy=0.3))
    assert messy > clean


def test_recall_probability_none_for_unseen():
    assert (
        priority.recall_probability(
            now=NOW, last_review_at=None, stability=None, interval_days=0.0, reps=0
        )
        is None
    )
