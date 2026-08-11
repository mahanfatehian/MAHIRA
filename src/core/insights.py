from __future__ import annotations

import re
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
class RecentFailure(TroubleItem):
    failure_count: int = 0
    last_failed_at: int = 0
    is_leech: bool = False
    leech_window_days: int = 30


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

    _PRIMARY_MODES = {
        'vocab': 'recognition',
        'grammar': 'production',
        'sentences': 'builder',
        'listening': 'comprehension',
    }

    # SQL fragments are fixed internal constants. Caller values are always
    # parameters, so adding a lane cannot turn filters into SQL identifiers.
    _FAILURE_LANES = {
        ("vocab", "recognition"): {
            "reviews": "reviews",
            "items": "vocab",
            "review_fk": "vocab_id",
            "prompt": "COALESCE(i.article || ' ', '') || i.word",
            "answer": "i.meaning",
            "state_join": "LEFT JOIN vocab_states s ON s.vocab_id=f.item_id",
            "buried": "s.buried_until",
            "suspended": "s.suspended",
        },
        ("vocab", "production"): {
            "reviews": "reviews",
            "items": "vocab",
            "review_fk": "vocab_id",
            "prompt": "COALESCE(i.article || ' ', '') || i.word",
            "answer": "i.meaning",
            "state_join": (
                "LEFT JOIN vocab_practice_states s ON s.vocab_id=f.item_id "
                "AND s.practice_mode='production' "
                "LEFT JOIN vocab_states controls ON controls.vocab_id=f.item_id"
            ),
            "buried": "controls.buried_until",
            "suspended": "controls.suspended",
        },
        ("vocab", "dictation"): {
            "reviews": "reviews",
            "items": "vocab",
            "review_fk": "vocab_id",
            "prompt": "COALESCE(i.article || ' ', '') || i.word",
            "answer": "i.meaning",
            "state_join": (
                "LEFT JOIN vocab_practice_states s ON s.vocab_id=f.item_id "
                "AND s.practice_mode='dictation' "
                "LEFT JOIN vocab_states controls ON controls.vocab_id=f.item_id"
            ),
            "buried": "controls.buried_until",
            "suspended": "controls.suspended",
        },
        ("grammar", "production"): {
            "reviews": "grammar_reviews",
            "items": "grammar",
            "review_fk": "grammar_id",
            "prompt": "i.test_text",
            "answer": "i.answer",
            "state_join": "LEFT JOIN grammar_states s ON s.grammar_id=f.item_id",
            "buried": "s.buried_until",
            "suspended": "s.suspended",
        },
        ("sentences", "builder"): {
            "reviews": "sentence_reviews",
            "items": "sentences",
            "review_fk": "sentence_id",
            "prompt": "COALESCE(i.translation, i.target_text)",
            "answer": "i.target_text",
            "state_join": "LEFT JOIN sentence_states s ON s.sentence_id=f.item_id",
            "buried": "s.buried_until",
            "suspended": "s.suspended",
        },
        ("listening", "comprehension"): {
            "reviews": "listening_reviews",
            "items": "listening",
            "review_fk": "listening_id",
            "prompt": "i.question",
            "answer": "i.answer",
            "state_join": "LEFT JOIN listening_states s ON s.listening_id=f.item_id",
            "buried": "s.buried_until",
            "suspended": "s.suspended",
        },
    }
    _FAILURE_WINDOW_DAYS = 30
    _LEECH_FAILURE_COUNT = 3
    _MAX_FAILURE_LIMIT = 500
    _ERROR_TAG_RE = re.compile(r"^[a-z0-9_]+$")

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

    def recent_failures(
        self,
        *,
        level: str | None = None,
        book_slug: str | None = None,
        lektion_number: int | None = None,
        objective: str | None = None,
        practice_mode: str | None = None,
        tag: str | None = None,
        limit: int = 20,
        now: int | float | None = None,
    ) -> list[RecentFailure]:
        """Return newest unique Again cards, optionally filtered.

        Lane identity is always the exact (objective, practice_mode) pair.
        Lesson identity is the full (level, book_slug, lektion_number)
        tuple. Partial lane or lesson filters are rejected instead of silently
        broadening a drill. A failure is the persisted effective rating=0;
        imperfect Hard/Good rows are not scheduler failures.
        """
        lesson_values = (level, book_slug, lektion_number)
        supplied_lesson_values = sum(value is not None for value in lesson_values)
        if supplied_lesson_values not in {0, len(lesson_values)}:
            raise ValueError(
                "level, book_slug, and lektion_number must be supplied together"
            )
        lesson: tuple[str, str, int] | None = None
        if supplied_lesson_values:
            if isinstance(lektion_number, bool):
                raise ValueError("lektion_number must be an integer")
            try:
                lesson_number = int(lektion_number)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("lektion_number must be an integer") from exc
            normalized_level = str(level or "").strip().upper()
            normalized_book = str(book_slug or "").strip().lower()
            if not normalized_level or not normalized_book or lesson_number <= 0:
                raise ValueError("lesson context must be non-empty and positive")
            lesson = (normalized_level, normalized_book, lesson_number)

        supplied_lane_values = int(objective is not None) + int(
            practice_mode is not None
        )
        if supplied_lane_values == 1:
            raise ValueError(
                "objective and practice_mode must be supplied together"
            )
        if supplied_lane_values:
            lane = (
                str(objective or "").strip().lower(),
                str(practice_mode or "").strip().lower(),
            )
            if lane not in self._FAILURE_LANES:
                raise ValueError(f"Unsupported review lane: {lane!r}")
            lanes = (lane,)
        else:
            lanes = tuple(self._FAILURE_LANES)

        normalized_tag = str(tag or "").strip().lower()
        if normalized_tag and self._ERROR_TAG_RE.fullmatch(normalized_tag) is None:
            raise ValueError(f"Invalid error tag: {tag!r}")

        if isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        try:
            requested_limit = int(limit)
            current = int(time.time() if now is None else float(now))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("limit and now must be numeric") from exc
        if requested_limit <= 0:
            return []
        requested_limit = min(requested_limit, self._MAX_FAILURE_LIMIT)

        failures: list[RecentFailure] = []
        for lane in lanes:
            failures.extend(
                self._recent_failures_for_lane(
                    lane,
                    lesson=lesson,
                    tag=(normalized_tag or None),
                    limit=requested_limit,
                    now=current,
                )
            )
        failures.sort(
            key=lambda item: (
                -item.last_failed_at,
                item.objective,
                item.item_id,
                item.practice_mode,
            )
        )
        return failures[:requested_limit]

    def _recent_failures_for_lane(
        self,
        lane: tuple[str, str],
        *,
        lesson: tuple[str, str, int] | None,
        tag: str | None,
        limit: int,
        now: int,
    ) -> list[RecentFailure]:
        objective, practice_mode = lane
        spec = self._FAILURE_LANES[lane]
        context_filter = ""
        params: list[Any] = [practice_mode, objective, now]
        if lesson is not None:
            context_filter = (
                "AND d.level=? AND l.level=? AND b.slug=? AND l.number=?"
            )
            level, book_slug, lesson_number = lesson
            params.extend((level, level, book_slug, lesson_number))

        cutoff = now - self._FAILURE_WINDOW_DAYS * 24 * 60 * 60
        params.extend((cutoff, now))
        tag_filter = ""
        if tag is not None:
            # Delimiter guards keep article from matching article_missing.
            # Removing spaces also tolerates legacy "a, b" rows.
            tag_filter = (
                "WHERE instr(',' || replace(lower(error_tags), ' ', '') || ',', "
                "',' || ? || ',') > 0"
            )
            params.append(tag)
        params.extend((now, limit))

        reviews = spec["reviews"]
        items = spec["items"]
        review_fk = spec["review_fk"]
        state_join = spec["state_join"]
        buried = spec["buried"]
        suspended = spec["suspended"]
        query = f"""
            WITH lane_failures AS (
                SELECT r.id AS review_id,
                       r.{review_fk} AS item_id,
                       r.created_at,
                       COALESCE(r.error_tags, '') AS error_tags,
                       i.deck_id,
                       {spec['prompt']} AS prompt,
                       {spec['answer']} AS answer,
                       d.level,
                       COALESCE(b.slug, '') AS book_slug,
                       COALESCE(l.number, 0) AS lektion_number
                  FROM {reviews} r
                  JOIN {items} i ON i.id=r.{review_fk}
                  JOIN decks d ON d.id=i.deck_id
                  LEFT JOIN lektions l ON l.id=d.lektion_id
                  LEFT JOIN books b ON b.id=l.book_id
                 WHERE r.rating=0
                   AND COALESCE(r.was_skipped, 0)=0
                   AND r.practice_mode=?
                   AND d.objective=?
                   AND r.created_at<=?
                   {context_filter}
            ),
            failure_counts AS (
                SELECT item_id, COUNT(*) AS failure_count
                  FROM lane_failures
                 WHERE created_at>=? AND created_at<=?
                 GROUP BY item_id
            ),
            matching_failures AS (
                SELECT * FROM lane_failures
                {tag_filter}
            ),
            ranked AS (
                SELECT matching_failures.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY item_id
                           ORDER BY created_at DESC, review_id DESC
                       ) AS item_rank
                  FROM matching_failures
            )
            SELECT f.item_id, f.deck_id, f.prompt, f.answer,
                   COALESCE(s.lapses, 0) AS lapses,
                   COALESCE(s.reps, 0) AS reps,
                   COALESCE({suspended}, 0) AS suspended,
                   f.level, f.book_slug, f.lektion_number,
                   f.error_tags, f.created_at,
                   COALESCE(c.failure_count, 0) AS failure_count
              FROM ranked f
              LEFT JOIN failure_counts c ON c.item_id=f.item_id
              {state_join}
             WHERE f.item_rank=1
               AND ({buried} IS NULL OR {buried}<=?)
             ORDER BY f.created_at DESC, f.item_id ASC, f.review_id DESC
             LIMIT ?
        """
        with self.repo._conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        failures: list[RecentFailure] = []
        for row in rows:
            failure_count = int(row["failure_count"] or 0)
            failures.append(
                RecentFailure(
                    objective=objective,
                    item_id=int(row["item_id"]),
                    prompt=str(row["prompt"] or ""),
                    answer=str(row["answer"] or ""),
                    lapses=int(row["lapses"] or 0),
                    reps=int(row["reps"] or 0),
                    suspended=bool(row["suspended"]),
                    deck_id=int(row["deck_id"]),
                    level=str(row["level"] or ""),
                    book_slug=str(row["book_slug"] or ""),
                    lektion_number=int(row["lektion_number"] or 0),
                    practice_mode=practice_mode,
                    error_tags=str(row["error_tags"] or ""),
                    failure_count=failure_count,
                    last_failed_at=int(row["created_at"] or 0),
                    is_leech=failure_count >= self._LEECH_FAILURE_COUNT,
                    leech_window_days=self._FAILURE_WINDOW_DAYS,
                )
            )
        return failures

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
                        self._PRIMARY_MODES[objective],
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
