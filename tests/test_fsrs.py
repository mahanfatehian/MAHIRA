"""FSRS-4.5 memory model: forgetting curve + stability/difficulty dynamics."""

import pytest

from core import fsrs


def test_retrievability_is_one_at_zero_elapsed():
    assert fsrs.retrievability(0.0, 10.0) == pytest.approx(1.0)


def test_retrievability_is_target_at_one_stability():
    # By construction R == 0.9 when elapsed == stability.
    assert fsrs.retrievability(10.0, 10.0) == pytest.approx(0.9, abs=1e-6)


def test_retrievability_monotonically_decreases():
    s = 8.0
    prev = 1.01
    for t in range(0, 60, 2):
        r = fsrs.retrievability(float(t), s)
        assert r <= prev
        prev = r


def test_interval_round_trips_to_stability_at_default_retention():
    # The interval chosen for retention 0.9 should be ~= stability.
    for s in (1.0, 5.0, 30.0, 365.0):
        assert fsrs.interval_for_retention(s, 0.9) == pytest.approx(s, rel=1e-6)


def test_again_enters_relearning_step_not_days():
    out = fsrs.schedule(rating=0, stability=10.0, difficulty=5.0, elapsed_days=10.0)
    assert out.interval_days == 0.0
    assert out.due_in_seconds == fsrs.RELEARN_STEP_SECONDS


def test_first_review_grades_order_intervals():
    again = fsrs.schedule(rating=0, stability=None, difficulty=None, elapsed_days=0.0)
    hard = fsrs.schedule(rating=1, stability=None, difficulty=None, elapsed_days=0.0)
    good = fsrs.schedule(rating=2, stability=None, difficulty=None, elapsed_days=0.0)
    easy = fsrs.schedule(rating=3, stability=None, difficulty=None, elapsed_days=0.0)

    # Again is a sub-day relearning step; the rest are increasing intervals.
    assert again.interval_days == 0.0
    assert hard.interval_days <= good.interval_days <= easy.interval_days
    assert easy.interval_days > hard.interval_days


def test_successful_review_increases_stability():
    s0 = 5.0
    out = fsrs.schedule(rating=2, stability=s0, difficulty=5.0, elapsed_days=5.0)
    assert out.stability > s0


def test_lapse_never_increases_stability():
    s0 = 40.0
    out = fsrs.schedule(rating=0, stability=s0, difficulty=5.0, elapsed_days=40.0)
    assert out.stability <= s0


def test_easy_grows_stability_more_than_hard():
    base = dict(stability=10.0, difficulty=5.0, elapsed_days=10.0)
    hard = fsrs.schedule(rating=1, **base)
    easy = fsrs.schedule(rating=3, **base)
    assert easy.stability > hard.stability


def test_difficulty_stays_in_bounds():
    d = 5.0
    s = 5.0
    # Hammer "Again" repeatedly: difficulty must stay clamped to [1, 10].
    for _ in range(20):
        out = fsrs.schedule(rating=0, stability=s, difficulty=d, elapsed_days=1.0)
        d, s = out.difficulty, out.stability
        assert 1.0 <= d <= 10.0
        assert s >= fsrs._MIN_STABILITY


def test_legacy_migration_helpers():
    # ease<->difficulty are inverse-ish and bounded.
    assert 1.0 <= fsrs.difficulty_from_ease(2.5) <= 10.0
    assert 1.3 <= fsrs.ease_from_difficulty(5.0) <= 3.0
    # Unseen item (reps == 0) has no derived stability yet.
    assert fsrs.stability_from_interval(0.0, reps=0) is None
    assert fsrs.stability_from_interval(7.0, reps=3) == pytest.approx(7.0)
