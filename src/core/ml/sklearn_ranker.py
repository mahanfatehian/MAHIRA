# src/core/ml/sklearn_ranker.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import math
import re
import time

try:
    import numpy as _np
    from sklearn.linear_model import SGDRegressor
    from sklearn.preprocessing import StandardScaler
    import joblib

    _SKLEARN_OK = True
except Exception:
    _SKLEARN_OK = False


_POS_BUCKETS = [
    "noun", "verb", "adj", "adjective", "adv", "adverb",
    "prep", "preposition", "conj", "conjunction",
    "pron", "pronoun", "phrase", "other",
]


def _safe_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "_", s)
    return s.strip("_") or "default"


def _clip01(x: float) -> float:
    if x != x:
        return 0.5
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


@dataclass
class _OnlineRegressor:
    scaler: Any
    reg: Any
    is_fitted: bool = False

    @classmethod
    def fresh(cls) -> "_OnlineRegressor":
        scaler = StandardScaler(with_mean=True, with_std=True)
        reg = SGDRegressor(
            loss="squared_error",
            penalty="l2",
            alpha=1e-4,
            learning_rate="optimal",
            max_iter=1,
            tol=None,
            random_state=42,
        )
        return cls(scaler=scaler, reg=reg, is_fitted=False)

    def partial_fit(self, X: list[list[float]], y: list[float]) -> None:
        if not X:
            return
        Xn = _np.asarray(X, dtype=float)
        yn = _np.asarray(y, dtype=float)
        self.scaler.partial_fit(Xn)
        Xs = self.scaler.transform(Xn)
        self.reg.partial_fit(Xs, yn)
        self.is_fitted = True

    def predict(self, X: list[list[float]]) -> list[float]:
        if not X:
            return []
        if not self.is_fitted:
            return [0.5] * len(X)
        Xn = _np.asarray(X, dtype=float)
        Xs = self.scaler.transform(Xn)
        pred = self.reg.predict(Xs)
        return [_clip01(float(v)) for v in pred]


