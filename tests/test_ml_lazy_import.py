from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_session_import_does_not_eagerly_load_ml_stack():
    """Opening MAHIRA must not import sklearn/scipy before a model is used."""

    src = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(src), env.get("PYTHONPATH", "")) if part
    )
    code = (
        "import sys; import core.session; "
        "heavy=('sklearn', 'scipy', 'joblib'); "
        "loaded=[name for name in heavy if name in sys.modules]; "
        "assert not loaded, loaded"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_new_model_keeps_backend_lazy_until_training(monkeypatch):
    from core.ml import sklearn_ranker as module

    for name in (
        "_SKLEARN_OK",
        "joblib",
        "np",
        "SGDRegressor",
        "StandardScaler",
    ):
        monkeypatch.setattr(module, name, None)
    model = module._OnlineDifficultyModel()

    assert module._SKLEARN_OK is None
    assert model.predict_many([[0.0] * 18]) == [0.5]
    assert module._SKLEARN_OK is None
