from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta
from typing import Any


@dataclass(frozen=True)
class StudyLane:
    objective: str
    due: int
    unseen: int
    trouble: int


@dataclass(frozen=True)
class TroubleItem:
    objective: str
    item_id: int
    prompt: str
    answer: str
    lapses: int
    reps: int
    suspended: bool
    deck_id: int
    level: str
    book_slug: str
    lektion_number: int
    practice_mode: str = "recognition"
    error_tags: str = ""


@dataclass(frozen=True)
class LessonReadiness:
    number: int
    title: str
    mastery: int
    unlocked: bool


class InsightsService:
    """Read-model for global study planning and actionable mistake review."""

    _KINDS = {
        "vocab": ("vocab", "vocab_states", "vocab_id"),
        "grammar": ("grammar", "grammar_states", "grammar_id"),
        "sentences": ("sentences", "sentence_states", "sentence_id"),
        "listening": ("listening", "listening_states", "listening_id"),
    }

    def __init__(self, repo):
        self.repo = repo

    def lanes(self) -> list[StudyLane]:
        now = int(time.time())
        result: list[StudyLane] = []
        with self.repo._conn() as conn:
            for objective, (items, states, fk) in self._KINDS.items():
                due = conn.execute(
                    f"SELECT COUNT(*) FROM {states} WHERE due_at<=? AND suspended=0 "
                    "AND (buried_until IS NULL OR buried_until<=?)",
                    (now, now),
                ).fetchone()[0]
                unseen = conn.execute(
                    f"SELECT COUNT(*) FROM {items} i LEFT JOIN {states} s ON s.{fk}=i.id "
                    "WHERE (s.reps IS NULL OR s.reps=0) "
                    "AND COALESCE(s.suspended, 0)=0 "
                    "AND (s.buried_until IS NULL OR s.buried_until<=?)",
                    (now,),
                ).fetchone()[0]
                if objective == "vocab":
                    # Count a vocabulary card once even if it is troublesome in
                    # recognition and one or both active-recall Lab lanes.
                    trouble = conn.execute(
                        """
                        SELECT COUNT(DISTINCT i.id)
                          FROM vocab i
                          LEFT JOIN vocab_states s ON s.vocab_id=i.id
                         WHERE COALESCE(s.suspended, 0)=0
                           AND (s.buried_until IS NULL OR s.buried_until<=?)
                           AND (
                             COALESCE(s.lapses, 0)>=3 OR EXISTS (
                               SELECT 1 FROM vocab_practice_states ps
                                WHERE ps.vocab_id=i.id AND ps.lapses>=3
                             )
                           )
                        """,
                        (now,),
                    ).fetchone()[0]
                else:
                    trouble = conn.execute(
                        f"SELECT COUNT(*) FROM {states} WHERE lapses>=3 AND suspended=0 "
                        "AND (buried_until IS NULL OR buried_until<=?)",
                        (now,),
                    ).fetchone()[0]
                result.append(StudyLane(objective, int(due), int(unseen), int(trouble)))
        return result

    def reviewed_today(self) -> int:
        # Calendar days are local UX concepts. Epoch modulo computes midnight
        # in UTC and makes the Today count reset at the wrong hour elsewhere.
        local_now = datetime.fromtimestamp(time.time())
        start = int(datetime.combine(local_now.date(), datetime_time.min).timestamp())
        return sum(self.repo.daily_review_counts(start).values())

    def recommended_context(self, objective: str) -> tuple[str, str, int] | None:
        if objective not in self._KINDS:
            return None
        items, states, fk = self._KINDS[objective]
        now = int(time.time())
        with self.repo._conn() as conn:
            row = conn.execute(
                f"""
                SELECT d.level, COALESCE(b.slug, '') AS book_slug,
                       COALESCE(l.number, 0) AS lektion_number,
                       SUM(CASE WHEN s.due_at<=? THEN 1 ELSE 0 END) AS due_count
                FROM {items} i JOIN {states} s ON s.{fk}=i.id
                JOIN decks d ON d.id=i.deck_id
                LEFT JOIN lektions l ON l.id=d.lektion_id
                LEFT JOIN books b ON b.id=l.book_id
                WHERE s.suspended=0 AND (s.buried_until IS NULL OR s.buried_until<=?)
                GROUP BY d.id
                ORDER BY due_count DESC, MIN(s.due_at) ASC
                LIMIT 1
                """,
                (now, now),
            ).fetchone()
        if not row or not row["book_slug"] or not row["lektion_number"]:
            return None
        return str(row["level"]), str(row["book_slug"]), int(row["lektion_number"])

    def trouble_items(self, limit: int = 100) -> list[TroubleItem]:
        selects = (
            ("vocab", "vocab", "vocab_states", "vocab_id", "COALESCE(i.article || ' ', '') || i.word", "i.meaning"),
            ("grammar", "grammar", "grammar_states", "grammar_id", "i.test_text", "i.answer"),
            ("sentences", "sentences", "sentence_states", "sentence_id", "COALESCE(i.translation, i.target_text)", "i.target_text"),
            ("listening", "listening", "listening_states", "listening_id", "i.question", "i.answer"),
        )
        found: list[TroubleItem] = []
        now = int(time.time())
        with self.repo._conn() as conn:
            for objective, items, states, fk, prompt, answer in selects:
                rows = conn.execute(
                    f"""
                    SELECT i.id, i.deck_id, {prompt} AS prompt, {answer} AS answer,
                           s.lapses, s.reps, s.suspended, d.level,
                           COALESCE(b.slug, '') AS book_slug, COALESCE(l.number, 0) AS lektion_number
                    FROM {items} i JOIN {states} s ON s.{fk}=i.id
                    JOIN decks d ON d.id=i.deck_id
                    LEFT JOIN lektions l ON l.id=d.lektion_id
                    LEFT JOIN books b ON b.id=l.book_id
                    WHERE (
                      s.lapses>=2 OR EXISTS (
                        SELECT 1 FROM card_flags f WHERE f.item_type=? AND f.item_id=i.id
                      )
                    )
                    AND (s.buried_until IS NULL OR s.buried_until<=?)
                    ORDER BY s.suspended ASC, s.lapses DESC, s.reps DESC
                    LIMIT ?
                    """,
                    (objective, now, int(limit)),
                ).fetchall()
                found.extend(
                    TroubleItem(
                        objective, int(r["id"]), str(r["prompt"] or ""), str(r["answer"] or ""),
                        int(r["lapses"]), int(r["reps"]), bool(r["suspended"]), int(r["deck_id"]),
                        str(r["level"] or ""), str(r["book_slug"] or ""), int(r["lektion_number"] or 0),
                    )
                    for r in rows
                )

            # Production and dictation are intentionally separate FSRS lanes,
            # but their recurring failures still belong in the learner's one
            # Mistakes notebook. Base state contributes only suspend/bury
            # controls; no recognition scheduling values are shared here.
            lab_rows = conn.execute(
                """
                SELECT i.id, i.deck_id,
                       COALESCE(i.article || ' ', '') || i.word AS prompt,
                       i.meaning AS answer,
                       ps.lapses, ps.reps, COALESCE(base.suspended, 0) AS suspended,
                       d.level, COALESCE(b.slug, '') AS book_slug,
                       COALESCE(l.number, 0) AS lektion_number,
                       ps.practice_mode,
                       COALESCE((
                         SELECT r.error_tags FROM reviews r
                          WHERE r.vocab_id=i.id AND r.practice_mode=ps.practice_mode
                          ORDER BY r.created_at DESC, r.id DESC LIMIT 1
                       ), '') AS error_tags
                  FROM vocab i
                  JOIN vocab_practice_states ps ON ps.vocab_id=i.id
                  LEFT JOIN vocab_states base ON base.vocab_id=i.id
                  JOIN decks d ON d.id=i.deck_id
                  LEFT JOIN lektions l ON l.id=d.lektion_id
                  LEFT JOIN books b ON b.id=l.book_id
                 WHERE ps.lapses>=2
                   AND (base.buried_until IS NULL OR base.buried_until<=?)
                 ORDER BY suspended ASC, ps.lapses DESC, ps.reps DESC
                 LIMIT ?
                """,
                (now, int(limit)),
            ).fetchall()
            found.extend(
                TroubleItem(
                    "vocab",
                    int(r["id"]),
                    str(r["prompt"] or ""),
                    str(r["answer"] or ""),
                    int(r["lapses"]),
                    int(r["reps"]),
                    bool(r["suspended"]),
                    int(r["deck_id"]),
                    str(r["level"] or ""),
                    str(r["book_slug"] or ""),
                    int(r["lektion_number"] or 0),
                    str(r["practice_mode"] or "recognition"),
                    str(r["error_tags"] or ""),
                )
                for r in lab_rows
            )
        return sorted(found, key=lambda item: (item.suspended, -item.lapses, -item.reps))[:limit]

    def lesson_path(self, level: str, book_slug: str) -> list[LessonReadiness]:
        book_id = self.repo.get_book_id(book_slug) if book_slug else None
        if book_id is None:
            return []
        lessons = self.repo.get_lektions_for_book_level(book_id, level)
        result: list[LessonReadiness] = []
        previous_mastery = 100
        with self.repo._conn() as conn:
            for lesson in lessons:
                total = learned = 0
                for items, states, fk in self._KINDS.values():
                    row = conn.execute(
                        f"""
                        SELECT COUNT(i.id) AS total,
                               SUM(CASE WHEN COALESCE(s.reps,0)>=2 AND COALESCE(s.stability,0)>=7
                                   THEN 1 ELSE 0 END) AS learned
                        FROM {items} i JOIN decks d ON d.id=i.deck_id
                        LEFT JOIN {states} s ON s.{fk}=i.id
                        WHERE d.lektion_id=?
                        """,
                        (lesson.id,),
                    ).fetchone()
                    total += int(row["total"] or 0)
                    learned += int(row["learned"] or 0)
                mastery = round(100 * learned / total) if total else 0
                unlocked = lesson.number == lessons[0].number or previous_mastery >= 60
                result.append(LessonReadiness(lesson.number, lesson.title, mastery, unlocked))
                previous_mastery = mastery
        return result

    def set_suspended(self, objective: str, item_id: int, suspended: bool) -> None:
        normalized = str(objective or "").strip().lower()
        spec = self._KINDS.get(normalized)
        if spec is None:
            raise ValueError(f"Unsupported study objective: {objective!r}")
        items, table, fk = spec
        with self.repo._conn() as conn:
            exists = conn.execute(
                f"SELECT 1 FROM {items} WHERE id=?",
                (int(item_id),),
            ).fetchone()
            if exists is None:
                raise LookupError(f"No {normalized} item exists for id {item_id!r}")
            if normalized == "vocab":
                conn.execute(
                    "INSERT OR IGNORE INTO vocab_states(vocab_id, due_at) VALUES (?, ?)",
                    (int(item_id), int(time.time())),
                )
            cursor = conn.execute(
                f"UPDATE {table} SET suspended=? WHERE {fk}=?",
                (int(suspended), int(item_id)),
            )
            if cursor.rowcount != 1:
                raise LookupError(
                    f"No {normalized} scheduling state exists for item {item_id!r}"
                )

    @staticmethod
    def next_local_midnight(now: int | float | None = None) -> int:
        """Return the epoch second at the start of the next local day.

        ``datetime.timestamp`` applies the operating system's local timezone
        rules, including daylight-saving transitions.  Accepting ``now`` keeps
        the calendar-boundary behavior deterministic in tests without changing
        the process-wide clock.
        """
        current = float(time.time() if now is None else now)
        local_now = datetime.fromtimestamp(current)
        next_day = local_now.date() + timedelta(days=1)
        return int(datetime.combine(next_day, datetime_time.min).timestamp())

    def bury(
        self,
        objective: str,
        item_id: int,
        *,
        now: int | float | None = None,
    ) -> int:
        """Exclude one card until tomorrow, committed as one database write.

        The returned epoch can be used by the UI for an accurate confirmation.
        A missing state row is reported instead of presenting a false success.
        """
        normalized = str(objective or "").strip().lower()
        spec = self._KINDS.get(normalized)
        if spec is None:
            raise ValueError(f"Unsupported study objective: {objective!r}")

        items, table, fk = spec
        buried_until = self.next_local_midnight(now)
        with self.repo._conn() as conn:
            exists = conn.execute(
                f"SELECT 1 FROM {items} WHERE id=?",
                (int(item_id),),
            ).fetchone()
            if exists is None:
                raise LookupError(f"No {normalized} item exists for id {item_id!r}")
            if normalized == "vocab":
                conn.execute(
                    "INSERT OR IGNORE INTO vocab_states(vocab_id, due_at) VALUES (?, ?)",
                    (int(item_id), int(time.time() if now is None else float(now))),
                )
            cursor = conn.execute(
                f"UPDATE {table} SET buried_until=? WHERE {fk}=?",
                (buried_until, int(item_id)),
            )
            if cursor.rowcount != 1:
                raise LookupError(
                    f"No {normalized} scheduling state exists for item {item_id!r}"
                )
        return buried_until
