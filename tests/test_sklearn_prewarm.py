"""Ranking must never wait for scikit-learn to import.

scikit-learn, scipy and numpy cost roughly 1.1 s to import together. That used
to happen on the GUI thread the first time anything ranked - which is while the
very first page paints - and again on the first rating click of a session.

The ranker is documented to augment the deterministic recall priority and never
to gate it, so an unimported backend is already a supported state: the model
stays unfitted, the blend weight is zero, and ordering falls back to priority.
"""

from __future__ import annotations

import pytest

from core.ml import sklearn_ranker


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Never disturb the process-wide backend state other tests rely on."""
    monkeypatch.setattr(sklearn_ranker, "_SKLEARN_WARM_THREAD", None, raising=False)
    yield


def test_ready_is_false_and_fast_before_the_import(monkeypatch):
    monkeypatch.setattr(sklearn_ranker, "_SKLEARN_OK", None, raising=False)
    started = []
    monkeypatch.setattr(
        sklearn_ranker, "prewarm_sklearn_backend", lambda: started.append(1)
    )
    assert sklearn_ranker._sklearn_backend_ready() is False
    assert started == [1], "a miss must kick off the warm-up"


def test_ready_reports_true_once_loaded(monkeypatch):
    monkeypatch.setattr(sklearn_ranker, "_SKLEARN_OK", True, raising=False)
    assert sklearn_ranker._sklearn_backend_ready() is True


def test_ready_reports_false_when_the_stack_is_genuinely_absent(monkeypatch):
    monkeypatch.setattr(sklearn_ranker, "_SKLEARN_OK", False, raising=False)
    assert sklearn_ranker._sklearn_backend_ready() is False


def test_prewarm_is_a_no_op_once_resolved(monkeypatch):
    monkeypatch.setattr(sklearn_ranker, "_SKLEARN_OK", True, raising=False)
    made = []
    monkeypatch.setattr(
        sklearn_ranker.threading,
        "Thread",
        lambda **kw: made.append(kw) or _Fake(),
    )
    sklearn_ranker.prewarm_sklearn_backend()
    assert made == []


def test_prewarm_starts_one_daemon_thread(monkeypatch):
    monkeypatch.setattr(sklearn_ranker, "_SKLEARN_OK", None, raising=False)
    made = []
    monkeypatch.setattr(
        sklearn_ranker.threading,
        "Thread",
        lambda **kw: made.append(kw) or _Fake(),
    )
    sklearn_ranker.prewarm_sklearn_backend()
    sklearn_ranker.prewarm_sklearn_backend()
    assert len(made) == 1
    assert made[0]["daemon"] is True
    assert made[0]["target"] is sklearn_ranker._ensure_sklearn_backend


class _Fake:
    def start(self):
        return None

    def is_alive(self):
        return True


# --------------------------------------------------------------------------
# The invariant this relies on
# --------------------------------------------------------------------------

def test_an_unloaded_backend_leaves_ranking_deterministic(tmp_path, monkeypatch):
    """The fallback must be the documented priority order, not a broken one."""
    from db.init_db import init_db
    from db.repo import Repo

    db = tmp_path / "rank.db"
    init_db(db)
    repo = Repo(db)
    deck_id, _ = repo.upsert_deck("A1", "vocab", "v.csv", "sha")
    ids = [
        repo.insert_vocab(deck_id, "noun", f"W{i}", "das", "n", None, f"m{i}")
        for i in range(12)
    ]

    ranker = sklearn_ranker.SklearnRanker(repo, model_dir=tmp_path / "models")
    monkeypatch.setattr(sklearn_ranker, "_SKLEARN_OK", None, raising=False)
    monkeypatch.setattr(sklearn_ranker, "prewarm_sklearn_backend", lambda: None)

    ranked = ranker.rank_vocab_ids(list(ids))
    assert sorted(ranked) == sorted(ids), "every card must survive ranking"
    # A fresh all-unseen deck is introduced in natural order once reversed.
    assert list(reversed(ranked)) == sorted(ids)
