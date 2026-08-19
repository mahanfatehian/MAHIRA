"""Superseded model files must not accumulate in the learner's data folder.

The model filename carries a version that is bumped whenever a training change
invalidates existing models. Nothing removed the previous file, so a real
install accumulated vocab__a1__v2, __v3 and __v4 side by side - every bump
stranded a few hundred KB inside the portable data directory permanently.
"""

from __future__ import annotations

import pytest

from core.ml.sklearn_ranker import SklearnRanker

pytest.importorskip("sklearn")


@pytest.fixture()
def ranker(tmp_path):
    return SklearnRanker(object(), model_dir=tmp_path / "ml_models")


def _trained(ranker, objective="vocab", level="A1"):
    model = ranker._load_model(objective, level)
    for i in range(25):
        model.partial_fit([0.1 * ((i + j) % 7) for j in range(18)], (i % 5) / 4.0)
    return model


def test_saving_removes_older_versions_of_the_same_model(ranker, tmp_path):
    model_dir = tmp_path / "ml_models"
    model_dir.mkdir(parents=True, exist_ok=True)
    stale = [
        model_dir / "vocab__a1__v2.joblib",
        model_dir / "vocab__a1__v3.joblib",
    ]
    for path in stale:
        path.write_bytes(b"superseded")

    model = _trained(ranker)
    ranker._save_model("vocab", "A1", model)

    current = ranker._model_path("vocab", "A1")
    assert current.exists()
    assert not any(path.exists() for path in stale)


def test_it_keeps_models_for_other_objectives(ranker, tmp_path):
    model_dir = tmp_path / "ml_models"
    model_dir.mkdir(parents=True, exist_ok=True)
    other = model_dir / "grammar__a1__v3.joblib"
    other.write_bytes(b"another lane")

    ranker._save_model("vocab", "A1", _trained(ranker))

    assert other.exists(), "pruning must not touch a different objective"


def test_it_keeps_models_for_other_levels(ranker, tmp_path):
    model_dir = tmp_path / "ml_models"
    model_dir.mkdir(parents=True, exist_ok=True)
    other = model_dir / "vocab__a2__v4.joblib"
    other.write_bytes(b"another level")

    ranker._save_model("vocab", "A1", _trained(ranker))

    assert other.exists(), "pruning must not touch a different level"


def test_it_never_deletes_the_file_it_just_wrote(ranker):
    model = _trained(ranker)
    ranker._save_model("vocab", "A1", model)
    current = ranker._model_path("vocab", "A1")
    assert current.exists()
    assert current.stat().st_size > 0


def test_saving_twice_is_stable(ranker):
    model = _trained(ranker)
    ranker._save_model("vocab", "A1", model)
    ranker._save_model("vocab", "A1", model)
    matches = list((ranker.model_dir).glob("vocab__a1__*.joblib"))
    assert len(matches) == 1


def test_an_unsaveable_model_prunes_nothing(ranker, tmp_path):
    """A model with no samples is not persisted, so nothing may be deleted."""
    model_dir = tmp_path / "ml_models"
    model_dir.mkdir(parents=True, exist_ok=True)
    stale = model_dir / "vocab__a1__v2.joblib"
    stale.write_bytes(b"superseded")

    ranker._save_model("vocab", "A1", ranker._load_model("vocab", "A1"))

    assert stale.exists()
