from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any

from core import fsrs, priority

joblib = None
np = None
SGDRegressor = None
StandardScaler = None
_SKLEARN_OK: bool | None = None


_SKLEARN_WARM_LOCK = threading.Lock()
_SKLEARN_WARM_THREAD: Any = None


def prewarm_sklearn_backend() -> None:
    """Import the learned-ranking stack on a background thread, once.

    scikit-learn, scipy and numpy together take about 1.1 s to import. That
    used to happen on the GUI thread the first time anything ranked - which is
    while the very first page paints - and again on the first rating click of a
    session. Warming it off-thread keeps both instant.
    """
    global _SKLEARN_WARM_THREAD
    if _SKLEARN_OK is not None:
        return
    with _SKLEARN_WARM_LOCK:
        existing = _SKLEARN_WARM_THREAD
        if existing is not None and existing.is_alive():
            return
        if _SKLEARN_OK is not None:
            return
        thread = threading.Thread(
            target=_ensure_sklearn_backend,
            name="mahira-sklearn-prewarm",
            daemon=True,
        )
        _SKLEARN_WARM_THREAD = thread
        thread.start()


def _sklearn_backend_ready() -> bool:
    """True only if the stack is already imported; never waits for it.

    Ranking uses this so a cold start never blocks on scikit-learn. An
    unavailable backend leaves the model unfitted, which drives the blend
    weight to zero and falls back to the deterministic recall priority - the
    documented "ML augments, never gates" behaviour.
    """
    if _SKLEARN_OK is None:
        prewarm_sklearn_backend()
        return False
    return _SKLEARN_OK


def _ensure_sklearn_backend() -> bool:
    """Load sklearn once, after the first learned-model operation."""

    global joblib, np, SGDRegressor, StandardScaler, _SKLEARN_OK
    if _SKLEARN_OK is not None:
        return _SKLEARN_OK
    try:
        import joblib as loaded_joblib
        import numpy as loaded_numpy
        from sklearn.linear_model import SGDRegressor as loaded_sgd
        from sklearn.preprocessing import StandardScaler as loaded_scaler
    except Exception:
        _SKLEARN_OK = False
        return False
    joblib, np = loaded_joblib, loaded_numpy
    SGDRegressor, StandardScaler = loaded_sgd, loaded_scaler
    _SKLEARN_OK = True
    return True


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


# StandardScaler needs a real spread before its output is meaningful. Fitting
# and transforming the same single sample gives a per-feature variance of ~0,
# so the scaled values explode and the very first SGD updates blow the weights
# past any recovery. Buffer this many samples, fit only the scaler on them,
# then replay them into the model in one go.
_SCALER_WARMUP_SAMPLES = 20

