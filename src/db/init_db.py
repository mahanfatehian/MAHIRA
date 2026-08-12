# src/db/init_db.py
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from db.connection import connect
from db.backup import BackupService


SCHEMA_VERSION = 4


def _has_column(conn, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any((r[1] == col) for r in rows)


def _has_table(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _ensure_column(conn, table: str, col: str, col_def_sql: str) -> None:
    if not _has_column(conn, table, col):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def_sql}")


def _enable_wal(conn) -> None:
    """Put the learner database in the durable, reader-friendly journal mode."""
    row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
    mode = str(row[0] if row else "").strip().lower()
    if mode != "wal":
        raise RuntimeError(f"SQLite refused WAL mode (reported {mode or 'unknown'})")
    # NORMAL is SQLite's recommended WAL trade-off: committed transactions
    # survive application/process crashes while avoiding a full fsync per page.
    conn.execute("PRAGMA synchronous=NORMAL")


def _verify_database(conn) -> None:
    row = conn.execute("PRAGMA quick_check").fetchone()
    if not row or str(row[0]).strip().lower() != "ok":
        raise RuntimeError(f"Database quick check failed: {row!r}")
    violations = conn.execute("PRAGMA foreign_key_check").fetchmany(10)
    if violations:
        raise RuntimeError(
            "Database contains foreign-key violations; migration was rolled back: "
            f"{violations!r}"
        )


def _checkpoint_before_replacement(db_path: Path) -> None:
    """Make an existing WAL database self-contained before file replacement."""
    conn = connect(db_path)
    try:
        mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if mode == "wal":
            result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if result and int(result[0]) != 0:
                raise RuntimeError(
                    "Legacy migration could not obtain a safe WAL checkpoint"
                )
    finally:
        conn.close()


_TOKEN_RE = re.compile(
    r"[A-Za-zÄÖÜäöüß]+(?:[-'][A-Za-zÄÖÜäöüß]+)*|\d+|[.,!?;:()\[\]{}\"""„‚''…–—-]"
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text or "") if t and not t.isspace()]


def _looks_like_json_list(s: str) -> bool:
    s = (s or "").strip()
    return s.startswith("[") and s.endswith("]")


def _repair_sentences(conn) -> None:
    if not _has_table(conn, "sentences"):
        return

    rows = conn.execute("SELECT id, target_text, words_json FROM sentences").fetchall()

    for r in rows:
        try:
            sid = int(r["id"])
            target = (r["target_text"] or "").strip()
            if not target:
                continue

            words_raw = str(r["words_json"] or "").strip()

            if (not words_raw) or (words_raw == "[]") or (not _looks_like_json_list(words_raw)):
                if "|" in words_raw:
                    words = [t.strip() for t in words_raw.split("|") if t.strip()]
                else:
                    words = []
                if not words:
                    words = _tokenize(target)
                conn.execute(
                    "UPDATE sentences SET words_json=? WHERE id=?",
                    (json.dumps(words, ensure_ascii=False), sid),
                )
        except Exception:
            continue


def _needs_full_reset(conn) -> bool:
    """Return True if DB is an older schema and must be recreated."""
    if not _has_table(conn, "books"):
        return True
    if not _has_table(conn, "lektions"):
        return True
    # If decks exists but has no lektion_id column it's the old schema
    if _has_table(conn, "decks") and not _has_column(conn, "decks", "lektion_id"):
        return True
    # German-only migration: old multi-language schema carried a language_code
    # column on decks/books and a languages table. Rebuild from seeds when seen.
    if _has_table(conn, "decks") and _has_column(conn, "decks", "language_code"):
        return True
    if _has_table(conn, "languages"):
        return True
    # Per-level Lektion identity: lektions gained a `level` column. Rebuild older
    # DBs that key Lektionen only by (book, number).
    if _has_table(conn, "lektions") and not _has_column(conn, "lektions", "level"):
        return True
    return False


_COPY_ORDER = (
    "books", "lektions", "decks", "vocab", "vocab_examples", "vocab_states",
    "vocab_practice_states", "reviews", "grammar", "grammar_states",
    "grammar_reviews", "sentences", "sentence_states", "sentence_reviews",
    "listening", "listening_states", "listening_reviews", "card_flags",
)


