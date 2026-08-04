from __future__ import annotations

import random
import re
import time
from contextlib import nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from db.repo import (
    GrammarItem,
    GrammarState,
    ListeningItem,
    ListeningState,
    Repo,
    SentenceItem,
    SentenceState,
    VocabItem,
    VocabState,
)
from core.srs import schedule_next
from core.ml.sklearn_ranker import SklearnRanker
from core.semantic_match import get_matcher
from core.german_feedback import classify_german_answer


# ---------------------------------------------------------------------
# Shared normalizers / answer matching
# ---------------------------------------------------------------------
# Alternative glosses in the seed data are separated inconsistently
# ("leaf / paper", "a; b", "x, y"), so we split on any of these.
_ALT_SEP_RE = re.compile(r"\s*[/;|,]\s*")
_PARENS_RE = re.compile(r"\([^)]*\)")
# Leading English markers we strip so "to work" == "work", "a house" == "house".
_LEADING_PREFIXES = ("to ", "the ", "a ", "an ")


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = _PARENS_RE.sub(" ", s)               # drop "(coll.)", "(formal)" notes
    s = re.sub(r"[^\w\säöüß-]", " ", s)       # punctuation -> space
    s = " ".join(s.split())
    for pref in _LEADING_PREFIXES:
        if s.startswith(pref):
            s = s[len(pref):].strip()
            break
    return s


def _split_answers(ans: str) -> list[str]:
    """All acceptable normalized forms of an answer key.

    Splits alternatives on / ; | , AND keeps the whole phrase, so a learner who
    types one valid gloss ("leaf") matches a key of "leaf / paper", while a
    phrase that legitimately contains a separator still matches in full.
    """
    raw = (ans or "").strip()
    if not raw:
        return []
    candidates = _ALT_SEP_RE.split(raw)
    candidates.append(raw)
    out: list[str] = []
    for c in candidates:
        n = _norm(c)
        if n and n not in out:
            out.append(n)
    return out


def _answer_matches(typed: str, accepted: list[str]) -> bool:
    """True if the typed answer exactly matches any accepted gloss (after
    normalization). Used for grammar forms, which must stay precise. Vocab
    *meaning* matching is semantic and lives in core.semantic_match."""
    t = _norm(typed)
    if not t or not accepted:
        return False
    return t in accepted


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
    # Grammar forms must stay precise (e.g. "ist" vs "isst") — exact match only.
    return _answer_matches(typed, accepted)


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


def _repo_transaction(repo):
    """Use one atomic repository write scope when the backend supports it."""
    transaction = getattr(repo, "transaction", None)
    return transaction() if callable(transaction) else nullcontext()


def _rating_0_3(value: int | str | None) -> int:
    try:
        value = int(value)
    except Exception:
        value = 0

    return max(0, min(3, value))


def _fmt_interval(seconds: int) -> str:
    """Compact human label for an SRS interval (rating-button preview)."""
    s = max(0, int(seconds))
    m = s // 60
    h = m // 60
    d = h // 24
    if s < 90:
        return "1m"
    if m < 60:
        return f"{m}m"
    if h < 24:
        return f"{h}h"
    if d < 30:
        return f"{d}d"
    if d < 365:
        return f"{max(1, round(d / 30))}mo"
    return f"{max(1, round(d / 365))}y"


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

    if ratio >= 2.0 / 3.0:
        # Two-thirds or more of the applicable fields right -> Hard, not a full
        # lapse. Use the exact fraction so the 2-of-3 case (0.6666…) isn't lost
        # to a 0.67 rounding cliff and mis-scheduled as Again.
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
    level: str = "A1"
    objective: str = "vocab"  # vocab | grammar | sentences
    book_slug: str = ""
    lektion_number: int = 0


@dataclass
class SessionPlan:
    limit: int = 30
    mode: str = "mixed"  # mixed | due_only | random_only
    pool_factor: int = 8
    new_limit: int | None = None


