# src/db/init_db.py
from __future__ import annotations

import json
import re
from pathlib import Path

from db.connection import connect


def _has_column(conn, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any((r[1] == col) for r in rows)


def _ensure_column(conn, table: str, col: str, col_def_sql: str) -> None:
    try:
        if not _has_column(conn, table, col):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def_sql}")
    except Exception:
        pass


_TOKEN_RE = re.compile(
    r"[A-Za-zÄÖÜäöüß]+(?:[-'][A-Za-zÄÖÜäöüß]+)*|\d+|[.,!?;:()\[\]{}\"“”„‚’‘…–—-]"
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text or "") if t and not t.isspace()]


def _looks_like_json_list(s: str) -> bool:
    s = (s or "").strip()
    return s.startswith("[") and s.endswith("]")


def _repair_sentences(conn) -> None:
    # only if table exists
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sentences'"
    ).fetchone()
    if not row:
        return

    rows = conn.execute("SELECT id, target_text, words_json FROM sentences").fetchall()

    for r in rows:
        try:
            sid = int(r["id"])
            target = (r["target_text"] or "").strip()
            if not target:
                continue

            words_raw = str(r["words_json"] or "").strip()
            req_raw = str(r["required_json"] or "").strip()

            # words_json fix
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

            # required_json fix
            if req_raw and (not _looks_like_json_list(req_raw)):
                if "|" in req_raw:
                    req = [x.strip() for x in req_raw.split("|") if x.strip()]
                else:
                    req = [x.strip() for x in re.split(r"[,;]", req_raw) if x.strip()]
                conn.execute(
                    "UPDATE sentences SET required_json=? WHERE id=?",
                    (json.dumps(req, ensure_ascii=False), sid),
                )
        except Exception:
            continue


def init_db(db_path: str | Path, schema_path: str | Path | None = None) -> None:
    db_path = Path(db_path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if schema_path is None:
        schema_path = Path(__file__).with_name("schema.sql")
    else:
        schema_path = Path(schema_path).expanduser().resolve()

    conn = connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(schema_path.read_text(encoding="utf-8"))

        _ensure_column(conn, "sentence_reviews", "translation_used", "INTEGER NOT NULL DEFAULT 0")

        _repair_sentences(conn)

        conn.commit()
    finally:
        conn.close()