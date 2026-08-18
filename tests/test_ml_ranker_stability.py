"""The online ranker has to predict something, not diverge into a sign bit.

_OnlineDifficultyModel used SGDRegressor(learning_rate="optimal") and fitted
StandardScaler on one sample at a time, then transformed that same sample. With
a near-zero variance estimate the scaled values explode, and the first few SGD
updates blew the weights past recovery: ||coef_|| reached 1e14, every prediction
clipped to 0.0 or 1.0, and rank correlation against the truth was NEGATIVE.

is_fitted flipped True after a single partial_fit, so _rank_rows immediately
began blending 25% of a worse-than-random signal into every ranking.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.ml.sklearn_ranker import (
    _DIVERGENCE_LIMIT,
    _SCALER_WARMUP_SAMPLES,
    _OnlineDifficultyModel,
)

pytest.importorskip("sklearn")


def _stream(n: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        x = rng.random(18)
        y = float(np.clip(0.6 * x[0] + 0.3 * x[3] - 0.2 * x[7] + 0.1, 0.0, 1.0))
        out.append((list(x), y))
    return out


def _trained(n: int = 300) -> _OnlineDifficultyModel:
    model = _OnlineDifficultyModel()
    for x, y in _stream(n):
        model.partial_fit(x, y)
    return model


def test_the_model_learns_the_signal():
    scipy_stats = pytest.importorskip("scipy.stats")
    model = _trained()
    holdout = _stream(200, seed=7)
    preds = model.predict_many([x for x, _ in holdout])
    truth = [y for _, y in holdout]
    correlation = scipy_stats.spearmanr(preds, truth).statistic
    assert correlation > 0.8, f"ranker is not predictive (spearman={correlation:.3f})"


def test_the_weights_stay_finite_and_small():
    model = _trained()
    norm = float(np.linalg.norm(model.model.coef_))
    assert np.isfinite(norm)
    assert norm < 100.0, f"weights diverged (||coef_||={norm:.3g})"


def test_predictions_are_not_collapsed_to_the_clip_bounds():
    model = _trained()
    preds = model.predict_many([x for x, _ in _stream(100, seed=3)])
    assert len(set(preds)) > 10, "predictions collapsed to a sign bit"
    assert not all(p in (0.0, 1.0) for p in preds)


# --------------------------------------------------------------------------
# Warm-up
# --------------------------------------------------------------------------

def test_the_model_does_not_train_during_scaler_warmup():
    model = _OnlineDifficultyModel()
    for x, y in _stream(_SCALER_WARMUP_SAMPLES - 1):
        model.partial_fit(x, y)
    assert model.is_fitted is False


def test_an_unfitted_model_returns_the_neutral_score():
    """_rank_rows weights the learned term at zero while is_fitted is False."""
    model = _OnlineDifficultyModel()
    for x, y in _stream(3):
        model.partial_fit(x, y)
    assert model.predict_many([[0.5] * 18] * 4) == [0.5] * 4


def test_warmup_samples_are_replayed_not_discarded():
    model = _OnlineDifficultyModel()
    for x, y in _stream(_SCALER_WARMUP_SAMPLES):
        model.partial_fit(x, y)
    assert model.is_fitted is True
    assert model.samples_seen == _SCALER_WARMUP_SAMPLES
    assert not model._warmup


def test_sample_count_keeps_rising_after_warmup():
    model = _trained(60)
    assert model.samples_seen == 60


# --------------------------------------------------------------------------
# Self-healing
# --------------------------------------------------------------------------

def test_a_diverged_model_stands_down_instead_of_ranking():
    model = _trained(40)
    model.model.coef_ = model.model.coef_ * 1e12

    preds = model.predict_many([x for x, _ in _stream(5, seed=11)])
    assert preds == [0.5] * 5
    assert model.is_fitted is False, "a diverged model must stop being blended in"


def test_non_finite_predictions_are_caught():
    model = _trained(40)
    model.model.coef_ = np.full_like(model.model.coef_, np.nan)
    assert model.predict_many([[0.5] * 18]) == [0.5]


def test_the_divergence_limit_is_loose_enough_for_real_predictions():
    model = _trained()
    preds = model.predict_many([x for x, _ in _stream(100, seed=5)])
    assert _DIVERGENCE_LIMIT > 1.0
    assert model.is_fitted is True, "healthy predictions tripped the guard"
    assert all(0.0 <= p <= 1.0 for p in preds)
