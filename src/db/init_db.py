# src/db/init_db.py
from __future__ import annotations

import json
import re
from pathlib import Path

from db.connection import connect


def _has_column(conn, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any((r[1] == col) for r in rows)


def _has_table(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _ensure_column(conn, table: str, col: str, col_def_sql: str) -> None:
    try:
        if not _has_column(conn, table, col):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def_sql}")
    except Exception:
        pass


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


def init_db(db_path: str | Path, schema_path: str | Path | None = None) -> None:
    db_path = Path(db_path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if schema_path is None:
        schema_path = Path(__file__).with_name("schema.sql")
    else:
        schema_path = Path(schema_path).expanduser().resolve()

    schema_sql = schema_path.read_text(encoding="utf-8")

    # Check if a reset is needed before applying new schema
    if db_path.exists():
        conn = connect(db_path)
        try:
            needs_reset = _needs_full_reset(conn)
        finally:
            conn.close()

        if needs_reset:
            # Old schema (no books/lektions). Seeds are always reimported so
            # dropping and recreating is the cleanest migration path.
            db_path.unlink(missing_ok=True)

    conn = connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(schema_sql)

        _ensure_column(conn, "sentence_reviews", "translation_used", "INTEGER NOT NULL DEFAULT 0")

        # FSRS memory model columns. Added in-place (no reset) on existing DBs;
        # left NULL so the scheduler migrates each item lazily on its next review.
        for _tbl in ("vocab_states", "grammar_states", "sentence_states"):
            _ensure_column(conn, _tbl, "stability", "REAL")
            _ensure_column(conn, _tbl, "difficulty", "REAL")

        _repair_sentences(conn)

        conn.commit()
    finally:
        conn.close()