def _columns(conn, database: str, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA {database}.table_info({table})").fetchall()
    return [str(row[1]) for row in rows]


def _copy_legacy_data(conn, backup_path: Path) -> None:
    """Copy compatible content and progress from a legacy schema by stable IDs."""
    conn.execute("ATTACH DATABASE ? AS legacy", (str(backup_path),))
    try:
        legacy_tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM legacy.sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.execute("PRAGMA foreign_keys=OFF")
        for table in _COPY_ORDER:
            if table not in legacy_tables or not _has_table(conn, table):
                continue
            expected = int(
                conn.execute(f'SELECT COUNT(*) FROM legacy."{table}"').fetchone()[0]
            )
            new_cols = _columns(conn, "main", table)
            old_cols = _columns(conn, "legacy", table)
            common = [name for name in new_cols if name in old_cols]
            if not common:
                if expected:
                    raise RuntimeError(
                        f"Legacy table {table!r} has {expected} rows but no compatible columns"
                    )
                continue
            quoted = ", ".join(f'"{name}"' for name in common)
            if table == "lektions" and "level" not in old_cols:
                insert_cols = quoted + ', "level"'
                select_cols = quoted + ", COALESCE((SELECT d.level FROM legacy.decks d WHERE d.lektion_id=lektions.id LIMIT 1), 'A1')"
            else:
                insert_cols = select_cols = quoted
            before = int(
                conn.execute(f'SELECT COUNT(*) FROM main."{table}"').fetchone()[0]
            )
            conn.execute(
                f'INSERT OR IGNORE INTO main."{table}" ({insert_cols}) '
                f'SELECT {select_cols} FROM legacy."{table}"'
            )
            copied = int(
                conn.execute(f'SELECT COUNT(*) FROM main."{table}"').fetchone()[0]
            ) - before
            if copied != expected:
                raise RuntimeError(
                    f"Legacy migration would lose rows in {table!r}: "
                    f"expected {expected}, copied {copied}"
                )
        conn.commit()
    finally:
        conn.execute("DETACH DATABASE legacy")
        conn.execute("PRAGMA foreign_keys=ON")


def _rebuild_legacy_database(db_path: Path, schema_sql: str) -> None:
    _checkpoint_before_replacement(db_path)
    backup = BackupService(db_path).create("pre-legacy-migration")
    if backup is None:
        raise RuntimeError("Legacy database could not be backed up")
    temp_path = db_path.with_suffix(".migrating.db")
    temp_path.unlink(missing_ok=True)
    conn = connect(temp_path)
    try:
        conn.executescript(schema_sql)
        _copy_legacy_data(conn, backup.path)
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations(version, description) VALUES (?, ?)",
            (SCHEMA_VERSION, "backup-first legacy schema migration"),
        )
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.commit()
        _verify_database(conn)
    except Exception:
        conn.close()
        temp_path.unlink(missing_ok=True)
        raise
    else:
        conn.close()
    # The original database may have been in WAL mode. It was checkpointed
    # before backup, so these now-stale sidecars must not accompany the newly
    # migrated main file.
    Path(str(db_path) + "-wal").unlink(missing_ok=True)
    Path(str(db_path) + "-shm").unlink(missing_ok=True)
    os.replace(temp_path, db_path)


def init_db(db_path: str | Path, schema_path: str | Path | None = None) -> None:
    db_path = Path(db_path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if schema_path is None:
        schema_path = Path(__file__).with_name("schema.sql")
    else:
        schema_path = Path(schema_path).expanduser().resolve()

    schema_sql = schema_path.read_text(encoding="utf-8")

    existing_version = 0

    # Check if a migration is needed before applying new schema.
    if db_path.exists() and db_path.stat().st_size > 0:
        conn = connect(db_path)
        try:
            needs_reset = _needs_full_reset(conn)
            existing_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()

        if existing_version > SCHEMA_VERSION:
            raise RuntimeError(
                "This learner database was created by a newer MAHIRA version "
                f"(schema {existing_version}; this build supports {SCHEMA_VERSION}). "
                "It was not modified."
            )
        if needs_reset:
            logging.info("Legacy database detected; creating a safety backup and migrating")
            _rebuild_legacy_database(db_path, schema_sql)
            existing_version = SCHEMA_VERSION
        elif existing_version < SCHEMA_VERSION:
            logging.info("Schema upgrade %s -> %s; creating safety backup", existing_version, SCHEMA_VERSION)
            backup = BackupService(db_path).create(
                f"pre-schema-{existing_version}-to-{SCHEMA_VERSION}"
            )
            if backup is None:
                raise RuntimeError("Schema upgrade was stopped because its safety backup failed")

    conn = connect(db_path)
    try:
        _enable_wal(conn)

        # sqlite3.executescript otherwise commits before running and executes
        # each DDL statement outside one explicit migration boundary. BEGIN
        # IMMEDIATE guarantees that schema, repair, and version writes either
        # all commit or all roll back together.
        conn.executescript("BEGIN IMMEDIATE;\n" + schema_sql)

        _ensure_column(conn, "sentence_reviews", "translation_used", "INTEGER NOT NULL DEFAULT 0")

        # FSRS memory model columns. Added in-place (no reset) on existing DBs;
        # left NULL so the scheduler migrates each item lazily on its next review.
        for _tbl in ("vocab_states", "grammar_states", "sentence_states", "listening_states"):
            _ensure_column(conn, _tbl, "stability", "REAL")
            _ensure_column(conn, _tbl, "difficulty", "REAL")
            _ensure_column(conn, _tbl, "suspended", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column(conn, _tbl, "buried_until", "INTEGER")

        for _tbl, default_mode in (
            ("reviews", "recognition"),
            ("grammar_reviews", "production"),
            ("sentence_reviews", "builder"),
            ("listening_reviews", "comprehension"),
        ):
            _ensure_column(conn, _tbl, "practice_mode", f"TEXT NOT NULL DEFAULT '{default_mode}'")
            _ensure_column(conn, _tbl, "error_tags", "TEXT")
            _ensure_column(
                conn,
                _tbl,
                "selection_bucket",
                "TEXT NOT NULL DEFAULT 'legacy' "
                "CHECK(selection_bucket IN ('new', 'due', 'extra', 'legacy'))",
            )

        _repair_sentences(conn)

        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, description) VALUES (?, ?)",
            (SCHEMA_VERSION, "classified primary reviews for the daily planner"),
        )
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

        _verify_database(conn)
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
