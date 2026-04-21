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


# ---- shared normalizers ----
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
    return re.sub(r"\bnull\b", "_____", text, count=1, flags=re.IGNORECASE)


def _grammar_correct(item: GrammarItem, typed: str) -> bool:
    accepted = _split_answers(item.answer)
    return _norm(typed) in accepted


def _norm_objective(obj: str) -> str:
    return (obj or "").strip().lower()


def _norm_level(level: str) -> str:
    return (level or "").strip().upper()


def _norm_lang(lang: str) -> str:
    return (lang or "").strip().lower()


def _unique_preserve_order(ids: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for x in ids:
        try:
            i = int(x)
        except Exception:
            continue
        if i in seen:
            continue
        seen.add(i)
        out.append(i)
    return out


# Sentence tokenizer (shared)
_TOKEN_RE = re.compile(
    r"[A-Za-zÄÖÜäöüß]+(?:[-'][A-Za-zÄÖÜäöüß]+)*|\d+|[.,!?;:()\[\]{}\"“”„‚’‘…–—-]"
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text or "") if t and not t.isspace()]


def _is_punct(tok: str) -> bool:
    return bool(tok) and len(tok) == 1 and tok in ".,!?;:()[]{}\"“”„‚’‘…–—-"


@dataclass
class AppState:
    language_code: str = "de"
    level: str = "A1"
    objective: str = "vocab"       # vocab | grammar | sentences


@dataclass
class SessionPlan:
    limit: int = 30
    mode: str = "mixed"            # mixed | due_only | random_only
    pool_factor: int = 8


