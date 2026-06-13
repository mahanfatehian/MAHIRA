from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

try:
    import joblib
    import numpy as np
    from sklearn.linear_model import SGDRegressor
    from sklearn.preprocessing import StandardScaler

    _SKLEARN_OK = True
except Exception:
    joblib = None
    np = None
    SGDRegressor = None
    StandardScaler = None
    _SKLEARN_OK = False


def _safe_key(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "_", value)
    return value.strip("_") or "default"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _row(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except Exception:
        return default
    return default if value is None else value


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class _OnlineDifficultyModel:
    """
    Tiny online sklearn model.

    Target:
    - 0.0 = easy / low priority
    - 1.0 = difficult / high priority

    Ranking still has a deterministic DB-score fallback, so the app keeps
    adapting even before the sklearn model has enough data.
    """

    def __init__(self) -> None:
        if not _SKLEARN_OK:
            self.scaler = None
            self.model = None
            self.is_fitted = False
            return

        self.scaler = StandardScaler()
        self.model = SGDRegressor(
            loss="squared_error",
            penalty="l2",
            alpha=0.0001,
            learning_rate="optimal",
            max_iter=1,
            tol=None,
            random_state=42,
        )
        self.is_fitted = False

    def partial_fit(self, x: list[float], y: float) -> None:
        if not _SKLEARN_OK or self.scaler is None or self.model is None:
            return

        X = np.asarray([x], dtype=float)
        Y = np.asarray([float(_clip(y, 0.0, 1.0))], dtype=float)

        self.scaler.partial_fit(X)
        Xs = self.scaler.transform(X)
        self.model.partial_fit(Xs, Y)
        self.is_fitted = True

    def predict_many(self, vectors: list[list[float]]) -> list[float]:
        if not vectors:
            return []

        if not _SKLEARN_OK or self.scaler is None or self.model is None:
            return [0.5] * len(vectors)

        if not self.is_fitted:
            return [0.5] * len(vectors)

        X = np.asarray(vectors, dtype=float)
        Xs = self.scaler.transform(X)
        preds = self.model.predict(Xs)

        return [_clip(float(v), 0.0, 1.0) for v in preds]


class SklearnRanker:
    """
    Adaptive ranker for vocab / grammar / sentences.

    Very important:
    SessionService uses queue.pop(), so this ranker returns:
    LOW priority first, HIGH priority last.
    """

    def __init__(self, repo, model_dir: str | Path):
        self.repo = repo
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self.enabled = True
        self._models: dict[str, _OnlineDifficultyModel] = {}

    # ------------------------------------------------------------------
    # Public readiness
    # ------------------------------------------------------------------
    def is_ready(
        self,
        *,
        level: str | None = None,
        objective: str = "vocab",
        min_seen: int = 8,
    ) -> bool:
        count = self._review_count(objective=objective, level=level)
        return count >= int(min_seen or 0)

    # ------------------------------------------------------------------
    # Online updates after review submit
    # ------------------------------------------------------------------
    def update_vocab(
        self,
        *,
        item: Any,
        state_before: Any,
        review_result: dict[str, Any],
        effective_rating: int,
        tip_used: bool,
        gender_tip_used: bool,
        was_checked: bool,
        was_skipped: bool,
        response_ms: int | None,
        level: str | None = None,
    ) -> None:
        target = self._target_from_review(
            effective_rating=effective_rating,
            correct=bool(review_result.get("meaning_ok")),
            tip_used=bool(tip_used or gender_tip_used),
            was_checked=was_checked,
            was_skipped=was_skipped,
        )

        features = self._vector(
            ease=_float(getattr(state_before, "ease", 2.5), 2.5),
            interval_days=_float(getattr(state_before, "interval_days", 0.0), 0.0),
            reps=_float(getattr(state_before, "reps", 0), 0.0),
            lapses=_float(getattr(state_before, "lapses", 0), 0.0),
            total_reviews=0.0,
            avg_rating=float(effective_rating),
            accuracy=self._vocab_accuracy_from_result(review_result),
            tip_rate=1.0 if tip_used else 0.0,
            helper_rate=1.0 if gender_tip_used else 0.0,
            skip_rate=1.0 if was_skipped else 0.0,
            response_ms=_float(response_ms, 0.0),
            text_len=float(len(str(getattr(item, "word", "") or ""))),
            extra_len=float(len(str(getattr(item, "meaning", "") or ""))),
            is_unseen=1.0 if _int(getattr(state_before, "reps", 0), 0) <= 0 else 0.0,
            overdue_days=0.0,
        )

        self._fit("vocab", level, features, target)

    def update_grammar(
        self,
        *,
        item: Any,
        state_before: Any,
        review_result: dict[str, Any],
        effective_rating: int,
        meaning_tip_used: bool,
        hint_used: bool,
        grammar_tip_used: bool,
        was_checked: bool,
        was_skipped: bool,
        response_ms: int | None,
        level: str | None = None,
    ) -> None:
        target = self._target_from_review(
            effective_rating=effective_rating,
            correct=bool(review_result.get("ok")),
            tip_used=bool(meaning_tip_used or hint_used or grammar_tip_used),
            was_checked=was_checked,
            was_skipped=was_skipped,
        )

        features = self._vector(
            ease=_float(getattr(state_before, "ease", 2.5), 2.5),
            interval_days=_float(getattr(state_before, "interval_days", 0.0), 0.0),
            reps=_float(getattr(state_before, "reps", 0), 0.0),
            lapses=_float(getattr(state_before, "lapses", 0), 0.0),
            total_reviews=0.0,
            avg_rating=float(effective_rating),
            accuracy=1.0 if review_result.get("ok") else 0.0,
            tip_rate=1.0 if meaning_tip_used else 0.0,
            helper_rate=1.0 if (hint_used or grammar_tip_used) else 0.0,
            skip_rate=1.0 if was_skipped else 0.0,
            response_ms=_float(response_ms, 0.0),
            text_len=float(len(str(getattr(item, "test_text", "") or ""))),
            extra_len=float(len(str(getattr(item, "answer", "") or ""))),
            is_unseen=1.0 if _int(getattr(state_before, "reps", 0), 0) <= 0 else 0.0,
            overdue_days=0.0,
        )

        self._fit("grammar", level, features, target)

    def update_sentence(
        self,
        *,
        item: Any,
        state_before: Any,
        review_result: dict[str, Any],
        effective_rating: int,
        tip_used: bool,
        translation_used: bool,
        was_checked: bool,
        was_skipped: bool,
        response_ms: int | None,
        level: str | None = None,
    ) -> None:
        target = self._target_from_review(
            effective_rating=effective_rating,
            correct=bool(review_result.get("ok")),
            tip_used=bool(tip_used or translation_used),
            was_checked=was_checked,
            was_skipped=was_skipped,
        )

        features = self._vector(
            ease=_float(getattr(state_before, "ease", 2.5), 2.5),
            interval_days=_float(getattr(state_before, "interval_days", 0.0), 0.0),
            reps=_float(getattr(state_before, "reps", 0), 0.0),
            lapses=_float(getattr(state_before, "lapses", 0), 0.0),
            total_reviews=0.0,
            avg_rating=float(effective_rating),
            accuracy=1.0 if review_result.get("ok") else 0.0,
            tip_rate=1.0 if tip_used else 0.0,
            helper_rate=1.0 if translation_used else 0.0,
            skip_rate=1.0 if was_skipped else 0.0,
            response_ms=_float(response_ms, 0.0),
            text_len=float(len(str(getattr(item, "target_text", "") or ""))),
            extra_len=float(len(getattr(item, "words", []) or [])),
            is_unseen=1.0 if _int(getattr(state_before, "reps", 0), 0) <= 0 else 0.0,
            overdue_days=0.0,
        )

        self._fit("sentences", level, features, target)

    # ------------------------------------------------------------------
    # Public ranking
    # ------------------------------------------------------------------
    def rank_vocab_ids(
        self,
        ids: list[int],
        *,
        level: str | None = None,
        **_: Any,
    ) -> list[int]:
        if not ids:
            return []

        try:
            rows = self._fetch_vocab_rows(ids)
            return self._rank_rows(
                ids=ids,
                rows=rows,
                objective="vocab",
                level=level,
                score_fn=self._score_vocab_row,
                vector_fn=self._vector_vocab_row,
            )
        except Exception:
            return list(ids)

    def rank_grammar_ids(
        self,
        ids: list[int],
        *,
        level: str | None = None,
        **_: Any,
    ) -> list[int]:
        if not ids:
            return []

        try:
            rows = self._fetch_grammar_rows(ids)
            return self._rank_rows(
                ids=ids,
                rows=rows,
                objective="grammar",
                level=level,
                score_fn=self._score_grammar_row,
                vector_fn=self._vector_grammar_row,
            )
        except Exception:
            return list(ids)

    def rank_sentence_ids(
        self,
        ids: list[int],
        *,
        level: str | None = None,
        **_: Any,
    ) -> list[int]:
        if not ids:
            return []

        try:
            rows = self._fetch_sentence_rows(ids)
            return self._rank_rows(
                ids=ids,
                rows=rows,
                objective="sentences",
                level=level,
                score_fn=self._score_sentence_row,
                vector_fn=self._vector_sentence_row,
            )
        except Exception:
            return list(ids)

    # ------------------------------------------------------------------
    # DB reads
    # ------------------------------------------------------------------
    def _fetch_vocab_rows(self, ids: list[int]) -> dict[int, Any]:
        placeholders = ",".join("?" for _ in ids)
        q = f"""
            SELECT
                v.id,
                v.word,
                v.meaning,
                v.pos,
                s.ease,
                s.interval_days,
                s.reps,
                s.lapses,
                s.due_at,
                s.last_review_at,
                COUNT(r.id) AS total_reviews,
                AVG(r.rating) AS avg_rating,
                AVG(CASE WHEN r.meaning_correct IS NOT NULL THEN r.meaning_correct END) AS meaning_acc,
                AVG(CASE WHEN r.gender_correct IS NOT NULL THEN r.gender_correct END) AS gender_acc,
                AVG(CASE WHEN r.plural_correct IS NOT NULL THEN r.plural_correct END) AS plural_acc,
                AVG(r.tip_used) AS tip_rate,
                AVG(r.gender_tip_used) AS helper_rate,
                AVG(r.was_skipped) AS skip_rate,
                AVG(r.response_ms) AS avg_response_ms
            FROM vocab v
            LEFT JOIN vocab_states s ON s.vocab_id = v.id
            LEFT JOIN reviews r ON r.vocab_id = v.id
            WHERE v.id IN ({placeholders})
            GROUP BY v.id
        """
        with self.repo._conn() as conn:
            rows = conn.execute(q, tuple(ids)).fetchall()
        return {int(r["id"]): r for r in rows}

    def _fetch_grammar_rows(self, ids: list[int]) -> dict[int, Any]:
        placeholders = ",".join("?" for _ in ids)
        q = f"""
            SELECT
                g.id,
                g.test_text,
                g.answer,
                g.meaning,
                g.tip,
                g.grammar_tip,
                s.ease,
                s.interval_days,
                s.reps,
                s.lapses,
                s.due_at,
                s.last_review_at,
                COUNT(r.id) AS total_reviews,
                AVG(r.rating) AS avg_rating,
                AVG(r.correct) AS accuracy,
                AVG(r.meaning_tip_used) AS tip_rate,
                AVG(CASE WHEN r.hint_used = 1 OR r.grammar_tip_used = 1 THEN 1.0 ELSE 0.0 END) AS helper_rate,
                AVG(r.was_skipped) AS skip_rate,
                AVG(r.response_ms) AS avg_response_ms
            FROM grammar g
            LEFT JOIN grammar_states s ON s.grammar_id = g.id
            LEFT JOIN grammar_reviews r ON r.grammar_id = g.id
            WHERE g.id IN ({placeholders})
            GROUP BY g.id
        """
        with self.repo._conn() as conn:
            rows = conn.execute(q, tuple(ids)).fetchall()
        return {int(r["id"]): r for r in rows}

    def _fetch_sentence_rows(self, ids: list[int]) -> dict[int, Any]:
        placeholders = ",".join("?" for _ in ids)
        q = f"""
            SELECT
                se.id,
                se.target_text,
                se.translation,
                se.tip,
                st.ease,
                st.interval_days,
                st.reps,
                st.lapses,
                st.due_at,
                st.last_review_at,
                COUNT(r.id) AS total_reviews,
                AVG(r.rating) AS avg_rating,
                AVG(r.correct) AS accuracy,
                AVG(r.tip_used) AS tip_rate,
                AVG(r.translation_used) AS helper_rate,
                AVG(r.was_skipped) AS skip_rate,
                AVG(r.response_ms) AS avg_response_ms,
                AVG(r.mismatch_count) AS avg_mismatch_count,
                AVG(r.cap_errors) AS avg_cap_errors,
                AVG(r.punct_errors) AS avg_punct_errors
            FROM sentences se
            LEFT JOIN sentence_states st ON st.sentence_id = se.id
            LEFT JOIN sentence_reviews r ON r.sentence_id = se.id
            WHERE se.id IN ({placeholders})
            GROUP BY se.id
        """
        with self.repo._conn() as conn:
            rows = conn.execute(q, tuple(ids)).fetchall()
        return {int(r["id"]): r for r in rows}

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    def _rank_rows(
        self,
        *,
        ids: list[int],
        rows: dict[int, Any],
        objective: str,
        level: str | None,
        score_fn,
        vector_fn,
    ) -> list[int]:
        original_index = {int(v): i for i, v in enumerate(ids)}

        vectors: list[list[float]] = []
        ordered_ids: list[int] = []

        for item_id in ids:
            row = rows.get(int(item_id))
            if row is None:
                continue
            ordered_ids.append(int(item_id))
            vectors.append(vector_fn(row))

        model = self._load_model(objective, level)
        preds = model.predict_many(vectors)

        scored: list[tuple[float, int, int]] = []

        pred_by_id = {
            item_id: preds[i]
            for i, item_id in enumerate(ordered_ids)
            if i < len(preds)
        }

        for item_id in ids:
            item_id = int(item_id)
            row = rows.get(item_id)

            if row is None:
                priority = 0.0
            else:
                deterministic = float(score_fn(row))
                learned = float(pred_by_id.get(item_id, 0.5))
                priority = (deterministic * 0.75) + (learned * 0.25)

            scored.append((priority, original_index.get(item_id, 0), item_id))

        # LOW priority first, HIGH priority last because SessionService uses .pop()
        scored.sort(key=lambda x: (x[0], x[1]))
        return [item_id for _, _, item_id in scored]

    def _base_score(
        self,
        *,
        ease: float,
        reps: float,
        lapses: float,
        due_at: float,
        last_review_at: float | None,
        total_reviews: float,
        avg_rating: float,
        accuracy: float,
        tip_rate: float,
        helper_rate: float,
        skip_rate: float,
        response_ms: float,
        extra_penalty: float = 0.0,
    ) -> float:
        now = time.time()

        due_in_days = (due_at - now) / 86400.0
        overdue_days = max(0.0, -due_in_days)
        is_due = due_at <= now

        is_unseen = total_reviews <= 0 or reps <= 0
        low_rating_pressure = _clip((3.0 - avg_rating) / 3.0, 0.0, 1.0)
        weak_accuracy = _clip(1.0 - accuracy, 0.0, 1.0)
        slow_pressure = _clip(response_ms / 20000.0, 0.0, 1.0)

        score = 0.0

        score += weak_accuracy * 2.3
        score += low_rating_pressure * 1.4
        score += _clip(tip_rate, 0.0, 1.0) * 0.55
        score += _clip(helper_rate, 0.0, 1.0) * 0.45
        score += _clip(skip_rate, 0.0, 1.0) * 1.6
        score += _clip(lapses / 5.0, 0.0, 1.0) * 0.8
        score += _clip((2.5 - ease) / 1.2, 0.0, 1.0) * 0.6
        score += slow_pressure * 0.25
        score += _clip(overdue_days / 7.0, 0.0, 1.0) * 0.9
        score += 0.35 if is_due else 0.0
        score += 0.55 if is_unseen else 0.0
        score += extra_penalty

        if last_review_at:
            hours_since = (now - float(last_review_at)) / 3600.0
            if hours_since < 2.0:
                score -= 0.8

        return _clip(score / 6.0, 0.0, 1.0)

    def _score_vocab_row(self, row: Any) -> float:
        accuracies = [
            _row(row, "meaning_acc", None),
            _row(row, "gender_acc", None),
            _row(row, "plural_acc", None),
        ]
        valid = [_float(x, 0.0) for x in accuracies if x is not None]
        accuracy = sum(valid) / len(valid) if valid else 0.55

        return self._base_score(
            ease=_float(_row(row, "ease", 2.5), 2.5),
            reps=_float(_row(row, "reps", 0), 0.0),
            lapses=_float(_row(row, "lapses", 0), 0.0),
            due_at=_float(_row(row, "due_at", time.time()), time.time()),
            last_review_at=_row(row, "last_review_at", None),
            total_reviews=_float(_row(row, "total_reviews", 0), 0.0),
            avg_rating=_float(_row(row, "avg_rating", 2.0), 2.0),
            accuracy=accuracy,
            tip_rate=_float(_row(row, "tip_rate", 0.0), 0.0),
            helper_rate=_float(_row(row, "helper_rate", 0.0), 0.0),
            skip_rate=_float(_row(row, "skip_rate", 0.0), 0.0),
            response_ms=_float(_row(row, "avg_response_ms", 0.0), 0.0),
        )

    def _score_grammar_row(self, row: Any) -> float:
        return self._base_score(
            ease=_float(_row(row, "ease", 2.5), 2.5),
            reps=_float(_row(row, "reps", 0), 0.0),
            lapses=_float(_row(row, "lapses", 0), 0.0),
            due_at=_float(_row(row, "due_at", time.time()), time.time()),
            last_review_at=_row(row, "last_review_at", None),
            total_reviews=_float(_row(row, "total_reviews", 0), 0.0),
            avg_rating=_float(_row(row, "avg_rating", 2.0), 2.0),
            accuracy=_float(_row(row, "accuracy", 0.55), 0.55),
            tip_rate=_float(_row(row, "tip_rate", 0.0), 0.0),
            helper_rate=_float(_row(row, "helper_rate", 0.0), 0.0),
            skip_rate=_float(_row(row, "skip_rate", 0.0), 0.0),
            response_ms=_float(_row(row, "avg_response_ms", 0.0), 0.0),
        )

    def _score_sentence_row(self, row: Any) -> float:
        mismatch_penalty = _clip(_float(_row(row, "avg_mismatch_count", 0.0), 0.0) / 6.0, 0.0, 1.0) * 0.35

        return self._base_score(
            ease=_float(_row(row, "ease", 2.5), 2.5),
            reps=_float(_row(row, "reps", 0), 0.0),
            lapses=_float(_row(row, "lapses", 0), 0.0),
            due_at=_float(_row(row, "due_at", time.time()), time.time()),
            last_review_at=_row(row, "last_review_at", None),
            total_reviews=_float(_row(row, "total_reviews", 0), 0.0),
            avg_rating=_float(_row(row, "avg_rating", 2.0), 2.0),
            accuracy=_float(_row(row, "accuracy", 0.55), 0.55),
            tip_rate=_float(_row(row, "tip_rate", 0.0), 0.0),
            helper_rate=_float(_row(row, "helper_rate", 0.0), 0.0),
            skip_rate=_float(_row(row, "skip_rate", 0.0), 0.0),
            response_ms=_float(_row(row, "avg_response_ms", 0.0), 0.0),
            extra_penalty=mismatch_penalty,
        )

    # ------------------------------------------------------------------
    # Feature vectors
    # ------------------------------------------------------------------
    def _vector(
        self,
        *,
        ease: float,
        interval_days: float,
        reps: float,
        lapses: float,
        total_reviews: float,
        avg_rating: float,
        accuracy: float,
        tip_rate: float,
        helper_rate: float,
        skip_rate: float,
        response_ms: float,
        text_len: float,
        extra_len: float,
        is_unseen: float,
        overdue_days: float,
    ) -> list[float]:
        return [
            _clip(ease / 4.0, 0.0, 1.0),
            _clip(interval_days / 60.0, 0.0, 1.0),
            _clip(reps / 20.0, 0.0, 1.0),
            _clip(lapses / 10.0, 0.0, 1.0),
            _clip(total_reviews / 50.0, 0.0, 1.0),
            _clip(avg_rating / 3.0, 0.0, 1.0),
            _clip(accuracy, 0.0, 1.0),
            _clip(tip_rate, 0.0, 1.0),
            _clip(helper_rate, 0.0, 1.0),
            _clip(skip_rate, 0.0, 1.0),
            _clip(response_ms / 30000.0, 0.0, 1.0),
            _clip(text_len / 120.0, 0.0, 1.0),
            _clip(extra_len / 120.0, 0.0, 1.0),
            _clip(is_unseen, 0.0, 1.0),
            _clip(overdue_days / 30.0, 0.0, 1.0),
        ]

    def _vector_vocab_row(self, row: Any) -> list[float]:
        now = time.time()
        due_at = _float(_row(row, "due_at", now), now)
        overdue_days = max(0.0, (now - due_at) / 86400.0)

        accuracies = [
            _row(row, "meaning_acc", None),
            _row(row, "gender_acc", None),
            _row(row, "plural_acc", None),
        ]
        valid = [_float(x, 0.0) for x in accuracies if x is not None]
        accuracy = sum(valid) / len(valid) if valid else 0.55

        reps = _float(_row(row, "reps", 0), 0.0)
        total_reviews = _float(_row(row, "total_reviews", 0), 0.0)

        return self._vector(
            ease=_float(_row(row, "ease", 2.5), 2.5),
            interval_days=_float(_row(row, "interval_days", 0.0), 0.0),
            reps=reps,
            lapses=_float(_row(row, "lapses", 0.0), 0.0),
            total_reviews=total_reviews,
            avg_rating=_float(_row(row, "avg_rating", 2.0), 2.0),
            accuracy=accuracy,
            tip_rate=_float(_row(row, "tip_rate", 0.0), 0.0),
            helper_rate=_float(_row(row, "helper_rate", 0.0), 0.0),
            skip_rate=_float(_row(row, "skip_rate", 0.0), 0.0),
            response_ms=_float(_row(row, "avg_response_ms", 0.0), 0.0),
            text_len=float(len(str(_row(row, "word", "") or ""))),
            extra_len=float(len(str(_row(row, "meaning", "") or ""))),
            is_unseen=1.0 if reps <= 0 or total_reviews <= 0 else 0.0,
            overdue_days=overdue_days,
        )

    def _vector_grammar_row(self, row: Any) -> list[float]:
        now = time.time()
        due_at = _float(_row(row, "due_at", now), now)
        overdue_days = max(0.0, (now - due_at) / 86400.0)

        reps = _float(_row(row, "reps", 0), 0.0)
        total_reviews = _float(_row(row, "total_reviews", 0), 0.0)

        return self._vector(
            ease=_float(_row(row, "ease", 2.5), 2.5),
            interval_days=_float(_row(row, "interval_days", 0.0), 0.0),
            reps=reps,
            lapses=_float(_row(row, "lapses", 0.0), 0.0),
            total_reviews=total_reviews,
            avg_rating=_float(_row(row, "avg_rating", 2.0), 2.0),
            accuracy=_float(_row(row, "accuracy", 0.55), 0.55),
            tip_rate=_float(_row(row, "tip_rate", 0.0), 0.0),
            helper_rate=_float(_row(row, "helper_rate", 0.0), 0.0),
            skip_rate=_float(_row(row, "skip_rate", 0.0), 0.0),
            response_ms=_float(_row(row, "avg_response_ms", 0.0), 0.0),
            text_len=float(len(str(_row(row, "test_text", "") or ""))),
            extra_len=float(len(str(_row(row, "answer", "") or ""))),
            is_unseen=1.0 if reps <= 0 or total_reviews <= 0 else 0.0,
            overdue_days=overdue_days,
        )

    def _vector_sentence_row(self, row: Any) -> list[float]:
        now = time.time()
        due_at = _float(_row(row, "due_at", now), now)
        overdue_days = max(0.0, (now - due_at) / 86400.0)

        reps = _float(_row(row, "reps", 0), 0.0)
        total_reviews = _float(_row(row, "total_reviews", 0), 0.0)

        return self._vector(
            ease=_float(_row(row, "ease", 2.5), 2.5),
            interval_days=_float(_row(row, "interval_days", 0.0), 0.0),
            reps=reps,
            lapses=_float(_row(row, "lapses", 0.0), 0.0),
            total_reviews=total_reviews,
            avg_rating=_float(_row(row, "avg_rating", 2.0), 2.0),
            accuracy=_float(_row(row, "accuracy", 0.55), 0.55),
            tip_rate=_float(_row(row, "tip_rate", 0.0), 0.0),
            helper_rate=_float(_row(row, "helper_rate", 0.0), 0.0),
            skip_rate=_float(_row(row, "skip_rate", 0.0), 0.0),
            response_ms=_float(_row(row, "avg_response_ms", 0.0), 0.0),
            text_len=float(len(str(_row(row, "target_text", "") or ""))),
            extra_len=float(len(str(_row(row, "translation", "") or ""))),
            is_unseen=1.0 if reps <= 0 or total_reviews <= 0 else 0.0,
            overdue_days=overdue_days,
        )

    # ------------------------------------------------------------------
    # Model persistence
    # ------------------------------------------------------------------
    def _model_name(self, objective: str, level: str | None) -> str:
        return f"{_safe_key(objective)}__{_safe_key(level)}"

    def _model_path(self, objective: str, level: str | None) -> Path:
        return self.model_dir / f"{self._model_name(objective, level)}.joblib"

    def _load_model(self, objective: str, level: str | None) -> _OnlineDifficultyModel:
        key = self._model_name(objective, level)

        if key in self._models:
            return self._models[key]

        path = self._model_path(objective, level)

        if _SKLEARN_OK and joblib is not None and path.exists():
            try:
                model = joblib.load(path)
                self._models[key] = model
                return model
            except Exception:
                pass

        model = _OnlineDifficultyModel()
        self._models[key] = model
        return model

    def _save_model(self, objective: str, level: str | None, model: _OnlineDifficultyModel) -> None:
        if not _SKLEARN_OK or joblib is None:
            return

        try:
            joblib.dump(model, self._model_path(objective, level))
        except Exception:
            pass

    def _fit(
        self,
        objective: str,
        level: str | None,
        features: list[float],
        target: float,
    ) -> None:
        model = self._load_model(objective, level)
        model.partial_fit(features, target)
        self._save_model(objective, level, model)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _target_from_review(
        self,
        *,
        effective_rating: int,
        correct: bool,
        tip_used: bool,
        was_checked: bool,
        was_skipped: bool,
    ) -> float:
        if was_skipped or not was_checked:
            return 1.0

        rating_pressure = 1.0 - (_clip(float(effective_rating), 0.0, 3.0) / 3.0)

        if not correct:
            rating_pressure = max(rating_pressure, 0.9)

        if tip_used:
            rating_pressure = max(rating_pressure, 0.55)

        return _clip(rating_pressure, 0.0, 1.0)

    def _vocab_accuracy_from_result(self, result: dict[str, Any]) -> float:
        vals = [
            result.get("meaning_ok"),
            result.get("gender_ok"),
            result.get("plural_ok"),
        ]
        applicable = [v for v in vals if v is not None]

        if not applicable:
            return 0.5

        ok = sum(1 for v in applicable if bool(v))
        return ok / len(applicable)

    def _review_count(
        self,
        *,
        objective: str,
        level: str | None,
    ) -> int:
        objective = (objective or "vocab").strip().lower()

        deck_id = None
        if level and hasattr(self.repo, "get_deck_id"):
            try:
                deck_id = self.repo.get_deck_id(level, objective)
            except Exception:
                deck_id = None

        try:
            with self.repo._conn() as conn:
                if objective == "grammar":
                    if deck_id:
                        row = conn.execute(
                            """
                            SELECT COUNT(*) AS c
                            FROM grammar_reviews r
                            JOIN grammar g ON g.id = r.grammar_id
                            WHERE g.deck_id = ?
                            """,
                            (deck_id,),
                        ).fetchone()
                    else:
                        row = conn.execute("SELECT COUNT(*) AS c FROM grammar_reviews").fetchone()

                elif objective == "sentences":
                    if deck_id:
                        row = conn.execute(
                            """
                            SELECT COUNT(*) AS c
                            FROM sentence_reviews r
                            JOIN sentences s ON s.id = r.sentence_id
                            WHERE s.deck_id = ?
                            """,
                            (deck_id,),
                        ).fetchone()
                    else:
                        row = conn.execute("SELECT COUNT(*) AS c FROM sentence_reviews").fetchone()

                else:
                    if deck_id:
                        row = conn.execute(
                            """
                            SELECT COUNT(*) AS c
                            FROM reviews r
                            JOIN vocab v ON v.id = r.vocab_id
                            WHERE v.deck_id = ?
                            """,
                            (deck_id,),
                        ).fetchone()
                    else:
                        row = conn.execute("SELECT COUNT(*) AS c FROM reviews").fetchone()

            return int(row["c"] or 0) if row else 0

        except Exception:
            return 0