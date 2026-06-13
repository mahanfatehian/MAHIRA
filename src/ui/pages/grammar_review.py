from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
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

        self.current_item: Any | None = None
        self.was_checked = False
        self.was_skipped = False
        self.meaning_tip_used = False
        self.hint_used = False
        self.grammar_tip_used = False
        self.typed_blank = ""
        self.card_started_at: float | None = None

        self.setObjectName("GrammarReviewPage")
        self.setStyleSheet("GrammarReviewPage { background-color: #0E0E0E; }")

        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)

        top_bar = QFrame()
        top_bar.setObjectName("TopBarCard")
        top_bar.setStyleSheet(
            "QFrame#TopBarCard { "
            "background-color: #141414; "
            "border: 1px solid #2A2A2A; "
            "border-radius: 14px; "
            "}"
        )

        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 12, 16, 12)
        top_bar_layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)

        self.page_title = QLabel("Grammar Review")
        self.page_title.setStyleSheet(
            "QLabel { "
            "color:#FFFFFF; "
            "font-size:20px; "
            "font-weight:950; "
            "border:none; "
            "background:transparent; "
            "}"
        )

        self.page_subtitle = QLabel("Focused fill-the-blank practice")
        self.page_subtitle.setStyleSheet(
            "QLabel { "
            "color:#9A9A9A; "
            "font-size:11px; "
            "font-weight:700; "
            "border:none; "
            "background:transparent; "
            "}"
        )

        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)

        top_bar_layout.addLayout(title_col)
        top_bar_layout.addStretch(1)

        self.counter_lbl = QLabel("0 / 0")
        self.counter_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.counter_lbl.setMinimumWidth(60)
        self.counter_lbl.setStyleSheet(
            "QLabel { "
            "color:#FFFFFF; "
            "font-size:12px; "
            "font-weight:800; "
            "background:#1A1A1A; "
            "border:1px solid #2E2E2E; "
            "border-radius:8px; "
            "padding:6px 10px; "
            "}"
        )

        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedWidth(60)
        self.start_btn.setStyleSheet(
            "QPushButton { "
            "background-color: #244B36; "
            "color: #F4FFF7; "
            "border: 1px solid #4CAF50; "
            "border-radius: 10px; "
            "padding: 8px; "
            "font-weight: 900; "
            "font-size: 12px; "
            "}"
            "QPushButton:hover { background-color: #2B5B41; border: 1px solid #7AE582; }"
        )

        self.stats_btn = QPushButton("Stats")
        self.stats_btn.setFixedWidth(60)
        self.stats_btn.setStyleSheet(
            "QPushButton { "
            "background-color: #163A5C; "
            "color: #FFFFFF; "
            "border: 1px solid #24537D; "
            "border-radius: 10px; "
            "padding: 8px; "
            "font-weight: 900; "
            "font-size: 12px; "
            "}"
            "QPushButton:hover { background-color: #1B4B78; border: 1px solid #FFFFFF; }"
        )

        self.start_btn.clicked.connect(self._start_session)
        self.stats_btn.clicked.connect(self.go_progress.emit)

        top_bar_layout.addWidget(self.counter_lbl)
        top_bar_layout.addWidget(self.start_btn)
        top_bar_layout.addWidget(self.stats_btn)

        outer.addWidget(top_bar)

        # Milestone celebration banner (hidden by default)
        self.milestone_bar = QFrame()
        self.milestone_bar.setObjectName("MilestoneBar")
        self.milestone_bar.setFixedHeight(48)
        self.milestone_bar.setStyleSheet(
            "QFrame#MilestoneBar { background: #1A3A20; border: 1px solid #4CAF50; border-radius: 12px; }"
        )
        ms_layout = QHBoxLayout(self.milestone_bar)
        ms_layout.setContentsMargins(16, 6, 12, 6)
        ms_layout.setSpacing(8)
        self.milestone_lbl = QLabel("Milestone reached!")
        self.milestone_lbl.setStyleSheet(
            "QLabel { color: #7AE582; font-size: 13px; font-weight: 900; border: none; background: transparent; }"
        )
        ms_dismiss = QPushButton("×")
        ms_dismiss.setFixedSize(26, 26)
        ms_dismiss.setStyleSheet(
            "QPushButton { background: #2A2A2A; color: #888; border: 1px solid #3A3A3A; border-radius: 6px; font-size: 14px; font-weight: 700; }"
            "QPushButton:hover { color: #FFF; border-color: #666; }"
        )
        ms_dismiss.clicked.connect(self._dismiss_milestone_banner)
        ms_layout.addWidget(self.milestone_lbl, 1)
        ms_layout.addWidget(ms_dismiss)
        self.milestone_bar.hide()
        outer.addWidget(self.milestone_bar)

        self.special_kbd = SpecialCharKeyboard()
        self.special_kbd.setVisible(False)
        outer.addWidget(self.special_kbd)

        self.main_shell = QFrame()
        self.main_shell.setObjectName("MainShell")
        self.main_shell.setStyleSheet(
            "QFrame#MainShell { background: transparent; border: none; }"
        )
        self.main_shell.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        shell_layout = QVBoxLayout(self.main_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(10)

        self.card = GrammarCardWidget()
        self.card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self.special_kbd.char_clicked.connect(self.card.insert_special_char)
        self.card.check_clicked.connect(self._on_check)
        self.card.rated.connect(self._on_rated)
        self.card.skipped.connect(self._on_skipped)
        self.card.meaning_tip_clicked.connect(self._on_meaning_tip)
        self.card.hint_clicked.connect(self._on_hint)
        self.card.grammar_tip_clicked.connect(self._on_grammar_tip)

        shell_layout.addWidget(self.card)
        outer.addWidget(self.main_shell)

        self.empty_card = QFrame()
        self.empty_card.setObjectName("EmptyCard")
        self.empty_card.setMinimumHeight(420)
        self.empty_card.setStyleSheet(
            "QFrame#EmptyCard { "
            "background-color: #141414; "
            "border: 1px solid #2A2A2A; "
            "border-radius: 14px; "
            "}"
        )

        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)

        self.empty_title = QLabel("No grammar reviews available.")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet(
            "QLabel { "
            "color:#FFFFFF; "
            "font-size:18px; "
            "font-weight:950; "
            "border:none; "
            "background:transparent; "
            "}"
        )

        self.empty_desc = QLabel("Choose a level and start a grammar session.")
        self.empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_desc.setStyleSheet(
            "QLabel { "
            "color:#9A9A9A; "
            "font-size:12px; "
            "font-weight:700; "
            "border:none; "
            "background:transparent; "
            "}"
        )

        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_desc)
        empty_layout.addStretch(1)

        self.empty_card.hide()
        outer.addWidget(self.empty_card)

        outer.addStretch(1)
        self._update_counter()

    def _show_main(self) -> None:
        self.main_shell.show()
        self.empty_card.hide()

    def _show_empty(self, title: str, desc: str) -> None:
        self.empty_title.setText(title)
        self.empty_desc.setText(desc)
        self.main_shell.hide()
        self.empty_card.show()

    def _reset_tracking(self) -> None:
        self.was_checked = False
        self.was_skipped = False
        self.meaning_tip_used = False
        self.hint_used = False
        self.grammar_tip_used = False
        self.typed_blank = ""

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
        self.special_kbd.set_language("de")

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
            self.card.lock_for_empty_state()

            self._show_empty(
                "No grammar reviews available.",
                "Choose a level, book, and grammar deck first.",
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
            self.card.lock_for_empty_state()

            self._show_empty(
                "No grammar reviews available.",
                "Choose a level, book, and grammar deck first.",
            )
            self._update_counter()
            return

        self._show_main()
        self._load_next()

    def _update_counter(self) -> None:
        try:
            answered, milestone = self.session.study_progress()
            self.counter_lbl.setText(f"{answered} / {milestone}")
        except Exception:
            self.counter_lbl.setText("0 / 30")

    def _show_milestone_banner(self) -> None:
        answered = getattr(self.session, "study_answered", 0)
        self.milestone_lbl.setText(
            f"Milestone! {answered} items reviewed this session. Keep going!"
        )
        self.counter_lbl.setStyleSheet(
            "QLabel { color:#FFD700; font-size:12px; font-weight:800; "
            "background:#2A2000; border:1px solid #FFD700; border-radius:8px; padding:6px 10px; }"
        )
        self.milestone_bar.show()
        QTimer.singleShot(6000, self._dismiss_milestone_banner)
        self._update_counter()

    def _dismiss_milestone_banner(self) -> None:
        self.milestone_bar.hide()
        self.counter_lbl.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:12px; font-weight:800; "
            "background:#1A1A1A; border:1px solid #2E2E2E; border-radius:8px; padding:6px 10px; }"
        )

    def _load_next(self) -> None:
        self._update_counter()
        self.current_item = self.session.next_grammar_item()

        self._reset_tracking()
        self.card.reset_for_next()

        if not self.current_item:
            self.card.set_prompt("Session finished")
            self.card.set_meaning_blurred(None)
            self.card.set_hint_blurred(None, None)
            self.card.set_grammar_tip_blurred(None)
            self.card.lock_for_empty_state()

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
        self.card.set_meaning_blurred(getattr(item, "meaning", None))
        self.card.set_hint_blurred(getattr(item, "test_verb", None), getattr(item, "tip", None))
        self.card.set_grammar_tip_blurred(getattr(item, "grammar_tip", None))

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

        response_ms = (
            None
            if self.card_started_at is None
            else int((time.time() - self.card_started_at) * 1000)
        )

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

        milestone_hit = False
        if hasattr(self.session, "record_item_answered"):
            try:
                milestone_hit = bool(self.session.record_item_answered())
            except Exception:
                pass

        self._load_next()

        if milestone_hit:
            self._show_milestone_banner()