# A healthy prediction lives in [0, 1]. Anything far outside means the weights
# have diverged and the model is worthless.
_DIVERGENCE_LIMIT = 10.0


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
        self.scaler = None
        self.model = None
        self.is_fitted = False
        self.samples_seen = 0
        self._warmup: list[tuple[list[float], float]] = []

    def _initialize(self) -> bool:
        if self.scaler is not None and self.model is not None:
            return True
        if not _ensure_sklearn_backend():
            return False
        self.scaler = StandardScaler()
        self.model = SGDRegressor(
            loss="squared_error",
            penalty="l2",
            alpha=0.0001,
            # "optimal" derives its step size from a classification-loss
            # schedule and diverges badly here. A small constant step is stable
            # for this feature scale.
            learning_rate="constant",
            eta0=0.01,
            max_iter=1,
            tol=None,
            random_state=42,
        )
        return True

    def partial_fit(self, x: list[float], y: float) -> None:
        if not self._initialize():
            return

        X = np.asarray([x], dtype=float)
        target = float(_clip(y, 0.0, 1.0))

        self.scaler.partial_fit(X)
        self.samples_seen = int(getattr(self, "samples_seen", 0)) + 1

        warmup = getattr(self, "_warmup", None)
        if warmup is None:
            warmup = self._warmup = []

        if not self.is_fitted and self.samples_seen < _SCALER_WARMUP_SAMPLES:
            # Scaler only: the model must not see samples scaled against a
            # near-zero variance estimate.
            warmup.append((list(x), target))
            return

        if not self.is_fitted:
            warmup.append((list(x), target))
            buffered = np.asarray([row for row, _ in warmup], dtype=float)
            targets = np.asarray([t for _, t in warmup], dtype=float)
            self._warmup = []
            self.model.partial_fit(self.scaler.transform(buffered), targets)
            self.is_fitted = True
            return

        self.model.partial_fit(
            self.scaler.transform(X),
            np.asarray([target], dtype=float),
        )

    def predict_many(self, vectors: list[list[float]]) -> list[float]:
        if not vectors:
            return []

        if not self.is_fitted:
            return [0.5] * len(vectors)

        if self.scaler is None or self.model is None:
            return [0.5] * len(vectors)

        X = np.asarray(vectors, dtype=float)
        Xs = self.scaler.transform(X)
        preds = self.model.predict(Xs)

        # A diverged model clips to a sign bit and is worse than no model at
        # all. Stand down to the neutral score so the deterministic priority
        # carries the ranking on its own.
        if not np.all(np.isfinite(preds)) or np.abs(preds).max() > _DIVERGENCE_LIMIT:
            self.is_fitted = False
            return [0.5] * len(vectors)

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

        # Train on the SAME feature vector used at ranking time (built from the
        # post-review DB aggregates), so there is no train/serve skew.
        features = self._training_vector(
            item, objective="vocab", vector_fn=self._vector_vocab_row, fetch_fn=self._fetch_vocab_rows
        )
        if features is None:
            return

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

        features = self._training_vector(
            item, objective="grammar", vector_fn=self._vector_grammar_row, fetch_fn=self._fetch_grammar_rows
        )
        if features is None:
            return

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

        features = self._training_vector(
            item, objective="sentences", vector_fn=self._vector_sentence_row, fetch_fn=self._fetch_sentence_rows
        )
        if features is None:
            return

        self._fit("sentences", level, features, target)

    def update_listening(
        self,
        *,
        item: Any,
        state_before: Any,
        review_result: dict[str, Any],
        effective_rating: int,
        was_checked: bool,
        was_skipped: bool,
        response_ms: int | None,
        level: str | None = None,
    ) -> None:
        """Train the listening lane from a just-submitted review.

        session.submit_listening already calls this behind a hasattr guard; without
        the method, listening never contributed training data and the ranker for
        that lane stayed unfitted forever.
        """
        target = self._target_from_review(
            effective_rating=effective_rating,
            correct=bool(review_result.get("ok")),
            tip_used=False,
            was_checked=was_checked,
            was_skipped=was_skipped,
        )

        features = self._training_vector(
            item,
            objective="listening",
            vector_fn=self._vector_listening_row,
            fetch_fn=self._fetch_listening_rows,
        )
        if features is None:
            return

        self._fit("listening", level, features, target)

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

    def rank_listening_ids(
        self,
        ids: list[int],
        *,
        level: str | None = None,
        **_: Any,
    ) -> list[int]:
        if not ids:
            return []

        try:
            rows = self._fetch_listening_rows(ids)
            return self._rank_rows(
                ids=ids,
                rows=rows,
                objective="listening",
                level=level,
                score_fn=self._score_listening_row,
                vector_fn=self._vector_listening_row,
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
                s.stability,
                s.difficulty,
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
            LEFT JOIN reviews r
              ON r.vocab_id = v.id
             AND r.practice_mode = 'recognition'
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
                s.stability,
                s.difficulty,
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
                st.stability,
                st.difficulty,
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

    def _fetch_listening_rows(self, ids: list[int]) -> dict[int, Any]:
        placeholders = ",".join("?" for _ in ids)
        # listening_reviews has no tip_used/translation_used columns; replay
        # count is this lane's struggle signal instead.
        q = f"""
            SELECT
                li.id,
                li.question,
                li.text,
                li.translation,
                li.tip,
                st.ease,
                st.interval_days,
                st.reps,
                st.lapses,
                st.due_at,
                st.last_review_at,
                st.stability,
                st.difficulty,
                COUNT(r.id) AS total_reviews,
                AVG(r.rating) AS avg_rating,
                AVG(r.correct) AS accuracy,
                AVG(r.was_skipped) AS skip_rate,
                AVG(r.response_ms) AS avg_response_ms,
                AVG(r.replay_count) AS avg_replay_count
            FROM listening li
            LEFT JOIN listening_states st ON st.listening_id = li.id
            LEFT JOIN listening_reviews r ON r.listening_id = li.id
            WHERE li.id IN ({placeholders})
            GROUP BY li.id
        """
        with self.repo._conn() as conn:
            rows = conn.execute(q, tuple(ids)).fetchall()
        return {int(r["id"]): r for r in rows}

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def _training_vector(self, item: Any, *, objective: str, vector_fn, fetch_fn):
        """Build the feature vector for online training from the item's current
        DB aggregates -- identical to the vector used when ranking, so the model
        never suffers train/serve skew."""
        try:
            item_id = int(item.id)
        except Exception:
            return None
        try:
            rows = fetch_fn([item_id])
            row = rows.get(item_id)
        except Exception:
            row = None
        if row is None:
            return None
        try:
            return vector_fn(row)
        except Exception:
            return None

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

        # The deterministic recall-priority is ALWAYS applied. The learned model
        # only augments the ordering once it has actually been trained -- it is
        # never a gate, so weak/forgotten items are targeted from review #1.
        w_learned = 0.25 if getattr(model, "is_fitted", False) else 0.0
        w_det = 1.0 - w_learned

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
                priority = (deterministic * w_det) + (learned * w_learned)

            scored.append((priority, original_index.get(item_id, 0), item_id))

        # LOW priority first, HIGH priority last because SessionService uses
        # .pop(). Tie-break: equal-priority items (e.g. a fresh, all-unseen
        # deck) are ordered so the EARLIEST item pops first -> new material is
        # introduced in natural deck/Lektion order.
        scored.sort(key=lambda x: (x[0], -x[1]))
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
        stability: float | None = None,
        difficulty: float | None = None,
        interval_days: float = 0.0,
    ) -> float:
        # Single source of truth: the always-on recall priority (FSRS
        # retrievability + weakness signals + coverage).
        return priority.compute_priority(
            now=time.time(),
            due_at=due_at,
            last_review_at=last_review_at,
            stability=stability,
            difficulty=difficulty if difficulty is not None else fsrs.difficulty_from_ease(ease),
            interval_days=interval_days,
            reps=reps,
            lapses=lapses,
            total_reviews=total_reviews,
            avg_rating=avg_rating,
            accuracy=accuracy,
            tip_rate=tip_rate,
            helper_rate=helper_rate,
            skip_rate=skip_rate,
            response_ms=response_ms,
            extra_penalty=extra_penalty,
        )

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
            stability=_row(row, "stability", None),
            difficulty=_row(row, "difficulty", None),
            interval_days=_float(_row(row, "interval_days", 0.0), 0.0),
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
            stability=_row(row, "stability", None),
            difficulty=_row(row, "difficulty", None),
            interval_days=_float(_row(row, "interval_days", 0.0), 0.0),
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
            stability=_row(row, "stability", None),
            difficulty=_row(row, "difficulty", None),
            interval_days=_float(_row(row, "interval_days", 0.0), 0.0),
        )

    def _score_listening_row(self, row: Any) -> float:
        # Replaying the audio repeatedly is the listening equivalent of a
        # near-miss: the learner could not parse it at speed.
        replay_penalty = _clip(
            _float(_row(row, "avg_replay_count", 0.0), 0.0) / 4.0, 0.0, 1.0
        ) * 0.35

        return self._base_score(
            ease=_float(_row(row, "ease", 2.5), 2.5),
            reps=_float(_row(row, "reps", 0), 0.0),
            lapses=_float(_row(row, "lapses", 0), 0.0),
            due_at=_float(_row(row, "due_at", time.time()), time.time()),
            last_review_at=_row(row, "last_review_at", None),
            total_reviews=_float(_row(row, "total_reviews", 0), 0.0),
            avg_rating=_float(_row(row, "avg_rating", 2.0), 2.0),
            accuracy=_float(_row(row, "accuracy", 0.55), 0.55),
            tip_rate=0.0,
            helper_rate=0.0,
            skip_rate=_float(_row(row, "skip_rate", 0.0), 0.0),
            response_ms=_float(_row(row, "avg_response_ms", 0.0), 0.0),
            extra_penalty=replay_penalty,
            stability=_row(row, "stability", None),
            difficulty=_row(row, "difficulty", None),
            interval_days=_float(_row(row, "interval_days", 0.0), 0.0),
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
        stability: float = 0.0,
        difficulty: float = 5.0,
        recall: float = 0.5,
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
            _clip(stability / 365.0, 0.0, 1.0),
            _clip((difficulty - 1.0) / 9.0, 0.0, 1.0),
            _clip(recall, 0.0, 1.0),
        ]

    def _fsrs_features(self, row: Any, now: float) -> tuple[float, float, float]:
        """Return (stability_days, difficulty, recall_prob) for an item row,
        deriving values for legacy items that predate the FSRS columns."""
        reps = _int(_row(row, "reps", 0), 0)
        interval_days = _float(_row(row, "interval_days", 0.0), 0.0)
        ease = _float(_row(row, "ease", 2.5), 2.5)
        stability_raw = _row(row, "stability", None)
        difficulty_raw = _row(row, "difficulty", None)
        last_review_at = _row(row, "last_review_at", None)

        if stability_raw is not None:
            stability = _float(stability_raw, 0.0)
        else:
            stability = (interval_days if interval_days > 0 else 1.0) if reps > 0 else 0.0

        if difficulty_raw is not None:
            difficulty = _float(difficulty_raw, 5.0)
        else:
            difficulty = fsrs.difficulty_from_ease(ease)

        r = priority.recall_probability(
            now=now,
            last_review_at=last_review_at,
            stability=stability_raw,
            interval_days=interval_days,
            reps=reps,
        )
        return stability, difficulty, (0.5 if r is None else r)

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
        stability, difficulty, recall = self._fsrs_features(row, now)

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
            stability=stability,
            difficulty=difficulty,
            recall=recall,
        )

    def _vector_grammar_row(self, row: Any) -> list[float]:
        now = time.time()
        due_at = _float(_row(row, "due_at", now), now)
        overdue_days = max(0.0, (now - due_at) / 86400.0)

        reps = _float(_row(row, "reps", 0), 0.0)
        total_reviews = _float(_row(row, "total_reviews", 0), 0.0)
        stability, difficulty, recall = self._fsrs_features(row, now)

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
            stability=stability,
            difficulty=difficulty,
            recall=recall,
        )

    def _vector_sentence_row(self, row: Any) -> list[float]:
        now = time.time()
        due_at = _float(_row(row, "due_at", now), now)
        overdue_days = max(0.0, (now - due_at) / 86400.0)

        reps = _float(_row(row, "reps", 0), 0.0)
        total_reviews = _float(_row(row, "total_reviews", 0), 0.0)
        stability, difficulty, recall = self._fsrs_features(row, now)

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
            stability=stability,
            difficulty=difficulty,
            recall=recall,
        )

    def _vector_listening_row(self, row: Any) -> list[float]:
        now = time.time()
        due_at = _float(_row(row, "due_at", now), now)
        overdue_days = max(0.0, (now - due_at) / 86400.0)

        reps = _float(_row(row, "reps", 0), 0.0)
        total_reviews = _float(_row(row, "total_reviews", 0), 0.0)
        stability, difficulty, recall = self._fsrs_features(row, now)

        return self._vector(
            ease=_float(_row(row, "ease", 2.5), 2.5),
            interval_days=_float(_row(row, "interval_days", 0.0), 0.0),
            reps=reps,
            lapses=_float(_row(row, "lapses", 0.0), 0.0),
            total_reviews=total_reviews,
            avg_rating=_float(_row(row, "avg_rating", 2.0), 2.0),
            accuracy=_float(_row(row, "accuracy", 0.55), 0.55),
            tip_rate=0.0,
            helper_rate=0.0,
            skip_rate=_float(_row(row, "skip_rate", 0.0), 0.0),
            response_ms=_float(_row(row, "avg_response_ms", 0.0), 0.0),
            text_len=float(len(str(_row(row, "question", "") or ""))),
            extra_len=float(len(str(_row(row, "text", "") or ""))),
            is_unseen=1.0 if reps <= 0 or total_reviews <= 0 else 0.0,
            overdue_days=overdue_days,
            stability=stability,
            difficulty=difficulty,
            recall=recall,
        )

    # ------------------------------------------------------------------
    # Model persistence
    # ------------------------------------------------------------------
    # Bump when a feature vector's layout or meaning changes so stale joblib
    # models are never applied to incompatible inputs. Vocabulary moved to v3
    # when its aggregates became recognition-only; the other objectives keep
    # their compatible v2 models.
    # v3/v4 retire every model trained by the diverging "optimal" schedule.
    _MODEL_VERSION = "v3"
    _MODEL_VERSION_BY_OBJECTIVE = {"vocab": "v4"}

    def _model_name(self, objective: str, level: str | None) -> str:
        objective_key = _safe_key(objective)
        version = self._MODEL_VERSION_BY_OBJECTIVE.get(
            objective_key,
            self._MODEL_VERSION,
        )
        return f"{objective_key}__{_safe_key(level)}__{version}"

    def _model_path(self, objective: str, level: str | None) -> Path:
        return self.model_dir / f"{self._model_name(objective, level)}.joblib"

    def _load_model(self, objective: str, level: str | None) -> _OnlineDifficultyModel:
        key = self._model_name(objective, level)

        if key in self._models:
            return self._models[key]

        path = self._model_path(objective, level)

        # Ranking must never wait for the import: a cold Today render would
        # freeze for ~1.1 s. Not ready yet simply means deterministic priority.
        if path.exists() and _sklearn_backend_ready() and joblib is not None:
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
        # Also persist a model still in scaler warm-up, otherwise the buffer is
        # discarded between sessions and training never starts.
        if not getattr(model, "is_fitted", False) and not int(
            getattr(model, "samples_seen", 0)
        ):
            return
        if not _ensure_sklearn_backend() or joblib is None:
            return

        path = self._model_path(objective, level)
        try:
            joblib.dump(model, path)
        except Exception:
            return
        self._prune_superseded_models(objective, level, keep=path)

    def _prune_superseded_models(
        self,
        objective: str,
        level: str | None,
        *,
        keep: Path,
    ) -> None:
        """Delete models this objective/level left behind at older versions.

        The model filename carries a version that is bumped whenever a training
        change invalidates existing models. Nothing ever removed the old file,
        so each bump stranded a few hundred KB inside the learner's portable
        data directory permanently. Models are a rebuildable cache, so the
        superseded ones are safe to drop.
        """
        prefix = f"{_safe_key(objective)}__{_safe_key(level)}__"
        try:
            stale = [
                candidate
                for candidate in self.model_dir.glob(f"{prefix}*.joblib")
                if candidate != keep
            ]
        except OSError:
            return
        for candidate in stale:
            try:
                candidate.unlink()
            except OSError:
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
                              AND r.practice_mode = 'recognition'
                            """,
                            (deck_id,),
                        ).fetchone()
                    else:
                        row = conn.execute(
                            "SELECT COUNT(*) AS c FROM reviews "
                            "WHERE practice_mode = 'recognition'"
                        ).fetchone()

            return int(row["c"] or 0) if row else 0

        except Exception:
            return 0
