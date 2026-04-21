from __future__ import annotations

import time
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout

from core.session import SessionService
from ui.widgets.grammar_card_widget import GrammarCardWidget
from ui.widgets.special_char_keyboard import SpecialCharKeyboard


class GrammarReviewPage(QWidget):
    go_progress = Signal()

    def __init__(self, session: SessionService):
        super().__init__()
        self.session = session

        self.current_item = None

        self.was_checked = False
        self.was_skipped = False

        self.meaning_tip_used = False
        self.hint_used = False
        self.grammar_tip_used = False

        self.typed_blank = ""
        self.card_started_at: float | None = None

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.title = QLabel("Grammar Review")
        self.title.setStyleSheet("font-size:16px; font-weight:600;")

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

        # ✅ Special character keyboard
        self.special_kbd = SpecialCharKeyboard()
        self.special_kbd.setVisible(False)  # enabled in on_show()

        self.card = GrammarCardWidget()
        self.special_kbd.char_clicked.connect(self.card.insert_special_char)
        self.card.check_clicked.connect(self._on_check)
        self.card.rated.connect(self._on_rated)
        self.card.skipped.connect(self._on_skipped)

        self.card.meaning_tip_clicked.connect(self._on_meaning_tip)
        self.card.hint_clicked.connect(self._on_hint)
        self.card.grammar_tip_clicked.connect(self._on_grammar_tip)

        layout.addLayout(top)
        layout.addWidget(self.special_kbd, 0)
        layout.addWidget(self.card, 1)

    def _on_meaning_tip(self):
        self.meaning_tip_used = True

    def _on_hint(self):
        self.hint_used = True

    def _on_grammar_tip(self):
        self.grammar_tip_used = True

    def _on_skipped(self):
        self.was_skipped = True
        self.was_checked = False
        self.typed_blank = ""

    def on_show(self):
        # ✅ configure keyboard for current language
        lang = getattr(self.session.state, "language_code", "de") or "de"
        self.special_kbd.set_language(lang)

        try:
            deck_id = self.session.active_deck_id()
        except Exception:
            deck_id = None

        if not deck_id:
            self.card.reset_for_next()
            self.card.set_prompt("Select level and grammar deck first.")
            self.card.set_meaning_blurred(None)
            self.card.set_hint_blurred(None, None)
            self.card.set_grammar_tip_blurred(None)
            self.card.lock_after_check()
            return

        if self.session.remaining() == 0:
            self.session.start_new_session()
        self._load_next()

    def _start_session(self):
        ok = self.session.start_new_session()
        if not ok:
            self.card.reset_for_next()
            self.card.set_prompt("Select level and grammar deck first.")
            self.card.lock_after_check()
            return
        self._load_next()

    def _update_counter(self):
        self.counter.setText(f"Remaining: {self.session.remaining()}/{self.session.plan.limit}")

    def _load_next(self):
        self._update_counter()

        self.current_item = self.session.next_grammar_item()

        self.was_checked = False
        self.was_skipped = False
        self.meaning_tip_used = False
        self.hint_used = False
        self.grammar_tip_used = False
        self.typed_blank = ""

        self.card.reset_for_next()

        if not self.current_item:
            self.card.set_prompt("Session finished")
            self.card.set_meaning_blurred(None)
            self.card.set_hint_blurred(None, None)
            self.card.set_grammar_tip_blurred(None)
            self.card.lock_after_check()
            self._update_counter()
            return

        self.card_started_at = time.time()

        item = self.current_item
        self.card.set_prompt(self.session.grammar_prompt_text(item))
        self.card.set_meaning_blurred(item.meaning)
        self.card.set_hint_blurred(item.test_verb, item.tip)
        self.card.set_grammar_tip_blurred(item.grammar_tip)

        self._update_counter()

    def _on_check(self, typed_blank: str):
        if not self.current_item:
            return

        self.was_checked = True
        self.was_skipped = False

        self.typed_blank = typed_blank or ""

        res = self.session.check_grammar(self.current_item, self.typed_blank)
        self.card.set_result(res["ok"], res["expected"], res["typed"])
        self.card.lock_after_check()

    def _on_rated(self, rating: int):
        if not self.current_item:
            return

        response_ms = None if self.card_started_at is None else int((time.time() - self.card_started_at) * 1000)

        self.session.submit_grammar(
            item=self.current_item,
            typed_blank=self.typed_blank,
            rating=rating,
            meaning_tip_used=self.meaning_tip_used,
            hint_used=self.hint_used,
            grammar_tip_used=self.grammar_tip_used,
            was_checked=self.was_checked,
            was_skipped=self.was_skipped,
            response_ms=response_ms,
        )
        self._load_next()
