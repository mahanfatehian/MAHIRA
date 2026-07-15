from __future__ import annotations

import json
import sqlite3

import pytest


def test_settings_round_trip_and_ignores_unknown_fields(tmp_path):
    from core.settings import SettingsService

    path = tmp_path / "settings.json"
    service = SettingsService(path)
    service.update(daily_goal=42, font_scale=115, future_key="ignored")
    loaded = SettingsService(path).value
    assert loaded.daily_goal == 42
    assert loaded.font_scale == 115
    assert not hasattr(loaded, "future_key")


def test_settings_valid_non_object_json_uses_safe_defaults(tmp_path):
    from core.settings import AppSettings, SettingsService

    path = tmp_path / "settings.json"
    for payload in ([], ["daily_goal"], "settings", 42, None):
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert SettingsService(path).value == AppSettings()


def test_settings_load_normalizes_types_enums_and_ranges(tmp_path):
    from core.settings import SettingsService

    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "level": " a2 ",
                "objective": "GRAMMAR",
                "daily_goal": -20,
                "session_limit": "1000",
                "new_card_limit": "12",
                "audio_speed": 9,
                "audio_autoplay": "false",
                "theme": "HIGH_CONTRAST",
                "font_scale": "115",
                "reduced_motion": "yes",
                "window_width": 100,
                "window_height": 99999,
                "active_profile": "../outside",
            }
        ),
        encoding="utf-8",
    )

    value = SettingsService(path).value
    assert value.level == "A2"
    assert value.objective == "grammar"
    assert value.daily_goal == 5
    assert value.session_limit == 100
    assert value.new_card_limit == 12
    assert value.audio_speed == 1.0
    assert value.audio_autoplay is False
    assert value.theme == "high_contrast"
    assert value.font_scale == 115
    assert value.reduced_motion is True
    assert value.window_width == 860
    assert value.window_height == 4320
    assert value.active_profile == "default"


def test_settings_update_applies_the_same_normalization_as_load(tmp_path):
    from core.settings import SettingsService

    service = SettingsService(tmp_path / "settings.json")
    value = service.update(
        daily_goal=999,
        new_card_limit=-5,
        font_scale=float("nan"),
        update_checks="true",
    )

    assert value.daily_goal == 200
    assert value.new_card_limit == 0
    assert value.font_scale == 100
    assert value.update_checks is True
    assert SettingsService(service.path).value == value


def test_verified_backup_and_retention(tmp_path):
    from db.backup import BackupService

    source = tmp_path / "mahira.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE sample(value TEXT)")
    conn.execute("INSERT INTO sample VALUES ('safe')")
    conn.commit()
    conn.close()

    service = BackupService(source)
    info = service.create("test")
    assert info is not None and info.path.exists()
    check = sqlite3.connect(info.path)
    assert check.execute("SELECT value FROM sample").fetchone()[0] == "safe"
    check.close()


