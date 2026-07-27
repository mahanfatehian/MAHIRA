from __future__ import annotations

import time
from types import SimpleNamespace

import pytest


@pytest.fixture()
def practice_repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "practice-lanes.db"
    init_db(db_path)
    repo = Repo(db_path)
    deck_id, _ = repo.upsert_deck("A1", "vocab", "test.csv", "test-sha")
    vocab_ids = [
        repo.insert_vocab(deck_id, "noun", "Haus", "das", "n", "Häuser", "house"),
        repo.insert_vocab(deck_id, "noun", "Tag", "der", "m", "Tage", "day"),
        repo.insert_vocab(deck_id, "verb", "lernen", "", "", "", "to learn"),
        repo.insert_vocab(deck_id, "verb", "arbeiten", "", "", "", "to work"),
    ]
    return repo, deck_id, vocab_ids


def _session_shell(repo):
    from core.session import SessionService

    session = object.__new__(SessionService)
    session.repo = repo
    return session


def test_production_review_does_not_mutate_recognition_state(practice_repo):
    repo, _deck_id, vocab_ids = practice_repo
    item = repo.get_vocab_by_id(vocab_ids[0])
    assert item is not None

    recognition_before = repo.ensure_state(item.id)
    result = _session_shell(repo).submit_vocab_production(
        item,
        "das Haus",
        practice_mode="production",
        response_ms=850,
    )

    assert result["ok"] is True
    assert result["practice_mode"] == "production"
    assert repo.ensure_state(item.id) == recognition_before

    production = repo.ensure_vocab_practice_state(item.id, "production")
    assert production.reps == 1
    assert production.stability is not None and production.stability > 0
    with repo._conn() as conn:
        logged = conn.execute(
            "SELECT practice_mode FROM reviews WHERE vocab_id=? ORDER BY id DESC LIMIT 1",
            (item.id,),
        ).fetchone()
    assert logged["practice_mode"] == "production"


@pytest.mark.parametrize("lane", ["production", "dictation"])
def test_lab_reviews_do_not_inflate_recognition_mastery(practice_repo, lane):
    from ui.pages.progress import ProgressPage

    repo, deck_id, vocab_ids = practice_repo
    item = repo.get_vocab_by_id(vocab_ids[0])
    assert item is not None

    result = _session_shell(repo).submit_vocab_production(
        item,
        "das Haus",
        practice_mode=lane,
    )
    assert result["ok"] is True

    page = SimpleNamespace(_conn=repo._conn)
    assert ProgressPage._calculate_mastery(page, deck_id, len(vocab_ids)) == 0

    with repo._conn() as conn:
        conn.execute(
            "INSERT INTO reviews(vocab_id, meaning_correct, practice_mode) "
            "VALUES (?, 1, 'recognition')",
            (item.id,),
        )
    assert ProgressPage._calculate_mastery(page, deck_id, len(vocab_ids)) == 70


def test_production_and_dictation_fsrs_states_are_independent(practice_repo):
    repo, _deck_id, vocab_ids = practice_repo
    item = repo.get_vocab_by_id(vocab_ids[0])
    assert item is not None
    session = _session_shell(repo)

    session.submit_vocab_production(item, "das Haus", practice_mode="production")
    production_after_first = repo.ensure_vocab_practice_state(item.id, "production")

    session.submit_vocab_production(item, "falsch", practice_mode="dictation")
    dictation_after_first = repo.ensure_vocab_practice_state(item.id, "dictation")

    assert repo.ensure_vocab_practice_state(item.id, "production") == production_after_first
    assert production_after_first.reps == 1 and production_after_first.lapses == 0
    assert dictation_after_first.reps == 1 and dictation_after_first.lapses == 1

    session.submit_vocab_production(item, "das Haus", practice_mode="dictation")
    assert repo.ensure_vocab_practice_state(item.id, "production") == production_after_first
    assert repo.ensure_vocab_practice_state(item.id, "dictation").reps == 2
    with repo._conn() as conn:
        recognition_rows = conn.execute(
            "SELECT COUNT(*) FROM vocab_states WHERE vocab_id=?", (item.id,)
        ).fetchone()[0]
    assert recognition_rows == 0


