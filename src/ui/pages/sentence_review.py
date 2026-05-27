from __future__ import annotations

import time
from typing import Any

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
from ui.widgets.sentence_builder_widget import SentenceBuilderWidget


class SentenceReviewPage(QWidget):
    """Sentence builder review page."""

    go_progress = Signal()

    def __init__(self, session: SessionService, nav=None) -> None:
        super().__init__()
        self.session = session
        self.nav = nav

        self.current_item: Any = None
        self.tip_used = False
        self.translation_used = False
        self.was_checked = False
        self.was_skipped = False
        self.card_started_at = 0.0

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

        self.page_title = QLabel("Sentence Review")
        self.page_title.setStyleSheet(
            "color:#FFFFFF; font-size:24px; font-weight:950; border:none;"
        )

        self.page_subtitle = QLabel("Interactive language construction")
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

        outer.addStretch(1)

        self.main_shell = QFrame()
        self.main_shell.setObjectName("MainShell")
        self.main_shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        shell_layout = QVBoxLayout(self.main_shell)
        shell_layout.setContentsMargins(18, 18, 18, 18)
        shell_layout.setSpacing(0)

        self.card = SentenceBuilderWidget(accent="#FFB020")
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.card.check_clicked.connect(self._on_check)
        self.card.rated.connect(self._on_rated)
        self.card.tip_clicked.connect(self._on_tip)
        self.card.translation_clicked.connect(self._on_translation)
        self.card.skipped.connect(self._on_skipped)

        shell_layout.addWidget(self.card)

        outer.addWidget(self.main_shell, 1)

        self.empty_card = QFrame()
        self.empty_card.setObjectName("EmptyCard")
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(30, 28, 30, 28)
        empty_layout.setSpacing(8)

        self.empty_title = QLabel("No sentence reviews available.")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet(
            "color:#FFFFFF; font-size:22px; font-weight:950; border:none;"
        )

        self.empty_desc = QLabel("Start learning or import sentence decks.")
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

        outer.addStretch(1)

        self._update_counter()

    def on_show(self) -> None:
        if self.session.remaining() == 0:
            self._start_session()
            return
        self._load_next()

    def _start_session(self) -> None:
        self.session.start_new_session()
        self._load_next()

    def _update_counter(self) -> None:
        remaining = int(self.session.remaining())
        limit = int(getattr(getattr(self.session, "plan", None), "limit", 0) or 0)
        completed = max(0, limit - remaining) if limit > 0 else 0

        if limit > 0:
            shown = min(limit, completed + 1) if remaining > 0 else completed
            self.counter_lbl.setText(f"{shown} / {limit}")
        else:
            self.counter_lbl.setText(f"{completed} / ?")

    def _load_next(self) -> None:
        self._update_counter()
        self.current_item = self.session.next_sentence_item()

        self.tip_used = False
        self.translation_used = False
        self.was_checked = False
        self.was_skipped = False

        self.card.reset_for_next()

        if not self.current_item:
            self.main_shell.hide()
            self.empty_card.show()
            self.card.lock_after_finish("Session finished")
            self._update_counter()
            return

        self.main_shell.show()
        self.empty_card.hide()

        self.card_started_at = time.time()

        words = list(getattr(self.current_item, "words", []) or [])
        self.card.set_item(
            words=words,
            tip=getattr(self.current_item, "tip", None),
            translation=getattr(self.current_item, "translation", None),
        )
        self._update_counter()

    def _on_tip(self) -> None:
        self.tip_used = True

    def _on_translation(self) -> None:
        self.translation_used = True

    def _on_skipped(self) -> None:
        self.was_skipped = True
        self.was_checked = False
        self._on_rated(0)

    def _on_check(self, typed_text: str) -> None:
        if not self.current_item:
            return

        self.was_checked = True
        res = self.session.check_sentence(self.current_item, typed_text)

        details: list[str] = []
        cap_errors = list(getattr(res, "cap_errors", []) or [])
        punct_errors = list(getattr(res, "punct_errors", []) or [])

        if cap_errors:
            details.append("Capitalization needs attention.")
        if punct_errors:
            details.append("Punctuation needs attention.")

        self.card.show_result(
            ok=bool(getattr(res, "ok", False)),
            expected=str(getattr(res, "expected", "") or ""),
            details=" ".join(details),
        )

    def _on_rated(self, rating: int) -> None:
        if not self.current_item:
            return

        typed = self.card.typed_text()
        response_ms = int(max(0.0, time.time() - float(self.card_started_at or time.time())) * 1000)

        self.session.submit_sentence(
            item=self.current_item,
            typed_text=typed,
            rating=int(rating),
            tip_used=bool(self.tip_used),
            translation_used=bool(self.translation_used),
            was_checked=bool(self.was_checked),
            was_skipped=bool(self.was_skipped),
            response_ms=response_ms,
        )

        self._load_next()