class SessionService:
    def __init__(self, repo: Repo, state: AppState):
        self.repo = repo
        self.state = state
        self._active_deck_id: int | None = None
        self.plan = SessionPlan()
        self._queue: list[int] = []

        self.rng = random.SystemRandom()

        model_dir = Path(getattr(repo, "db_path", Path("."))).expanduser().resolve().parent / "ml_models"
        model_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.ml = SklearnRanker(repo, model_dir=model_dir)
        except TypeError:
            self.ml = SklearnRanker(repo)

        self.enable_ml_ranking = True
        self.ml_min_seen_before_ranking = 80
        self.ml_exploration_eps = 0.12

    # ---------------------------
    # Context / deck selection
    # ---------------------------
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
        return self._active_deck_id

    # ---------------------------
    # Picker wrappers
    # ---------------------------
    def _pick_vocab_ids(self, deck_id: int, *, limit: Optional[int] = None) -> list[int]:
        fn = getattr(self.repo, "pick_session_vocab_ids", None)
        if not callable(fn):
            return []
        lim = int(limit if limit is not None else self.plan.limit)

        for args, kwargs in (
            ((deck_id, lim, self.plan.mode), {"cooldown_hours": 12}),
            ((deck_id, lim, self.plan.mode), {}),
        ):
            try:
                out = fn(*args, **kwargs)
                return list(out) if out else []
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

        for args, kwargs in (
            ((deck_id, lim, self.plan.mode), {"cooldown_hours": 12}),
            ((deck_id, lim, self.plan.mode), {}),
        ):
            try:
                out = fn(*args, **kwargs)
                return list(out) if out else []
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
        try:
            out = fn(deck_id, lim, mode=self.plan.mode, cooldown_hours=12)
        except TypeError:
            out = fn(deck_id, lim, self.plan.mode)
        return list(out) if out else []

    # ---------------------------
    # Full-deck helpers
    # ---------------------------
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

    def _top_up_with_random_from_full_deck(self, picked: list[int], full: list[int], desired_pool: int) -> list[int]:
        picked_u = _unique_preserve_order(picked)
        if len(picked_u) >= desired_pool:
            return picked_u

        remaining = [i for i in full if i not in set(picked_u)]
        need = desired_pool - len(picked_u)
        if need <= 0 or not remaining:
            return picked_u

        if need >= len(remaining):
            extra = remaining
            self.rng.shuffle(extra)
        else:
            extra = self.rng.sample(remaining, k=need)

        return picked_u + extra

    # ---------------------------
    # Session creation
    # ---------------------------
    def start_new_session(self) -> bool:
        deck_id = self.active_deck_id()
        if deck_id is None:
            self._queue = []
            return False

        desired = max(1, int(self.plan.limit))
        pool_size = max(desired, desired * max(2, int(self.plan.pool_factor)))

        use_ml = bool(self.enable_ml_ranking and getattr(self.ml, "enabled", False))

        obj = _norm_objective(self.state.objective)

        if obj == "sentences":
            ids = self._pick_sentence_ids(deck_id, limit=pool_size)
            ids = _unique_preserve_order(ids)

            if len(ids) < desired:
                full = self._all_sentence_ids_for_deck(deck_id)
                ids = self._top_up_with_random_from_full_deck(ids, full, pool_size)

            self.rng.shuffle(ids)

        elif obj == "grammar":
            ids = self._pick_grammar_ids(deck_id, limit=pool_size)
            ids = _unique_preserve_order(ids)

            if len(ids) < desired:
                full = self._all_grammar_ids_for_deck(deck_id)
                ids = self._top_up_with_random_from_full_deck(ids, full, pool_size)

            self.rng.shuffle(ids)

            if use_ml:
                ready = False
                try:
                    ready = self.ml.is_ready(
                        lang=self.state.language_code,
                        level=self.state.level,
                        objective="grammar",
                        min_seen=self.ml_min_seen_before_ranking,
                    )
                except Exception:
                    ready = False

                exploring = (self.rng.random() < float(self.ml_exploration_eps))
                if ready and not exploring:
                    try:
                        ids = self.ml.rank_vocab_ids(
                            ids,
                            level=self.state.level,
                            lang=self.state.language_code,
                        )
                    except Exception:
                        pass


        else:
            ids = self._pick_vocab_ids(deck_id, limit=pool_size)
            ids = _unique_preserve_order(ids)

            if len(ids) < desired:
                full = self._all_vocab_ids_for_deck(deck_id)
                ids = self._top_up_with_random_from_full_deck(ids, full, pool_size)

            self.rng.shuffle(ids)

            if use_ml:
                ready = False
                try:
                    ready = self.ml.is_ready(
                        lang=self.state.language_code,
                        level=self.state.level,
                        objective="vocab",
                        min_seen=self.ml_min_seen_before_ranking,
                    )
                except Exception:
                    ready = False

                exploring = (self.rng.random() < float(self.ml_exploration_eps))
                if ready and not exploring:
                    try:
                        ids = self.ml.rank_vocab_ids(
                            ids,
                            level=self.state.level,
                            lang=self.state.language_code,
                        )
                    except Exception:
                        pass


        ids = _unique_preserve_order(ids)
        self._queue = ids[:desired]
        return bool(self._queue)

    def remaining(self) -> int:
        return len(self._queue)

    # ==========================================================
    # Unified next_item
    # ==========================================================
    def next_item(self):
        obj = _norm_objective(self.state.objective)
        if obj == "grammar":
            return self.next_grammar_item()
        if obj == "sentences":
            return self.next_sentence_item()
        return self.next_vocab_item()

    def next(self):
        return self.next_item()

    # ======================
    # Vocab
    # ======================
    def next_vocab_item(self) -> Optional[VocabItem]:
        if not self._queue:
            return None
        vid = self._queue.pop()
        return self.repo.get_vocab_by_id(vid)

    def prompt_text(self, item: VocabItem) -> str:
        return item.word

    def check_vocab_fields(self, item: VocabItem, typed_meaning: str, typed_gender: str, typed_plural: str) -> dict:
        # Always check target -> English meaning
        accepted = _split_answers(item.meaning)
        meaning_ok = _norm(typed_meaning) in accepted
        expected_meaning = item.meaning

        gender_ok: bool | None = None
        plural_ok: bool | None = None
        expected_gender: str | None = None
        expected_plural: str | None = None

        if item.pos == "noun":
            if item.gender:
                gender_ok = _norm_gender(typed_gender) == _norm_gender(item.gender)
                expected_gender = item.gender
            if item.plural:
                plural_ok = _norm(typed_plural) == _norm(item.plural)
                expected_plural = item.plural

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

        meaning_correct_bool = bool(res["meaning_ok"])
        gender_correct_bool = (None if res["gender_ok"] is None else bool(res["gender_ok"]))
        plural_correct_bool = (None if res["plural_ok"] is None else bool(res["plural_ok"]))

        meaning_correct = 1 if meaning_correct_bool else 0
        gender_correct = None if gender_correct_bool is None else (1 if gender_correct_bool else 0)
        plural_correct = None if plural_correct_bool is None else (1 if plural_correct_bool else 0)

        self.repo.insert_review(
            vocab_id=item.id,
            typed_meaning=typed_meaning or None,
            typed_gender=typed_gender or None,
            typed_plural=typed_plural or None,
            meaning_correct=meaning_correct,
            gender_correct=gender_correct,
            plural_correct=plural_correct,
            tip_used=1 if tip_used else 0,
            gender_tip_used=1 if gender_tip_used else 0,
            was_checked=1 if was_checked else 0,
            was_skipped=1 if was_skipped else 0,
            rating=rating,
            response_ms=response_ms,
        )

        st2 = schedule_next(st, rating)
        self.repo.update_state(st2)
        return res

    # ======================
    # Grammar
    # ======================
    def next_grammar_item(self) -> Optional[GrammarItem]:
        if not self._queue:
            return None
        gid = self._queue.pop()
        return self.repo.get_grammar_by_id(gid)

    def grammar_prompt_text(self, item: GrammarItem) -> str:
        return _render_blank(item.test_text)

    def check_grammar(self, item: GrammarItem, typed_blank: str) -> dict:
        ok = _grammar_correct(item, typed_blank)
        return {"ok": ok, "expected": item.answer, "typed": typed_blank}

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
            rating=rating,
            response_ms=response_ms,
        )

        st2 = _schedule_next_grammar(st, rating)
        self.repo.update_grammar_state(st2)
        return res

    # ======================
    # Sentences
    # ======================
    def next_sentence_item(self) -> Optional[SentenceItem]:
        if not self._queue:
            return None
        sid = self._queue.pop()
        return self.repo.get_sentence_by_id(sid)

    def check_sentence(self, item: Any, typed_text: str) -> Dict[str, Any]:
        """
        Return a dict with the evaluation of *typed_text* against the sentence
        stored in *item*. The verdict is based only on the full sentence text.
        The `required` field is optional feedback and never decides correctness.
        """

        # Use ONLY the sentence text as source of truth
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
        if getattr(item, "required", None):
            got_lower = {t.lower() for t in got_toks}
            for req in item.required:
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
        """
        Persist a review for the given sentence item.
        Only the full sentence comparison controls correctness.
        """

        st = self.repo.ensure_sentence_state(item.id)
        res = self.check_sentence(item, typed_text)

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
            rating=rating,
            response_ms=response_ms,
            bank_size=len(getattr(item, "words", []) or []),
            tokens_used=len(got_toks),
            mismatch_count=int(res.get("mismatch_count") or 0),
            cap_errors=int(res.get("cap_errors") or 0),
            punct_errors=int(res.get("punct_errors") or 0),
        )

        st2 = schedule_next(st, rating)
        self.repo.update_sentence_state(st2)

        return res


def _schedule_next_grammar(state, rating: int):
    now = int(time.time())
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
        mult = {1: 1.2, 2: 1.0, 3: 1.3}[rating]
        interval = max(1.0, s.interval_days * s.ease * mult)

    if rating == 1:
        ease = max(1.3, s.ease - 0.15)
    elif rating == 3:
        ease = max(1.3, s.ease + 0.10)
    else:
        ease = max(1.3, s.ease)

    due_at = now + int(interval * 86400)
    return replace(s, ease=ease, reps=reps, interval_days=interval, due_at=due_at)