class SklearnRanker:
    """
    Online ranking with warmup tracking.

    - update_* increments ctx 'seen' count (persisted).
    - is_ready(...) lets SessionService delay ranking until enough samples exist.
    """

    def __init__(self, repo, model_dir: str | Path):
        self.repo = repo
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self.enabled = _SKLEARN_OK

        # ctx -> {"models": {target: _OnlineRegressor}, "seen": int}
        self._packs: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _kw(kwargs: dict[str, Any], *names: str, default=None):
        for n in names:
            if n in kwargs and kwargs[n] is not None:
                return kwargs[n]
        return default

    # -----------------------
    # Warmup / readiness
    # -----------------------
    def is_ready(self, *, lang: str, level: str, objective: str, direction: str, min_seen: int = 80) -> bool:
        if not self.enabled:
            return False
        ctx = self._ctx(lang, level, objective, direction)
        pack = self._load_pack_if_exists(ctx)
        if not pack:
            return False
        seen = int(pack.get("seen", 0) or 0)
        models = pack.get("models") or {}
        if objective == "grammar":
            m = models.get("ok")
            return bool(seen >= int(min_seen) and m is not None and getattr(m, "is_fitted", False))
        # vocab
        m = models.get("meaning")
        return bool(seen >= int(min_seen) and m is not None and getattr(m, "is_fitted", False))

    # -------- updates --------

    def update_vocab(self, *args, **kwargs) -> None:
        if not self.enabled:
            return

        lang = str(self._kw(kwargs, "language_code", "lang", default=""))
        level = str(self._kw(kwargs, "level", default=""))
        direction = str(self._kw(kwargs, "direction", default=""))

        y_meaning = kwargs.get("y_meaning")
        y_gender = kwargs.get("y_gender")
        y_plural = kwargs.get("y_plural")

        if y_meaning is None and "y" in kwargs:
            y_meaning = kwargs.get("y")

        if y_meaning is None and y_gender is None and y_plural is None:
            return

        features = self._vocab_training_features_from_kwargs(kwargs)
        ctx = self._ctx(lang, level, "vocab", direction)
        pack = self._ensure_pack(ctx, targets=("meaning", "gender", "plural"))

        X = [self._vectorize_vocab_training(features)]
        updated = 0

        if y_meaning is not None:
            pack["models"]["meaning"].partial_fit(X, [float(y_meaning)])
            updated += 1
        if y_gender is not None:
            pack["models"]["gender"].partial_fit(X, [float(y_gender)])
            updated += 1
        if y_plural is not None:
            pack["models"]["plural"].partial_fit(X, [float(y_plural)])
            updated += 1

        pack["seen"] = int(pack.get("seen", 0) or 0) + int(updated)
        self._save_ctx(ctx)

    def update_grammar(self, *args, **kwargs) -> None:
        if not self.enabled:
            return

        lang = str(self._kw(kwargs, "language_code", "lang", default=""))
        level = str(self._kw(kwargs, "level", default=""))

        y = kwargs.get("y")
        if y is None:
            return

        features = self._grammar_training_features_from_kwargs(kwargs)
        ctx = self._ctx(lang, level, "grammar", "")
        pack = self._ensure_pack(ctx, targets=("ok",))

        X = [self._vectorize_grammar_training(features)]
        pack["models"]["ok"].partial_fit(X, [float(y)])

        pack["seen"] = int(pack.get("seen", 0) or 0) + 1
        self._save_ctx(ctx)

    # -------- ranking --------

    def rank_vocab_ids(self, ids: list[int], *args, **kwargs) -> list[int]:
        if not self.enabled or not ids:
            return ids

        lang = str(self._kw(kwargs, "language_code", "lang", default=""))
        level = str(self._kw(kwargs, "level", default=""))
        direction = str(self._kw(kwargs, "direction", default=""))

        ctx = self._ctx(lang, level, "vocab", direction)
        pack = self._load_pack_if_exists(ctx)
        if not pack:
            return ids
        models = pack.get("models") or {}
        m = models.get("meaning")
        if not m or not m.is_fitted:
            return ids

        rows = self._fetch_vocab_rows(ids)
        X = [self._vectorize_vocab_rank(r) for r in rows]
        p = m.predict(X)

        scored: list[tuple[float, int]] = []
        for prob_easy, r in zip(p, rows):
            urgency = float(r.get("overdue_days", 0.0)) + (0.35 if r.get("is_unseen") else 0.0)
            difficulty = 1.0 - float(prob_easy)
            score = (0.7 * difficulty) + (0.3 * min(2.0, urgency))
            scored.append((score, int(r["id"])))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [i for _, i in scored]

    def rank_grammar_ids(self, ids: list[int], *args, **kwargs) -> list[int]:
        if not self.enabled or not ids:
            return ids

        lang = str(self._kw(kwargs, "language_code", "lang", default=""))
        level = str(self._kw(kwargs, "level", default=""))

        ctx = self._ctx(lang, level, "grammar", "")
        pack = self._load_pack_if_exists(ctx)
        if not pack:
            return ids
        models = pack.get("models") or {}
        m = models.get("ok")
        if not m or not m.is_fitted:
            return ids

        rows = self._fetch_grammar_rows(ids)
        X = [self._vectorize_grammar_rank(r) for r in rows]
        p = m.predict(X)

        scored: list[tuple[float, int]] = []
        for prob_easy, r in zip(p, rows):
            urgency = float(r.get("overdue_days", 0.0)) + (0.35 if r.get("is_unseen") else 0.0)
            difficulty = 1.0 - float(prob_easy)
            score = (0.7 * difficulty) + (0.3 * min(2.0, urgency))
            scored.append((score, int(r["id"])))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [i for _, i in scored]

    # -------- persistence --------

    def _ctx(self, language_code: str, level: str, objective: str, direction: str) -> str:
        return "__".join([_safe_key(language_code), _safe_key(level), _safe_key(objective), _safe_key(direction)])

    def _ctx_path(self, ctx: str) -> Path:
        return self.model_dir / f"{ctx}.joblib"

    def _ensure_pack(self, ctx: str, targets: tuple[str, ...]) -> dict[str, Any]:
        pack = self._load_pack_if_exists(ctx) or {"models": {}, "seen": 0}
        models = pack["models"]

        for t in targets:
            if t not in models:
                models[t] = _OnlineRegressor.fresh()

        self._packs[ctx] = pack
        return pack

    def _save_ctx(self, ctx: str) -> None:
        if ctx not in self._packs:
            return
        try:
            joblib.dump(self._packs[ctx], self._ctx_path(ctx))
        except Exception:
            pass

    def _load_pack_if_exists(self, ctx: str) -> dict[str, Any] | None:
        if ctx in self._packs:
            return self._packs[ctx]

        p = self._ctx_path(ctx)
        if not p.exists():
            return None

        try:
            obj = joblib.load(p)

            # NEW format: {"models": {...}, "seen": int}
            if isinstance(obj, dict) and "models" in obj:
                pack = {"models": obj.get("models") or {}, "seen": int(obj.get("seen", 0) or 0)}
                self._packs[ctx] = pack
                return pack

            # OLD format: dict[target -> regressor]
            if isinstance(obj, dict):
                pack = {"models": obj, "seen": 0}
                self._packs[ctx] = pack
                return pack

        except Exception:
            return None

        return None

    # -------- feature utils --------

    @staticmethod
    def _bool(x: Any) -> float:
        return 1.0 if bool(x) else 0.0

    @staticmethod
    def _safe_float(x: Any, default: float = 0.0) -> float:
        try:
            if x is None:
                return float(default)
            v = float(x)
            if math.isfinite(v):
                return v
        except Exception:
            pass
        return float(default)

    @staticmethod
    def _one_hot_pos(pos: str) -> list[float]:
        pos_n = (pos or "other").strip().lower()
        return [1.0 if pos_n == p else 0.0 for p in _POS_BUCKETS]

    def _vocab_training_features_from_kwargs(self, kw: dict[str, Any]) -> dict[str, Any]:
        now = int(time.time())
        due_at = self._safe_float(kw.get("state_due_at"), now)
        last = kw.get("state_last_review_at")
        due_in_days = (due_at - now) / 86400.0
        time_since_last = ((now - int(last)) / 3600.0) if last is not None else 0.0
        is_unseen = (self._safe_float(kw.get("state_reps"), 0.0) <= 0.0) and (last is None)

        word = str(kw.get("word") or "")
        meaning = str(kw.get("meaning") or "")

        return {
            "state_ease": self._safe_float(kw.get("state_ease"), 2.5),
            "state_reps": self._safe_float(kw.get("state_reps"), 0.0),
            "state_lapses": self._safe_float(kw.get("state_lapses"), 0.0),
            "state_interval_days": self._safe_float(kw.get("state_interval"), 0.0),
            "due_in_days": float(due_in_days),
            "time_since_last_hours": float(time_since_last),
            "is_unseen": bool(is_unseen),
            "tip_used": bool(int(kw.get("tip_used") or 0)),
            "gender_tip_used": bool(int(kw.get("gender_tip_used") or 0)),
            "was_skipped": bool(int(kw.get("was_skipped") or 0)),
            "rating": self._safe_float(kw.get("rating"), 0.0),
            "response_ms": self._safe_float(kw.get("response_ms"), 0.0),
            "word_len": float(len(word)),
            "meaning_len": float(len(meaning)),
        }

    def _grammar_training_features_from_kwargs(self, kw: dict[str, Any]) -> dict[str, Any]:
        now = int(time.time())
        due_at = self._safe_float(kw.get("state_due_at"), now)
        last = kw.get("state_last_review_at")
        due_in_days = (due_at - now) / 86400.0
        time_since_last = ((now - int(last)) / 3600.0) if last is not None else 0.0
        is_unseen = (self._safe_float(kw.get("state_reps"), 0.0) <= 0.0) and (last is None)

        test_text = str(kw.get("test_text") or "")

        return {
            "state_ease": self._safe_float(kw.get("state_ease"), 2.5),
            "state_reps": self._safe_float(kw.get("state_reps"), 0.0),
            "state_lapses": self._safe_float(kw.get("state_lapses"), 0.0),
            "state_interval_days": self._safe_float(kw.get("state_interval"), 0.0),
            "due_in_days": float(due_in_days),
            "time_since_last_hours": float(time_since_last),
            "is_unseen": bool(is_unseen),
            "meaning_tip_used": bool(int(kw.get("meaning_tip_used") or 0)),
            "hint_used": bool(int(kw.get("hint_used") or 0)),
            "grammar_tip_used": bool(int(kw.get("grammar_tip_used") or 0)),
            "was_skipped": bool(int(kw.get("was_skipped") or 0)),
            "rating": self._safe_float(kw.get("rating"), 0.0),
            "response_ms": self._safe_float(kw.get("response_ms"), 0.0),
            "test_text_len": float(len(test_text)),
        }

    def _vectorize_vocab_training(self, f: dict[str, Any]) -> list[float]:
        return [
            self._safe_float(f.get("state_ease"), 2.5),
            self._safe_float(f.get("state_reps"), 0.0),
            self._safe_float(f.get("state_lapses"), 0.0),
            self._safe_float(f.get("state_interval_days"), 0.0),
            self._safe_float(f.get("due_in_days"), 0.0),
            self._safe_float(f.get("time_since_last_hours"), 0.0),
            self._bool(f.get("is_unseen")),
            self._bool(f.get("tip_used")),
            self._bool(f.get("gender_tip_used")),
            self._bool(f.get("was_skipped")),
            self._safe_float(f.get("rating"), 0.0),
            self._safe_float(f.get("response_ms"), 0.0) / 1000.0,
            self._safe_float(f.get("word_len"), 0.0),
            self._safe_float(f.get("meaning_len"), 0.0),
        ]

    def _vectorize_vocab_rank(self, r: dict[str, Any]) -> list[float]:
        base = [
            self._safe_float(r.get("ease"), 2.5),
            self._safe_float(r.get("reps"), 0.0),
            self._safe_float(r.get("lapses"), 0.0),
            self._safe_float(r.get("interval_days"), 0.0),
            self._safe_float(r.get("due_in_days"), 0.0),
            self._safe_float(r.get("time_since_last_hours"), 0.0),
            self._bool(r.get("is_unseen")),
            0.0, 0.0, 0.0,
            0.0, 0.0,
            self._safe_float(r.get("word_len"), 0.0),
            self._safe_float(r.get("meaning_len"), 0.0),
        ]
        base.extend(self._one_hot_pos(r.get("pos", "other")))
        base.append(self._bool(r.get("has_gender")))
        base.append(self._bool(r.get("has_plural")))
        return base

    def _vectorize_grammar_training(self, f: dict[str, Any]) -> list[float]:
        return [
            self._safe_float(f.get("state_ease"), 2.5),
            self._safe_float(f.get("state_reps"), 0.0),
            self._safe_float(f.get("state_lapses"), 0.0),
            self._safe_float(f.get("state_interval_days"), 0.0),
            self._safe_float(f.get("due_in_days"), 0.0),
            self._safe_float(f.get("time_since_last_hours"), 0.0),
            self._bool(f.get("is_unseen")),
            self._bool(f.get("meaning_tip_used")),
            self._bool(f.get("hint_used")),
            self._bool(f.get("grammar_tip_used")),
            self._bool(f.get("was_skipped")),
            self._safe_float(f.get("rating"), 0.0),
            self._safe_float(f.get("response_ms"), 0.0) / 1000.0,
            self._safe_float(f.get("test_text_len"), 0.0),
        ]

    def _vectorize_grammar_rank(self, r: dict[str, Any]) -> list[float]:
        base = [
            self._safe_float(r.get("ease"), 2.5),
            self._safe_float(r.get("reps"), 0.0),
            self._safe_float(r.get("lapses"), 0.0),
            self._safe_float(r.get("interval_days"), 0.0),
            self._safe_float(r.get("due_in_days"), 0.0),
            self._safe_float(r.get("time_since_last_hours"), 0.0),
            self._bool(r.get("is_unseen")),
            0.0, 0.0, 0.0,
            0.0, 0.0,
            self._safe_float(r.get("test_text_len"), 0.0),
        ]
        base.append(self._bool(r.get("has_hint")))
        base.append(self._bool(r.get("has_meaning")))
        base.append(self._bool(r.get("has_grammar_tip")))
        return base

    # -------- DB fetch (rank-time only) --------

    def _fetch_vocab_rows(self, ids: list[int]) -> list[dict[str, Any]]:
        now = int(time.time())
        placeholders = ",".join(["?"] * len(ids))
        q = f"""
        SELECT v.id, v.pos, v.word, v.meaning, v.gender, v.plural,
               s.ease, s.interval_days, s.reps, s.lapses, s.due_at, s.last_review_at
          FROM vocab v
          LEFT JOIN vocab_states s ON s.vocab_id = v.id
         WHERE v.id IN ({placeholders})
        """
        with self.repo._conn() as conn:
            rows = conn.execute(q, tuple(ids)).fetchall()

        by_id = {int(r["id"]): r for r in rows}
        out: list[dict[str, Any]] = []
        for vid in ids:
            r = by_id.get(int(vid))
            if not r:
                continue

            due_at = int(r["due_at"]) if r["due_at"] is not None else now
            last = r["last_review_at"]

            due_in_days = (due_at - now) / 86400.0
            overdue_days = max(0.0, -due_in_days)
            time_since_last = ((now - int(last)) / 3600.0) if last is not None else 0.0
            is_unseen = (r["ease"] is None)

            out.append(
                {
                    "id": int(vid),
                    "pos": str(r["pos"] or "other"),
                    "word_len": float(len(str(r["word"] or ""))),
                    "meaning_len": float(len(str(r["meaning"] or ""))),
                    "has_gender": bool(r["gender"]),
                    "has_plural": bool(r["plural"]),
                    "ease": float(r["ease"]) if r["ease"] is not None else 2.5,
                    "interval_days": float(r["interval_days"]) if r["interval_days"] is not None else 0.0,
                    "reps": int(r["reps"]) if r["reps"] is not None else 0,
                    "lapses": int(r["lapses"]) if r["lapses"] is not None else 0,
                    "due_in_days": float(due_in_days),
                    "overdue_days": float(overdue_days),
                    "time_since_last_hours": float(time_since_last),
                    "is_unseen": bool(is_unseen),
                }
            )

        return out

    def _fetch_grammar_rows(self, ids: list[int]) -> list[dict[str, Any]]:
        now = int(time.time())
        placeholders = ",".join(["?"] * len(ids))
        q = f"""
        SELECT g.id, g.test_text, g.test_verb, g.tip, g.meaning, g.grammar_tip,
               s.ease, s.interval_days, s.reps, s.lapses, s.due_at, s.last_review_at
          FROM grammar g
          LEFT JOIN grammar_states s ON s.grammar_id = g.id
         WHERE g.id IN ({placeholders})
        """
        with self.repo._conn() as conn:
            rows = conn.execute(q, tuple(ids)).fetchall()

        by_id = {int(r["id"]): r for r in rows}
        out: list[dict[str, Any]] = []
        for gid in ids:
            r = by_id.get(int(gid))
            if not r:
                continue

            due_at = int(r["due_at"]) if r["due_at"] is not None else now
            last = r["last_review_at"]

            due_in_days = (due_at - now) / 86400.0
            overdue_days = max(0.0, -due_in_days)
            time_since_last = ((now - int(last)) / 3600.0) if last is not None else 0.0
            is_unseen = (r["ease"] is None)

            out.append(
                {
                    "id": int(gid),
                    "test_text_len": float(len(str(r["test_text"] or ""))),
                    "has_hint": bool(r["test_verb"] or r["tip"]),
                    "has_meaning": bool(r["meaning"]),
                    "has_grammar_tip": bool(r["grammar_tip"]),
                    "ease": float(r["ease"]) if r["ease"] is not None else 2.5,
                    "interval_days": float(r["interval_days"]) if r["interval_days"] is not None else 0.0,
                    "reps": int(r["reps"]) if r["reps"] is not None else 0,
                    "lapses": int(r["lapses"]) if r["lapses"] is not None else 0,
                    "due_in_days": float(due_in_days),
                    "overdue_days": float(overdue_days),
                    "time_since_last_hours": float(time_since_last),
                    "is_unseen": bool(is_unseen),
                }
            )

        return out


if not _SKLEARN_OK:
    class SklearnRanker:  # no-op fallback
        def __init__(self, repo, model_dir: str | Path):
            self.repo = repo
            self.model_dir = Path(model_dir)
            self.enabled = False

        def is_ready(self, **kwargs) -> bool: return False
        def update_vocab(self, *args, **kwargs): ...
        def update_grammar(self, *args, **kwargs): ...
        def rank_vocab_ids(self, ids: list[int], *args, **kwargs) -> list[int]: return ids
        def rank_grammar_ids(self, ids: list[int], *args, **kwargs) -> list[int]: return ids
