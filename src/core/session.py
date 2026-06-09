from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from db.repo import Repo, VocabItem, GrammarItem, SentenceItem
from core.srs import schedule_next
from core.ml.sklearn_ranker import SklearnRanker


# ---------------------------------------------------------------------
# Shared normalizers
# ---------------------------------------------------------------------
def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\säöüß-]", "", s)
    s = " ".join(s.split())
    return s


def _split_answers(ans: str) -> list[str]:
    return [_norm(x) for x in (ans or "").split(";") if x.strip()]


def _norm_gender(s: str) -> str:
    s = _norm(s)

    if s == "der":
        return "m"
    if s == "die":
        return "f"
    if s == "das":
        return "n"
    if s in ("m", "f", "n"):
        return s

    return s


def _render_blank(text: str) -> str:
    return re.sub(r"\bnull\b", "_____", text or "", count=1, flags=re.IGNORECASE)


def _grammar_correct(item: GrammarItem, typed: str) -> bool:
    accepted = _split_answers(getattr(item, "answer", "") or "")
    return _norm(typed) in accepted


def _norm_objective(obj: str) -> str:
    obj = (obj or "").strip().lower()

    mapping = {
        "vocabulary": "vocab",
        "words": "vocab",
        "word": "vocab",
        "vocab": "vocab",
        "grammar": "grammar",
        "grammars": "grammar",
        "sentence": "sentences",
        "sentences": "sentences",
        "sentence_review": "sentences",
    }
    return mapping.get(obj, obj)


def _norm_level(level: str) -> str:
    return (level or "").strip().upper()


def _norm_lang(lang: str) -> str:
    return (lang or "").strip().lower()


def _unique_preserve_order(ids: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []

    for x in ids or []:
        try:
            i = int(x)
        except Exception:
            continue

        if i <= 0 or i in seen:
            continue

        seen.add(i)
        out.append(i)

    return out


def _rating_0_3(value: int | str | None) -> int:
    try:
        value = int(value)
    except Exception:
        value = 0

    return max(0, min(3, value))


def _effective_vocab_rating(
    *,
    result: dict,
    user_rating: int,
    tip_used: bool,
    gender_tip_used: bool,
    was_checked: bool,
    was_skipped: bool,
) -> int:
    """
    Converts UI rating into learning-safe rating.

    Rules:
    - skipped / not checked => Again
    - any wrong required field => cannot be Good/Easy
    - correct but used tips => max Good
    - all correct without tips => user rating allowed
    """
    raw = _rating_0_3(user_rating)

    if was_skipped or not was_checked:
        return 0

    vals = [
        result.get("meaning_ok"),
        result.get("gender_ok"),
        result.get("plural_ok"),
    ]
    applicable = [v for v in vals if v is not None]

    if not applicable:
        return min(raw, 2)

    correct_count = sum(1 for v in applicable if bool(v))
    ratio = correct_count / len(applicable)

    if ratio >= 1.0:
        if tip_used or gender_tip_used:
            return min(raw, 2)
        return raw

    if ratio >= 0.67:
        return min(raw, 1)

    return 0


def _effective_binary_rating(
    *,
    ok: bool,
    user_rating: int,
    used_help: bool,
    was_checked: bool,
    was_skipped: bool,
) -> int:
    raw = _rating_0_3(user_rating)

    if was_skipped or not was_checked:
        return 0

    if not ok:
        return 0

    if used_help:
        return min(raw, 2)

    return raw


# ---------------------------------------------------------------------
# Sentence helpers
# ---------------------------------------------------------------------
_TOKEN_RE = re.compile(
    r"[A-Za-zÄÖÜäöüß]+(?:[-'][A-Za-zÄÖÜäöüß]+)*|\d+|[.,!?;:()\[\]{}\"“”„‚’‘…–—-]"
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text or "") if t and not t.isspace()]


def _is_punct(tok: str) -> bool:
    return bool(tok) and len(tok) == 1 and tok in ".,!?;:()[]{}\"“”„‚’‘…–—-"


def _as_required_list(value: Any) -> list[str]:
    if not value:
        return []

    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []

        if "|" in raw:
            return [part.strip() for part in raw.split("|") if part.strip()]

        if ";" in raw:
            return [part.strip() for part in raw.split(";") if part.strip()]

        return [raw]

    return []


