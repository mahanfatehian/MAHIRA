"""End-to-end: real schema + seeds -> session selection -> FSRS review round-trip."""

import sqlite3
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "src" / "db" / "schema.sql"


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo
    from db.seed_loader import load_all_seeds

    db_path = tmp_path / "mahira.db"
    init_db(db_path, SCHEMA)
    r = Repo(db_path)
    load_all_seeds(r, REPO_ROOT)
    return r


def _session(repo):
    from core.session import SessionService, AppState

    s = SessionService(repo, AppState())
    s.set_context("A1", "vocab", book_slug="starten_wir", lektion_number=1)
    return s


def test_session_builds_a_queue_without_duplicates(repo):
    s = _session(repo)
    assert s.start_new_session() is True
    assert s.remaining() > 0

    seen = []
    item = s.next_vocab_item()
    while item is not None:
        seen.append(item.id)
        item = s.next_vocab_item()

    assert seen, "session produced no items"
    assert len(seen) == len(set(seen)), "session contained duplicate items"
    assert len(seen) <= s.plan.limit


def test_review_persists_fsrs_state_and_schedules_forward(repo):
    s = _session(repo)
    s.start_new_session()
    item = s.next_vocab_item()
    assert item is not None

    now = int(time.time())
    meaning = (item.meaning or "").split(";")[0].strip()

    res = s.submit_vocab(
        item,
        typed_meaning=meaning,
        typed_gender=(item.gender or ""),
        typed_plural=(item.plural or ""),
        rating=2,  # Good
        tip_used=False,
        gender_tip_used=False,
        was_checked=True,
        was_skipped=False,
        response_ms=1500,
    )
    assert res["meaning_ok"] is True

    st = repo.ensure_state(item.id)
    # FSRS latent variables must now be populated...
    assert st.stability is not None and st.stability > 0
    assert st.difficulty is not None and 1.0 <= st.difficulty <= 10.0
    assert st.reps >= 1
    # ...and a correct first review schedules at least a day out (not a relapse).
    assert st.due_at > now + 86_400


def test_failed_review_enters_short_relearning_step(repo):
    s = _session(repo)
    s.start_new_session()
    item = s.next_vocab_item()
    assert item is not None

    now = int(time.time())
    res = s.submit_vocab(
        item,
        typed_meaning="",
        typed_gender="",
        typed_plural="",
        rating=2,
        tip_used=False,
        gender_tip_used=False,
        was_checked=True,
        was_skipped=True,  # skip -> Again
        response_ms=1000,
    )
    assert res["effective_rating"] == 0

    st = repo.ensure_state(item.id)
    # Relearning step: due back within minutes, not blocked for hours.
    assert now < st.due_at <= now + 3600
    assert st.stability is not None


def test_migration_adds_fsrs_columns_to_legacy_db(tmp_path):
    """An old DB whose *_states tables lack stability/difficulty must gain them
    in-place, with no data loss."""
    from db.init_db import init_db

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    # Minimal legacy schema fragment WITHOUT the FSRS columns, plus the marker
    # tables that _needs_full_reset checks so it does NOT trigger a rebuild.
    conn.executescript(
        """
        CREATE TABLE books (id INTEGER PRIMARY KEY, slug TEXT);
        CREATE TABLE lektions (id INTEGER PRIMARY KEY, book_id INTEGER, level TEXT, number INTEGER);
        CREATE TABLE decks (id INTEGER PRIMARY KEY, level TEXT, lektion_id INTEGER, objective TEXT);
        CREATE TABLE vocab (id INTEGER PRIMARY KEY, deck_id INTEGER);
        CREATE TABLE vocab_states (
            id INTEGER PRIMARY KEY, vocab_id INTEGER, ease REAL DEFAULT 2.5,
            interval_days REAL DEFAULT 0, reps INTEGER DEFAULT 0,
            lapses INTEGER DEFAULT 0, due_at INTEGER, last_review_at INTEGER
        );
        INSERT INTO vocab_states(vocab_id, ease, interval_days, reps, due_at)
        VALUES (1, 2.5, 4.0, 2, 123);
        """
    )
    conn.commit()
    conn.close()

    init_db(db_path, SCHEMA)

    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(vocab_states)").fetchall()}
    # legacy row preserved
    row = conn.execute("SELECT reps, interval_days FROM vocab_states WHERE vocab_id=1").fetchone()
    conn.close()

    assert "stability" in cols and "difficulty" in cols
    assert row == (2, 4.0)
