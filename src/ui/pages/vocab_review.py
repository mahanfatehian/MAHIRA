from __future__ import annotations

import random
import time
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout , QApplication

from core.session import SessionService
from ui.widgets.card_widget import CardWidget, VocabCheckPayload
from ui.widgets.special_char_keyboard import SpecialCharKeyboard


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _gender_norm(s: str) -> str:
    s = _norm(s)
    mapping = {"der": "m", "die": "f", "das": "n"}
    return mapping.get(s, s)



class VocabReviewPage(QWidget):
    go_progress = Signal()

    def __init__(self, session: SessionService):
        super().__init__()
        self.session = session

        self.current_item: Any | None = None

        self.tip_used = False
        self.gender_tip_used = False

        self.was_checked = False
        self.was_skipped = False

        self.typed_meaning = ""
        self.typed_gender = ""
        self.typed_plural = ""

        self.example_de = ""
        self.example_en = None

        self.card_started_at: float | None = None

        # fallback session queue (only used if SessionService lacks next_item/next_vocab/next)
        self._fallback_ids: list[int] = []

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.title = QLabel("Vocab Review")
        self.title.setStyleSheet("font-size:16px; font-weight:700;")

        self.counter = QLabel("")
        self.counter.setStyleSheet("opacity:0.8;")

        btn_start = QPushButton("Start New Session")
        btn_start.clicked.connect(self._start_session)

        btn_progress = QPushButton("Progress")
        btn_progress.clicked.connect(self.go_progress.emit)

        top.addWidget(self.title)
        top.addWidget(self.counter)
        top.addStretch(1)
        top.addWidget(btn_start)
        top.addWidget(btn_progress)

        # ✅ Special character keyboard (DE etc.)
        self.special_kbd = SpecialCharKeyboard()
        self.special_kbd.setVisible(False)  # will be enabled in on_show()

        self.card = CardWidget()
        self.special_kbd.char_clicked.connect(self.card.insert_special_char)
        self.card.check_clicked.connect(self._on_check)
        self.card.rated.connect(self._on_rated)
        self.card.tip_clicked.connect(self._on_tip)
        self.card.gender_tip_clicked.connect(self._on_gender_tip)
        self.card.skipped.connect(self._on_skipped)

        layout.addLayout(top)
        layout.addWidget(self.special_kbd, 0)  # keyboard appears above the card
        layout.addWidget(self.card, 1)

    def _on_tip(self):
        self.tip_used = True

    def _on_gender_tip(self) -> None:
        self.gender_tip_used = True

    def _on_skipped(self) -> None:
        self.was_skipped = True
        self.was_checked = False
        self.typed_meaning = ""
        self.typed_gender = ""
        self.typed_plural = ""

    def _active_deck_id(self) -> int | None:
        if hasattr(self.session, "active_deck_id"):
            try:
                return self.session.active_deck_id()
            except Exception:
                return None

        # fallback: compute from state + repo
        lang = getattr(self.session.state, "language_code", None)
        level = getattr(self.session.state, "level", None)
        obj = getattr(self.session.state, "objective", None) or "vocab"
        if not lang or not level:
            return None
        if hasattr(self.session.repo, "get_deck_id"):
            return self.session.repo.get_deck_id(lang, level, obj)
        return None

    def on_show(self):
        # ✅ configure keyboard for current language
        lang = getattr(self.session.state, "language_code", "de") or "de"
        self.special_kbd.set_language(lang)

        deck_id = self._active_deck_id()

        if not deck_id:
            self.card.reset_for_next()
            self.card.set_prompt("Choose level first")
            self.card.set_helper("Go to Home and select language, level, and objective.")
            self.card.configure_fields(ask_gender=False, ask_plural=False)
            self.card.lock_after_check()
            return

        # If SessionService has its own sessions, use it. Otherwise build fallback ids.
        if hasattr(self.session, "remaining") and callable(self.session.remaining):
            try:
                if self.session.remaining() == 0 and hasattr(self.session, "start_new_session"):
                    self.session.start_new_session()
            except Exception:
                pass
        else:
            self._build_fallback_session(deck_id)

        self._load_next()

    def _start_session(self):
        deck_id = self._active_deck_id()
        if not deck_id:
            self.card.reset_for_next()
            self.card.set_prompt("Choose level first")
            self.card.set_helper("Go to language, level, then objective.")
            self.card.configure_fields(False, False)
            self.card.lock_after_check()
            return

        if hasattr(self.session, "start_new_session"):
            ok = self.session.start_new_session()
            if not ok:
                self._build_fallback_session(deck_id)
        else:
            self._build_fallback_session(deck_id)

        self._load_next()

    def _build_fallback_session(self, deck_id: int) -> None:
        limit = 10
        if hasattr(self.session, "plan") and hasattr(self.session.plan, "limit"):
            try:
                limit = int(self.session.plan.limit)
            except Exception:
                pass

        if hasattr(self.session.repo, "pick_session_vocab_ids"):
            try:
                ids = self.session.repo.pick_session_vocab_ids(deck_id, limit, mode="mixed")
                self._fallback_ids = list(ids)
                return
            except Exception:
                pass

        with self.session.repo._conn() as conn:
            rows = conn.execute("SELECT id FROM vocab WHERE deck_id=?", (deck_id,)).fetchall()
            all_ids = [int(r["id"]) for r in rows]
            random.shuffle(all_ids)
            self._fallback_ids = all_ids[:limit]

    def _update_counter(self):
        if hasattr(self.session, "remaining") and callable(self.session.remaining):
            try:
                lim = getattr(getattr(self.session, "plan", None), "limit", None)
                lim_txt = str(lim) if lim is not None else "?"
                self.counter.setText(f"Remaining: {self.session.remaining()}/{lim_txt}")
                return
            except Exception:
                pass

        self.counter.setText(f"Remaining: {len(self._fallback_ids)}")

    def _next_item_any_api(self):
        for name in ("next_item", "next_vocab", "next"):
            fn = getattr(self.session, name, None)
            if callable(fn):
                return fn()
        return None

    def _load_next(self):
        self._update_counter()

        self.current_item = self._next_item_any_api()
        if self.current_item is None and self._fallback_ids:
            vid = self._fallback_ids.pop(0)
            if hasattr(self.session.repo, "get_vocab_by_id"):
                self.current_item = self.session.repo.get_vocab_by_id(vid)

        self.tip_used = False
        self.gender_tip_used = False
        self.was_checked = False
        self.was_skipped = False

        self.typed_meaning = ""
        self.typed_gender = ""
        self.typed_plural = ""

        self.example_de = ""
        self.example_en = None

        self.card.reset_for_next()

        if not self.current_item:
            self.card.set_prompt("Session finished")
            self.card.set_example_de_visible_en_blurred("", None)
            self.card.set_gender_tip(None)
            self.card.configure_fields(ask_gender=False, ask_plural=False)
            self.card.set_helper("Click Start New Session to practice another set.")
            self.card.lock_after_check()
            self._update_counter()
            return

        self.card_started_at = time.time()

        item = self.current_item

        word = getattr(item, "word", "")

        if hasattr(self.session, "prompt_text"):
            try:
                word = self.session.prompt_text(item)
            except Exception:
                pass

        self.card.set_prompt(word)
        self.card.set_pos(getattr(item, "pos", ""))

        pos = (getattr(item, "pos", "") or "").lower()

        tip_text = getattr(item, "gender_tip", None)
        if pos != "noun":
            tip_text = None

        self.card.set_gender_tip(tip_text)

        ask_gender = pos == "noun" and bool(getattr(item, "gender", None))
        ask_plural = pos == "noun" and bool(getattr(item, "plural", None))

        self.card.configure_fields(
            ask_gender=ask_gender,
            ask_plural=ask_plural,
        )


        if hasattr(self.session.repo, "get_examples"):
            exs = self.session.repo.get_examples(item.id, limit=1)
            if exs:
                self.example_de, self.example_en = exs[0]
        self.card.set_example_de_visible_en_blurred(self.example_de, self.example_en)
        self.card.set_helper("")
        self._update_counter()

    def _check_fields_fallback(self, item, typed_meaning: str, typed_gender: str, typed_plural: str) -> dict:
        

        expected_meaning = getattr(item, "meaning", "") or ""
        meaning_ok = (_norm(typed_meaning) == _norm(expected_meaning)) if expected_meaning else None

        expected_gender = _gender_norm(getattr(item, "gender", "") or "")
        typed_g = _gender_norm(typed_gender or "")
        gender_ok = (typed_g == expected_gender) if expected_gender else None

        expected_plural = _norm(getattr(item, "plural", "") or "")
        typed_p = _norm(typed_plural or "")
        plural_ok = (typed_p == expected_plural) if expected_plural else None

        return {
            "meaning_ok": meaning_ok,
            "expected_meaning": expected_meaning,
            "gender_ok": gender_ok,
            "expected_gender": expected_gender or None,
            "plural_ok": plural_ok,
            "expected_plural": expected_plural or None,
        }

    def _on_check(self, typed_meaning: str, typed_gender: str, typed_plural: str):
        if not self.current_item:
            return

        self.was_checked = True
        self.was_skipped = False

        self.typed_meaning = typed_meaning or ""
        self.typed_gender = typed_gender or ""
        self.typed_plural = typed_plural or ""

        if hasattr(self.session, "check_vocab_fields"):
            try:
                res = self.session.check_vocab_fields(self.current_item, self.typed_meaning, self.typed_gender, self.typed_plural)
            except Exception:
                res = self._check_fields_fallback(self.current_item, self.typed_meaning, self.typed_gender, self.typed_plural)
        else:
            res = self._check_fields_fallback(self.current_item, self.typed_meaning, self.typed_gender, self.typed_plural)


        
        meaning_label = "Meaning"

        payload = VocabCheckPayload(
            meaning_ok=res.get("meaning_ok"),
            expected_meaning=res.get("expected_meaning"),
            typed_meaning=self.typed_meaning,
            gender_ok=res.get("gender_ok"),
            expected_gender=res.get("expected_gender"),
            typed_gender=self.typed_gender,
            plural_ok=res.get("plural_ok"),
            expected_plural=res.get("expected_plural"),
            typed_plural=self.typed_plural,
            meaning_label=meaning_label,
        )

        self.card.apply_check_results(payload)
        self.card.lock_after_check()

    def _on_rated(self, rating: int):
        if not self.current_item:
            return

        response_ms = None if self.card_started_at is None else int((time.time() - self.card_started_at) * 1000)

        if hasattr(self.session, "submit_vocab"):
            try:
                self.session.submit_vocab(
                    item=self.current_item,
                    typed_meaning=self.typed_meaning,
                    typed_gender=self.typed_gender,
                    typed_plural=self.typed_plural,
                    rating=rating,
                    tip_used=self.tip_used,
                    gender_tip_used=self.gender_tip_used,
                    was_checked=self.was_checked,
                    was_skipped=self.was_skipped,
                    response_ms=response_ms,
                )
            except Exception:
                pass


        self._load_next()
