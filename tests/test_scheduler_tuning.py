"""Learner-tunable scheduling: the FSRS target retention."""

from __future__ import annotations

import pytest

from core import fsrs
from core.settings import AppSettings, SettingsService, _normalize_settings
from core.srs import DEFAULT_TUNING, SchedulerTuning, schedule_next, tuning_from_settings
from db.repo import VocabState


def _state(**overrides) -> VocabState:
    base = dict(
        vocab_id=1,
        ease=2.5,
        interval_days=10.0,
        reps=3,
        lapses=0,
        due_at=1_000_000,
        last_review_at=1_000_000 - 10 * 86400,
        stability=10.0,
        difficulty=5.0,
    )
    base.update(overrides)
    return VocabState(**base)


# --------------------------------------------------------------------------
# Settings validation
# --------------------------------------------------------------------------

def test_target_retention_defaults_to_the_fsrs_default():
    assert AppSettings().target_retention == pytest.approx(
        fsrs.DEFAULT_REQUEST_RETENTION
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.95, 0.95),
        (0.70, 0.70),
        (0.97, 0.97),
        (0.10, 0.70),      # below the band -> clamped up
        (1.50, 0.97),      # above the band -> clamped down
        ("0.85", 0.85),    # numeric strings are accepted
        (True, 0.90),      # bools are not numbers here
        ("nonsense", 0.90),
        # Non-finite values are rejected outright rather than clamped, which
        # is how _normalized_int already treats them.
        (float("nan"), 0.90),
        (float("inf"), 0.90),
        (float("-inf"), 0.90),
        (None, 0.90),
    ],
)
def test_target_retention_is_clamped_to_a_usable_band(raw, expected):
    value = _normalize_settings({"target_retention": raw})
    assert value.target_retention == pytest.approx(expected)


def test_target_retention_survives_a_save_load_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    service = SettingsService(path)
    service.update(target_retention=0.85)
    assert SettingsService(path).value.target_retention == pytest.approx(0.85)


# --------------------------------------------------------------------------
# Tuning construction
# --------------------------------------------------------------------------

def test_tuning_from_missing_settings_reproduces_default_behaviour():
    assert tuning_from_settings(None) == DEFAULT_TUNING
    assert DEFAULT_TUNING.target_retention == pytest.approx(
        fsrs.DEFAULT_REQUEST_RETENTION
    )


def test_tuning_tolerates_objects_without_the_field():
    class Bare:
        pass

    assert tuning_from_settings(Bare()) == DEFAULT_TUNING


def test_tuning_tolerates_a_non_numeric_field():
    class Broken:
        target_retention = "not a number"

    assert tuning_from_settings(Broken()) == DEFAULT_TUNING


# --------------------------------------------------------------------------
# Scheduling behaviour
# --------------------------------------------------------------------------

def test_untuned_scheduling_is_unchanged():
    """The default path must schedule exactly what it always did."""
    now = 2_000_000
    assert schedule_next(_state(), 2, now=now) == schedule_next(
        _state(), 2, now=now, tuning=DEFAULT_TUNING
    )


def test_higher_retention_shortens_the_interval():
    now = 2_000_000
    low = schedule_next(_state(), 2, now=now, tuning=SchedulerTuning(0.80))
    high = schedule_next(_state(), 2, now=now, tuning=SchedulerTuning(0.95))
    assert high.interval_days < low.interval_days


def test_retention_is_monotonic_across_the_whole_band():
    now = 2_000_000
    intervals = [
        schedule_next(
            _state(), 2, now=now, tuning=SchedulerTuning(r / 100.0)
        ).interval_days
        for r in range(70, 98)
    ]
    assert intervals == sorted(intervals, reverse=True)


def test_retention_does_not_change_the_memory_model():
    """Only the interval derived from stability moves, never stability itself."""
    now = 2_000_000
    low = schedule_next(_state(), 2, now=now, tuning=SchedulerTuning(0.80))
    high = schedule_next(_state(), 2, now=now, tuning=SchedulerTuning(0.95))
    assert low.stability == pytest.approx(high.stability)
    assert low.difficulty == pytest.approx(high.difficulty)


def test_retention_never_shortens_a_lapse_below_the_relearning_step():
    now = 2_000_000
    for retention in (0.70, 0.90, 0.97):
        result = schedule_next(
            _state(), 0, now=now, tuning=SchedulerTuning(retention)
        )
        assert result.due_at == now + fsrs.RELEARN_STEP_SECONDS


def test_successful_reviews_stay_at_least_one_day_out():
    now = 2_000_000
    result = schedule_next(
        _state(stability=0.1, difficulty=10.0),
        1,
        now=now,
        tuning=SchedulerTuning(0.97),
    )
    assert result.interval_days >= 1.0