class SessionService:
    def __init__(self, repo: Repo, state: AppState):
        self.repo = repo
        self.state = state

        self.state.level = _norm_level(getattr(self.state, "level", "A1"))
        self.state.objective = _norm_objective(getattr(self.state, "objective", "vocab"))

        self._active_deck_id: int | None = None
        self.plan = SessionPlan()
        self._queue: list[int] = []
        self._undo = None

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

        # Global study session tracker — shared across all panels
        self.study_answered: int = 0
        self.study_next_milestone: int = 30

    # -----------------------------------------------------------------
    # Context / deck selection
    # -----------------------------------------------------------------
    def _resolve_lektion_id(self) -> int | None:
        """Look up lektion_id from state.book_slug + level + lektion_number."""
        book_slug = (getattr(self.state, "book_slug", "") or "").strip()
        lektion_number = int(getattr(self.state, "lektion_number", 0) or 0)
        level = _norm_level(getattr(self.state, "level", "") or "")
        if not book_slug or lektion_number <= 0:
            return None
        try:
            book_id = self.repo.get_book_id(book_slug)
            if book_id is None:
                return None
            return self.repo.get_lektion_id(book_id, level, lektion_number)
        except Exception:
            return None

    def set_context(
        self,
        level: str,
        objective: str,
        book_slug: str = "",
        lektion_number: int = 0,
    ) -> None:
        lvl = _norm_level(level)
        obj = _norm_objective(objective)
        book_slug = (book_slug or "").strip()
        lektion_number = int(lektion_number or 0)

        # Reset study tracker when the lektion context changes (not just objective)
        old_lvl = _norm_level(getattr(self.state, "level", ""))
        old_book = (getattr(self.state, "book_slug", "") or "").strip()
        old_lektion = int(getattr(self.state, "lektion_number", 0) or 0)
        if lvl != old_lvl or book_slug != old_book or lektion_number != old_lektion:
            self.study_answered = 0
            self.study_next_milestone = 30

        # Write level/book/lektion to state so _resolve_lektion_id (which is
        # level-aware) resolves against the NEW context, not the previous one.
        self.state.level = lvl
        self.state.book_slug = book_slug
        self.state.lektion_number = lektion_number
        lektion_id = self._resolve_lektion_id()

        deck_id = self.repo.get_deck_id(lvl, obj, lektion_id=lektion_id)
        if deck_id is None:
            self._active_deck_id = None
            self._queue = []
            self._undo = None
            raise RuntimeError(
                f"No deck found for {lvl}/{obj} "
                f"(book={book_slug or 'none'}, lektion={lektion_number or 'none'}). "
                "Did you import seeds?"
            )

        if self._active_deck_id != deck_id:
            self._queue = []
            self._undo = None

        self.state.level = lvl
        self.state.objective = obj
        self._active_deck_id = deck_id

    def active_deck_id(self) -> int | None:
        lvl = _norm_level(getattr(self.state, "level", "A1"))
        obj = _norm_objective(getattr(self.state, "objective", "vocab"))
        lektion_id = self._resolve_lektion_id()

        deck_id = self.repo.get_deck_id(lvl, obj, lektion_id=lektion_id)

        if deck_id != self._active_deck_id:
            self._queue = []
            self._undo = None
            self._active_deck_id = deck_id

        self.state.level = lvl
        self.state.objective = obj

        return self._active_deck_id

    def vocab_deck_id(self) -> int | None:
        """The vocab deck for the current level/book/lektion, resolved WITHOUT
        touching state.objective — the read-only vocab table is reachable from
        the vocab card regardless of which objective is being practiced."""
        lvl = _norm_level(getattr(self.state, "level", "") or "")
        lektion_id = self._resolve_lektion_id()
        try:
            return self.repo.get_deck_id(lvl, "vocab", lektion_id=lektion_id)
        except Exception:
            return None

    def vocab_table_rows(self) -> list[dict]:
        """(word, article, plural, meaning) rows for the current lektion's vocab
        deck — the data backing the read-only study table. Empty when there is
        no vocab deck for the current context."""
        deck_id = self.vocab_deck_id()
        if deck_id is None:
            return []
        try:
            return self.repo.vocab_table_rows(deck_id)
        except Exception:
            return []

    def pick_vocab_practice_ids(
        self,
        practice_mode: str,
        *,
        limit: int | None = None,
        mode: str = "mixed",
        cooldown_hours: int = 0,
    ) -> list[int]:
        """Build a production/dictation queue for the current vocabulary deck.

        This deliberately bypasses the recognition queue and its ML ranking;
        the repository selects against the requested lane's independent FSRS
        state while still honoring base-card suspension and burial controls.
        """
        deck_id = self.vocab_deck_id()
        if deck_id is None:
            return []
        picker = getattr(self.repo, "pick_practice_vocab_ids", None)
        if not callable(picker):
            picker = getattr(self.repo, "pick_vocab_practice_ids", None)
        if not callable(picker):
            return []
        requested = self.plan.limit if limit is None else int(limit)
        return _unique_preserve_order(
            picker(
                deck_id,
                practice_mode,
                max(0, requested),
                mode=mode,
                cooldown_hours=cooldown_hours,
            )
        )

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

    def exclude_from_queue(self, objective: str, item_id: int) -> bool:
        """Remove a learner-controlled card from the active in-memory queue.

        Item identifiers are only unique within their objective table, so an
        action from another lane must never evict a numerically equal ID.  The
        database remains the source of truth; this method only prevents a queue
        built before a suspend/bury action from serving stale work.
        """
        if _norm_objective(objective) != _norm_objective(
            getattr(self.state, "objective", "")
        ):
            return False
        try:
            target = int(item_id)
        except (TypeError, ValueError):
            return False

        previous_size = len(self._queue)
        self._queue[:] = [queued for queued in self._queue if int(queued) != target]
        return len(self._queue) != previous_size

    def record_item_answered(self) -> bool:
        """
        Increment the global study counter (shared across all panels).
        Returns True when a milestone of 30 is reached, so the UI can celebrate.
        """
        self.study_answered += 1
        if self.study_answered >= self.study_next_milestone:
            self.study_next_milestone += 30
            return True
        return False

    def study_progress(self) -> tuple[int, int]:
        """Returns (total_answered_this_session, next_milestone_target) for the counter."""
        return self.study_answered, self.study_next_milestone

    def context_label(self) -> str:
        """Human-readable "CEFR · Book · Lektion" path for the current context,
        shown on the review pages so the learner always knows what they are
        practicing. Missing parts are simply omitted."""
        parts: list[str] = []
        lvl = (getattr(self.state, "level", "") or "").upper().strip()
        if lvl:
            parts.append(lvl)
        book = (getattr(self.state, "book_slug", "") or "").strip()
        if book:
            parts.append(" ".join(w.capitalize() for w in book.replace("-", "_").split("_")))
        n = int(getattr(self.state, "lektion_number", 0) or 0)
        if n:
            parts.append(f"Lektion {n}")
        return "  ·  ".join(parts)

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
                rows = conn.execute(
                    "SELECT v.id FROM vocab v LEFT JOIN vocab_states s ON s.vocab_id=v.id "
                    "WHERE v.deck_id=? AND COALESCE(s.suspended,0)=0 "
                    "AND (s.buried_until IS NULL OR s.buried_until<=?)", (deck_id, int(time.time()))
                ).fetchall()

            return [int(r["id"]) for r in rows if r and r["id"] is not None]
        except Exception:
            return []

    def _all_grammar_ids_for_deck(self, deck_id: int) -> list[int]:
        try:
            with self.repo._conn() as conn:
                rows = conn.execute(
                    "SELECT g.id FROM grammar g LEFT JOIN grammar_states s ON s.grammar_id=g.id "
                    "WHERE g.deck_id=? AND COALESCE(s.suspended,0)=0 "
                    "AND (s.buried_until IS NULL OR s.buried_until<=?)", (deck_id, int(time.time()))
                ).fetchall()

            return [int(r["id"]) for r in rows if r and r["id"] is not None]
        except Exception:
            return []

    def _all_sentence_ids_for_deck(self, deck_id: int) -> list[int]:
        try:
            with self.repo._conn() as conn:
                rows = conn.execute(
                    "SELECT t.id FROM sentences t LEFT JOIN sentence_states s ON s.sentence_id=t.id "
                    "WHERE t.deck_id=? AND COALESCE(s.suspended,0)=0 "
                    "AND (s.buried_until IS NULL OR s.buried_until<=?)", (deck_id, int(time.time()))
                ).fetchall()

            return [int(r["id"]) for r in rows if r and r["id"] is not None]
        except Exception:
            return []

    def _all_listening_ids_for_deck(self, deck_id: int) -> list[int]:
        try:
            with self.repo._conn() as conn:
                rows = conn.execute(
                    "SELECT l.id FROM listening l LEFT JOIN listening_states s ON s.listening_id=l.id "
                    "WHERE l.deck_id=? AND COALESCE(s.suspended,0)=0 "
                    "AND (s.buried_until IS NULL OR s.buried_until<=?)", (deck_id, int(time.time()))
                ).fetchall()

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

        Recall-engine contract (see core/priority.py and core/fsrs.py):
        - We score the FULL deck with the always-on recall priority (FSRS
          retrievability + weakness signals + coverage). The ML model only
          augments the ordering once trained -- it is never a gate, so weak or
          forgotten items are targeted from the very first review.
        - Selection takes the highest-priority items first, so the items you
          are most likely to forget can NEVER be randomly dropped from a
          session (the old picker shuffled and truncated the due queue).
        - A coverage quota guarantees a steady trickle of never-seen items so
          new material is always introduced.

        Queue order: next_* use self._queue.pop(), so the END of the queue is
        shown first. rank_*_ids returns LOW priority first / HIGH priority
        last, so the highest-priority item is popped first.
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

        specs = {
            "vocab": (self._all_vocab_ids_for_deck, "vocab", "vocab_states", "vocab_id",
                      getattr(self.ml, "rank_vocab_ids", None)),
            "grammar": (self._all_grammar_ids_for_deck, "grammar", "grammar_states", "grammar_id",
                        getattr(self.ml, "rank_grammar_ids", None)),
            "sentences": (self._all_sentence_ids_for_deck, "sentences", "sentence_states", "sentence_id",
                          getattr(self.ml, "rank_sentence_ids", None)),
            "listening": (self._all_listening_ids_for_deck, "listening", "listening_states", "listening_id",
                          getattr(self.ml, "rank_listening_ids", None)),
        }

        spec = specs.get(objective)
        if spec is None:
            self._queue = []
            return False

        full_fn, table, state_table, fk, rank_fn = spec

        full = _unique_preserve_order(full_fn(deck_id))
        if not full:
            self._queue = []
            return False

        unseen = self._unseen_ids_for_deck(deck_id, table, state_table, fk)

        # Always rank the full deck with the recall priority (ML-augmented when
        # trained). Fall back to a shuffle only if ranking is unavailable.
        ranked: list[int] = []
        use_ml = bool(getattr(self, "enable_ml_ranking", True) and getattr(self, "ml", None))
        if use_ml and callable(rank_fn):
            try:
                ranked = _unique_preserve_order(
                    rank_fn(list(full), level=getattr(self.state, "level", None))
                )
            except Exception:
                ranked = []

        if not ranked:
            ranked = list(full)
            self.rng.shuffle(ranked)

        self._queue = self._assemble_queue(
            full_ids=full, unseen_ids=unseen, ranked_ids=ranked, limit=limit
        )
        return bool(self._queue)

    # -----------------------------------------------------------------
    # Selection assembly
    # -----------------------------------------------------------------
    def _unseen_ids_for_deck(self, deck_id: int, table: str, state_table: str, fk: str) -> list[int]:
        """Items in the deck that have never been reviewed (no state row)."""
        try:
            with self.repo._conn() as conn:
                rows = conn.execute(
                    f"""
                    SELECT t.id
                    FROM {table} t
                    LEFT JOIN {state_table} s ON s.{fk} = t.id
                    WHERE t.deck_id = ? AND s.id IS NULL
                    """,
                    (deck_id,),
                ).fetchall()
            return [int(r["id"]) for r in rows if r and r["id"] is not None]
        except Exception:
            return []

    def _coverage_target(self, limit: int) -> int:
        try:
            frac = float(getattr(self, "unseen_coverage_fraction", 0.3) or 0.0)
        except Exception:
            frac = 0.3
        frac = max(0.0, min(1.0, frac))
        target = max(1, int(round(limit * frac))) if frac > 0 else 0
        return min(target, self._new_item_limit(limit))

    def _new_item_limit(self, limit: int) -> int:
        """Maximum never-reviewed cards allowed in one assembled queue."""
        configured = getattr(getattr(self, "plan", None), "new_limit", None)
        if configured is None:
            return max(0, int(limit))
        try:
            return max(0, min(int(limit), int(configured)))
        except (TypeError, ValueError, OverflowError):
            return max(0, int(limit))

    def _enforce_new_item_limit(
        self,
        selected: list[int],
        ranked: list[int],
        unseen_set: set[int],
        limit: int,
    ) -> list[int]:
        """Replace excess unseen cards with the best available reviewed ones.

        A deck containing fewer reviewed cards may yield a shorter queue. That
        is preferable to silently violating the learner's explicit new-card
        maximum, especially when it is set to zero.
        """
        cap = self._new_item_limit(limit)
        selected = _unique_preserve_order(selected)
        excess = sum(item in unseen_set for item in selected) - cap
        if excess <= 0:
            return selected

        # `selected` and `ranked` are low -> high priority. Remove only the
        # lowest-priority excess new cards, retaining urgent new material.
        selected_unseen = [item for item in selected if item in unseen_set]
        remove = set(selected_unseen[:excess])
        kept = [item for item in selected if item not in remove]
        kept_set = set(kept)
        replacements = [
            item
            for item in reversed(ranked)
            if item not in unseen_set and item not in kept_set
        ][:excess]

        rank_position = {item: index for index, item in enumerate(ranked)}
        return sorted(
            kept + replacements,
            key=lambda item: rank_position.get(item, -1),
        )

    def _assemble_queue(
        self,
        *,
        full_ids: list[int],
        unseen_ids: list[int],
        ranked_ids: list[int],
        limit: int,
    ) -> list[int]:
        """
        Turn a low->high priority ranking of the full deck into a session queue
        of at most `limit`, prioritizing the most urgent items while enforcing
        both the configured new-card maximum and the bounded coverage target.
        """
        full_ids = _unique_preserve_order(full_ids)
        ranked = _unique_preserve_order(ranked_ids)
        unseen_set = set(_unique_preserve_order(unseen_ids))

        # Make sure every deck item appears in the ranking (missing -> lowest).
        ranked_set = set(ranked)
        missing = [i for i in full_ids if i not in ranked_set]
        ranked = missing + ranked

        if len(ranked) <= limit:
            selected = list(ranked)
        else:
            selected = list(ranked[-limit:])  # top `limit`, low->high priority

            if unseen_set:
                sel_set = set(selected)
                in_sel_unseen = [i for i in selected if i in unseen_set]
                quota = min(self._coverage_target(limit), len(unseen_set))
                if len(in_sel_unseen) < quota:
                    need = quota - len(in_sel_unseen)
                    # Highest-priority unseen items not already selected.
                    unseen_not_sel = [
                        i for i in reversed(ranked) if i in unseen_set and i not in sel_set
                    ]
                    to_add = unseen_not_sel[:need]
                    if to_add:
                        # Evict the lowest-priority SEEN items to make room
                        # (never evict an at-risk seen item for coverage).
                        seen_in_sel = [i for i in selected if i not in unseen_set]
                        evict = set(seen_in_sel[: len(to_add)])
                        selected = [i for i in selected if i not in evict]
                        selected = to_add + selected  # coverage shown after urgent items

        selected = self._enforce_new_item_limit(
            selected, ranked, unseen_set, limit
        )
        selected = self._maybe_explore(selected, ranked, limit)
        # Exploration may promote an unseen card, so enforce the hard maximum
        # once more on the final queue rather than treating it as a soft hint.
        selected = self._enforce_new_item_limit(
            selected, ranked, unseen_set, limit
        )
        return _unique_preserve_order(selected)

    def _maybe_explore(self, selected: list[int], ranked: list[int], limit: int) -> list[int]:
        """Occasionally promote one non-selected item to avoid starving an item
        whose priority sits just below the cut (epsilon-greedy)."""
        try:
            eps = float(getattr(self, "ml_exploration_eps", 0.12) or 0.0)
        except Exception:
            eps = 0.12
        eps = max(0.0, min(1.0, eps))

        if eps <= 0 or len(ranked) <= limit or not selected:
            return selected
        try:
            if self.rng.random() >= eps:
                return selected
            sel_set = set(selected)
            candidates = [i for i in ranked if i not in sel_set]
            if not candidates:
                return selected
            pick = self.rng.choice(candidates)
            out = list(selected)
            # Replace the lowest-priority SELECTED item. `ranked` is low->high
            # priority, so that's the selected item appearing earliest in it.
            # Computing it (rather than assuming index 0) avoids evicting a
            # high-priority unseen coverage item that a top-up prepended.
            rank_pos = {item: idx for idx, item in enumerate(ranked)}
            lowest_idx = min(range(len(out)), key=lambda j: rank_pos.get(out[j], -1))
            out[lowest_idx] = pick
            return out
        except Exception:
            return selected

    # -----------------------------------------------------------------
    # Unified next item API
    # -----------------------------------------------------------------
    def next_item(self):
        obj = _norm_objective(self.state.objective)

        if obj == "grammar":
            return self.next_grammar_item()

        if obj == "sentences":
            return self.next_sentence_item()

        if obj == "listening":
            return self.next_listening_item()

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
        # Semantic meaning match (offline embedding model) — understands that
        # "work" == "to work" but "eight" != "eighty".
        strict = bool(
            getattr(getattr(getattr(self, "settings", None), "value", None), "strict_answers", False)
        )
        meaning_ok = (
            _answer_matches(typed_meaning, accepted)
            if strict
            else get_matcher().matches(_norm(typed_meaning), accepted)
        )
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

    # -----------------------------------------------------------------
    # Rating-button interval preview + one-deep undo
    # -----------------------------------------------------------------
    def rating_interval_labels(self, state) -> dict:
        """For each rating 0-3, the interval FSRS would schedule from `state`
        (e.g. {2: '9d'}). schedule_next is pure (no persistence), so this is a
        safe forward-looking preview shown on the rating buttons."""
        now = int(time.time())
        out: dict = {}
        for r in (0, 1, 2, 3):
            try:
                s2 = schedule_next(state, r, now=now)
                out[r] = _fmt_interval(int(getattr(s2, "due_at", now)) - now)
            except Exception:
                out[r] = ""
        return out

    def vocab_interval_labels(self, item) -> dict:
        state = self.repo.get_state(item.id)
        if state is None:
            state = VocabState(
                vocab_id=item.id,
                ease=2.5,
                interval_days=0.0,
                reps=0,
                lapses=0,
                due_at=int(time.time()),
                last_review_at=None,
            )
        return self.rating_interval_labels(state)

    def grammar_interval_labels(self, item) -> dict:
        state = self.repo.get_grammar_state(item.id)
        if state is None:
            state = GrammarState(
                grammar_id=item.id,
                ease=2.5,
                interval_days=0.0,
                reps=0,
                lapses=0,
                due_at=int(time.time()),
                last_review_at=None,
            )
        return self.rating_interval_labels(state)

    def sentence_interval_labels(self, item) -> dict:
        state = self.repo.get_sentence_state(item.id)
        if state is None:
            state = SentenceState(
                sentence_id=item.id,
                ease=2.5,
                interval_days=0.0,
                reps=0,
                lapses=0,
                due_at=int(time.time()),
                last_review_at=None,
            )
        return self.rating_interval_labels(state)

    def listening_interval_labels(self, item) -> dict:
        state = self.repo.get_listening_state(item.id)
        if state is None:
            state = ListeningState(
                listening_id=item.id,
                ease=2.5,
                interval_days=0.0,
                reps=0,
                lapses=0,
                due_at=int(time.time()),
                last_review_at=None,
            )
        return self.rating_interval_labels(state)

    def can_undo(self) -> bool:
        return getattr(self, "_undo", None) is not None

    def undo_last(self, requeue_current=None):
        """Reverse the most recent submission (one-deep): restore the pre-review
        FSRS state and delete the logged review row, then re-queue the undone item
        so it is served NEXT (and the card currently on screen, if passed via
        requeue_current, right after it). Returns the undone item or None."""
        snap = getattr(self, "_undo", None)
        if not snap:
            return None
        obj = snap.get("objective")
        prev = snap.get("prev_state")
        iid = snap.get("item_id")
        logged = bool(snap.get("logged"))
        state_was_missing = bool(snap.get("state_was_missing"))
        try:
            with _repo_transaction(self.repo):
                if obj == "vocab":
                    if logged:
                        self.repo.delete_last_review(iid)
                    if state_was_missing:
                        self.repo.delete_state(iid)
                    else:
                        self.repo.update_state(prev)
                elif obj == "grammar":
                    if logged:
                        self.repo.delete_last_grammar_review(iid)
                    if state_was_missing:
                        self.repo.delete_grammar_state(iid)
                    else:
                        self.repo.update_grammar_state(prev)
                elif obj == "sentence":
                    if logged:
                        self.repo.delete_last_sentence_review(iid)
                    if state_was_missing:
                        self.repo.delete_sentence_state(iid)
                    else:
                        self.repo.update_sentence_state(prev)
                elif obj == "listening":
                    if logged:
                        self.repo.delete_last_listening_review(iid)
                    if state_was_missing:
                        self.repo.delete_listening_state(iid)
                    else:
                        self.repo.update_listening_state(prev)
                else:
                    return None
        except Exception:
            return None  # keep the snapshot so the undo can be retried
        study_progress = snap.get("study_progress")
        if isinstance(study_progress, tuple) and len(study_progress) == 2:
            self.study_answered = max(0, int(study_progress[0]))
            self.study_next_milestone = max(30, int(study_progress[1]))
        self._undo = None  # one-deep: consume only after the DB reversal succeeded
        try:
            # Queue pops from the END, so append the current card first and the
            # undone item last -> undone item is served NEXT, current right after.
            if requeue_current is not None:
                self._queue.append(int(requeue_current))
            if iid is not None:
                self._queue.append(int(iid))
        except Exception:
            pass
        return snap.get("item")

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
        accept_override: bool = False,
    ) -> dict:
        res = self.check_vocab_fields(item, typed_meaning, typed_gender, typed_plural)

        # Learner override ("Accept my answer"): they assert their meaning was a
        # valid gloss the key didn't list, so count meaning as correct.
        if accept_override:
            res = dict(res)
            res["meaning_ok"] = True

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

        # A skip is not a real review attempt, so it is NOT logged. That keeps
        # skips out of every "reviewed" count, the activity heatmap, mastery and
        # accuracy — they all read the reviews table. The card is still
        # rescheduled below (Again) so it comes back.
        with _repo_transaction(self.repo):
            st = self.repo.get_state(item.id)
            state_was_missing = st is None
            if st is None:
                st = self.repo.ensure_state(item.id)
            st2 = schedule_next(st, effective_rating)
            if not was_skipped:
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
            self.repo.update_state(st2)
        self._undo = {
            "objective": "vocab",
            "item": item,
            "item_id": item.id,
            "prev_state": st,
            "logged": not was_skipped,
            "state_was_missing": state_was_missing,
            "study_progress": self.study_progress(),
        }

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
        accept_override: bool = False,
    ) -> dict:
        res = self.check_grammar(item, typed_blank)

        # Learner override ("Accept my answer"): count the answer as correct.
        if accept_override:
            res = dict(res)
            res["ok"] = True

        used_help = bool(meaning_tip_used or hint_used or grammar_tip_used)

        effective_rating = _effective_binary_rating(
            ok=bool(res["ok"]),
            user_rating=rating,
            used_help=used_help,
            was_checked=was_checked,
            was_skipped=was_skipped,
        )

        correct = 1 if bool(res["ok"]) else 0

        with _repo_transaction(self.repo):
            st = self.repo.get_grammar_state(item.id)
            state_was_missing = st is None
            if st is None:
                st = self.repo.ensure_grammar_state(item.id)
            st2 = schedule_next(st, effective_rating)
            # Skips are not logged (see submit_vocab) so they never count as reviews.
            if not was_skipped:
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
            self.repo.update_grammar_state(st2)
        self._undo = {
            "objective": "grammar",
            "item": item,
            "item_id": item.id,
            "prev_state": st,
            "logged": not was_skipped,
            "state_was_missing": state_was_missing,
            "study_progress": self.study_progress(),
        }

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
        res = self.check_sentence(item, typed_text)
        language_feedback = classify_german_answer(typed_text, getattr(item, "target_text", "") or "")
        res["error_tags"] = list(language_feedback.tags)
        res["feedback_message"] = language_feedback.message

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

        with _repo_transaction(self.repo):
            st = self.repo.get_sentence_state(item.id)
            state_was_missing = st is None
            if st is None:
                st = self.repo.ensure_sentence_state(item.id)
            st2 = schedule_next(st, effective_rating)
            # Skips are not logged (see submit_vocab) so they never count as reviews.
            if not was_skipped:
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
                    practice_mode="builder",
                    error_tags=",".join(res.get("error_tags") or []) or None,
                )
            self.repo.update_sentence_state(st2)
        self._undo = {
            "objective": "sentence",
            "item": item,
            "item_id": item.id,
            "prev_state": st,
            "logged": not was_skipped,
            "state_was_missing": state_was_missing,
            "study_progress": self.study_progress(),
        }

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
                    level=getattr(self.state, "level", None),
                )
            except Exception:
                pass

        res["effective_rating"] = effective_rating
        return res

    # -----------------------------------------------------------------
    # Listening (multiple choice over a hidden, read-aloud passage)
    # -----------------------------------------------------------------
    def next_listening_item(self) -> Optional[ListeningItem]:
        if not self._queue:
            return None

        lid = self._queue.pop()
        return self.repo.get_listening_by_id(lid)

    def listening_options(self, item: ListeningItem, *, count: int = 4) -> list[str]:
        """Return the shuffled multiple-choice options for a listening item.

        The correct answer is always included; distractors fill the rest. The
        list is reshuffled every call so the same item never shows the same
        A/B/C/D ordering twice.
        """
        answer = (getattr(item, "answer", "") or "").strip()

        seen = {answer.strip().lower()}
        distractors: list[str] = []
        for d in (getattr(item, "distractors", None) or []):
            d = (str(d) or "").strip()
            if not d:
                continue
            k = d.lower()
            if k in seen:
                continue
            seen.add(k)
            distractors.append(d)

        self.rng.shuffle(distractors)
        chosen = distractors[: max(0, int(count) - 1)]

        options = [answer] + chosen
        self.rng.shuffle(options)
        return options

    def check_listening(self, item: ListeningItem, chosen: str) -> dict:
        answer = (getattr(item, "answer", "") or "").strip()
        ok = (str(chosen) or "").strip().lower() == answer.lower()
        return {
            "ok": ok,
            "answer": answer,
            "chosen": chosen,
        }

    def submit_listening(
        self,
        item: ListeningItem,
        chosen: str,
        was_checked: bool,
        was_skipped: bool,
        response_ms: int | None,
        replay_count: int = 0,
        rating: int | None = None,
    ) -> dict:
        res = self.check_listening(item, chosen)

        # The learner may self-rate how the passage felt (Again/Hard/Good/Easy),
        # exactly like the other review tabs. When no manual rating is given we
        # default to Good, so correctness still drives the schedule. A wrong or
        # skipped answer is always capped to Again by _effective_binary_rating.
        user_rating = 2 if rating is None else int(rating)
        effective_rating = _effective_binary_rating(
            ok=bool(res["ok"]),
            user_rating=user_rating,
            used_help=False,
            was_checked=was_checked,
            was_skipped=was_skipped,
        )

        correct = 1 if bool(res["ok"]) else 0

        with _repo_transaction(self.repo):
            st = self.repo.get_listening_state(item.id)
            state_was_missing = st is None
            if st is None:
                st = self.repo.ensure_listening_state(item.id)
            st2 = schedule_next(st, effective_rating)
            # Skips are not logged (see submit_vocab) so they never count as reviews.
            if not was_skipped:
                self.repo.insert_listening_review(
                    listening_id=item.id,
                    chosen=(chosen or None),
                    correct=correct,
                    replay_count=int(replay_count or 0),
                    was_checked=1 if was_checked else 0,
                    was_skipped=1 if was_skipped else 0,
                    rating=effective_rating,
                    response_ms=response_ms,
                )
            self.repo.update_listening_state(st2)
        self._undo = {
            "objective": "listening",
            "item": item,
            "item_id": item.id,
            "prev_state": st,
            "logged": not was_skipped,
            "state_was_missing": state_was_missing,
            "study_progress": self.study_progress(),
        }

        ml = getattr(self, "ml", None)
        if ml is not None and hasattr(ml, "update_listening"):
            try:
                ml.update_listening(
                    item=item,
                    state_before=st,
                    review_result=res,
                    effective_rating=effective_rating,
                    was_checked=was_checked,
                    was_skipped=was_skipped,
                    response_ms=response_ms,
                    level=getattr(self.state, "level", None),
                )
            except Exception:
                pass

        res["effective_rating"] = effective_rating
        return res

    def submit_vocab_production(
        self,
        item: VocabItem,
        typed_german: str,
        *,
        practice_mode: str = "production",
        response_ms: int | None = None,
    ) -> dict:
        """Schedule one isolated German-production or audio-dictation attempt.

        The review remains in the shared event log with a ``practice_mode``
        tag, but only the matching practice lane state advances.  Recognition,
        production, and dictation therefore cannot inflate one another's FSRS
        stability or due dates.
        """
        article = (item.article or "").strip()
        if not article and (item.pos or "").strip().lower() == "noun":
            article = Repo._article_from_gender(item.gender)
        expected = f"{article} {item.word}".strip() if article else item.word
        feedback = classify_german_answer(typed_german, expected)
        # Non-nouns do not need an article. For nouns, accepting the bare word as
        # fully correct would train exactly the gender omission MAHIRA aims to fix.
        rating = 2 if feedback.correct else 0
        with _repo_transaction(self.repo):
            state = self.repo.ensure_vocab_practice_state(item.id, practice_mode)
            lane = state.practice_mode
            self.repo.insert_review(
                vocab_id=item.id,
                typed_meaning=typed_german or None,
                typed_gender=None,
                typed_plural=None,
                meaning_correct=1 if feedback.correct else 0,
                gender_correct=None,
                plural_correct=None,
                tip_used=0,
                gender_tip_used=0,
                was_checked=1,
                was_skipped=0,
                rating=rating,
                response_ms=response_ms,
                practice_mode=lane,
                error_tags=",".join(feedback.tags) or None,
            )
            self.repo.update_vocab_practice_state(schedule_next(state, rating))
        # Lab lanes do not own the recognition undo stack; drop any stale snap
        # so Ctrl+Z cannot restore recognition state while deleting a Lab row.
        self._undo = None
        return {
            "ok": feedback.correct,
            "expected": expected,
            "typed": typed_german,
            "practice_mode": lane,
            "error_tags": list(feedback.tags),
            "message": feedback.message,
            "effective_rating": rating,
        }
