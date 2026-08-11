from __future__ import annotations

import os
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _vocab_library(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / ".mahira" / "mahira.db"
    init_db(db_path)
    repo = Repo(db_path)
    book_id = repo.ensure_book("drills", "Drills")
    lesson_id = repo.ensure_lektion(book_id, "A1", 1, "Target lesson")
    other_lesson_id = repo.ensure_lektion(book_id, "A1", 2, "Other lesson")
    deck_id, _changed = repo.upsert_deck(
        "A1", "vocab", "drills.csv", "drills-sha", lektion_id=lesson_id
    )
    ids = [
        repo.insert_vocab(
            deck_id,
            "noun",
            word,
            article,
            gender,
            plural,
            meaning,
        )
        for word, article, gender, plural, meaning in (
            ("Haus", "das", "n", "Häuser", "house"),
            ("Stadt", "die", "f", "Städte", "city"),
            ("Tag", "der", "m", "Tage", "day"),
            ("Buch", "das", "n", "Bücher", "book"),
        )
    ]
    other_deck, _changed = repo.upsert_deck(
        "A1",
        "vocab",
        "other.csv",
        "other-sha",
        lektion_id=other_lesson_id,
    )
    foreign_id = repo.insert_vocab(
        other_deck, "noun", "Zeit", "die", "f", "Zeiten", "time"
    )
    return repo, deck_id, ids, foreign_id


def _session(repo):
    from core.session import AppState, SessionService

    session = SessionService(repo, AppState("A1", "vocab", "drills", 1))
    session.set_context("A1", "vocab", "drills", 1)
    session.enable_ml_ranking = False
    session.plan.limit = 10
    session.plan.new_limit = 10
    return session


def test_targeted_session_revalidates_scope_controls_and_order(tmp_path):
    repo, _deck_id, ids, foreign_id = _vocab_library(tmp_path)
    session = _session(repo)
    active_first, suspended, buried, active_last = ids
    repo.ensure_state(suspended)
    repo.ensure_state(buried)
    with repo._conn() as conn:
        conn.execute(
            "UPDATE vocab_states SET suspended=1 WHERE vocab_id=?",
            (suspended,),
        )
        conn.execute(
            "UPDATE vocab_states SET buried_until=? WHERE vocab_id=?",
            (int(time.time()) + 3600, buried),
        )

    requested = [active_last, foreign_id, active_first, active_last, suspended, buried]
    assert session.targeted_item_ids("vocab", requested) == [
        active_last,
        active_first,
    ]

    assert session.start_targeted_session("vocab", requested) is True
    assert session._session_kind == "drill"
    assert session.remaining() == 2
    assert session.next_vocab_item().id == active_last
    assert session.next_vocab_item().id == active_first
    assert session.next_vocab_item() is None


def test_invalid_target_set_does_not_replace_an_open_review(tmp_path):
    repo, _deck_id, _ids, foreign_id = _vocab_library(tmp_path)
    session = _session(repo)
    assert session.start_new_session() is True
    queue_before = list(session._queue)

    assert session.start_targeted_session("vocab", [foreign_id]) is False
    assert session._queue == queue_before
    assert session._session_kind == "review"


def test_three_card_drill_writes_normal_ratings_without_copying_content(tmp_path):
    repo, _deck_id, ids, _foreign_id = _vocab_library(tmp_path)
    session = _session(repo)
    selected = ids[:3]
    checkpoint = repo.db_path.parent / "active_session.json"

    # A targeted drill explicitly replaces an ordinary checkpoint, but is not
    # serialized as an ordinary resumable review session itself.
    assert session.start_new_session() is True
    assert checkpoint.exists()
    assert session.start_targeted_session("vocab", selected) is True
    assert not checkpoint.exists()

    with repo._conn() as conn:
        deck_count_before = conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0]
        item_count_before = conn.execute("SELECT COUNT(*) FROM vocab").fetchone()[0]

    served: list[int] = []
    item = session.next_vocab_item()
    while item is not None:
        served.append(item.id)
        result = session.submit_vocab(
            item,
            typed_meaning=item.meaning,
            typed_gender=item.gender or "",
            typed_plural=item.plural or "",
            rating=2,
            tip_used=False,
            gender_tip_used=False,
            was_checked=True,
            was_skipped=False,
            response_ms=500,
        )
        assert result["effective_rating"] == 2
        item = session.next_vocab_item()

    assert served == selected
    with repo._conn() as conn:
        rows = conn.execute(
            "SELECT vocab_id, rating, practice_mode FROM reviews ORDER BY id"
        ).fetchall()
        assert [(row["vocab_id"], row["rating"], row["practice_mode"]) for row in rows] == [
            (item_id, 2, "recognition") for item_id in selected
        ]
        assert conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0] == deck_count_before
        assert conn.execute("SELECT COUNT(*) FROM vocab").fetchone()[0] == item_count_before
    assert all(repo.ensure_state(item_id).reps == 1 for item_id in selected)
    assert not checkpoint.exists()


def test_practice_lab_targeted_drill_stops_instead_of_refilling(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from ui.pages.practice_lab import PracticeLabPage

    app = QApplication.instance() or QApplication([])
    repo, _deck_id, ids, _foreign_id = _vocab_library(tmp_path)
    session = _session(repo)
    page = PracticeLabPage(session)
    monkeypatch.setattr(
        page,
        "_pick_ids",
        lambda _deck_id: pytest.fail("a one-off drill must not refill"),
    )
    try:
        assert page.start_targeted_drill(ids[:2], "production") is True
        page.on_show()
        assert page.current.id == ids[0]

        page._load_next()
        assert page.current.id == ids[1]
        page._load_next()

        assert page.current is None
        assert "complete" in page.prompt.text().lower()
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