@pytest.mark.parametrize("lane", ["production", "dictation"])
@pytest.mark.parametrize("selection_mode", ["mixed", "due_only", "random_only"])
def test_practice_pickers_never_select_suspended_or_buried_cards(
    practice_repo, lane, selection_mode
):
    repo, deck_id, vocab_ids = practice_repo
    suspended_id, buried_id, active_id, second_active_id = vocab_ids

    # Give every item a due lane row so all selection branches are exercised.
    for vocab_id in vocab_ids:
        repo.ensure_vocab_practice_state(vocab_id, lane)
    repo.ensure_state(suspended_id)
    repo.ensure_state(buried_id)
    with repo._conn() as conn:
        conn.execute(
            "UPDATE vocab_states SET suspended=1 WHERE vocab_id=?",
            (suspended_id,),
        )
        conn.execute(
            "UPDATE vocab_states SET buried_until=? WHERE vocab_id=?",
            (int(time.time()) + 86_400, buried_id),
        )
        conn.execute(
            "UPDATE vocab_practice_states SET due_at=0, last_review_at=NULL "
            "WHERE practice_mode=?",
            (lane,),
        )

    picked = repo.pick_vocab_practice_ids(
        deck_id,
        lane,
        20,
        mode=selection_mode,
        cooldown_hours=0,
    )

    assert suspended_id not in picked
    assert buried_id not in picked
    assert {active_id, second_active_id}.issubset(set(picked))


def test_practice_picker_has_no_flag_bypassing_fallback(practice_repo):
    repo, deck_id, vocab_ids = practice_repo
    future = int(time.time()) + 86_400
    for vocab_id in vocab_ids:
        repo.ensure_state(vocab_id)
    with repo._conn() as conn:
        conn.execute("UPDATE vocab_states SET buried_until=?", (future,))

    for lane in ("production", "dictation"):
        assert repo.pick_vocab_practice_ids(deck_id, lane, 20, mode="mixed") == []
        assert repo.pick_vocab_practice_ids(deck_id, lane, 20, mode="random_only") == []


def test_mixed_picker_does_not_immediately_repeat_not_due_lane_cards(practice_repo):
    repo, deck_id, vocab_ids = practice_repo
    session = _session_shell(repo)
    for vocab_id in vocab_ids:
        item = repo.get_vocab_by_id(vocab_id)
        assert item is not None
        expected = f"{item.article or ''} {item.word}".strip()
        assert session.submit_vocab_production(
            item, expected, practice_mode="production"
        )["ok"] is True

    assert repo.pick_practice_vocab_ids(
        deck_id, "production", limit=20, mode="mixed", cooldown_hours=0
    ) == []


def test_v2_upgrade_adds_lane_table_without_touching_progress(tmp_path):
    from db.init_db import SCHEMA_VERSION, init_db
    from db.repo import Repo

    db_path = tmp_path / "upgrade.db"
    init_db(db_path)
    repo = Repo(db_path)
    deck_id, _ = repo.upsert_deck("A1", "vocab", "old.csv", "old-sha")
    vocab_id = repo.insert_vocab(deck_id, "noun", "Buch", "das", "n", "Bücher", "book")
    state_before = repo.ensure_state(vocab_id)
    with repo._conn() as conn:
        conn.execute("DROP TABLE vocab_practice_states")
        conn.execute("DELETE FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,))
        conn.execute("PRAGMA user_version=2")

    init_db(db_path)
    upgraded = Repo(db_path)

    assert upgraded.ensure_state(vocab_id) == state_before
    assert upgraded.get_vocab_by_id(vocab_id).word == "Buch"
    assert upgraded.ensure_vocab_practice_state(vocab_id, "production").reps == 0
    with upgraded._conn() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_unknown_practice_lane_is_rejected_before_writing(practice_repo):
    repo, _deck_id, vocab_ids = practice_repo
    item = repo.get_vocab_by_id(vocab_ids[0])
    assert item is not None

    with pytest.raises(ValueError, match="production.*dictation"):
        _session_shell(repo).submit_vocab_production(
            item, "das Haus", practice_mode="recognition"
        )

    with repo._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM vocab_practice_states").fetchone()[0] == 0
