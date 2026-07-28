from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest


def test_reopened_wal_connections_keep_normal_sync(tmp_path):
    from db.connection import connect
    from db.init_db import init_db

    db = tmp_path / "runtime-sync.db"
    init_db(db)

    conn = connect(db)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        conn.close()


def test_schema_upgrade_is_wal_atomic_and_refuses_future_databases(
    tmp_path,
    monkeypatch,
):
    import db.init_db as init_module

    db = tmp_path / "atomic.db"
    init_module.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE vocab_practice_states")
    conn.execute("PRAGMA user_version=2")
    conn.commit()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    conn.close()

    def fail_repair(_conn) -> None:
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(init_module, "_repair_sentences", fail_repair)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        init_module.init_db(db)

    check = sqlite3.connect(db)
    assert check.execute("PRAGMA user_version").fetchone()[0] == 2
    assert check.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='vocab_practice_states'"
    ).fetchone() is None
    check.close()

    future = tmp_path / "future.db"
    conn = sqlite3.connect(future)
    conn.execute("CREATE TABLE future_only(value TEXT)")
    conn.execute("INSERT INTO future_only VALUES ('preserve me')")
    conn.execute("PRAGMA user_version=99")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="newer MAHIRA version"):
        init_module.init_db(future)
    check = sqlite3.connect(future)
    assert check.execute("PRAGMA user_version").fetchone()[0] == 99
    assert check.execute("SELECT value FROM future_only").fetchone()[0] == "preserve me"
    check.close()


def test_windows_legacy_state_move_is_verified_and_retryable(tmp_path, monkeypatch):
    import mahira.config as config

    install = tmp_path / "install"
    legacy = install / config.STATE_DIRNAME
    legacy.mkdir(parents=True)
    executable = install / "MAHIRA.exe"
    executable.touch()
    legacy_db = legacy / config.DB_FILENAME
    conn = sqlite3.connect(legacy_db)
    conn.execute("CREATE TABLE history(value TEXT)")
    conn.execute("INSERT INTO history VALUES ('kept')")
    conn.commit()
    conn.close()
    (legacy / "settings.json").write_text(
        '{"daily_goal": 25}',
        encoding="utf-8",
    )

    # Windows user-data paths may legally contain percent signs. The migration
    # integrity check must not decode percent-like filename text as a URI.
    target = tmp_path / "local %23 app data" / config.STATE_DIRNAME
    monkeypatch.setattr(config, "is_frozen", lambda: True)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setattr(config.sys, "executable", str(executable))

    paths = SimpleNamespace(state_dir=target)
    assert config.migrate_legacy_windows_state(paths)
    check = sqlite3.connect(target / config.DB_FILENAME)
    assert check.execute("SELECT value FROM history").fetchone()[0] == "kept"
    check.close()
    assert not list(target.parent.glob(f"{config.STATE_DIRNAME}.migrating-*"))
    assert not config.migrate_legacy_windows_state(paths)
