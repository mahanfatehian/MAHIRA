"""Interval fuzz: spread reviews so a Lektion does not come due as one spike."""

from __future__ import annotations

import math
import statistics

import pytest

from core import fsrs
from core.settings import AppSettings, _normalize_settings
from core.srs import SchedulerTuning, schedule_next, tuning_from_settings
from db.repo import VocabState

NO_FUZZ = SchedulerTuning(interval_fuzz=False)
FUZZ = SchedulerTuning(interval_fuzz=True)


def _state(vocab_id: int = 1, **overrides) -> VocabState:
    base = dict(
        vocab_id=vocab_id,
        ease=2.5,
        interval_days=30.0,
        reps=4,
        lapses=0,
        due_at=1_000_000,
        last_review_at=1_000_000 - 30 * 86400,
        stability=30.0,
        difficulty=5.0,
    )
    base.update(overrides)
    return VocabState(**base)


# --------------------------------------------------------------------------
# fuzz_bounds
# --------------------------------------------------------------------------

@pytest.mark.parametrize("interval", [0.0, 0.5, 1.0, 2.0, 2.49])
def test_short_intervals_are_never_fuzzed(interval):
    """Nudging a 1-day interval is the difference between tomorrow and not."""
    assert fsrs.fuzz_bounds(interval) == (interval, interval)
    assert fsrs.apply_fuzz(interval, seed=12345) == pytest.approx(interval)


@pytest.mark.parametrize("interval", [2.5, 7.0, 20.0, 60.0, 365.0, 3650.0])
def test_bounds_always_bracket_the_exact_interval(interval):
    lower, upper = fsrs.fuzz_bounds(interval)
    assert lower <= interval <= upper
    assert lower >= 2.0


def test_the_fuzz_window_widens_with_the_interval():
    widths = []
    for interval in (3.0, 10.0, 30.0, 100.0, 400.0):
        lower, upper = fsrs.fuzz_bounds(interval)
        widths.append(upper - lower)
    assert widths == sorted(widths)


def test_fuzz_never_moves_an_interval_far_from_the_exact_value():
    """Fuzz must spread the load without distorting the schedule."""
    for interval in (10.0, 30.0, 100.0, 365.0, 3650.0):
        lower, upper = fsrs.fuzz_bounds(interval)
        assert (interval - lower) / interval < 0.25
        assert (upper - interval) / interval < 0.25


def test_relative_fuzz_shrinks_as_intervals_grow():
    ratios = [
        (fsrs.fuzz_bounds(i)[1] - fsrs.fuzz_bounds(i)[0]) / i
        for i in (10.0, 30.0, 100.0, 365.0, 3650.0)
    ]
    assert ratios == sorted(ratios, reverse=True)


def test_bounds_are_finite_for_a_very_long_interval():
    lower, upper = fsrs.fuzz_bounds(36500.0)
    assert math.isfinite(lower) and math.isfinite(upper)


# --------------------------------------------------------------------------
# Determinism — the property the interval previews depend on
# --------------------------------------------------------------------------

def test_the_same_seed_always_gives_the_same_interval():
    first = [fsrs.apply_fuzz(30.0, seed=seed) for seed in range(200)]
    second = [fsrs.apply_fuzz(30.0, seed=seed) for seed in range(200)]
    assert first == second


def test_preview_matches_what_the_review_schedules():
    """rating_interval_labels calls schedule_next; it must not lie."""
    now = 2_000_000
    state = _state()
    for rating in (0, 1, 2, 3):
        preview = schedule_next(state, rating, now=now, tuning=FUZZ)
        applied = schedule_next(state, rating, now=now, tuning=FUZZ)
        assert preview.due_at == applied.due_at


def test_fuzz_spreads_a_cohort_of_identical_cards():
    """The whole point: identical cards must not stay locked together."""
    now = 2_000_000
    scheduled = {
        schedule_next(_state(vocab_id=i), 2, now=now, tuning=FUZZ).interval_days
        for i in range(1, 60)
    }
    assert len(scheduled) > 1
    unfuzzed = schedule_next(_state(vocab_id=1), 2, now=now, tuning=NO_FUZZ)
    # ...and stays centred on the interval FSRS actually asked for.
    assert abs(statistics.mean(scheduled) - unfuzzed.interval_days) < 3.0


def test_practice_lanes_of_one_word_fuzz_independently():
    from db.repo import VocabPracticeState

    def lane(mode: str):
        return VocabPracticeState(
            vocab_id=7,
            practice_mode=mode,
            ease=2.5,
            interval_days=30.0,
            reps=4,
            lapses=0,
            due_at=1_000_000,
            last_review_at=1_000_000 - 30 * 86400,
            stability=30.0,
            difficulty=5.0,
        )

    now = 2_000_000
    seen = {
        schedule_next(lane(mode), 2, now=now, tuning=FUZZ).interval_days
        for mode in ("recognition", "production", "dictation")
    }
    assert len(seen) > 1


# --------------------------------------------------------------------------
# Safety: fuzz must not break the scheduling contract
# --------------------------------------------------------------------------

def test_fuzz_never_shortens_a_lapse_below_the_relearning_step():
    now = 2_000_000
    result = schedule_next(_state(), 0, now=now, tuning=FUZZ)
    assert result.interval_days == 0.0
    assert result.due_at == now + fsrs.RELEARN_STEP_SECONDS


def test_fuzz_never_produces_a_sub_day_interval():
    now = 2_000_000
    for vocab_id in range(1, 80):
        for stability in (0.5, 3.0, 30.0):
            result = schedule_next(
                _state(vocab_id=vocab_id, stability=stability),
                2,
                now=now,
                tuning=FUZZ,
            )
            assert result.interval_days >= 1.0
            assert result.due_at > now


def test_fuzz_does_not_touch_the_memory_model():
    now = 2_000_000
    fuzzed = schedule_next(_state(), 2, now=now, tuning=FUZZ)
    exact = schedule_next(_state(), 2, now=now, tuning=NO_FUZZ)
    assert fuzzed.stability == pytest.approx(exact.stability)
    assert fuzzed.difficulty == pytest.approx(exact.difficulty)
    assert fuzzed.reps == exact.reps


def test_due_at_stays_consistent_with_interval_days():
    now = 2_000_000
    for vocab_id in range(1, 40):
        result = schedule_next(_state(vocab_id=vocab_id), 2, now=now, tuning=FUZZ)
        expected = now + int(round(result.interval_days * fsrs.SECONDS_PER_DAY))
        assert result.due_at == expected


def test_disabling_fuzz_restores_exact_scheduling():
    now = 2_000_000
    state = _state()
    exact = schedule_next(state, 2, now=now, tuning=NO_FUZZ)
    elapsed = (now - state.last_review_at) / 86400.0
    raw = fsrs.schedule(
        rating=2,
        stability=state.stability,
        difficulty=state.difficulty,
        elapsed_days=elapsed,
    )
    assert exact.interval_days == pytest.approx(raw.interval_days)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def test_fuzz_is_on_by_default():
    assert AppSettings().interval_fuzz is True
    assert tuning_from_settings(AppSettings()).interval_fuzz is True


def test_fuzz_can_be_turned_off_in_settings():
    value = _normalize_settings({"interval_fuzz": False})
    assert tuning_from_settings(value).interval_fuzz is False
