from __future__ import annotations

import json
import sqlite3

import pytest


OBJECTIVES = ("vocab", "grammar", "sentences", "listening")
REVIEW_TABLES = (
    ("reviews", "vocab_id", "typed_meaning", "house"),
    ("grammar_reviews", "grammar_id", "typed_blank", "bin"),
    ("sentence_reviews", "sentence_id", "typed_text", "Ich lerne."),
    ("listening_reviews", "listening_id", "chosen", "Berlin"),
)


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {str(row[1]): row for row in conn.execute(f"PRAGMA table_info({table})")}


def _prepare_v3_review_database(db) -> None:
    """Build the exact additive-migration boundary, including real review rows."""
    from db.init_db import init_db

    init_db(db)
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            INSERT INTO books(id, slug, title) VALUES (1, 'phase-6', 'Phase 6');
            INSERT INTO lektions(id, book_id, level, number, title)
            VALUES (1, 1, 'A1', 1, 'Planner');
            INSERT INTO decks(id, level, lektion_id, objective, name)
            VALUES
              (1, 'A1', 1, 'vocab', 'Vocabulary'),
              (2, 'A1', 1, 'grammar', 'Grammar'),
              (3, 'A1', 1, 'sentences', 'Sentences'),
              (4, 'A1', 1, 'listening', 'Listening');
            INSERT INTO vocab(id, deck_id, pos, word, meaning)
            VALUES (101, 1, 'noun', 'Haus', 'house');
            INSERT INTO grammar(id, deck_id, test_text, answer)
            VALUES (102, 2, 'Ich ___ hier.', 'bin');
            INSERT INTO sentences(id, deck_id, target_text)
            VALUES (103, 3, 'Ich lerne.');
            INSERT INTO listening(id, deck_id, text, question, answer)
            VALUES (104, 4, 'Berlin.', 'Welche Stadt?', 'Berlin');
            """
        )
        for offset, (table, foreign_key, payload_column, payload) in enumerate(
            REVIEW_TABLES,
            start=1,
        ):
            conn.execute(
                f"INSERT INTO {table} "
                f"({foreign_key}, created_at, {payload_column}) VALUES (?, ?, ?)",
                (100 + offset, 1_700_000_000 + offset, payload),
            )
            if "selection_bucket" in _columns(conn, table):
                conn.execute(f"ALTER TABLE {table} DROP COLUMN selection_bucket")
        conn.execute("DELETE FROM schema_migrations WHERE version >= 4")
        conn.execute("PRAGMA user_version=3")
        conn.commit()
    finally:
        conn.close()


def test_fresh_schema_constrains_all_primary_review_selection_buckets(tmp_path):
    from db.init_db import SCHEMA_VERSION, init_db

    db = tmp_path / "fresh-v4.db"
    init_db(db)
    conn = sqlite3.connect(db)
    try:
        assert SCHEMA_VERSION == 4
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4

        for offset, (table, foreign_key, _payload_column, _payload) in enumerate(
            REVIEW_TABLES,
            start=1,
        ):
            column = _columns(conn, table)["selection_bucket"]
            assert column[3] == 1
            assert str(column[4]).strip("'\"") == "legacy"

            conn.execute(
                f"INSERT INTO {table} ({foreign_key}, created_at) VALUES (?, ?)",
                (200 + offset, 1_800_000_000 + offset),
            )
            assert conn.execute(
                f"SELECT selection_bucket FROM {table} WHERE {foreign_key}=?",
                (200 + offset,),
            ).fetchone()[0] == "legacy"

            with pytest.raises(sqlite3.IntegrityError, match="selection_bucket"):
                conn.execute(
                    f"INSERT INTO {table} "
                    f"({foreign_key}, created_at, selection_bucket) VALUES (?, ?, ?)",
                    (300 + offset, 1_900_000_000 + offset, "surprise"),
                )
    finally:
        conn.close()


def test_v3_upgrade_backs_up_then_preserves_reviews_as_legacy(tmp_path):
    from db.backup import BackupService
    from db.init_db import init_db

    db = tmp_path / "upgrade-v3.db"
    _prepare_v3_review_database(db)

    init_db(db)

    backups = [
        item
        for item in BackupService(db).list()
        if item.reason == "pre-schema-3-to-4"
    ]
    assert len(backups) == 1
    backup = sqlite3.connect(backups[0].path)
    try:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 3
        for table, _foreign_key, payload_column, payload in REVIEW_TABLES:
            assert "selection_bucket" not in _columns(backup, table)
            assert backup.execute(
                f"SELECT {payload_column} FROM {table}"
            ).fetchone()[0] == payload
    finally:
        backup.close()

    upgraded = sqlite3.connect(db)
    try:
        assert upgraded.execute("PRAGMA user_version").fetchone()[0] == 4
        for table, _foreign_key, payload_column, payload in REVIEW_TABLES:
            assert upgraded.execute(
                f"SELECT {payload_column}, selection_bucket FROM {table}"
            ).fetchone() == (payload, "legacy")
    finally:
        upgraded.close()


def test_v3_upgrade_backup_failure_leaves_database_untouched(
    tmp_path,
    monkeypatch,
):
    import db.init_db as init_module

    db = tmp_path / "backup-failure.db"
    _prepare_v3_review_database(db)

    monkeypatch.setattr(
        init_module.BackupService,
        "create",
        lambda _service, _reason: None,
    )
    with pytest.raises(RuntimeError, match="safety backup failed"):
        init_module.init_db(db)

    unchanged = sqlite3.connect(db)
    try:
        assert unchanged.execute("PRAGMA user_version").fetchone()[0] == 3
        for table, _foreign_key, payload_column, payload in REVIEW_TABLES:
            assert "selection_bucket" not in _columns(unchanged, table)
            assert unchanged.execute(
                f"SELECT {payload_column} FROM {table}"
            ).fetchone()[0] == payload
    finally:
        unchanged.close()


def test_planner_settings_default_to_independent_equal_objective_maps():
    from core.settings import AppSettings

    first = AppSettings()
    second = AppSettings()

    assert first.planner_due_caps == {objective: 30 for objective in OBJECTIVES}
    assert first.planner_new_caps == {objective: 8 for objective in OBJECTIVES}
    assert first.planner_weights == {objective: 1 for objective in OBJECTIVES}
    assert first.planner_weighted_mix is False

    first.planner_due_caps["vocab"] = 0
    assert second.planner_due_caps["vocab"] == 30


def test_old_new_card_limit_populates_missing_per_objective_new_caps(tmp_path):
    from core.settings import SettingsService

    path = tmp_path / "old-settings.json"
    path.write_text(json.dumps({"new_card_limit": "12"}), encoding="utf-8")

    value = SettingsService(path).value

    assert value.new_card_limit == 12
    assert value.planner_new_caps == {objective: 12 for objective in OBJECTIVES}


def test_planner_maps_normalize_known_keys_ranges_and_types(tmp_path):
    from core.settings import SettingsService

    path = tmp_path / "planner-settings.json"
    path.write_text(
        json.dumps(
            {
                "planner_due_caps": {
                    "vocab": True,
                    "grammar": "25",
                    "sentences": 201,
                    "listening": -3,
                    "future": 77,
                },
                "planner_new_caps": {
                    "vocab": 5.0,
                    "grammar": "8.5",
                    "sentences": -1,
                    "listening": 99,
                    "future": 12,
                },
                "planner_weights": {
                    "vocab": 0,
                    "grammar": "3",
                    "sentences": 101,
                    "listening": False,
                    "future": 4,
                },
                "planner_weighted_mix": "yes",
            }
        ),
        encoding="utf-8",
    )

    value = SettingsService(path).value

    assert value.planner_due_caps == {
        "vocab": 30,
        "grammar": 25,
        "sentences": 200,
        "listening": 0,
    }
    assert value.planner_new_caps == {
        "vocab": 5,
        "grammar": 8,
        "sentences": 0,
        "listening": 30,
    }
    assert value.planner_weights == {
        "vocab": 1,
        "grammar": 3,
        "sentences": 100,
        "listening": 1,
    }
    assert value.planner_weighted_mix is True


def test_partial_planner_map_update_preserves_existing_objective_values(tmp_path):
    from core.settings import SettingsService

    service = SettingsService(tmp_path / "settings.json")
    service.update(planner_due_caps={"grammar": 44})

    value = service.update(planner_due_caps={"vocab": 15})

    assert value.planner_due_caps == {
        "vocab": 15,
        "grammar": 44,
        "sentences": 30,
        "listening": 30,
    }
    assert SettingsService(service.path).value == value


def test_planner_map_aliases_are_canonical_and_exact_keys_win(tmp_path):
    from core.settings import SettingsService

    path = tmp_path / "planner-aliases.json"
    path.write_text(
        json.dumps(
            {
                "planner_due_caps": {
                    "vocabulary": 11,
                    "vocab": 12,
                    "sentence": 13,
                    "future-objective": 99,
                }
            }
        ),
        encoding="utf-8",
    )

    value = SettingsService(path).value

    assert value.planner_due_caps == {
        "vocab": 12,
        "grammar": 30,
        "sentences": 13,
        "listening": 30,
    }