@dataclass
class AppState:
    language_code: str = "de"
    level: str = "A1"
    objective: str = "vocab"  # vocab | grammar | sentences


@dataclass
class SessionPlan:
    limit: int = 30
    mode: str = "mixed"  # mixed | due_only | random_only
    pool_factor: int = 8


class SessionService:
    def __init__(self, repo: Repo, state: AppState):
        self.repo = repo
        self.state = state

        self.state.language_code = _norm_lang(getattr(self.state, "language_code", "de"))
        self.state.level = _norm_level(getattr(self.state, "level", "A1"))
        self.state.objective = _norm_objective(getattr(self.state, "objective", "vocab"))

        self._active_deck_id: int | None = None
        self.plan = SessionPlan()
        self._queue: list[int] = []

        self.rng = random.SystemRandom()

        model_dir = (
            Path(getattr(repo, "db_path", Path(".")))
            .expanduser()
            .resolve()
            .parent
            / "ml_models"
        )
        model_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.ml = SklearnRanker(repo, model_dir=model_dir)
        except TypeError:
            self.ml = SklearnRanker(repo)

        self.enable_ml_ranking = True
        self.ml_min_seen_before_ranking = 80
        self.ml_exploration_eps = 0.12

    # -----------------------------------------------------------------
    # Context / deck selection
    # -----------------------------------------------------------------
    def set_context(self, language_code: str, level: str, objective: str) -> None:
        lang = _norm_lang(language_code)
        lvl = _norm_level(level)
        obj = _norm_objective(objective)

        deck_id = self.repo.get_deck_id(lang, lvl, obj)
        if deck_id is None:
            self._active_deck_id = None
            self._queue = []
            raise RuntimeError(f"No deck found for {lang}/{lvl}/{obj}. Did you import seeds?")

        if self._active_deck_id != deck_id:
            self._queue = []

        self.state.language_code = lang
        self.state.level = lvl
        self.state.objective = obj
        self._active_deck_id = deck_id

    def active_deck_id(self) -> int | None:
        lang = _norm_lang(getattr(self.state, "language_code", "de"))
        lvl = _norm_level(getattr(self.state, "level", "A1"))
        obj = _norm_objective(getattr(self.state, "objective", "vocab"))

        deck_id = self.repo.get_deck_id(lang, lvl, obj)

        if deck_id != self._active_deck_id:
            self._queue = []
            self._active_deck_id = deck_id

        self.state.language_code = lang
        self.state.level = lvl
        self.state.objective = obj

        return self._active_deck_id

    # -----------------------------------------------------------------
    # Compatibility helpers used by UI pages
    # -----------------------------------------------------------------
    def remaining(self) -> int:
        """
        Required by vocab/grammar/sentence pages.

        Pages call this even during construction, before any session has
        started. So this must be safe and simply reflect queue length.
        """
        return len(self._queue)

    def has_active_session(self) -> bool:
        return bool(self._queue)

    def clear_session(self) -> None:
        self._queue = []

    # -----------------------------------------------------------------
    # Picker wrappers
    # -----------------------------------------------------------------
    def _pick_vocab_ids(self, deck_id: int, *, limit: Optional[int] = None) -> list[int]:
        fn = getattr(self.repo, "pick_session_vocab_ids", None)
        if not callable(fn):
            return []

        lim = int(limit if limit is not None else self.plan.limit)

        call_styles = (
            lambda: fn(deck_id, lim, self.plan.mode, cooldown_hours=12),
            lambda: fn(deck_id, lim, self.plan.mode),
            lambda: fn(deck_id, lim, mode=self.plan.mode),
            lambda: fn(deck_id, lim),
            lambda: fn(deck_id),
        )

        for call in call_styles:
            try:
                return _unique_preserve_order(call())
            except TypeError:
                continue
            except Exception:
                break

        return []

    def _pick_grammar_ids(self, deck_id: int, *, limit: Optional[int] = None) -> list[int]:
        fn = getattr(self.repo, "pick_session_grammar_ids", None)
        if not callable(fn):
            return []

        lim = int(limit if limit is not None else self.plan.limit)

        call_styles = (
            lambda: fn(deck_id, lim, self.plan.mode, cooldown_hours=12),
            lambda: fn(deck_id, lim, self.plan.mode),
            lambda: fn(deck_id, lim, mode=self.plan.mode),
            lambda: fn(deck_id, lim),
            lambda: fn(deck_id),
        )

        for call in call_styles:
            try:
                return _unique_preserve_order(call())
            except TypeError:
                continue
            except Exception:
                break

        return []

    def _pick_sentence_ids(self, deck_id: int, *, limit: Optional[int] = None) -> list[int]:
        fn = getattr(self.repo, "pick_session_sentence_ids", None)
        if not callable(fn):
            return []

        lim = int(limit if limit is not None else self.plan.limit)

        call_styles = (
            lambda: fn(deck_id, lim, mode=self.plan.mode, cooldown_hours=12),
            lambda: fn(deck_id, lim, self.plan.mode, cooldown_hours=12),
            lambda: fn(deck_id, lim, self.plan.mode),
            lambda: fn(deck_id, lim, mode=self.plan.mode),
            lambda: fn(deck_id, lim),
            lambda: fn(deck_id),
        )

        for call in call_styles:
            try:
                return _unique_preserve_order(call())
            except TypeError:
                continue
            except Exception:
                break

        return []

    # -----------------------------------------------------------------
    # Full-deck helpers
    # -----------------------------------------------------------------
    def _all_vocab_ids_for_deck(self, deck_id: int) -> list[int]:
        try:
            with self.repo._conn() as conn:
                rows = conn.execute("SELECT id FROM vocab WHERE deck_id=?", (deck_id,)).fetchall()

            return [int(r["id"]) for r in rows if r and r["id"] is not None]
        except Exception:
            return []

    def _all_grammar_ids_for_deck(self, deck_id: int) -> list[int]:
        try:
            with self.repo._conn() as conn:
                rows = conn.execute("SELECT id FROM grammar WHERE deck_id=?", (deck_id,)).fetchall()

            return [int(r["id"]) for r in rows if r and r["id"] is not None]
        except Exception:
            return []

    def _all_sentence_ids_for_deck(self, deck_id: int) -> list[int]:
        try:
            with self.repo._conn() as conn:
                rows = conn.execute("SELECT id FROM sentences WHERE deck_id=?", (deck_id,)).fetchall()

            return [int(r["id"]) for r in rows if r and r["id"] is not None]
        except Exception:
            return []

    def _top_up_with_random_from_full_deck(
        self,
        picked: list[int],
        full: list[int],
        desired_pool: int,
    ) -> list[int]:
        picked_u = _unique_preserve_order(picked)
        if len(picked_u) >= desired_pool:
            return picked_u

        picked_set = set(picked_u)
        remaining = [i for i in full if i not in picked_set]
        need = desired_pool - len(picked_u)

        if need <= 0 or not remaining:
            return picked_u

        if need >= len(remaining):
            extra = list(remaining)
            self.rng.shuffle(extra)
        else:
            extra = self.rng.sample(remaining, k=need)

        return picked_u + extra

    # -----------------------------------------------------------------
    # Session creation
    # -----------------------------------------------------------------
    def start_new_session(self) -> bool:
        """
        Build a new review queue for the active deck.

        Queue rule:
        - next_* methods use self._queue.pop()
        - the item at the END of self._queue is shown first

        ML ranker contract:
        - rank_*_ids returns LOW priority first, HIGH priority last
        - we keep that order so .pop() shows the highest-priority item first
        """
        deck_id = self.active_deck_id()
        if deck_id is None:
            self._queue = []
            return False

        objective = _norm_objective(getattr(self.state, "objective", "vocab"))

        try:
            limit = int(getattr(self.plan, "limit", 30) or 30)
        except Exception:
            limit = 30
        limit = max(1, limit)

        try:
            pool_factor = int(getattr(self.plan, "pool_factor", 8) or 8)
        except Exception:
            pool_factor = 8
        pool_factor = max(1, pool_factor)

        pool_limit = max(limit, limit * pool_factor)
        use_ml = bool(getattr(self, "enable_ml_ranking", True) and getattr(self, "ml", None))

        def _ml_ready(obj: str) -> bool:
            if not use_ml:
                return False

            try:
                return bool(
                    self.ml.is_ready(
                        lang=getattr(self.state, "language_code", None),
                        level=getattr(self.state, "level", None),
                        objective=obj,
                        min_seen=getattr(self, "ml_min_seen_before_ranking", 80),
                    )
                )
            except Exception:
                return False

        def _ml_should_explore() -> bool:
            try:
                eps = float(getattr(self, "ml_exploration_eps", 0.12) or 0.0)
            except Exception:
                eps = 0.12

            eps = max(0.0, min(1.0, eps))

            try:
                return bool(self.rng.random() < eps)
            except Exception:
                return False

        def _call_picker(method_name: str) -> list[int]:
            fn = getattr(self, method_name, None)
            if not callable(fn):
                return []

            call_styles = (
                lambda: fn(deck_id, limit=pool_limit),
                lambda: fn(deck_id, pool_limit),
                lambda: fn(deck_id),
            )

            for call in call_styles:
                try:
                    ids = _unique_preserve_order(call())
                    if ids:
                        return ids
                except TypeError:
                    continue
                except Exception:
                    return []

            return []

        def _call_repo_picker(method_names: tuple[str, ...]) -> list[int]:
            for method_name in method_names:
                fn = getattr(self.repo, method_name, None)
                if not callable(fn):
                    continue

                call_styles = (
                    lambda: fn(deck_id, pool_limit, self.plan.mode, cooldown_hours=12),
                    lambda: fn(deck_id, pool_limit, self.plan.mode),
                    lambda: fn(deck_id, pool_limit, mode=self.plan.mode),
                    lambda: fn(deck_id, pool_limit),
                    lambda: fn(deck_id),
                )

                for call in call_styles:
                    try:
                        ids = _unique_preserve_order(call())
                        if ids:
                            return ids
                    except TypeError:
                        continue
                    except Exception:
                        break

            return []

        def _finalize_queue(ids: list[int], *, ranked: bool) -> bool:
            ids = _unique_preserve_order(ids)

            if not ids:
                self._queue = []
                return False

            if ranked:
                selected = ids[-limit:]
            else:
                selected = ids[:limit]

            self._queue = _unique_preserve_order(selected)
            return bool(self._queue)

        # -------------------------
        # Vocab
        # -------------------------
        if objective == "vocab":
            ids = _call_picker("_pick_vocab_ids")

            if not ids:
                ids = _call_repo_picker(("pick_session_vocab_ids", "pick_vocab_ids"))

            if not ids:
                ids = self._top_up_with_random_from_full_deck(
                    picked=[],
                    full=self._all_vocab_ids_for_deck(deck_id),
                    desired_pool=pool_limit,
                )

            ids = _unique_preserve_order(ids)

            if use_ml and _ml_ready("vocab") and not _ml_should_explore() and ids:
                try:
                    ids = self.ml.rank_vocab_ids(
                        ids,
                        level=getattr(self.state, "level", None),
                        lang=getattr(self.state, "language_code", None),
                    )
                    return _finalize_queue(ids, ranked=True)
                except Exception:
                    pass

            self.rng.shuffle(ids)
            return _finalize_queue(ids, ranked=False)

        # -------------------------
        # Grammar
        # -------------------------
        if objective == "grammar":
            ids = _call_picker("_pick_grammar_ids")

            if not ids:
                ids = _call_repo_picker(("pick_session_grammar_ids", "pick_grammar_ids"))

            if not ids:
                ids = self._top_up_with_random_from_full_deck(
                    picked=[],
                    full=self._all_grammar_ids_for_deck(deck_id),
                    desired_pool=pool_limit,
                )

            ids = _unique_preserve_order(ids)

            if use_ml and _ml_ready("grammar") and not _ml_should_explore() and ids:
                try:
                    ids = self.ml.rank_grammar_ids(
                        ids,
                        level=getattr(self.state, "level", None),
                        lang=getattr(self.state, "language_code", None),
                    )
                    return _finalize_queue(ids, ranked=True)
                except Exception:
                    pass

            self.rng.shuffle(ids)
            return _finalize_queue(ids, ranked=False)

        # -------------------------
        # Sentences
        # -------------------------
        if objective == "sentences":
            ids = _call_picker("_pick_sentence_ids")

            if not ids:
                ids = _call_repo_picker(
                    (
                        "pick_session_sentence_ids",
                        "pick_sentence_ids",
                        "pick_session_sentences_ids",
                        "pick_sentences_ids",
                    )
                )

            if not ids:
                ids = self._top_up_with_random_from_full_deck(
                    picked=[],
                    full=self._all_sentence_ids_for_deck(deck_id),
                    desired_pool=pool_limit,
                )

            ids = _unique_preserve_order(ids)

            if use_ml and _ml_ready("sentences") and not _ml_should_explore() and ids:
                try:
                    ids = self.ml.rank_sentence_ids(
                        ids,
                        level=getattr(self.state, "level", None),
                        lang=getattr(self.state, "language_code", None),
                    )
                    return _finalize_queue(ids, ranked=True)
                except Exception:
                    pass

            self.rng.shuffle(ids)
            return _finalize_queue(ids, ranked=False)

        self._queue = []
        return False

    # -----------------------------------------------------------------
    # Unified next item API
    # -----------------------------------------------------------------
    def next_item(self):
        obj = _norm_objective(self.state.objective)

        if obj == "grammar":
            return self.next_grammar_item()

        if obj == "sentences":
            return self.next_sentence_item()

        return self.next_vocab_item()

    def next(self):
        return self.next_item()

    def next_vocab(self):
        return self.next_vocab_item()

    def next_grammar(self):
        return self.next_grammar_item()

    def next_sentence(self):
        return self.next_sentence_item()

    # -----------------------------------------------------------------
    # Vocab
    # -----------------------------------------------------------------
    def next_vocab_item(self) -> Optional[VocabItem]:
        if not self._queue:
            return None

        vid = self._queue.pop()
        return self.repo.get_vocab_by_id(vid)

    def prompt_text(self, item: VocabItem) -> str:
        return getattr(item, "word", "") or ""

    def check_vocab_fields(
        self,
        item: VocabItem,
        typed_meaning: str,
        typed_gender: str,
        typed_plural: str,
    ) -> dict:
        accepted = _split_answers(getattr(item, "meaning", "") or "")
        typed_norm = _norm(typed_meaning)

        meaning_ok = typed_norm in accepted if accepted else False
        expected_meaning = getattr(item, "meaning", "") or ""

        gender_ok: bool | None = None
        plural_ok: bool | None = None
        expected_gender: str | None = None
        expected_plural: str | None = None

        pos = (getattr(item, "pos", "") or "").strip().lower()

        if pos == "noun":
            item_gender = getattr(item, "gender", None)
            item_plural = getattr(item, "plural", None)

            if item_gender:
                gender_ok = _norm_gender(typed_gender) == _norm_gender(item_gender)
                expected_gender = item_gender

            if item_plural:
                plural_ok = _norm(typed_plural) == _norm(item_plural)
                expected_plural = item_plural

        return {
            "meaning_ok": meaning_ok,
            "gender_ok": gender_ok,
            "plural_ok": plural_ok,
            "expected_meaning": expected_meaning,
            "expected_gender": expected_gender,
            "expected_plural": expected_plural,
        }

    def submit_vocab(
        self,
        item: VocabItem,
        typed_meaning: str,
        typed_gender: str,
        typed_plural: str,
        rating: int,
        tip_used: bool,
        gender_tip_used: bool,
        was_checked: bool,
        was_skipped: bool,
        response_ms: int | None,
    ) -> dict:
        st = self.repo.ensure_state(item.id)
        res = self.check_vocab_fields(item, typed_meaning, typed_gender, typed_plural)

        effective_rating = _effective_vocab_rating(
            result=res,
            user_rating=rating,
            tip_used=tip_used,
            gender_tip_used=gender_tip_used,
            was_checked=was_checked,
            was_skipped=was_skipped,
        )

        meaning_correct_bool = bool(res["meaning_ok"])
        gender_correct_bool = None if res["gender_ok"] is None else bool(res["gender_ok"])
        plural_correct_bool = None if res["plural_ok"] is None else bool(res["plural_ok"])

        self.repo.insert_review(
            vocab_id=item.id,
            typed_meaning=typed_meaning or None,
            typed_gender=typed_gender or None,
            typed_plural=typed_plural or None,
            meaning_correct=1 if meaning_correct_bool else 0,
            gender_correct=None if gender_correct_bool is None else (1 if gender_correct_bool else 0),
            plural_correct=None if plural_correct_bool is None else (1 if plural_correct_bool else 0),
            tip_used=1 if tip_used else 0,
            gender_tip_used=1 if gender_tip_used else 0,
            was_checked=1 if was_checked else 0,
            was_skipped=1 if was_skipped else 0,
            rating=effective_rating,
            response_ms=response_ms,
        )

        st2 = schedule_next(st, effective_rating)
        self.repo.update_state(st2)

        ml = getattr(self, "ml", None)
        if ml is not None and hasattr(ml, "update_vocab"):
            try:
                ml.update_vocab(
                    item=item,
                    state_before=st,
                    review_result=res,
                    effective_rating=effective_rating,
                    tip_used=tip_used,
                    gender_tip_used=gender_tip_used,
                    was_checked=was_checked,
                    was_skipped=was_skipped,
                    response_ms=response_ms,
                    lang=getattr(self.state, "language_code", None),
                    level=getattr(self.state, "level", None),
                )
            except Exception:
                pass

        res["effective_rating"] = effective_rating
        return res

    # -----------------------------------------------------------------
    # Grammar
    # -----------------------------------------------------------------
    def next_grammar_item(self) -> Optional[GrammarItem]:
        if not self._queue:
            return None

        gid = self._queue.pop()
        return self.repo.get_grammar_by_id(gid)

    def grammar_prompt_text(self, item: GrammarItem) -> str:
        return _render_blank(getattr(item, "test_text", "") or "")

    def check_grammar(self, item: GrammarItem, typed_blank: str) -> dict:
        ok = _grammar_correct(item, typed_blank)
        return {
            "ok": ok,
            "expected": getattr(item, "answer", "") or "",
            "typed": typed_blank,
        }

    def submit_grammar(
        self,
        item: GrammarItem,
        typed_blank: str,
        rating: int,
        meaning_tip_used: bool,
        hint_used: bool,
        grammar_tip_used: bool,
        was_checked: bool,
        was_skipped: bool,
        response_ms: int | None,
    ) -> dict:
        st = self.repo.ensure_grammar_state(item.id)
        res = self.check_grammar(item, typed_blank)

        used_help = bool(meaning_tip_used or hint_used or grammar_tip_used)

        effective_rating = _effective_binary_rating(
            ok=bool(res["ok"]),
            user_rating=rating,
            used_help=used_help,
            was_checked=was_checked,
            was_skipped=was_skipped,
        )

        correct = 1 if bool(res["ok"]) else 0

        self.repo.insert_grammar_review(
            grammar_id=item.id,
            typed_blank=(typed_blank or None),
            correct=correct,
            meaning_tip_used=(1 if meaning_tip_used else 0),
            hint_used=(1 if hint_used else 0),
            grammar_tip_used=(1 if grammar_tip_used else 0),
            was_checked=(1 if was_checked else 0),
            was_skipped=(1 if was_skipped else 0),
            rating=effective_rating,
            response_ms=response_ms,
        )

        st2 = _schedule_next_grammar(st, effective_rating)
        self.repo.update_grammar_state(st2)

        ml = getattr(self, "ml", None)
        if ml is not None and hasattr(ml, "update_grammar"):
            try:
                ml.update_grammar(
                    item=item,
                    state_before=st,
                    review_result=res,
                    effective_rating=effective_rating,
                    meaning_tip_used=meaning_tip_used,
                    hint_used=hint_used,
                    grammar_tip_used=grammar_tip_used,
                    was_checked=was_checked,
                    was_skipped=was_skipped,
                    response_ms=response_ms,
                    lang=getattr(self.state, "language_code", None),
                    level=getattr(self.state, "level", None),
                )
            except Exception:
                pass

        res["effective_rating"] = effective_rating
        return res

    # -----------------------------------------------------------------
    # Sentences
    # -----------------------------------------------------------------
    def next_sentence_item(self) -> Optional[SentenceItem]:
        if not self._queue:
            return None

        sid = self._queue.pop()
        return self.repo.get_sentence_by_id(sid)

    def check_sentence(self, item: Any, typed_text: str) -> Dict[str, Any]:
        """
        Evaluation is based on the exact full sentence.

        `required` is optional feedback only and does not decide correctness.
        """
        expected = (getattr(item, "target_text", "") or "").strip()
        typed = (typed_text or "").strip()

        exp_toks = _tokenize(expected)
        got_toks = _tokenize(typed)

        mismatch_count = 0
        first_mismatch = -1
        cap_errors = 0
        punct_errors = 0

        n = max(len(exp_toks), len(got_toks))

        for i in range(n):
            exp = exp_toks[i] if i < len(exp_toks) else None
            got = got_toks[i] if i < len(got_toks) else None

            if exp == got:
                continue

            mismatch_count += 1

            if first_mismatch < 0:
                first_mismatch = i

            if exp and got and exp.lower() == got.lower() and exp.isalpha() and got.isalpha():
                cap_errors += 1

            if (exp and _is_punct(exp)) or (got and _is_punct(got)):
                punct_errors += 1

        missing_required = []
        required_items = _as_required_list(getattr(item, "required", None))

        if required_items:
            got_lower = {t.lower() for t in got_toks}
            for req in required_items:
                r = (req or "").strip()
                if r and r.lower() not in got_lower:
                    missing_required.append(r)

        ok = mismatch_count == 0

        return {
            "ok": ok,
            "expected": expected,
            "typed": typed,
            "mismatch_count": mismatch_count,
            "first_mismatch": first_mismatch,
            "cap_errors": cap_errors,
            "punct_errors": punct_errors,
            "missing_required": missing_required,
        }

    def submit_sentence(
        self,
        item: Any,
        typed_text: str,
        rating: int,
        tip_used: bool,
        translation_used: bool,
        was_checked: bool,
        was_skipped: bool,
        response_ms: int | None,
    ) -> Dict[str, Any]:
        st = self.repo.ensure_sentence_state(item.id)
        res = self.check_sentence(item, typed_text)

        used_help = bool(tip_used or translation_used)

        effective_rating = _effective_binary_rating(
            ok=bool(res.get("ok")),
            user_rating=rating,
            used_help=used_help,
            was_checked=was_checked,
            was_skipped=was_skipped,
        )

        correct = 1 if bool(res.get("ok")) else 0
        typed = (typed_text or "").strip() or None
        got_toks = _tokenize(typed_text)

        self.repo.insert_sentence_review(
            sentence_id=item.id,
            typed_text=typed,
            correct=correct,
            tip_used=int(tip_used),
            translation_used=int(translation_used),
            was_checked=int(was_checked),
            was_skipped=int(was_skipped),
            rating=effective_rating,
            response_ms=response_ms,
            bank_size=len(getattr(item, "words", []) or []),
            tokens_used=len(got_toks),
            mismatch_count=int(res.get("mismatch_count") or 0),
            cap_errors=int(res.get("cap_errors") or 0),
            punct_errors=int(res.get("punct_errors") or 0),
        )

        st2 = schedule_next(st, effective_rating)
        self.repo.update_sentence_state(st2)

        ml = getattr(self, "ml", None)
        if ml is not None and hasattr(ml, "update_sentence"):
            try:
                ml.update_sentence(
                    item=item,
                    state_before=st,
                    review_result=res,
                    effective_rating=effective_rating,
                    tip_used=tip_used,
                    translation_used=translation_used,
                    was_checked=was_checked,
                    was_skipped=was_skipped,
                    response_ms=response_ms,
                    lang=getattr(self.state, "language_code", None),
                    level=getattr(self.state, "level", None),
                )
            except Exception:
                pass

        res["effective_rating"] = effective_rating
        return res


def _schedule_next_grammar(state, rating: int):
    now = int(time.time())
    rating = _rating_0_3(rating)
    s = replace(state, last_review_at=now)

    if rating == 0:
        ease = max(1.3, s.ease - 0.2)
        return replace(
            s,
            ease=ease,
            lapses=s.lapses + 1,
            reps=max(0, s.reps - 1),
            interval_days=0.0,
            due_at=now + 10 * 60,
        )

    reps = s.reps + 1

    if reps == 1:
        interval = 1.0
    elif reps == 2:
        interval = 3.0
    else:
        mult = {1: 1.2, 2: 1.0, 3: 1.3}.get(rating, 1.0)
        interval = max(1.0, s.interval_days * s.ease * mult)

    if rating == 1:
        ease = max(1.3, s.ease - 0.15)
    elif rating == 3:
        ease = max(1.3, s.ease + 0.10)
    else:
        ease = max(1.3, s.ease)

    due_at = now + int(interval * 86400)

    return replace(
        s,
        ease=ease,
        reps=reps,
        interval_days=interval,
        due_at=due_at,
    )