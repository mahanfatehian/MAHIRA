from __future__ import annotations

import sqlite3


def test_schema_upgrade_creates_a_restorable_pre_migration_backup(tmp_path):
    from db.backup import BackupService
    from db.init_db import SCHEMA_VERSION, init_db

    db = tmp_path / "backup-first.db"
    init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO books(slug, title, created_at) VALUES (?, ?, ?)",
        ("phase-zero", "Phase Zero", 0),
    )
    conn.execute("DROP TABLE vocab_practice_states")
    conn.execute("PRAGMA user_version=2")
    conn.commit()
    conn.close()

    init_db(db)

    service = BackupService(db)
    migration_backups = [
        item
        for item in service.list()
        if item.reason == f"pre-schema-2-to-{SCHEMA_VERSION}"
    ]
    assert len(migration_backups) == 1
    backup = migration_backups[0]

    check = sqlite3.connect(backup.path)
    assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert check.execute("PRAGMA user_version").fetchone()[0] == 2
    assert check.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='vocab_practice_states'"
    ).fetchone() is None
    assert check.execute(
        "SELECT title FROM books WHERE slug='phase-zero'"
    ).fetchone()[0] == "Phase Zero"
    check.close()

    service.restore(backup.path)
    restored = sqlite3.connect(db)
    assert restored.execute("PRAGMA user_version").fetchone()[0] == 2
    assert restored.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='vocab_practice_states'"
    ).fetchone() is None
    assert restored.execute(
        "SELECT title FROM books WHERE slug='phase-zero'"
    ).fetchone()[0] == "Phase Zero"
    restored.close()

    init_db(db)
    upgraded = sqlite3.connect(db)
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert upgraded.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='vocab_practice_states'"
    ).fetchone() == (1,)
    assert upgraded.execute(
        "SELECT title FROM books WHERE slug='phase-zero'"
    ).fetchone()[0] == "Phase Zero"
    upgraded.close()
