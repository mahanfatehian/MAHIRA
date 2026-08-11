from __future__ import annotations

import pytest


def test_vocab_ml_aggregates_and_readiness_ignore_lab_reviews(tmp_path):
    from core.ml.sklearn_ranker import SklearnRanker
    from db.init_db import init_db
    from db.repo import Repo

    db = tmp_path / "ml-lanes.db"
    init_db(db)
    repo = Repo(db)
    deck, _ = repo.upsert_deck("A1", "vocab", "ml.csv", "ml-sha")
    first = repo.insert_vocab(
        deck, "noun", "Haus", "das", "n", "Haeuser", "house"
    )
    lab_only = repo.insert_vocab(
        deck, "noun", "Stadt", "die", "f", "Staedte", "city"
    )
    with repo._conn() as conn:
        conn.execute(
            """
            INSERT INTO reviews(
                vocab_id, rating, meaning_correct, response_ms, practice_mode
            ) VALUES (?, 2, 1, 100, 'recognition')
            """,
            (first,),
        )
        for item_id, lane, response_ms in (
            (first, "production", 900),
            (first, "dictation", 800),
            (lab_only, "production", 700),
        ):
            conn.execute(
                """
                INSERT INTO reviews(
                    vocab_id, rating, meaning_correct, response_ms, practice_mode
                ) VALUES (?, 0, 0, ?, ?)
                """,
                (item_id, response_ms, lane),
            )

    ranker = SklearnRanker(repo, tmp_path / "models")
    rows = ranker._fetch_vocab_rows([first, lab_only])
    assert rows[first]["total_reviews"] == 1
    assert rows[first]["avg_rating"] == pytest.approx(2.0)
    assert rows[first]["meaning_acc"] == pytest.approx(1.0)
    assert rows[first]["avg_response_ms"] == pytest.approx(100.0)
    assert rows[lab_only]["total_reviews"] == 0
    assert rows[lab_only]["avg_rating"] is None
    assert ranker._review_count(objective="vocab", level=None) == 1


def test_vocab_model_version_ignores_pre_isolation_cache(tmp_path, monkeypatch):
    from core.ml import sklearn_ranker as module
    from core.ml.sklearn_ranker import SklearnRanker

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    old_path = model_dir / "vocab__a1__v2.joblib"
    old_path.write_bytes(b"stale model")
    loaded = []

    class _JoblibStub:
        @staticmethod
        def load(path):
            loaded.append(path)
            raise AssertionError("the stale vocabulary model must not be loaded")

    monkeypatch.setattr(module, "_ensure_sklearn_backend", lambda: True)
    monkeypatch.setattr(module, "joblib", _JoblibStub())

    ranker = SklearnRanker(object(), model_dir)
    model = ranker._load_model("vocab", "A1")

    assert model is not None
    assert loaded == []
    assert ranker._model_path("vocab", "A1").name == "vocab__a1__v3.joblib"
    assert ranker._model_path("grammar", "A1").name == "grammar__a1__v2.joblib"
