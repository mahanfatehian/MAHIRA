"""A ceiling on how far ahead a well-known card can be scheduled."""

from __future__ import annotations

import pytest

from core.settings import AppSettings, _normalize_settings
from core.srs import DEFAULT_TUNING, SchedulerTuning, schedule_next, tuning_from_settings
from db.repo import VocabState


def _state(vocab_id: int = 1, stability: float = 4000.0) -> VocabState:
    """A card the learner has known cold for years."""
    return VocabState(
        vocab_id=vocab_id,
        ease=2.5,
        interval_days=stability,
        reps=40,
        lapses=0,
        due_at=1_000_000,
        last_review_at=1_000_000 - int(stability * 86400),
        stability=stability,
        difficulty=1.5,
    )


def test_the_default_preserves_previous_behaviour():
    """36500 days is effectively no cap, so upgrading changes no schedule."""
    assert AppSettings().max_interval_days == 36500
    assert DEFAULT_TUNING.max_interval_days == 36500


@pytest.mark.parametrize("cap", [180, 365, 730, 1825, 3650])
def test_a_cap_is_never_exceeded(cap):
    now = 2_000_000
    for vocab_id in range(1, 30):
        result = schedule_next(
            _state(vocab_id=vocab_id),
            3,
            now=now,
            tuning=SchedulerTuning(max_interval_days=cap),
        )
        assert result.interval_days <= cap
        assert result.due_at <= now + cap * 86400 + 1


def test_fuzz_cannot_push_an_interval_back_over_the_cap():
    """Fuzz runs first, so the clamp has to come last to be a guarantee."""
    now = 2_000_000
    for vocab_id in range(1, 60):
        result = schedule_next(
            _state(vocab_id=vocab_id, stability=364.0),
            3,
            now=now,
            tuning=SchedulerTuning(interval_fuzz=True, max_interval_days=365),
        )
        assert result.interval_days <= 365


def test_a_cap_does_not_disturb_shorter_intervals():
    now = 2_000_000
    state = VocabState(
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
    uncapped = schedule_next(
        state, 2, now=now, tuning=SchedulerTuning(interval_fuzz=False)
    )
    capped = schedule_next(
        state,
        2,
        now=now,
        tuning=SchedulerTuning(interval_fuzz=False, max_interval_days=365),
    )
    assert capped.interval_days == pytest.approx(uncapped.interval_days)


def test_a_cap_never_shortens_a_review_below_a_day():
    now = 2_000_000
    result = schedule_next(
        _state(), 3, now=now, tuning=SchedulerTuning(max_interval_days=30)
    )
    assert result.interval_days >= 1.0


def test_the_cap_leaves_the_memory_model_alone():
    """Capping the interval must not corrupt stability for later reviews."""
    now = 2_000_000
    capped = schedule_next(
        _state(), 3, now=now, tuning=SchedulerTuning(max_interval_days=365)
    )
    uncapped = schedule_next(_state(), 3, now=now, tuning=SchedulerTuning())
    assert capped.stability == pytest.approx(uncapped.stability)
    assert capped.difficulty == pytest.approx(uncapped.difficulty)


def test_a_lapse_ignores_the_cap():
    now = 2_000_000
    result = schedule_next(
        _state(), 0, now=now, tuning=SchedulerTuning(max_interval_days=30)
    )
    assert result.interval_days == 0.0


@pytest.mark.parametrize(
    "raw,expected",
    [
        (365, 365),
        (10, 30),           # below the band
        (99_999, 36500),    # above the band
        (True, 36500),
        ("730", 730),
        ("nope", 36500),
    ],
)
def test_the_setting_is_validated(raw, expected):
    assert _normalize_settings({"max_interval_days": raw}).max_interval_days == expected


def test_tuning_reads_the_setting():
    value = _normalize_settings({"max_interval_days": 730})
    assert tuning_from_settings(value).max_interval_days == 730