def test_legacy_rebuild_preserves_content_state_and_reviews(tmp_path):
    from db.init_db import SCHEMA_VERSION, init_db

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE decks (
          id INTEGER PRIMARY KEY, language_code TEXT, level TEXT NOT NULL,
          objective TEXT NOT NULL, name TEXT DEFAULT '', seed_file TEXT,
          seed_sha1 TEXT, created_at INTEGER, updated_at INTEGER
        );
        CREATE TABLE vocab (
          id INTEGER PRIMARY KEY, deck_id INTEGER NOT NULL, pos TEXT NOT NULL,
          word TEXT NOT NULL, article TEXT, gender TEXT, gender_tip TEXT,
          plural TEXT, meaning TEXT NOT NULL, notes TEXT, tags TEXT, created_at INTEGER
        );
        CREATE TABLE vocab_states (
          id INTEGER PRIMARY KEY, vocab_id INTEGER NOT NULL, ease REAL,
          interval_days REAL, reps INTEGER, lapses INTEGER, due_at INTEGER,
          last_review_at INTEGER
        );
        CREATE TABLE reviews (
          id INTEGER PRIMARY KEY, vocab_id INTEGER NOT NULL, created_at INTEGER,
          typed_meaning TEXT, rating INTEGER
        );
        INSERT INTO decks VALUES (7, 'de', 'A1', 'vocab', 'Legacy', NULL, NULL, 1, 1);
        INSERT INTO vocab VALUES (11, 7, 'noun', 'Haus', 'das', 'n', NULL, 'Häuser', 'house', NULL, NULL, 1);
        INSERT INTO vocab_states VALUES (3, 11, 2.5, 4, 5, 2, 9999999999, 100);
        INSERT INTO reviews VALUES (9, 11, 100, 'house', 2);
        """
    )
    conn.commit(); conn.close()

    init_db(db)
    migrated = sqlite3.connect(db)
    assert migrated.execute("SELECT word FROM vocab WHERE id=11").fetchone()[0] == "Haus"
    assert migrated.execute("SELECT reps, lapses FROM vocab_states WHERE vocab_id=11").fetchone() == (5, 2)
    assert migrated.execute("SELECT typed_meaning FROM reviews WHERE id=9").fetchone()[0] == "house"
    assert migrated.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    migrated.close()
    assert list((tmp_path / "backups").glob("mahira-*-pre-legacy-migration.db"))


def test_suspended_cards_are_not_selected(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db = tmp_path / "selection.db"
    init_db(db)
    repo = Repo(db)
    deck, _ = repo.upsert_deck("A1", "vocab", "test.csv", "sha")
    first = repo.insert_vocab(deck, "noun", "Haus", "das", "n", "Häuser", "house")
    second = repo.insert_vocab(deck, "noun", "Tag", "der", "m", "Tage", "day")
    repo.ensure_state(first)
    with repo._conn() as conn:
        conn.execute("UPDATE vocab_states SET suspended=1 WHERE vocab_id=?", (first,))
    picked = repo.pick_session_vocab_ids(deck, 20, mode="random_only", cooldown_hours=0)
    assert first not in picked
    assert second in picked


def test_german_feedback_identifies_actionable_error_types():
    from core.german_feedback import classify_german_answer

    assert classify_german_answer("Haus", "das Haus").tags == ("article_missing",)
    assert "capitalization" in classify_german_answer("das haus", "das Haus").tags
    assert "word_order" in classify_german_answer("Heute ich arbeite", "Ich arbeite heute").tags
    assert classify_german_answer("Ich lerne Deutsch.", "Ich lerne Deutsch.").correct


def test_profiles_use_independent_database_paths(tmp_path):
    from core.profiles import ProfileService

    service = ProfileService(tmp_path)
    learner = service.create("Anna Schmidt")
    assert service.db_path("default") == tmp_path / "mahira.db"
    assert service.db_path(learner.slug) == tmp_path / "profiles" / learner.slug / "mahira.db"
    assert ProfileService(tmp_path).list()[-1].name == "Anna Schmidt"


def test_profiles_load_valid_records_independently_and_reject_unsafe_slugs(tmp_path):
    from core.profiles import PROFILE_NAME_MAX_LENGTH, ProfileService

    (tmp_path / "profiles.json").write_text(
        json.dumps(
            [
                {"slug": "anna", "name": "Anna", "created_at": 1},
                None,
                {"slug": "../outside", "name": "Escape", "created_at": 2},
                {"slug": "missing-time", "name": "Broken"},
                {"slug": "ben", "name": " Ben\nLearner ", "created_at": "3"},
                {"slug": "anna", "name": "Duplicate", "created_at": 4},
                {"slug": "con", "name": "Windows device", "created_at": 5},
                {"slug": "x" * 200, "name": "Too long", "created_at": 6},
                {"slug": "long-name", "name": "N" * 200, "created_at": 7},
                {"slug": "after-errors", "name": "Still loaded", "created_at": 8},
            ]
        ),
        encoding="utf-8",
    )

    service = ProfileService(tmp_path)
    profiles = service.list()
    assert [profile.slug for profile in profiles] == [
        "default",
        "anna",
        "ben",
        "long-name",
        "after-errors",
    ]
    assert profiles[2].name == "Ben Learner"
    assert len(profiles[3].name) == PROFILE_NAME_MAX_LENGTH
    assert service.db_path("../outside") == tmp_path / "mahira.db"


def test_profile_creation_bounds_names_slugs_and_avoids_windows_devices(tmp_path):
    from core.profiles import (
        PROFILE_NAME_MAX_LENGTH,
        PROFILE_SLUG_MAX_LENGTH,
        ProfileService,
    )

    service = ProfileService(tmp_path)
    first = service.create("A" * 200)
    second = service.create("A" * 200)
    reserved = service.create("CON")

    assert len(first.name) == PROFILE_NAME_MAX_LENGTH
    assert len(first.slug) <= PROFILE_SLUG_MAX_LENGTH
    assert len(second.slug) <= PROFILE_SLUG_MAX_LENGTH
    assert first.slug != second.slug
    assert reserved.slug == "learner-con"
    assert not (tmp_path / "profiles.tmp").exists()
    assert ProfileService(tmp_path).list()[-1] == reserved

    with pytest.raises(ValueError):
        service.create(123)  # type: ignore[arg-type]


def test_update_version_comparison():
    from core.updates import _version_tuple

    assert _version_tuple("v1.10.0") > _version_tuple("1.9.9")
    assert _version_tuple("0.4.0-beta.1") >= (0, 4, 0)
