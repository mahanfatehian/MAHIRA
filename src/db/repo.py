from __future__ import annotations

import json
import random
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from db.connection import connect


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


class Repo:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextmanager
    def _conn(self):
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
                SELECT id, seed_sha1 FROM decks
                WHERE level=? AND COALESCE(lektion_id,0)=COALESCE(?,0) AND objective=?
                """,
                (level, lektion_id, objective),
            ).fetchone()

            if row:
                deck_id = int(row["id"])
                old_sha = (row["seed_sha1"] or "")
                changed = (old_sha != (seed_sha1 or ""))

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

    def clear_vocab_deck(self, deck_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM vocab WHERE deck_id=?", (deck_id,))

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
                    ORDER BY s.due_at ASC
                    LIMIT ?
                    """,
                    (deck_id, now, cooldown_since, limit),
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
                    """,
                    (deck_id, cooldown_since),
                ).fetchall()
                pool = [int(r["id"]) for r in rows if int(r["id"]) not in set(ids)]
                random.shuffle(pool)
                ids.extend(pool[: (limit - len(ids))])

            if not ids:
                rows2 = conn.execute("SELECT id FROM vocab WHERE deck_id=? LIMIT ?", (deck_id, limit)).fetchall()
                ids = [int(r["id"]) for r in rows2]

        random.shuffle(ids)
        return ids[:limit]

    def ensure_state(self, vocab_id: int) -> VocabState:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM vocab_states WHERE vocab_id=?", (vocab_id,)).fetchone()
            if row:
                return self._row_to_state(row)

            now = int(time.time())
            conn.execute("INSERT INTO vocab_states(vocab_id, due_at) VALUES (?, ?)", (vocab_id, now))
            row2 = conn.execute("SELECT * FROM vocab_states WHERE vocab_id=?", (vocab_id,)).fetchone()
            return self._row_to_state(row2)

    def update_state(self, state: VocabState) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE vocab_states
                   SET ease=?, interval_days=?, reps=?, lapses=?, due_at=?, last_review_at=?
                 WHERE vocab_id=?
                """,
                (state.ease, state.interval_days, state.reps, state.lapses, state.due_at, state.last_review_at, state.vocab_id),
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
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO reviews(
                    vocab_id,
                    typed_meaning, typed_gender, typed_plural,
                    meaning_correct, gender_correct, plural_correct,
                    tip_used, gender_tip_used,
                    was_checked, was_skipped,
                    rating, response_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vocab_id,
                    typed_meaning, typed_gender, typed_plural,
                    meaning_correct, gender_correct, plural_correct,
                    int(tip_used), int(gender_tip_used),
                    int(was_checked), int(was_skipped),
                    rating, response_ms,
                ),
            )

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
                    ORDER BY s.due_at ASC
                    LIMIT ?
                    """,
                    (deck_id, now, cooldown_since, limit),
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
                    """,
                    (deck_id, cooldown_since),
                ).fetchall()
                pool = [int(r["id"]) for r in rows if int(r["id"]) not in set(ids)]
                random.shuffle(pool)
                ids.extend(pool[: (limit - len(ids))])

            if not ids:
                rows2 = conn.execute("SELECT id FROM grammar WHERE deck_id=? LIMIT ?", (deck_id, limit)).fetchall()
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

    def update_grammar_state(self, state: GrammarState) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE grammar_states
                   SET ease=?, interval_days=?, reps=?, lapses=?, due_at=?, last_review_at=?
                 WHERE grammar_id=?
                """,
                (state.ease, state.interval_days, state.reps, state.lapses, state.due_at, state.last_review_at, state.grammar_id),
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
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO grammar_reviews(
                    grammar_id,
                    typed_blank, correct,
                    meaning_tip_used, hint_used, grammar_tip_used,
                    was_checked, was_skipped,
                    rating, response_ms
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (grammar_id, typed_blank, correct,
                 int(meaning_tip_used), int(hint_used), int(grammar_tip_used),
                 int(was_checked), int(was_skipped), rating, response_ms),
            )

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
                    ORDER BY st.due_at ASC
                    LIMIT ?
                    """,
                    (deck_id, now, cooldown_since, int(limit)),
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
                    """,
                    (deck_id, cooldown_since),
                ).fetchall()
                pool = [int(r["id"]) for r in rows if int(r["id"]) not in set(ids)]
                random.shuffle(pool)
                ids.extend(pool[: (limit - len(ids))])

            if not ids:
                rows2 = conn.execute(
                    "SELECT id FROM sentences WHERE deck_id=? LIMIT ?",
                    (deck_id, int(limit)),
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

    def update_sentence_state(self, state: SentenceState) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE sentence_states
                   SET ease=?, interval_days=?, reps=?, lapses=?, due_at=?, last_review_at=?
                 WHERE sentence_id=?
                """,
                (
                    state.ease,
                    state.interval_days,
                    state.reps,
                    state.lapses,
                    state.due_at,
                    state.last_review_at,
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
    ) -> None:
        with self._conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO sentence_reviews(sentence_id,
                                                 typed_text, correct,
                                                 tip_used, translation_used,
                                                 was_checked, was_skipped,
                                                 rating, response_ms,
                                                 bank_size, tokens_used, mismatch_count, cap_errors, punct_errors)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sentence_id,
                        typed_text,
                        correct,
                        int(tip_used),
                        int(translation_used),
                        int(was_checked),
                        int(was_skipped),
                        rating,
                        response_ms,
                        bank_size,
                        tokens_used,
                        mismatch_count,
                        cap_errors,
                        punct_errors,
                    ),
                )
            except Exception:
                conn.execute(
                    """
                    INSERT INTO sentence_reviews(sentence_id,
                                                 typed_text, correct,
                                                 tip_used, was_checked, was_skipped,
                                                 rating, response_ms,
                                                 bank_size, tokens_used, mismatch_count, cap_errors, punct_errors)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sentence_id,
                        typed_text,
                        correct,
                        int(tip_used),
                        int(was_checked),
                        int(was_skipped),
                        rating,
                        response_ms,
                        bank_size,
                        tokens_used,
                        mismatch_count,
                        cap_errors,
                        punct_errors,
                    ),
                )

    # ---------- Progress helpers ----------
    def due_count(self, deck_id: int) -> int:
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM vocab v
                  JOIN vocab_states s ON s.vocab_id=v.id
                 WHERE v.deck_id=? AND s.due_at<=?
                """,
                (deck_id, now),
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
                """,
                (deck_id, since),
            ).fetchone()
            return int(row["c"]) if row else 0

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

    def grammar_due_count(self, deck_id: int) -> int:
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM grammar g
                  JOIN grammar_states s ON s.grammar_id=g.id
                 WHERE g.deck_id=? AND s.due_at<=?
                """,
                (deck_id, now),
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

    def sentence_due_count(self, deck_id: int) -> int:
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                  FROM sentences s
                  JOIN sentence_states st ON st.sentence_id=s.id
                 WHERE s.deck_id=? AND st.due_at<=?
                """,
                (deck_id, now),
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
    def _row_to_state(r: sqlite3.Row) -> VocabState:
        return VocabState(
            vocab_id=int(r["vocab_id"]),
            ease=float(r["ease"]),
            interval_days=float(r["interval_days"]),
            reps=int(r["reps"]),
            lapses=int(r["lapses"]),
            due_at=int(r["due_at"]),
            last_review_at=int(r["last_review_at"]) if r["last_review_at"] is not None else None,
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
        )

    @staticmethod
    def _tokenize_sentence(text: str) -> list[str]:
        import re
        _TOKEN_RE = re.compile(
            r"[A-Za-zÄÖÜäöüß]+(?:[-'][A-Za-zÄÖÜäöß]+)*|\d+|[.,!?;:()\[\]{}\"""„‚''…–—-]"
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
        )
