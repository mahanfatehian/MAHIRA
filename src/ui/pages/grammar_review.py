from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.session import SessionService
from ui.widgets.grammar_card_widget import GrammarCardWidget
from ui.widgets.special_char_keyboard import SpecialCharKeyboard


class GrammarReviewPage(QWidget):
    go_progress = Signal()

    def __init__(self, session: SessionService, nav=None) -> None:
        super().__init__()
        self.session = session
        self.nav = nav

        self.current_item = None

        self.was_checked = False
        self.was_skipped = False

        self.meaning_tip_used = False
        self.hint_used = False
        self.grammar_tip_used = False

        self.typed_blank = ""
        self.card_started_at: float | None = None

        self.setObjectName("SentenceReviewPage")
        self.setStyleSheet(
            """
            QWidget#SentenceReviewPage {
                background-color: #0F0F10;
            }

            QLabel {
                color: #E6E6E6;
            }

            QFrame#TopBarCard, QFrame#MainShell, QFrame#EmptyCard {
                background-color: #141414;
                border: 1px solid #2A2A2A;
                border-radius: 14px;
            }

            QPushButton {
                background-color: #1B1B1B;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 800;
            }

            QPushButton:hover {
                border: 1px solid #FFFFFF;
                background-color: #232323;
            }

            QPushButton:pressed {
                background-color: #2B2B2B;
            }
            """
        )

        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        top_bar = QFrame()
        top_bar.setObjectName("TopBarCard")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(18, 14, 18, 14)
        top_bar_layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        self.page_title = QLabel("Grammar Review")
        self.page_title.setStyleSheet(
            "color:#FFFFFF; font-size:24px; font-weight:950; border:none;"
        )

        self.page_subtitle = QLabel("Targeted grammar recall")
        self.page_subtitle.setStyleSheet(
            "color:#9A9A9A; font-size:12px; font-weight:700; border:none;"
        )

        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)

        top_bar_layout.addLayout(title_col)
        top_bar_layout.addStretch(1)

        self.counter_lbl = QLabel("0 / 0")
        self.counter_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.counter_lbl.setMinimumWidth(70)
        self.counter_lbl.setStyleSheet(
            """
            color:#FFFFFF;
            font-size:13px;
            font-weight:900;
            border:none;
            background-color:#101010;
            border:1px solid #2A2A2A;
            border-radius:10px;
            padding:8px 12px;
            """
        )

        self.start_btn = QPushButton("Start")
        self.stats_btn = QPushButton("Stats")

        self.start_btn.clicked.connect(self._start_session)
        self.stats_btn.clicked.connect(self.go_progress.emit)

        top_bar_layout.addWidget(self.counter_lbl)
        top_bar_layout.addWidget(self.start_btn)
        top_bar_layout.addWidget(self.stats_btn)

        outer.addWidget(top_bar)

        self.main_shell = QFrame()
        self.main_shell.setObjectName("MainShell")
        self.main_shell.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        shell_layout = QVBoxLayout(self.main_shell)
        shell_layout.setContentsMargins(18, 18, 18, 18)
        shell_layout.setSpacing(12)

        self.special_kbd = SpecialCharKeyboard()
        self.special_kbd.setVisible(False)

        self.card = GrammarCardWidget()
        self.card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.special_kbd.char_clicked.connect(self.card.insert_special_char)
        self.card.check_clicked.connect(self._on_check)
        self.card.rated.connect(self._on_rated)
        self.card.skipped.connect(self._on_skipped)

        self.card.meaning_tip_clicked.connect(self._on_meaning_tip)
        self.card.hint_clicked.connect(self._on_hint)
        self.card.grammar_tip_clicked.connect(self._on_grammar_tip)

        shell_layout.addWidget(self.special_kbd, 0)
        shell_layout.addWidget(self.card, 1)

        outer.addWidget(self.main_shell, 1)

        self.empty_card = QFrame()
        self.empty_card.setObjectName("EmptyCard")
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(30, 28, 30, 28)
        empty_layout.setSpacing(8)

        self.empty_title = QLabel("No grammar reviews available.")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet(
            "color:#FFFFFF; font-size:22px; font-weight:950; border:none;"
        )

        self.empty_desc = QLabel("Choose a level and start a grammar session.")
        self.empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_desc.setStyleSheet(
            "color:#9A9A9A; font-size:13px; font-weight:700; border:none;"
        )

        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_desc)
        empty_layout.addStretch(1)

        self.empty_card.hide()
        outer.addWidget(self.empty_card, 1)

        self._update_counter()

    def _show_main(self) -> None:
        self.main_shell.show()
        self.empty_card.hide()

    def _show_empty(self, title: str, desc: str) -> None:
        self.empty_title.setText(title)
        self.empty_desc.setText(desc)
        self.main_shell.hide()
        self.empty_card.show()

    def _on_meaning_tip(self) -> None:
        self.meaning_tip_used = True

    def _on_hint(self) -> None:
        self.hint_used = True

    def _on_grammar_tip(self) -> None:
        self.grammar_tip_used = True

    def _on_skipped(self) -> None:
        self.was_skipped = True
        self.was_checked = False
        self.typed_blank = ""

    def on_show(self) -> None:
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

            self._show_empty(
                "No grammar reviews available.",
                "Choose language, level, and grammar deck first.",
            )
            self._update_counter()
            return

        self._show_main()

        if self.session.remaining() == 0:
            self.session.start_new_session()

        self._load_next()

    def _start_session(self) -> None:
        ok = self.session.start_new_session()
        if not ok:
            self.card.reset_for_next()
            self.card.set_prompt("Select level and grammar deck first.")
            self.card.set_meaning_blurred(None)
            self.card.set_hint_blurred(None, None)
            self.card.set_grammar_tip_blurred(None)
            self.card.lock_after_check()

            self._show_empty(
                "No grammar reviews available.",
                "Choose language, level, and grammar deck first.",
            )
            self._update_counter()
            return

        self._show_main()
        self._load_next()

    def _update_counter(self) -> None:
        try:
            remaining = int(self.session.remaining())
            limit = int(getattr(getattr(self.session, "plan", None), "limit", 0) or 0)
            completed = max(0, limit - remaining) if limit > 0 else 0

            if limit > 0:
                shown = min(limit, completed + 1) if remaining > 0 else completed
                self.counter_lbl.setText(f"{shown} / {limit}")
            else:
                self.counter_lbl.setText(f"{completed} / ?")
        except Exception:
            self.counter_lbl.setText("0 / 0")

    def _load_next(self) -> None:
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

            self._show_empty(
                "No grammar reviews available.",
                "Start a new session to practice another set.",
            )
            self._update_counter()
            return

        self._show_main()
        self.card_started_at = time.time()

        item = self.current_item
        self.card.set_prompt(self.session.grammar_prompt_text(item))
        self.card.set_meaning_blurred(item.meaning)
        self.card.set_hint_blurred(item.test_verb, item.tip)
        self.card.set_grammar_tip_blurred(item.grammar_tip)

        self._update_counter()

    def _on_check(self, typed_blank: str) -> None:
        if not self.current_item:
            return

        self.was_checked = True
        self.was_skipped = False

        self.typed_blank = typed_blank or ""

        res = self.session.check_grammar(self.current_item, self.typed_blank)
        self.card.set_result(res["ok"], res["expected"], res["typed"])
        self.card.lock_after_check()

    def _on_rated(self, rating: int) -> None:
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
