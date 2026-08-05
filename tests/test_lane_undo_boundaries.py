from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture()
def lab_session(tmp_path):
    from core.session import AppState, SessionService
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "lab-undo.db"
    init_db(db_path)
    repo = Repo(db_path)
    deck_id, _changed = repo.upsert_deck(
        "A1", "vocab", "lab-undo.csv", "lab-undo-sha"
    )
    item_id = repo.insert_vocab(
        deck_id, "noun", "Haus", "das", "n", "Häuser", "house"
    )

    session = object.__new__(SessionService)
    session.repo = repo
    session.state = AppState(level="A1", objective="vocab")
    session.plan = SimpleNamespace(limit=10)
    session._undo = {"objective": "vocab", "item_id": item_id}
    return session, repo, item_id


def test_building_a_lab_queue_clears_recognition_undo(lab_session):
    session, repo, item_id = lab_session

    picked = session.pick_vocab_practice_ids("production", limit=10)

    assert item_id in picked
    assert session.can_undo() is False
    with repo._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0


def test_failed_lab_submit_does_not_leave_stale_recognition_undo(
    lab_session,
    monkeypatch,
):
    session, repo, item_id = lab_session
    item = repo.get_vocab_by_id(item_id)
    assert item is not None

    def fail_review_write(**_kwargs):
        raise RuntimeError("injected Lab write failure")

    monkeypatch.setattr(repo, "insert_review", fail_review_write)

    with pytest.raises(RuntimeError, match="injected Lab write failure"):
        session.submit_vocab_production(
            item,
            "das Haus",
            practice_mode="production",
            response_ms=500,
        )

    assert session.can_undo() is False
    with repo._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM vocab_practice_states"
        ).fetchone()[0] == 0
