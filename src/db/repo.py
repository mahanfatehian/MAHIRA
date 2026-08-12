from __future__ import annotations

import json
import random
import sqlite3
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from db.connection import connect


def _seed_key(row, fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(row[field] or "").strip().casefold() for field in fields)


def _match_seed_rows(existing, desired, exact_fields, anchor_fields):
    """Pair desired seed rows with stable existing IDs.

    Exact logical identities win. Remaining rows reuse an ID only when a
    weaker anchor has exactly one old and one new candidate, so ambiguous
    homonyms/prompts are never assigned each other's learning history.
    """
    existing_by_exact = defaultdict(list)
    for old_row in existing:
        existing_by_exact[_seed_key(old_row, exact_fields)].append(old_row)

    pairs = []
    used_ids: set[int] = set()
    used_desired: set[int] = set()
    for index, new_row in enumerate(desired):
        candidates = existing_by_exact.get(_seed_key(new_row, exact_fields), [])
        old_row = next(
            (candidate for candidate in candidates if int(candidate["id"]) not in used_ids),
            None,
        )
        if old_row is None:
            continue
        pairs.append((old_row, new_row))
        used_ids.add(int(old_row["id"]))
        used_desired.add(index)

    old_anchors = defaultdict(list)
    for old_row in existing:
        if int(old_row["id"]) in used_ids:
            continue
        anchor = _seed_key(old_row, anchor_fields)
        if any(anchor):
            old_anchors[anchor].append(old_row)

    new_anchors = defaultdict(list)
    for index, new_row in enumerate(desired):
        if index in used_desired:
            continue
        anchor = _seed_key(new_row, anchor_fields)
        if any(anchor):
            new_anchors[anchor].append((index, new_row))

    for anchor, old_rows in old_anchors.items():
        new_rows = new_anchors.get(anchor, [])
        if len(old_rows) != 1 or len(new_rows) != 1:
            continue
        index, new_row = new_rows[0]
        old_row = old_rows[0]
        pairs.append((old_row, new_row))
        used_ids.add(int(old_row["id"]))
        used_desired.add(index)

    removed = [row for row in existing if int(row["id"]) not in used_ids]
    inserted = [row for index, row in enumerate(desired) if index not in used_desired]
    return pairs, removed, inserted


def _delete_seed_rows(conn, table: str, rows) -> None:
    ids = [int(row["id"]) for row in rows]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"DELETE FROM card_flags WHERE item_type=? AND item_id IN ({placeholders})",
        [table, *ids],
    )
    conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", ids)


@dataclass(frozen=True)
class BookInfo:
    id: int
    slug: str
    title: str
    description: Optional[str]


@dataclass(frozen=True)
class LektionInfo:
    id: int
    book_id: int
    level: str
    number: int
    title: str
    description: Optional[str]


@dataclass(frozen=True)
class VocabItem:
    id: int
    deck_id: int
    pos: str
    word: str
    meaning: str
    article: Optional[str]
    gender: Optional[str]
    gender_tip: Optional[str]
    plural: Optional[str]


@dataclass(frozen=True)
class VocabState:
    vocab_id: int
    ease: float
    interval_days: float
    reps: int
    lapses: int
    due_at: int
    last_review_at: Optional[int]
    stability: Optional[float] = None
    difficulty: Optional[float] = None
    id: Optional[int] = None
    suspended: bool = False
    buried_until: Optional[int] = None


@dataclass(frozen=True)
class VocabPracticeState:
    """FSRS state for one active-recall vocabulary lane.

    Recognition continues to use :class:`VocabState`; production and
    dictation each receive an independent row keyed by ``practice_mode``.
    """

    vocab_id: int
    practice_mode: str
    ease: float
    interval_days: float
    reps: int
    lapses: int
    due_at: int
    last_review_at: Optional[int]
    stability: Optional[float] = None
    difficulty: Optional[float] = None


@dataclass(frozen=True)
class GrammarItem:
    id: int
    deck_id: int
    test_text: str
    answer: str
    test_verb: Optional[str]
    tip: Optional[str]
    meaning: Optional[str]
    grammar_tip: Optional[str]


@dataclass(frozen=True)
class GrammarState:
    grammar_id: int
    ease: float
    interval_days: float
    reps: int
    lapses: int
    due_at: int
    last_review_at: Optional[int]
    stability: Optional[float] = None
    difficulty: Optional[float] = None
    id: Optional[int] = None
    suspended: bool = False
    buried_until: Optional[int] = None


@dataclass(frozen=True)
class SentenceItem:
    id: int
    deck_id: int
    target_text: str
    translation: Optional[str]
    tip: Optional[str]
    words: list[str]



@dataclass(frozen=True)
class SentenceState:
    sentence_id: int
    ease: float
    interval_days: float
    reps: int
    lapses: int
    due_at: int
    last_review_at: Optional[int]
    stability: Optional[float] = None
    difficulty: Optional[float] = None
    id: Optional[int] = None
    suspended: bool = False
    buried_until: Optional[int] = None


@dataclass(frozen=True)
class ListeningItem:
    id: int
    deck_id: int
    text: str            # passage read aloud (hidden until answered)
    question: str
    answer: str          # correct option
    distractors: list[str]
    translation: Optional[str]
    tip: Optional[str]


@dataclass(frozen=True)
class ListeningState:
    listening_id: int
    ease: float
    interval_days: float
    reps: int
    lapses: int
    due_at: int
    last_review_at: Optional[int]
    stability: Optional[float] = None
    difficulty: Optional[float] = None
    id: Optional[int] = None
    suspended: bool = False
    buried_until: Optional[int] = None


class Repo:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._active_conn = None

    @contextmanager
    def transaction(self):
        """Reuse one connection for bulk work such as first-run seed import."""
        if self._active_conn is not None:
            yield self._active_conn
            return
        conn = connect(self.db_path)
        self._active_conn = conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._active_conn = None
            conn.close()

    @contextmanager
    def _conn(self):
        if self._active_conn is not None:
            yield self._active_conn
            return
        conn = connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------- Books ----------
    def ensure_book(self, slug: str, title: str, description: str | None = None) -> int:
        slug = (slug or "").lower().strip()
        title = (title or slug).strip()
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO books(slug, title, description, created_at)
                VALUES (?,?,?,?)
                """,
                (slug, title, description, now),
            )
            row = conn.execute(
                "SELECT id FROM books WHERE slug=?",
                (slug,),
            ).fetchone()
            return int(row["id"])

    def get_book_id(self, slug: str) -> int | None:
        slug = (slug or "").lower().strip()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM books WHERE slug=?",
                (slug,),
            ).fetchone()
            return int(row["id"]) if row else None

    def get_books_for_level(self, level: str) -> list[BookInfo]:
        """Return books that have at least one deck for the given level."""
        level = (level or "").upper().strip()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT b.id, b.slug, b.title, b.description
                FROM books b
                JOIN lektions l ON l.book_id = b.id
                JOIN decks d ON d.lektion_id = l.id
                WHERE d.level = ?
                ORDER BY b.title
                """,
                (level,),
            ).fetchall()
        return [
            BookInfo(
                id=int(r["id"]),
                slug=str(r["slug"]),
                title=str(r["title"]),
                description=str(r["description"]) if r["description"] else None,
            )
            for r in rows
        ]

    # ---------- Lektions ----------
    def ensure_lektion(self, book_id: int, level: str, number: int, title: str, description: str | None = None) -> int:
        level = (level or "").upper().strip()
        default_title = f"Lektion {number}"
        title = (title or default_title).strip()
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO lektions(book_id, level, number, title, description, created_at)
                VALUES (?,?,?,?,?,?)
                """,
                (book_id, level, number, title, description, now),
            )
            row = conn.execute(
                "SELECT id, title, description FROM lektions WHERE book_id=? AND level=? AND number=?",
                (book_id, level, number),
            ).fetchone()
            lek_id = int(row["id"])

            # Apply filename metadata to an existing row. A real (non-default)
            # title overwrites; the placeholder "Lektion N" never clobbers a
            # name that was already set. Description is updated when provided.
            new_title = title if title != default_title else (row["title"] or title)
            new_desc = description if description is not None else row["description"]
            if new_title != row["title"] or new_desc != row["description"]:
                conn.execute(
                    "UPDATE lektions SET title=?, description=? WHERE id=?",
                    (new_title, new_desc, lek_id),
                )
            return lek_id

    def get_lektion_id(self, book_id: int, level: str, number: int) -> int | None:
        level = (level or "").upper().strip()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM lektions WHERE book_id=? AND level=? AND number=?",
                (book_id, level, number),
            ).fetchone()
            return int(row["id"]) if row else None

    def get_lektions_for_book_level(self, book_id: int, level: str) -> list[LektionInfo]:
        """Return lektions for the given book and level that have at least one deck."""
        level = (level or "").upper().strip()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT l.id, l.book_id, l.level, l.number, l.title, l.description
                FROM lektions l
                JOIN decks d ON d.lektion_id = l.id
                WHERE l.book_id = ? AND l.level = ? AND d.level = ?
                ORDER BY l.number
                """,
                (book_id, level, level),
            ).fetchall()
        return [
            LektionInfo(
                id=int(r["id"]),
                book_id=int(r["book_id"]),
                level=str(r["level"]),
                number=int(r["number"]),
                title=str(r["title"]),
                description=str(r["description"]) if r["description"] else None,
            )
            for r in rows
        ]

    # ---------- Decks / seeds ----------
    def upsert_deck(
        self,
        level: str,
        objective: str,
        seed_file: str | None,
        seed_sha1: str | None,
        lektion_id: int | None = None,
    ) -> tuple[int, bool]:
        now = int(time.time())
        objective = (objective or "").lower().strip()
        level = (level or "").upper().strip()

        if lektion_id is not None:
            deck_name = f"{level} L{lektion_id} {objective}"
        else:
            deck_name = f"{level} {objective}"

        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, name, seed_file, seed_sha1 FROM decks
                WHERE level=? AND COALESCE(lektion_id,0)=COALESCE(?,0) AND objective=?
                """,
                (level, lektion_id, objective),
            ).fetchone()

            if row:
                deck_id = int(row["id"])
                old_sha = (row["seed_sha1"] or "")
                changed = (old_sha != (seed_sha1 or ""))
                metadata_changed = (
                    str(row["name"] or "") != deck_name
                    or str(row["seed_file"] or "") != str(seed_file or "")
                    or changed
                )
                if metadata_changed:
                    conn.execute(
                        """
                        UPDATE decks
                           SET name=?,
                               seed_file=?,
                               seed_sha1=?,
                               updated_at=?
                         WHERE id=?
                        """,
                        (deck_name, seed_file, seed_sha1, now, deck_id),
                    )
                return deck_id, changed

            cur = conn.execute(
                """
                INSERT INTO decks(level, lektion_id, objective, name, seed_file, seed_sha1, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (level, lektion_id, objective, deck_name, seed_file, seed_sha1, now, now),
            )
            return int(cur.lastrowid), True

    def get_deck_id(self, level: str, objective: str, lektion_id: int | None = None) -> int | None:
        objective = (objective or "").lower().strip()
        level = (level or "").upper().strip()

        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id FROM decks
                WHERE level=? AND COALESCE(lektion_id,0)=COALESCE(?,0) AND objective=?
                """,
                (level, lektion_id, objective),
            ).fetchone()
            return int(row["id"]) if row else None

    def get_deck_seed_sha1(self, deck_id: int) -> str | None:
        """Return the content revision used to build a deck.

        Session checkpoints use this value to reject queues whose card IDs may
        have been replaced by a seed reimport while the app was closed.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT seed_sha1 FROM decks WHERE id=?",
                (int(deck_id),),
            ).fetchone()
            if row is None:
                return None
            return str(row["seed_sha1"] or "")

    def has_decks_for_level(self, level: str) -> bool:
        """Return True if any deck exists for this level (any lektion, any objective)."""
        level = (level or "").upper().strip()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM decks WHERE level=? LIMIT 1",
                (level,),
            ).fetchone()
            return row is not None

    # ======================
    # Vocab
    # ======================
    def deck_vocab_count(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM vocab WHERE deck_id=?", (deck_id,)).fetchone()
            return int(row["c"]) if row else 0

    def vocab_table_rows(self, deck_id: int) -> list[dict]:
        """Flat (word, article, plural, meaning, pos) rows for the read-only
        study table. The article is taken from the stored column, falling back
        to the der/die/das implied by the noun's gender, so a learner always
        sees a usable article column. Ordered case-insensitively by the word."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT word, article, gender, plural, meaning, pos
                FROM vocab
                WHERE deck_id=?
                ORDER BY LOWER(word), id
                """,
                (deck_id,),
            ).fetchall()

        out: list[dict] = []
        for r in rows:
            article = (r["article"] or "").strip()
            if not article:
                article = self._article_from_gender(r["gender"])
            out.append(
                {
                    "word": (r["word"] or "").strip(),
                    "article": article,
                    "plural": (r["plural"] or "").strip(),
                    "meaning": (r["meaning"] or "").strip(),
                    "pos": (r["pos"] or "").strip(),
                }
            )
        return out

    @staticmethod
    def _article_from_gender(gender: str | None) -> str:
        """der/die/das implied by a gender value (accepts 'm/f/n' or the
        article itself); empty string when the gender is unknown."""
        g = (gender or "").strip().lower()
        return {
            "m": "der", "masculine": "der", "der": "der",
            "f": "die", "feminine": "die", "die": "die",
            "n": "das", "neuter": "das", "das": "das",
        }.get(g, "")

    def clear_vocab_deck(self, deck_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM vocab WHERE deck_id=?", (deck_id,))

    def sync_vocab_seed(self, deck_id: int, rows) -> None:
        """Synchronize seeded vocabulary without replacing stable card IDs."""
        desired = list(rows)
        now = int(time.time())
        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT id, pos, word, article, gender, gender_tip, plural, meaning
                FROM vocab WHERE deck_id=? ORDER BY id
                """,
                (deck_id,),
            ).fetchall()
            pairs, removed, inserted = _match_seed_rows(
                existing,
                desired,
                ("pos", "word", "meaning"),
                ("word",),
            )

            # Removing unmatched rows first prevents uniqueness conflicts when
            # one unambiguous card has a corrected meaning.
            _delete_seed_rows(conn, "vocab", removed)
            for old_row, new_row in pairs:
                vocab_id = int(old_row["id"])
                conn.execute(
                    """
                    UPDATE vocab
                       SET pos=?, word=?, article=?, gender=?, gender_tip=?,
                           plural=?, meaning=?
                     WHERE id=?
                    """,
                    (
                        new_row["pos"],
                        new_row["word"],
                        new_row["article"],
                        new_row["gender"],
                        new_row["gender_tip"],
                        new_row["plural"],
                        new_row["meaning"],
                        vocab_id,
                    ),
                )
                conn.execute("DELETE FROM vocab_examples WHERE vocab_id=?", (vocab_id,))
                conn.executemany(
                    "INSERT INTO vocab_examples(vocab_id,de_text,en_text) VALUES(?,?,?)",
                    [
                        (vocab_id, german, english)
                        for german, english in new_row["examples"]
                    ],
                )

            for new_row in inserted:
                cursor = conn.execute(
                    """
                    INSERT INTO vocab(
                        deck_id,pos,word,article,gender,gender_tip,plural,meaning,created_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        deck_id,
                        new_row["pos"],
                        new_row["word"],
                        new_row["article"],
                        new_row["gender"],
                        new_row["gender_tip"],
                        new_row["plural"],
                        new_row["meaning"],
                        now,
                    ),
                )
                vocab_id = int(cursor.lastrowid)
                conn.executemany(
                    "INSERT INTO vocab_examples(vocab_id,de_text,en_text) VALUES(?,?,?)",
                    [
                        (vocab_id, german, english)
                        for german, english in new_row["examples"]
                    ],
                )

    def insert_vocab(
        self,
        deck_id: int,
        pos: str,
        word: str,
        article: str,
        gender: str,
        plural: str,
        meaning: str,
        gender_tip: str | None = None,
    ) -> int:
        now = int(time.time())
        pos_n = (pos or "other").strip().lower()
        word_n = (word or "").strip()
        meaning_n = (meaning or "").strip()

        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO vocab(deck_id,pos,word,article,gender,gender_tip,plural,meaning,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    deck_id,
                    pos_n,
                    word_n,
                    (article or "").strip() or None,
                    (gender or "").strip() or None,
                    (gender_tip or "").strip() or None,
                    (plural or "").strip() or None,
                    meaning_n,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM vocab WHERE deck_id=? AND pos=? AND word=? AND meaning=?",
                (deck_id, pos_n, word_n, meaning_n),
            ).fetchone()
            return int(row["id"])

    def insert_example(self, vocab_id: int, de_text: str, en_text: str | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO vocab_examples(vocab_id,de_text,en_text) VALUES(?,?,?)",
                (vocab_id, de_text, en_text),
            )

    def get_vocab_by_id(self, vocab_id: int) -> VocabItem | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM vocab WHERE id=?", (vocab_id,)).fetchone()
            return self._row_to_vocab(row) if row else None

    def get_examples(self, vocab_id: int, limit: int = 1) -> list[tuple[str, Optional[str]]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT de_text, en_text FROM vocab_examples WHERE vocab_id=? LIMIT ?",
                (vocab_id, limit),
            ).fetchall()
            return [(str(r["de_text"]), (str(r["en_text"]) if r["en_text"] is not None else None)) for r in rows]

    def pick_session_vocab_ids(self, deck_id: int, *args, mode: str = "mixed", cooldown_hours: int = 12) -> list[int]:
        """
        Supports BOTH call styles:
        - new: pick_session_vocab_ids(deck_id, limit, mode="mixed", cooldown_hours=12)
        - old: pick_session_vocab_ids(deck_id, direction, limit, mode="mixed", cooldown_hours=12)
        Direction is ignored (DB no longer stores direction).
        """
        limit: int | None = None

        if len(args) >= 1 and isinstance(args[0], str):
            if len(args) >= 2:
                limit = int(args[1])
            if len(args) >= 3:
                mode = str(args[2])
        elif len(args) >= 1:
            limit = int(args[0])
            if len(args) >= 2:
                mode = str(args[1])

        if limit is None:
            limit = 30
        mode = (mode or "mixed").strip().lower()

        now = int(time.time())
        cooldown_since = now - int(cooldown_hours * 3600)

        ids: list[int] = []

        with self._conn() as conn:
            if mode in ("mixed", "due_only"):
                due = conn.execute(
                    """
                    SELECT v.id
                    FROM vocab v
                    JOIN vocab_states s ON s.vocab_id=v.id
                    WHERE v.deck_id=?
                    AND s.due_at<=?
                    AND (s.last_review_at IS NULL OR s.last_review_at<=?)
                    AND s.suspended=0
                    AND (s.buried_until IS NULL OR s.buried_until<=?)
                    ORDER BY s.due_at ASC
                    LIMIT ?
                    """,
                    (deck_id, now, cooldown_since, now, limit),
                ).fetchall()
                ids.extend([int(r["id"]) for r in due])

            if len(ids) < limit and mode == "mixed":
                unseen = conn.execute(
                    """
                    SELECT v.id
                    FROM vocab v
                    LEFT JOIN vocab_states s ON s.vocab_id=v.id
                    WHERE v.deck_id=? AND s.id IS NULL
                    ORDER BY v.id ASC
                    LIMIT ?
                    """,
                    (deck_id, limit - len(ids)),
                ).fetchall()
                ids.extend([int(r["id"]) for r in unseen])

            if len(ids) < limit and mode in ("mixed", "random_only"):
                rows = conn.execute(
                    """
                    SELECT v.id
                    FROM vocab v
                    LEFT JOIN vocab_states s ON s.vocab_id=v.id
                    WHERE v.deck_id=?
                    AND (s.last_review_at IS NULL OR s.last_review_at<=?)
                    AND COALESCE(s.suspended, 0)=0
                    AND (s.buried_until IS NULL OR s.buried_until<=?)
                    """,
                    (deck_id, cooldown_since, now),
                ).fetchall()
                pool = [int(r["id"]) for r in rows if int(r["id"]) not in set(ids)]
                random.shuffle(pool)
                ids.extend(pool[: (limit - len(ids))])

            if not ids and mode != "due_only":
                rows2 = conn.execute(
                    "SELECT v.id FROM vocab v LEFT JOIN vocab_states s ON s.vocab_id=v.id "
                    "WHERE v.deck_id=? AND COALESCE(s.suspended,0)=0 "
                    "AND (s.buried_until IS NULL OR s.buried_until<=?) LIMIT ?",
                    (deck_id, now, limit),
                ).fetchall()
                ids = [int(r["id"]) for r in rows2]

        random.shuffle(ids)
        return ids[:limit]

    @staticmethod
    def _practice_lane(practice_mode: str) -> str:
        lane = str(practice_mode or "").strip().lower()
        if lane not in {"production", "dictation"}:
            raise ValueError(
                "practice_mode must be 'production' or 'dictation', "
                f"not {practice_mode!r}"
            )
        return lane

    def pick_vocab_practice_ids(
        self,
        deck_id: int,
        practice_mode: str,
        limit: int = 30,
        *,
        mode: str = "mixed",
        cooldown_hours: int = 0,
    ) -> list[int]:
        """Select vocabulary for one isolated production/dictation lane.

        Base recognition state is consulted only for learner controls.  A
        suspended or currently buried card is therefore excluded everywhere,
        including unseen and fallback paths, without sharing any FSRS values
        with the selected practice lane.
        """
        lane = self._practice_lane(practice_mode)
        limit = max(0, int(limit))
        if limit == 0:
            return []
        selection_mode = str(mode or "mixed").strip().lower()
        if selection_mode not in {"mixed", "due_only", "random_only"}:
            raise ValueError(f"unknown selection mode: {mode!r}")

        now = int(time.time())
        cooldown_since = now - max(0, int(float(cooldown_hours) * 3600))
        ids: list[int] = []

        with self._conn() as conn:
            if selection_mode in {"mixed", "due_only"}:
                rows = conn.execute(
                    """
                    SELECT v.id
                      FROM vocab v
                      JOIN vocab_practice_states ps
                        ON ps.vocab_id=v.id AND ps.practice_mode=?
                      LEFT JOIN vocab_states base ON base.vocab_id=v.id
                     WHERE v.deck_id=?
                       AND ps.due_at<=?
                       AND (ps.last_review_at IS NULL OR ps.last_review_at<=?)
                       AND COALESCE(base.suspended, 0)=0
                       AND (base.buried_until IS NULL OR base.buried_until<=?)
                     ORDER BY ps.due_at ASC, v.id ASC
                     LIMIT ?
                    """,
                    (lane, int(deck_id), now, cooldown_since, now, limit),
                ).fetchall()
                ids.extend(int(row["id"]) for row in rows)

            if len(ids) < limit and selection_mode == "mixed":
                rows = conn.execute(
                    """
                    SELECT v.id
                      FROM vocab v
                      LEFT JOIN vocab_practice_states ps
                        ON ps.vocab_id=v.id AND ps.practice_mode=?
                      LEFT JOIN vocab_states base ON base.vocab_id=v.id
                     WHERE v.deck_id=?
                       AND ps.id IS NULL
                       AND COALESCE(base.suspended, 0)=0
                       AND (base.buried_until IS NULL OR base.buried_until<=?)
                     ORDER BY v.id ASC
                     LIMIT ?
                    """,
                    (lane, int(deck_id), now, limit - len(ids)),
                ).fetchall()
                ids.extend(int(row["id"]) for row in rows)

            if len(ids) < limit and selection_mode == "random_only":
                rows = conn.execute(
                    """
                    SELECT v.id
                      FROM vocab v
                      LEFT JOIN vocab_practice_states ps
                        ON ps.vocab_id=v.id AND ps.practice_mode=?
                      LEFT JOIN vocab_states base ON base.vocab_id=v.id
                     WHERE v.deck_id=?
                       AND (ps.last_review_at IS NULL OR ps.last_review_at<=?)
                       AND COALESCE(base.suspended, 0)=0
                       AND (base.buried_until IS NULL OR base.buried_until<=?)
                    """,
                    (lane, int(deck_id), cooldown_since, now),
                ).fetchall()
                already_selected = set(ids)
                pool = [int(row["id"]) for row in rows if int(row["id"]) not in already_selected]
                random.shuffle(pool)
                ids.extend(pool[: limit - len(ids)])

            # A due-only lane intentionally returns no unseen/not-due cards.
            # Mixed/random selection has no flag-bypassing emergency fallback.

        random.shuffle(ids)
        return ids[:limit]

    def pick_practice_vocab_ids(
        self,
        deck_id: int,
        practice_mode: str,
        limit: int = 30,
        *,
        mode: str = "mixed",
        cooldown_hours: int = 0,
    ) -> list[int]:
        """UI-facing alias for :meth:`pick_vocab_practice_ids`."""
        return self.pick_vocab_practice_ids(
            deck_id,
            practice_mode,
            limit,
            mode=mode,
            cooldown_hours=cooldown_hours,
        )

    def ensure_vocab_practice_state(
        self, vocab_id: int, practice_mode: str
    ) -> VocabPracticeState:
        lane = self._practice_lane(practice_mode)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM vocab_practice_states WHERE vocab_id=? AND practice_mode=?",
                (int(vocab_id), lane),
            ).fetchone()
            if row is None:
                now = int(time.time())
                conn.execute(
                    """
                    INSERT OR IGNORE INTO vocab_practice_states(
                        vocab_id, practice_mode, due_at
                    ) VALUES (?, ?, ?)
                    """,
                    (int(vocab_id), lane, now),
                )
                row = conn.execute(
                    "SELECT * FROM vocab_practice_states WHERE vocab_id=? AND practice_mode=?",
                    (int(vocab_id), lane),
                ).fetchone()
            if row is None:  # defensive: FK failure should already have raised
                raise RuntimeError("vocabulary practice state could not be created")
            return self._row_to_vocab_practice_state(row)

    def update_vocab_practice_state(self, state: VocabPracticeState) -> None:
        lane = self._practice_lane(state.practice_mode)
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE vocab_practice_states
                   SET ease=?, interval_days=?, reps=?, lapses=?, due_at=?,
                       last_review_at=?, stability=?, difficulty=?
                 WHERE vocab_id=? AND practice_mode=?
                """,
                (
                    state.ease,
                    state.interval_days,
                    state.reps,
                    state.lapses,
                    state.due_at,
                    state.last_review_at,
                    state.stability,
                    state.difficulty,
                    state.vocab_id,
                    lane,
                ),
            )
            if cursor.rowcount != 1:
                raise LookupError(
                    f"no {lane!r} practice state exists for vocab {state.vocab_id}"
                )

    def ensure_state(self, vocab_id: int) -> VocabState:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM vocab_states WHERE vocab_id=?", (vocab_id,)).fetchone()
            if row:
                return self._row_to_state(row)

            now = int(time.time())
            conn.execute("INSERT INTO vocab_states(vocab_id, due_at) VALUES (?, ?)", (vocab_id, now))
            row2 = conn.execute("SELECT * FROM vocab_states WHERE vocab_id=?", (vocab_id,)).fetchone()
            return self._row_to_state(row2)

    def get_state(self, vocab_id: int) -> VocabState | None:
        """Return persisted recognition state without creating an unseen row."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM vocab_states WHERE vocab_id=?",
                (vocab_id,),
            ).fetchone()
            return self._row_to_state(row) if row else None

    def update_state(self, state: VocabState) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE vocab_states
                   SET ease=?, interval_days=?, reps=?, lapses=?, due_at=?, last_review_at=?,
                       stability=?, difficulty=?
                 WHERE vocab_id=?
                """,
                (state.ease, state.interval_days, state.reps, state.lapses, state.due_at, state.last_review_at,
                 state.stability, state.difficulty, state.vocab_id),
            )

    def insert_review(
        self,
        vocab_id: int,
        typed_meaning: str | None,
        typed_gender: str | None,
        typed_plural: str | None,
        meaning_correct: int | None,
        gender_correct: int | None,
        plural_correct: int | None,
        tip_used: int,
        gender_tip_used: int,
        was_checked: int,
        was_skipped: int,
        rating: int | None,
        response_ms: int | None,
        practice_mode: str = "recognition",
        error_tags: str | None = None,
    ) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reviews(
                    vocab_id,
                    typed_meaning, typed_gender, typed_plural,
                    meaning_correct, gender_correct, plural_correct,
                    tip_used, gender_tip_used,
                    was_checked, was_skipped,
                    rating, response_ms, practice_mode, error_tags
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vocab_id,
                    typed_meaning, typed_gender, typed_plural,
                    meaning_correct, gender_correct, plural_correct,
                    int(tip_used), int(gender_tip_used),
                    int(was_checked), int(was_skipped),
                    rating, response_ms, practice_mode, error_tags,
                ),
            )
            return int(cursor.lastrowid)

    # ======================
    # Grammar
    # ======================
    def deck_grammar_count(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM grammar WHERE deck_id=?", (deck_id,)).fetchone()
            return int(row["c"]) if row else 0

    def clear_grammar_deck(self, deck_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM grammar WHERE deck_id=?", (deck_id,))

    def sync_grammar_seed(self, deck_id: int, rows) -> None:
        """Synchronize grammar cards while keeping unambiguous IDs stable."""
        desired = list(rows)
        now = int(time.time())
        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT id, test_text, answer, test_verb, tip, meaning, grammar_tip
                FROM grammar WHERE deck_id=? ORDER BY id
                """,
                (deck_id,),
            ).fetchall()
            pairs, removed, inserted = _match_seed_rows(
                existing,
                desired,
                ("test_text", "answer"),
                ("test_text",),
            )
            _delete_seed_rows(conn, "grammar", removed)

            for old_row, new_row in pairs:
                conn.execute(
                    """
                    UPDATE grammar
                       SET test_text=?, answer=?, test_verb=?, tip=?,
                           meaning=?, grammar_tip=?
                     WHERE id=?
                    """,
                    (
                        new_row["test_text"],
                        new_row["answer"],
                        new_row["test_verb"],
                        new_row["tip"],
                        new_row["meaning"],
                        new_row["grammar_tip"],
                        int(old_row["id"]),
                    ),
                )

            conn.executemany(
                """
                INSERT INTO grammar(
                    deck_id,test_text,answer,test_verb,tip,meaning,grammar_tip,created_at
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        deck_id,
                        row["test_text"],
                        row["answer"],
                        row["test_verb"],
                        row["tip"],
                        row["meaning"],
                        row["grammar_tip"],
                        now,
                    )
                    for row in inserted
                ],
            )

    def insert_grammar(
        self,
        deck_id: int,
        test_text: str,
        answer: str,
        test_verb: str | None,
        tip: str | None,
        meaning: str | None,
        grammar_tip: str | None,
    ) -> int:
        now = int(time.time())
        tt = (test_text or "").strip()
        ans = (answer or "").strip()

        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO grammar(deck_id,test_text,answer,test_verb,tip,meaning,grammar_tip,created_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (deck_id, tt, ans, (test_verb or "").strip() or None, (tip or "").strip() or None,
                 (meaning or "").strip() or None, (grammar_tip or "").strip() or None, now),
            )
            row = conn.execute(
                "SELECT id FROM grammar WHERE deck_id=? AND test_text=? AND answer=?",
                (deck_id, tt, ans),
            ).fetchone()
            return int(row["id"])

    def get_grammar_by_id(self, grammar_id: int) -> GrammarItem | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM grammar WHERE id=?", (grammar_id,)).fetchone()
            return self._row_to_grammar(row) if row else None

    def pick_session_grammar_ids(self, deck_id: int, limit: int, mode: str = "mixed", cooldown_hours: float = 12.0) -> list[int]:
        mode = (mode or "mixed").strip().lower()
        now = int(time.time())
        cooldown_since = now - int(cooldown_hours * 3600)

        ids: list[int] = []

        with self._conn() as conn:
            if mode in ("mixed", "due_only"):
                due = conn.execute(
                    """
                    SELECT g.id
                    FROM grammar g
                    JOIN grammar_states s ON s.grammar_id = g.id
                    WHERE g.deck_id = ?
                    AND s.due_at <= ?
                    AND (s.last_review_at IS NULL OR s.last_review_at <= ?)
                    AND s.suspended=0
                    AND (s.buried_until IS NULL OR s.buried_until<=?)
                    ORDER BY s.due_at ASC
                    LIMIT ?
                    """,
                    (deck_id, now, cooldown_since, now, limit),
                ).fetchall()
                ids.extend([int(r["id"]) for r in due])

            if len(ids) < limit and mode in ("mixed", "unseen_only"):
                unseen = conn.execute(
                    """
                    SELECT g.id
                    FROM grammar g
                    LEFT JOIN grammar_states s ON s.grammar_id = g.id
                    WHERE g.deck_id = ? AND s.id IS NULL
                    ORDER BY g.id ASC
                    LIMIT ?
                    """,
                    (deck_id, limit - len(ids)),
                ).fetchall()
                ids.extend([int(r["id"]) for r in unseen])

            if len(ids) < limit and mode in ("mixed", "random_only"):
                rows = conn.execute(
                    """
                    SELECT g.id
                    FROM grammar g
                    LEFT JOIN grammar_states s ON s.grammar_id = g.id
                    WHERE g.deck_id = ?
                    AND (s.last_review_at IS NULL OR s.last_review_at <= ?)
                    AND COALESCE(s.suspended, 0)=0
                    AND (s.buried_until IS NULL OR s.buried_until<=?)
                    """,
                    (deck_id, cooldown_since, now),
                ).fetchall()
                pool = [int(r["id"]) for r in rows if int(r["id"]) not in set(ids)]
                random.shuffle(pool)
                ids.extend(pool[: (limit - len(ids))])

            if not ids and mode not in ("due_only", "unseen_only"):
                rows2 = conn.execute(
                    "SELECT g.id FROM grammar g LEFT JOIN grammar_states s ON s.grammar_id=g.id "
                    "WHERE g.deck_id=? AND COALESCE(s.suspended,0)=0 "
                    "AND (s.buried_until IS NULL OR s.buried_until<=?) LIMIT ?",
                    (deck_id, now, limit),
                ).fetchall()
                ids = [int(r["id"]) for r in rows2]

        random.shuffle(ids)
        return ids[:limit]

    def ensure_grammar_state(self, grammar_id: int) -> GrammarState:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM grammar_states WHERE grammar_id=?", (grammar_id,)).fetchone()
            if row:
                return self._row_to_grammar_state(row)

            now = int(time.time())
            conn.execute("INSERT INTO grammar_states(grammar_id, due_at) VALUES(?,?)", (grammar_id, now))
            row2 = conn.execute("SELECT * FROM grammar_states WHERE grammar_id=?", (grammar_id,)).fetchone()
            return self._row_to_grammar_state(row2)

    def get_grammar_state(self, grammar_id: int) -> GrammarState | None:
        """Return persisted grammar state without creating an unseen row."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM grammar_states WHERE grammar_id=?",
                (grammar_id,),
            ).fetchone()
            return self._row_to_grammar_state(row) if row else None

    def update_grammar_state(self, state: GrammarState) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE grammar_states
                   SET ease=?, interval_days=?, reps=?, lapses=?, due_at=?, last_review_at=?,
                       stability=?, difficulty=?
                 WHERE grammar_id=?
                """,
                (state.ease, state.interval_days, state.reps, state.lapses, state.due_at, state.last_review_at,
                 state.stability, state.difficulty, state.grammar_id),
            )

    def insert_grammar_review(
        self,
        grammar_id: int,
        typed_blank: str | None,
        correct: int | None,
        meaning_tip_used: int,
        hint_used: int,
        grammar_tip_used: int,
        was_checked: int,
        was_skipped: int,
        rating: int | None,
        response_ms: int | None,
        practice_mode: str = "production",
        error_tags: str | None = None,
    ) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO grammar_reviews(
                    grammar_id,
                    typed_blank, correct,
                    meaning_tip_used, hint_used, grammar_tip_used,
                    was_checked, was_skipped,
                    rating, response_ms, practice_mode, error_tags
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (grammar_id, typed_blank, correct,
                 int(meaning_tip_used), int(hint_used), int(grammar_tip_used),
                 int(was_checked), int(was_skipped), rating, response_ms,
                 practice_mode, error_tags),
            )
            return int(cursor.lastrowid)

    # ======================
    # Sentences
    # ======================
    def deck_sentences_count(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM sentences WHERE deck_id=?", (deck_id,)).fetchone()
            return int(row["c"]) if row else 0

    def clear_sentences_deck(self, deck_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sentences WHERE deck_id=?", (deck_id,))

    def sync_sentences_seed(self, deck_id: int, rows) -> None:
        """Synchronize sentence cards, using a unique translation as fallback."""
        desired = list(rows)
        now = int(time.time())
        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT id, target_text, translation, tip, words_json
                FROM sentences WHERE deck_id=? ORDER BY id
                """,
                (deck_id,),
            ).fetchall()
            pairs, removed, inserted = _match_seed_rows(
                existing,
                desired,
                ("target_text",),
                ("translation",),
            )
            _delete_seed_rows(conn, "sentences", removed)

            for old_row, new_row in pairs:
                conn.execute(
                    """
                    UPDATE sentences
                       SET target_text=?, translation=?, tip=?, words_json=?
                     WHERE id=?
                    """,
                    (
                        new_row["target_text"],
                        new_row["translation"],
                        new_row["tip"],
                        new_row["words_json"],
                        int(old_row["id"]),
                    ),
                )

            conn.executemany(
                """
                INSERT INTO sentences(
                    deck_id,target_text,translation,tip,words_json,created_at
                )
                VALUES(?,?,?,?,?,?)
                """,
                [
                    (
                        deck_id,
                        row["target_text"],
                        row["translation"],
                        row["tip"],
                        row["words_json"],
                        now,
                    )
                    for row in inserted
                ],
            )

    def insert_sentence(
        self,
        deck_id: int,
        target_text: str,
        translation: str | None,
        tip: str | None,
        words_json: str | None,
    ) -> int:
        now = int(time.time())
        tt = (target_text or "").strip()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sentences(deck_id,target_text,translation,tip,words_json,created_at)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    deck_id,
                    tt,
                    (translation or "").strip() or None,
                    (tip or "").strip() or None,
                    words_json or None,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM sentences WHERE deck_id=? AND target_text=?",
                (deck_id, tt),
            ).fetchone()
            return int(row["id"])

    def get_sentence_by_id(self, sentence_id: int) -> SentenceItem | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sentences WHERE id=?", (sentence_id,)).fetchone()
            if not row:
                return None

            item = self._row_to_sentence(row)

            try:
                if (not item.words) and item.target_text.strip():
                    words = self._tokenize_sentence(item.target_text)
                    if words:
                        conn.execute(
                            "UPDATE sentences SET words_json=? WHERE id=?",
                            (json.dumps(words, ensure_ascii=False), sentence_id),
                        )
                        item = SentenceItem(
                            id=item.id,
                            deck_id=item.deck_id,
                            target_text=item.target_text,
                            translation=item.translation,
                            tip=item.tip,
                            words=words,
                        )
            except Exception:
                pass

            return item

    def pick_session_sentence_ids(self, deck_id: int, limit: int, mode: str = "mixed", cooldown_hours: float = 12.0) -> list[int]:
        mode = (mode or "mixed").strip().lower()
        now = int(time.time())
        cooldown_since = now - int(float(cooldown_hours) * 3600)

        ids: list[int] = []

        with self._conn() as conn:
            if mode in ("mixed", "due_only"):
                due = conn.execute(
                    """
                    SELECT s.id
                    FROM sentences s
                    JOIN sentence_states st ON st.sentence_id = s.id
                    WHERE s.deck_id = ?
                      AND st.due_at <= ?
                      AND (st.last_review_at IS NULL OR st.last_review_at <= ?)
                      AND st.suspended=0
                      AND (st.buried_until IS NULL OR st.buried_until<=?)
                    ORDER BY st.due_at ASC
                    LIMIT ?
                    """,
                    (deck_id, now, cooldown_since, now, int(limit)),
                ).fetchall()
                ids.extend([int(r["id"]) for r in due])

            if len(ids) < limit and mode == "mixed":
                unseen = conn.execute(
                    """
                    SELECT s.id
                    FROM sentences s
                    LEFT JOIN sentence_states st ON st.sentence_id = s.id
                    WHERE s.deck_id = ?
                      AND st.id IS NULL
                    ORDER BY s.id ASC
                    LIMIT ?
                    """,
                    (deck_id, int(limit - len(ids))),
                ).fetchall()
                ids.extend([int(r["id"]) for r in unseen])

            if len(ids) < limit and mode in ("mixed", "random_only"):
                rows = conn.execute(
                    """
                    SELECT s.id
                    FROM sentences s
                    LEFT JOIN sentence_states st ON st.sentence_id = s.id
                    WHERE s.deck_id = ?
                      AND (st.last_review_at IS NULL OR st.last_review_at <= ?)
                      AND COALESCE(st.suspended, 0)=0
                      AND (st.buried_until IS NULL OR st.buried_until<=?)
                    """,
                    (deck_id, cooldown_since, now),
                ).fetchall()
                pool = [int(r["id"]) for r in rows if int(r["id"]) not in set(ids)]
                random.shuffle(pool)
                ids.extend(pool[: (limit - len(ids))])

            if not ids and mode != "due_only":
                rows2 = conn.execute(
                    "SELECT s.id FROM sentences s LEFT JOIN sentence_states st ON st.sentence_id=s.id "
                    "WHERE s.deck_id=? AND COALESCE(st.suspended,0)=0 "
                    "AND (st.buried_until IS NULL OR st.buried_until<=?) LIMIT ?",
                    (deck_id, now, int(limit)),
                ).fetchall()
                ids = [int(r["id"]) for r in rows2]

        random.shuffle(ids)
        return ids[: int(limit)]

    def ensure_sentence_state(self, sentence_id: int) -> SentenceState:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sentence_states WHERE sentence_id=?",
                (sentence_id,),
            ).fetchone()
            if row:
                return self._row_to_sentence_state(row)

            now = int(time.time())
            conn.execute(
                "INSERT INTO sentence_states(sentence_id, due_at) VALUES (?, ?)",
                (sentence_id, now),
            )
            row2 = conn.execute(
                "SELECT * FROM sentence_states WHERE sentence_id=?",
                (sentence_id,),
            ).fetchone()
            return self._row_to_sentence_state(row2)

    def get_sentence_state(self, sentence_id: int) -> SentenceState | None:
        """Return persisted sentence state without creating an unseen row."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sentence_states WHERE sentence_id=?",
                (sentence_id,),
            ).fetchone()
            return self._row_to_sentence_state(row) if row else None

    def update_sentence_state(self, state: SentenceState) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE sentence_states
                   SET ease=?, interval_days=?, reps=?, lapses=?, due_at=?, last_review_at=?,
                       stability=?, difficulty=?
                 WHERE sentence_id=?
                """,
                (
                    state.ease,
                    state.interval_days,
                    state.reps,
                    state.lapses,
                    state.due_at,
                    state.last_review_at,
                    state.stability,
                    state.difficulty,
                    state.sentence_id,
                ),
            )

    def insert_sentence_review(
            self,
            sentence_id: int,
            typed_text: str | None,
            correct: int | None,
            tip_used: int,
            translation_used: int = 0,
            was_checked: int = 0,
            was_skipped: int = 0,
            rating: int | None = None,
            response_ms: int | None = None,
            bank_size: int | None = None,
            tokens_used: int | None = None,
            mismatch_count: int | None = None,
            cap_errors: int | None = None,
            punct_errors: int | None = None,
            practice_mode: str = "builder",
            error_tags: str | None = None,
    ) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO sentence_reviews(sentence_id, typed_text, correct,
                    tip_used, translation_used, was_checked, was_skipped,
                    rating, response_ms, bank_size, tokens_used, mismatch_count,
                    cap_errors, punct_errors, practice_mode, error_tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sentence_id, typed_text, correct, int(tip_used), int(translation_used),
                 int(was_checked), int(was_skipped), rating, response_ms, bank_size,
                 tokens_used, mismatch_count, cap_errors, punct_errors, practice_mode, error_tags),
            )
            return int(cursor.lastrowid)

    # ======================
    # Listening
    # ======================
    def deck_listening_count(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM listening WHERE deck_id=?", (deck_id,)).fetchone()
            return int(row["c"]) if row else 0

    def clear_listening_deck(self, deck_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM listening WHERE deck_id=?", (deck_id,))

    def sync_listening_seed(self, deck_id: int, rows) -> None:
        """Synchronize listening cards, reusing only unique question anchors."""
        desired = list(rows)
        now = int(time.time())
        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT id, text, question, answer, distractors_json, translation, tip
                FROM listening WHERE deck_id=? ORDER BY id
                """,
                (deck_id,),
            ).fetchall()
            pairs, removed, inserted = _match_seed_rows(
                existing,
                desired,
                ("question", "text"),
                ("question",),
            )
            _delete_seed_rows(conn, "listening", removed)

            for old_row, new_row in pairs:
                conn.execute(
                    """
                    UPDATE listening
                       SET text=?, question=?, answer=?, distractors_json=?,
                           translation=?, tip=?
                     WHERE id=?
                    """,
                    (
                        new_row["text"],
                        new_row["question"],
                        new_row["answer"],
                        new_row["distractors_json"],
                        new_row["translation"],
                        new_row["tip"],
                        int(old_row["id"]),
                    ),
                )

            conn.executemany(
                """
                INSERT INTO listening(
                    deck_id,text,question,answer,distractors_json,
                    translation,tip,created_at
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        deck_id,
                        row["text"],
                        row["question"],
                        row["answer"],
                        row["distractors_json"],
                        row["translation"],
                        row["tip"],
                        now,
                    )
                    for row in inserted
                ],
            )

    def insert_listening(
        self,
        deck_id: int,
        text: str,
        question: str,
        answer: str,
        distractors_json: str | None,
        translation: str | None,
        tip: str | None,
    ) -> int:
        now = int(time.time())
        text_n = (text or "").strip()
        q_n = (question or "").strip()
        a_n = (answer or "").strip()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO listening(deck_id,text,question,answer,distractors_json,translation,tip,created_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    deck_id,
                    text_n,
                    q_n,
                    a_n,
                    distractors_json or None,
                    (translation or "").strip() or None,
                    (tip or "").strip() or None,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM listening WHERE deck_id=? AND question=? AND text=?",
                (deck_id, q_n, text_n),
            ).fetchone()
            return int(row["id"])

    def get_listening_by_id(self, listening_id: int) -> ListeningItem | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM listening WHERE id=?", (listening_id,)).fetchone()
            return self._row_to_listening(row) if row else None

    def pick_session_listening_ids(self, deck_id: int, limit: int, mode: str = "mixed", cooldown_hours: float = 12.0) -> list[int]:
        mode = (mode or "mixed").strip().lower()
        now = int(time.time())
        cooldown_since = now - int(float(cooldown_hours) * 3600)

        ids: list[int] = []

        with self._conn() as conn:
            if mode in ("mixed", "due_only"):
                due = conn.execute(
                    """
                    SELECT l.id
                    FROM listening l
                    JOIN listening_states st ON st.listening_id = l.id
                    WHERE l.deck_id = ?
                      AND st.due_at <= ?
                      AND (st.last_review_at IS NULL OR st.last_review_at <= ?)
                      AND st.suspended=0
                      AND (st.buried_until IS NULL OR st.buried_until<=?)
                    ORDER BY st.due_at ASC
                    LIMIT ?
                    """,
                    (deck_id, now, cooldown_since, now, int(limit)),
                ).fetchall()
                ids.extend([int(r["id"]) for r in due])

            if len(ids) < limit and mode == "mixed":
                unseen = conn.execute(
                    """
                    SELECT l.id
                    FROM listening l
                    LEFT JOIN listening_states st ON st.listening_id = l.id
                    WHERE l.deck_id = ?
                      AND st.id IS NULL
                    ORDER BY l.id ASC
                    LIMIT ?
                    """,
                    (deck_id, int(limit - len(ids))),
                ).fetchall()
                ids.extend([int(r["id"]) for r in unseen])

            if len(ids) < limit and mode in ("mixed", "random_only"):
                rows = conn.execute(
                    """
                    SELECT l.id
                    FROM listening l
                    LEFT JOIN listening_states st ON st.listening_id = l.id
                    WHERE l.deck_id = ?
                      AND (st.last_review_at IS NULL OR st.last_review_at <= ?)
                      AND COALESCE(st.suspended, 0)=0
                      AND (st.buried_until IS NULL OR st.buried_until<=?)
                    """,
                    (deck_id, cooldown_since, now),
                ).fetchall()
                pool = [int(r["id"]) for r in rows if int(r["id"]) not in set(ids)]
                random.shuffle(pool)
                ids.extend(pool[: (limit - len(ids))])

            if not ids and mode != "due_only":
                rows2 = conn.execute(
                    "SELECT l.id FROM listening l LEFT JOIN listening_states st ON st.listening_id=l.id "
                    "WHERE l.deck_id=? AND COALESCE(st.suspended,0)=0 "
                    "AND (st.buried_until IS NULL OR st.buried_until<=?) LIMIT ?",
                    (deck_id, now, int(limit)),
                ).fetchall()
                ids = [int(r["id"]) for r in rows2]

        random.shuffle(ids)
        return ids[: int(limit)]

    def ensure_listening_state(self, listening_id: int) -> ListeningState:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM listening_states WHERE listening_id=?",
                (listening_id,),
            ).fetchone()
            if row:
                return self._row_to_listening_state(row)

            now = int(time.time())
            conn.execute(
                "INSERT INTO listening_states(listening_id, due_at) VALUES (?, ?)",
                (listening_id, now),
            )
            row2 = conn.execute(
                "SELECT * FROM listening_states WHERE listening_id=?",
                (listening_id,),
            ).fetchone()
            return self._row_to_listening_state(row2)

    def get_listening_state(self, listening_id: int) -> ListeningState | None:
        """Return persisted listening state without creating an unseen row."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM listening_states WHERE listening_id=?",
                (listening_id,),
            ).fetchone()
            return self._row_to_listening_state(row) if row else None

    def update_listening_state(self, state: ListeningState) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE listening_states
                   SET ease=?, interval_days=?, reps=?, lapses=?, due_at=?, last_review_at=?,
                       stability=?, difficulty=?
                 WHERE listening_id=?
                """,
                (
                    state.ease,
                    state.interval_days,
                    state.reps,
                    state.lapses,
                    state.due_at,
                    state.last_review_at,
                    state.stability,
                    state.difficulty,
                    state.listening_id,
                ),
            )

    def insert_listening_review(
        self,
        listening_id: int,
        chosen: str | None,
        correct: int | None,
        replay_count: int = 0,
        was_checked: int = 0,
        was_skipped: int = 0,
        rating: int | None = None,
        response_ms: int | None = None,
        practice_mode: str = "comprehension",
        error_tags: str | None = None,
    ) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO listening_reviews(
                    listening_id, chosen, correct, replay_count,
                    was_checked, was_skipped, rating, response_ms,
                    practice_mode, error_tags
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    listening_id,
                    chosen,
                    correct,
                    int(replay_count or 0),
                    int(was_checked),
                    int(was_skipped),
                    rating,
                    response_ms,
                    practice_mode,
                    error_tags,
                ),
            )
            return int(cursor.lastrowid)

    def listening_due_count(
        self,
        deck_id: int,
        cooldown_hours: float = 0,
    ) -> int:
        now = int(time.time())
        cooldown_since = now - max(0, int(float(cooldown_hours) * 3600))
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM listening l
                  JOIN listening_states st ON st.listening_id=l.id
                 WHERE l.deck_id=? AND st.due_at<=?
                   AND (st.last_review_at IS NULL OR st.last_review_at<=?)
                   AND st.suspended=0
                   AND (st.buried_until IS NULL OR st.buried_until<=?)
                """,
                (deck_id, now, cooldown_since, now),
            ).fetchone()
            return int(row["c"]) if row else 0

    def listening_reviewed_last_24h(self, deck_id: int) -> int:
        since = int(time.time()) - 24 * 3600
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM listening_reviews r
                  JOIN listening l ON l.id=r.listening_id
                 WHERE l.deck_id=? AND r.created_at>=?
                """,
                (deck_id, since),
            ).fetchone()
            return int(row["c"]) if row else 0

    def listening_unseen_count(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM listening l
                  LEFT JOIN listening_states st ON st.listening_id=l.id
                 WHERE l.deck_id=? AND st.id IS NULL
                """,
                (deck_id,),
            ).fetchone()
            return int(row["c"]) if row else 0

    # ---------- Completion (review coverage) ----------
    def lektion_seen_map(self, book_id: int, level: str) -> dict[int, tuple[int, int]]:
        """Per-lektion (total_items, seen_items) for a book at a level, aggregated
        across ALL objectives (vocab + grammar + sentences + listening).

        An item is "seen" once it has a state row (reviewed/interacted with at
        least once). Only lektions that actually have items appear in the map.
        Powers the recursive "fully reviewed" ticks in the selection UI.
        """
        level = (level or "").upper().strip()
        sql = """
            WITH items(lek, sid) AS (
                SELECT d.lektion_id, vs.id
                  FROM vocab v JOIN decks d ON v.deck_id=d.id
                  LEFT JOIN vocab_states vs ON vs.vocab_id=v.id
                 WHERE d.level=?
                UNION ALL
                SELECT d.lektion_id, gs.id
                  FROM grammar g JOIN decks d ON g.deck_id=d.id
                  LEFT JOIN grammar_states gs ON gs.grammar_id=g.id
                 WHERE d.level=?
                UNION ALL
                SELECT d.lektion_id, ss.id
                  FROM sentences s JOIN decks d ON s.deck_id=d.id
                  LEFT JOIN sentence_states ss ON ss.sentence_id=s.id
                 WHERE d.level=?
                UNION ALL
                SELECT d.lektion_id, ls.id
                  FROM listening l JOIN decks d ON l.deck_id=d.id
                  LEFT JOIN listening_states ls ON ls.listening_id=l.id
                 WHERE d.level=?
            )
            SELECT lek,
                   COUNT(*) AS total,
                   SUM(CASE WHEN sid IS NOT NULL THEN 1 ELSE 0 END) AS seen
              FROM items
             WHERE lek IN (SELECT id FROM lektions WHERE book_id=? AND level=?)
             GROUP BY lek
        """
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    sql, (level, level, level, level, book_id, level)
                ).fetchall()
            return {
                int(r["lek"]): (int(r["total"] or 0), int(r["seen"] or 0))
                for r in rows
                if r["lek"] is not None
            }
        except Exception:
            return {}

    # ---------- Progress helpers ----------
    def due_count(self, deck_id: int, cooldown_hours: float = 0) -> int:
        now = int(time.time())
        cooldown_since = now - max(0, int(float(cooldown_hours) * 3600))
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM vocab v
                  JOIN vocab_states s ON s.vocab_id=v.id
                 WHERE v.deck_id=? AND s.due_at<=?
                   AND (s.last_review_at IS NULL OR s.last_review_at<=?)
                   AND s.suspended=0
                   AND (s.buried_until IS NULL OR s.buried_until<=?)
                """,
                (deck_id, now, cooldown_since, now),
            ).fetchone()
            return int(row["c"]) if row else 0

    def reviewed_last_24h(self, deck_id: int) -> int:
        since = int(time.time()) - 24 * 3600
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM reviews r
                  JOIN vocab v ON v.id=r.vocab_id
                 WHERE v.deck_id=? AND r.created_at>=?
                   AND r.practice_mode = 'recognition'
                """,
                (deck_id, since),
            ).fetchone()
            return int(row["c"]) if row else 0

    def daily_review_counts(
        self,
        since_ts: int,
        until_ts: int | None = None,
    ) -> dict[str, int]:
        """Return genuine primary reviews grouped by local calendar day.

        The optional upper bound is exclusive. One strict query keeps activity
        atomic: a damaged or missing table cannot yield plausible partial data.
        """
        end = None if until_ts is None else int(until_ts)
        with self._conn() as conn:
            rows = conn.execute(
                """
                WITH bounds(start_ts, end_ts) AS (VALUES(?, ?)),
                primary_events(created_at) AS (
                    SELECT r.created_at FROM reviews r, bounds b
                     WHERE r.created_at>=b.start_ts
                       AND (b.end_ts IS NULL OR r.created_at<b.end_ts)
                       AND r.practice_mode='recognition'
                       AND r.was_checked=1 AND r.was_skipped=0
                    UNION ALL
                    SELECT r.created_at FROM grammar_reviews r, bounds b
                     WHERE r.created_at>=b.start_ts
                       AND (b.end_ts IS NULL OR r.created_at<b.end_ts)
                       AND r.practice_mode='production'
                       AND r.was_checked=1 AND r.was_skipped=0
                    UNION ALL
                    SELECT r.created_at FROM sentence_reviews r, bounds b
                     WHERE r.created_at>=b.start_ts
                       AND (b.end_ts IS NULL OR r.created_at<b.end_ts)
                       AND r.practice_mode='builder'
                       AND r.was_checked=1 AND r.was_skipped=0
                    UNION ALL
                    SELECT r.created_at FROM listening_reviews r, bounds b
                     WHERE r.created_at>=b.start_ts
                       AND (b.end_ts IS NULL OR r.created_at<b.end_ts)
                       AND r.practice_mode='comprehension'
                       AND r.was_checked=1 AND r.was_skipped=0
                )
                SELECT date(created_at, 'unixepoch', 'localtime') AS day,
                       COUNT(*) AS c
                  FROM primary_events
                 GROUP BY day
                 ORDER BY day
                """,
                (int(since_ts), end),
            ).fetchall()
        return {
            str(row["day"]): int(row["c"])
            for row in rows
            if row["day"] is not None
        }

    def upcoming_due_counts(self, within_seconds: int = 86400) -> dict[str, int]:
        """Global (all decks + objectives) schedule pressure for the launch strip:
        how many SEEN items are due right now vs. ripen within `within_seconds`.
        Items without a state row (never studied) are not 'due'. A missing state
        table on a very old DB is skipped rather than fatal."""
        now = int(time.time())
        horizon = now + int(within_seconds)
        tables = ("vocab_states", "grammar_states", "sentence_states", "listening_states")
        due_now = 0
        due_soon = 0
        with self._conn() as conn:
            for table in tables:  # fixed constants, not user input
                try:
                    row = conn.execute(
                        f"""
                        SELECT
                            SUM(CASE WHEN due_at <= ? THEN 1 ELSE 0 END) AS now_due,
                            SUM(CASE WHEN due_at > ? AND due_at <= ? THEN 1 ELSE 0 END) AS soon_due
                          FROM {table}
                         WHERE suspended=0
                           AND (buried_until IS NULL OR buried_until<=?)
                        """,
                        (now, now, horizon, now),
                    ).fetchone()
                except Exception:
                    continue
                if row:
                    due_now += int(row["now_due"] or 0)
                    due_soon += int(row["soon_due"] or 0)
        return {"due_now": due_now, "due_soon": due_soon}

    # ---------- one-deep undo: drop the most recent review for an item ----------
    def _delete_last(self, table: str, fk: str, item_id: int) -> None:
        with self._conn() as conn:  # table/fk are fixed constants, not user input
            conn.execute(
                f"DELETE FROM {table} "
                f"WHERE rowid = (SELECT rowid FROM {table} WHERE {fk}=? ORDER BY rowid DESC LIMIT 1)",
                (int(item_id),),
            )

    def delete_last_review(
        self, vocab_id: int, *, practice_mode: str = "recognition"
    ) -> None:
        # Scope by lane so Lab production/dictation rows cannot be undone
        # when restoring a recognition review snapshot.
        with self._conn() as conn:
            conn.execute(
                """
                DELETE FROM reviews
                 WHERE rowid = (
                   SELECT rowid FROM reviews
                    WHERE vocab_id=? AND practice_mode=?
                    ORDER BY rowid DESC LIMIT 1
                 )
                """,
                (int(vocab_id), str(practice_mode or "recognition")),
            )

    def delete_last_grammar_review(self, grammar_id: int) -> None:
        self._delete_last("grammar_reviews", "grammar_id", grammar_id)

    def delete_last_sentence_review(self, sentence_id: int) -> None:
        self._delete_last("sentence_reviews", "sentence_id", sentence_id)

    def delete_last_listening_review(self, listening_id: int) -> None:
        self._delete_last("listening_reviews", "listening_id", listening_id)

    def delete_review_event(
        self,
        objective: str,
        review_id: int,
        item_id: int,
        practice_mode: str,
    ) -> None:
        mapping = {
            "vocab": ("reviews", "vocab_id", "recognition"),
            "grammar": ("grammar_reviews", "grammar_id", "production"),
            "sentence": ("sentence_reviews", "sentence_id", "builder"),
            "listening": (
                "listening_reviews",
                "listening_id",
                "comprehension",
            ),
        }
        try:
            table, fk, primary_mode = mapping[objective]
        except KeyError as exc:
            raise ValueError(f"unsupported review objective: {objective!r}") from exc
        if practice_mode != primary_mode:
            raise ValueError(
                f"practice mode {practice_mode!r} is not primary for {objective!r}"
            )
        with self._conn() as conn:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE id=? AND {fk}=? AND practice_mode=?",
                (int(review_id), int(item_id), practice_mode),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("exact primary review is missing or mismatched")

    def _delete_state(self, table: str, fk: str, item_id: int) -> None:
        with self._conn() as conn:  # table/fk are fixed constants, not user input
            conn.execute(
                f"DELETE FROM {table} WHERE {fk}=?",
                (int(item_id),),
            )

    def delete_state(self, vocab_id: int) -> None:
        self._delete_state("vocab_states", "vocab_id", vocab_id)

    def delete_grammar_state(self, grammar_id: int) -> None:
        self._delete_state("grammar_states", "grammar_id", grammar_id)

    def delete_sentence_state(self, sentence_id: int) -> None:
        self._delete_state("sentence_states", "sentence_id", sentence_id)

    def delete_listening_state(self, listening_id: int) -> None:
        self._delete_state("listening_states", "listening_id", listening_id)

    def unseen_count(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM vocab v
                  LEFT JOIN vocab_states s ON s.vocab_id=v.id
                 WHERE v.deck_id=? AND s.id IS NULL
                """,
                (deck_id,),
            ).fetchone()
            return int(row["c"]) if row else 0

    def grammar_due_count(
        self,
        deck_id: int,
        cooldown_hours: float = 0,
    ) -> int:
        now = int(time.time())
        cooldown_since = now - max(0, int(float(cooldown_hours) * 3600))
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM grammar g
                  JOIN grammar_states s ON s.grammar_id=g.id
                 WHERE g.deck_id=? AND s.due_at<=?
                   AND (s.last_review_at IS NULL OR s.last_review_at<=?)
                   AND s.suspended=0
                   AND (s.buried_until IS NULL OR s.buried_until<=?)
                """,
                (deck_id, now, cooldown_since, now),
            ).fetchone()
            return int(row["c"]) if row else 0

    def grammar_reviewed_last_24h(self, deck_id: int) -> int:
        since = int(time.time()) - 24 * 3600
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM grammar_reviews r
                  JOIN grammar g ON g.id=r.grammar_id
                 WHERE g.deck_id=? AND r.created_at>=?
                """,
                (deck_id, since),
            ).fetchone()
            return int(row["c"]) if row else 0

    def grammar_unseen_count(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM grammar g
                  LEFT JOIN grammar_states s ON s.grammar_id=g.id
                 WHERE g.deck_id=? AND s.id IS NULL
                """,
                (deck_id,),
            ).fetchone()
            return int(row["c"]) if row else 0

    def sentence_due_count(
        self,
        deck_id: int,
        cooldown_hours: float = 0,
    ) -> int:
        now = int(time.time())
        cooldown_since = now - max(0, int(float(cooldown_hours) * 3600))
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM sentences s
                  JOIN sentence_states st ON st.sentence_id=s.id
                 WHERE s.deck_id=? AND st.due_at<=?
                   AND (st.last_review_at IS NULL OR st.last_review_at<=?)
                   AND st.suspended=0
                   AND (st.buried_until IS NULL OR st.buried_until<=?)
                """,
                (deck_id, now, cooldown_since, now),
            ).fetchone()
            return int(row["c"]) if row else 0

    def sentence_reviewed_last_24h(self, deck_id: int) -> int:
        since = int(time.time()) - 24 * 3600
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM sentence_reviews r
                  JOIN sentences s ON s.id=r.sentence_id
                 WHERE s.deck_id=? AND r.created_at>=?
                """,
                (deck_id, since),
            ).fetchone()
            return int(row["c"]) if row else 0

    def sentence_unseen_count(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM sentences s
                  LEFT JOIN sentence_states st ON st.sentence_id=s.id
                 WHERE s.deck_id=? AND st.id IS NULL
                """,
                (deck_id,),
            ).fetchone()
            return int(row["c"]) if row else 0

    # ---------- row mappers ----------
    @staticmethod
    def _row_to_vocab(r: sqlite3.Row) -> VocabItem:
        keys = set(r.keys())
        return VocabItem(
            id=int(r["id"]),
            deck_id=int(r["deck_id"]),
            pos=str(r["pos"]),
            word=str(r["word"]),
            meaning=str(r["meaning"] or ""),
            article=str(r["article"]) if r["article"] is not None else None,
            gender=str(r["gender"]) if r["gender"] is not None else None,
            gender_tip=str(r["gender_tip"]) if ("gender_tip" in keys and r["gender_tip"] is not None) else None,
            plural=str(r["plural"]) if r["plural"] is not None else None,
        )

    @staticmethod
    def _opt_float(r: sqlite3.Row, key: str) -> Optional[float]:
        try:
            if key not in set(r.keys()):
                return None
            v = r[key]
            return float(v) if v is not None else None
        except Exception:
            return None

    @staticmethod
    def _row_to_state(r: sqlite3.Row) -> VocabState:
        return VocabState(
            vocab_id=int(r["vocab_id"]),
            ease=float(r["ease"]),
            interval_days=float(r["interval_days"]),
            reps=int(r["reps"]),
            lapses=int(r["lapses"]),
            due_at=int(r["due_at"]),
            last_review_at=int(r["last_review_at"]) if r["last_review_at"] is not None else None,
            stability=Repo._opt_float(r, "stability"),
            difficulty=Repo._opt_float(r, "difficulty"),
            id=int(r["id"]),
            suspended=bool(r["suspended"]),
            buried_until=(
                int(r["buried_until"])
                if r["buried_until"] is not None
                else None
            ),
        )

    @staticmethod
    def _row_to_vocab_practice_state(r: sqlite3.Row) -> VocabPracticeState:
        return VocabPracticeState(
            vocab_id=int(r["vocab_id"]),
            practice_mode=str(r["practice_mode"]),
            ease=float(r["ease"]),
            interval_days=float(r["interval_days"]),
            reps=int(r["reps"]),
            lapses=int(r["lapses"]),
            due_at=int(r["due_at"]),
            last_review_at=(
                int(r["last_review_at"]) if r["last_review_at"] is not None else None
            ),
            stability=Repo._opt_float(r, "stability"),
            difficulty=Repo._opt_float(r, "difficulty"),
        )

    @staticmethod
    def _row_to_grammar(r: sqlite3.Row) -> GrammarItem:
        return GrammarItem(
            id=int(r["id"]),
            deck_id=int(r["deck_id"]),
            test_text=str(r["test_text"]),
            answer=str(r["answer"]),
            test_verb=str(r["test_verb"]) if r["test_verb"] is not None else None,
            tip=str(r["tip"]) if r["tip"] is not None else None,
            meaning=str(r["meaning"]) if r["meaning"] is not None else None,
            grammar_tip=str(r["grammar_tip"]) if r["grammar_tip"] is not None else None,
        )

    @staticmethod
    def _row_to_grammar_state(r: sqlite3.Row) -> GrammarState:
        return GrammarState(
            grammar_id=int(r["grammar_id"]),
            ease=float(r["ease"]),
            interval_days=float(r["interval_days"]),
            reps=int(r["reps"]),
            lapses=int(r["lapses"]),
            due_at=int(r["due_at"]),
            last_review_at=int(r["last_review_at"]) if r["last_review_at"] is not None else None,
            stability=Repo._opt_float(r, "stability"),
            difficulty=Repo._opt_float(r, "difficulty"),
            id=int(r["id"]),
            suspended=bool(r["suspended"]),
            buried_until=(
                int(r["buried_until"])
                if r["buried_until"] is not None
                else None
            ),
        )

    @staticmethod
    def _tokenize_sentence(text: str) -> list[str]:
        import re
        _TOKEN_RE = re.compile(
            r"[A-Za-zÄÖÜäöüß]+(?:[-'][A-Za-zÄÖÜäöüß]+)*|\d+|[.,!?;:()\[\]{}\"""„‚''…–—-]"
        )
        return [t for t in _TOKEN_RE.findall(text or "") if t and not t.isspace()]

    @staticmethod
    def _row_to_sentence(r: sqlite3.Row) -> SentenceItem:
        import json, re

        def parse_words(raw: str | None, target: str) -> list[str]:
            s = (raw or "").strip()
            if not s or s == "[]":
                return Repo._tokenize_sentence(target)

            if s.startswith("[") and s.endswith("]"):
                try:
                    arr = json.loads(s)
                    if isinstance(arr, list):
                        out = [str(x).strip() for x in arr if str(x).strip()]
                        return out if out else Repo._tokenize_sentence(target)
                    if isinstance(arr, str):
                        s2 = arr.strip()
                        if "|" in s2:
                            out = [t.strip() for t in s2.split("|") if t.strip()]
                            return out if out else Repo._tokenize_sentence(target)
                except Exception:
                    pass

            if "|" in s:
                out = [t.strip() for t in s.split("|") if t.strip()]
                return out if out else Repo._tokenize_sentence(target)

            out = [t.strip() for t in s.split() if t.strip()]
            return out if out else Repo._tokenize_sentence(target)

        keys = set(r.keys())
        target_text = str(r["target_text"] or "")

        words_json = str(r["words_json"]) if ("words_json" in keys and r["words_json"] is not None) else None

        words = parse_words(words_json, target_text)

        return SentenceItem(
            id=int(r["id"]),
            deck_id=int(r["deck_id"]),
            target_text=target_text,
            translation=str(r["translation"]) if r["translation"] is not None else None,
            tip=str(r["tip"]) if r["tip"] is not None else None,
            words=words,
        )

    @staticmethod
    def _row_to_sentence_state(r: sqlite3.Row) -> SentenceState:
        return SentenceState(
            sentence_id=int(r["sentence_id"]),
            ease=float(r["ease"]),
            interval_days=float(r["interval_days"]),
            reps=int(r["reps"]),
            lapses=int(r["lapses"]),
            due_at=int(r["due_at"]),
            last_review_at=int(r["last_review_at"]) if r["last_review_at"] is not None else None,
            stability=Repo._opt_float(r, "stability"),
            difficulty=Repo._opt_float(r, "difficulty"),
            id=int(r["id"]),
            suspended=bool(r["suspended"]),
            buried_until=(
                int(r["buried_until"])
                if r["buried_until"] is not None
                else None
            ),
        )

    @staticmethod
    def _row_to_listening(r: sqlite3.Row) -> ListeningItem:
        keys = set(r.keys())

        distractors: list[str] = []
        raw = r["distractors_json"] if "distractors_json" in keys else None
        if raw:
            try:
                arr = json.loads(str(raw))
                if isinstance(arr, list):
                    distractors = [str(x).strip() for x in arr if str(x).strip()]
            except Exception:
                s = str(raw).strip()
                if "|" in s:
                    distractors = [t.strip() for t in s.split("|") if t.strip()]
                elif s:
                    distractors = [s]

        return ListeningItem(
            id=int(r["id"]),
            deck_id=int(r["deck_id"]),
            text=str(r["text"] or ""),
            question=str(r["question"] or ""),
            answer=str(r["answer"] or ""),
            distractors=distractors,
            translation=str(r["translation"]) if r["translation"] is not None else None,
            tip=str(r["tip"]) if ("tip" in keys and r["tip"] is not None) else None,
        )

    @staticmethod
    def _row_to_listening_state(r: sqlite3.Row) -> ListeningState:
        return ListeningState(
            listening_id=int(r["listening_id"]),
            ease=float(r["ease"]),
            interval_days=float(r["interval_days"]),
            reps=int(r["reps"]),
            lapses=int(r["lapses"]),
            due_at=int(r["due_at"]),
            last_review_at=int(r["last_review_at"]) if r["last_review_at"] is not None else None,
            stability=Repo._opt_float(r, "stability"),
            difficulty=Repo._opt_float(r, "difficulty"),
            id=int(r["id"]),
            suspended=bool(r["suspended"]),
            buried_until=(
                int(r["buried_until"])
                if r["buried_until"] is not None
                else None
            ),
        )
