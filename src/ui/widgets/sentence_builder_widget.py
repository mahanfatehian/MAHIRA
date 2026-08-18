from __future__ import annotations

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

from ui.widgets.audio_button import AudioButton
from ui.widgets.flow_layout import FlowLayout


def _btn_secondary() -> str:
    return """
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
    QPushButton:disabled {
        background-color: #101010;
        color: #6B6B6B;
        border: 1px solid #252525;
    }
    """


def _btn_colored(bg: str, fg: str = "#0B0B0B") -> str:
    return f"""
    QPushButton {{
        background-color: {bg};
        color: {fg};
        border: 1px solid #2E2E2E;
        border-radius: 12px;
        padding: 9px 18px;
        font-weight: 900;
    }}
    QPushButton:hover {{
        border: 1px solid #FFFFFF;
    }}
    QPushButton:disabled {{
        background-color: #101010;
        color: #6B6B6B;
        border: 1px solid #252525;
    }}
    """


def _rating_style(rating: int) -> str:
    palette = {
        0: ("#2B2B14", "#FFD700"),
        1: ("#2B1414", "#FF6B6B"),
        2: ("#14142B", "#6B9FFF"),
        3: ("#142B14", "#66E39A"),
    }
    bg, accent = palette.get(rating, ("#1B1B1B", "#FFFFFF"))
    return f"""
    QPushButton {{
        background-color: {bg};
        color: {accent};
        border: 1px solid #2A2A2A;
        border-radius: 10px;
        padding: 7px 12px;
        font-weight: 900;
        font-size: 12px;
    }}
    QPushButton:hover {{
        border: 1px solid {accent};
    }}
    QPushButton:disabled {{
        background-color: #101010;
        color: #6B6B6B;
        border: 1px solid #252525;
    }}
    """


def _chip_style(accent: str, *, used: bool) -> str:
    if used:
        return """
        QPushButton {
            background-color: #101010;
            color: #6E6E6E;
            border: 1px solid #252525;
            border-radius: 18px;
            padding: 10px 16px;
            font-weight: 900;
            font-size: 16px;
            min-height: 42px;
        }
        """
    return f"""
    QPushButton {{
        background-color: #1A1A1A;
        color: #FFFFFF;
        border: 1px solid #2E2E2E;
        border-radius: 18px;
        padding: 10px 16px;
        font-weight: 900;
        font-size: 16px;
        min-height: 42px;
    }}
    QPushButton:hover {{
        background-color: #262626;
        border: 1px solid {accent};
    }}
    QPushButton:pressed {{
        background-color: #303030;
    }}
    """


class SentenceBuilderWidget(QWidget):
    check_clicked = Signal(str)
    rated = Signal(int)
    tip_clicked = Signal()
    translation_clicked = Signal()
    skipped = Signal()
    audio_clicked = Signal()  # hear the correct German sentence (after checking)

    def __init__(self, accent: str = "#FFB020"):
        super().__init__()
        self.accent = accent

        self._words: list[str] = []
        self._selected_tokens: list[str] = []
        self._bank_buttons: list[QPushButton] = []
        self._built_buttons: list[QPushButton] = []
        self._tip_text: str | None = None
        self._translation_text: str | None = None
        self._checked = False
        self._locked = False
        self._result_ok: bool | None = None

        self.setObjectName("SentenceBuilderWidget")
        self.setStyleSheet(
            """
            SentenceBuilderWidget {
                background-color: transparent;
                border: none;
            }
            QLabel {
                color: #E6E6E6;
            }
            """
        )

        self._setup_ui()
        self.reset_for_next()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(12)

        self.header_row = QVBoxLayout()
        self.header_row.setSpacing(3)

        self.title_lbl = QLabel("Build the sentence")
        self.title_lbl.setStyleSheet(
            "color:#FFFFFF; font-size:28px; font-weight:950; border:none;"
        )

        self.subtitle_lbl = QLabel("Tap the words in the correct order")
        self.subtitle_lbl.setStyleSheet(
            "color:#9A9A9A; font-size:14px; font-weight:700; border:none;"
        )

        self.header_row.addWidget(self.title_lbl)
        self.header_row.addWidget(self.subtitle_lbl)
        root.addLayout(self.header_row)

        self.answer_frame = QFrame()
        self.answer_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.answer_frame.setStyleSheet(
            """
            QFrame {
                background-color: #101010;
                border: 1px solid #2E2E2E;
                border-radius: 18px;
            }
            """
        )
        answer_layout = QVBoxLayout(self.answer_frame)
        answer_layout.setContentsMargins(16, 16, 16, 14)
        answer_layout.setSpacing(8)

        top_meta = QHBoxLayout()
        top_meta.setSpacing(8)

        self.answer_hint_lbl = QLabel("Your sentence")
        self.answer_hint_lbl.setStyleSheet(
            "color:#B0B0B0; font-size:12px; font-weight:900; border:none;"
        )

        self.count_lbl = QLabel("0 / 0 words used")
        self.count_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.count_lbl.setStyleSheet(
            "color:#B0B0B0; font-size:12px; font-weight:900; border:none;"
        )

        top_meta.addWidget(self.answer_hint_lbl)
        top_meta.addStretch(1)
        top_meta.addWidget(self.count_lbl)

        answer_layout.addLayout(top_meta)

        self.built_wrap = QWidget()
        self.built_wrap.setStyleSheet("background: transparent; border: none;")
        self.built_flow = FlowLayout(self.built_wrap, margin=0, hspacing=8, vspacing=8)

        answer_layout.addWidget(self.built_wrap, 1)

        self.empty_lbl = QLabel("Tap words below to build the sentence")
        self.empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_lbl.setWordWrap(True)
        self.empty_lbl.setStyleSheet(
            "color:#707070; font-size:15px; font-weight:800; border:none;"
        )
        answer_layout.addWidget(self.empty_lbl)

        root.addWidget(self.answer_frame, 3)

        self.bank_frame = QFrame()
        self.bank_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.bank_frame.setStyleSheet(
            """
            QFrame {
                background-color: #101010;
                border: 1px solid #2A2A2A;
                border-radius: 18px;
            }
            """
        )
        bank_layout = QVBoxLayout(self.bank_frame)
        bank_layout.setContentsMargins(16, 14, 16, 14)
        bank_layout.setSpacing(10)

        bank_title = QLabel("Available words")
        bank_title.setStyleSheet(
            "color:#B0B0B0; font-size:12px; font-weight:900; border:none;"
        )
        bank_layout.addWidget(bank_title)

        self.bank_wrap = QWidget()
        self.bank_wrap.setStyleSheet("background: transparent; border: none;")
        self.bank_flow = FlowLayout(self.bank_wrap, margin=0, hspacing=8, vspacing=8)
        bank_layout.addWidget(self.bank_wrap, 1)

        root.addWidget(self.bank_frame, 3)

        self.reveal_row = QHBoxLayout()
        self.reveal_row.setSpacing(10)

        self.tip_btn = QPushButton("Reveal tip")
        self.tip_btn.setStyleSheet(_btn_secondary())

        self.tr_btn = QPushButton("Reveal translation")
        self.tr_btn.setStyleSheet(_btn_secondary())

        self.reveal_row.addWidget(self.tip_btn)
        self.reveal_row.addWidget(self.tr_btn)
        root.addLayout(self.reveal_row)

        self.tip_panel = QFrame()
        self.tip_panel.setStyleSheet(
            """
            QFrame {
                background-color: #101010;
                border: 1px solid #2A2A2A;
                border-radius: 12px;
            }
            """
        )
        tip_layout = QVBoxLayout(self.tip_panel)
        tip_layout.setContentsMargins(14, 12, 14, 12)
        tip_layout.setSpacing(6)

        tip_title = QLabel("Tip")
        tip_title.setStyleSheet(
            "color:#9A9A9A; font-size:11px; font-weight:900; border:none;"
        )
        self.tip_lbl = QLabel("")
        self.tip_lbl.setWordWrap(True)
        self.tip_lbl.setStyleSheet(
            "color:#E6E6E6; font-size:13px; font-weight:700; border:none;"
        )

        tip_layout.addWidget(tip_title)
        tip_layout.addWidget(self.tip_lbl)
        self.tip_panel.hide()
        root.addWidget(self.tip_panel)

        self.translation_panel = QFrame()
        self.translation_panel.setStyleSheet(
            """
            QFrame {
                background-color: #101010;
                border: 1px solid #2A2A2A;
                border-radius: 12px;
            }
            """
        )
        tr_layout = QVBoxLayout(self.translation_panel)
        tr_layout.setContentsMargins(14, 12, 14, 12)
        tr_layout.setSpacing(6)

        tr_title = QLabel("Translation")
        tr_title.setStyleSheet(
            "color:#9A9A9A; font-size:11px; font-weight:900; border:none;"
        )
        self.translation_lbl = QLabel("")
        self.translation_lbl.setWordWrap(True)
        self.translation_lbl.setStyleSheet(
            "color:#E6E6E6; font-size:13px; font-weight:700; border:none;"
        )

        tr_layout.addWidget(tr_title)
        tr_layout.addWidget(self.translation_lbl)
        self.translation_panel.hide()
        root.addWidget(self.translation_panel)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)

        self.btn_backspace = QPushButton("Undo")
        self.btn_backspace.setStyleSheet(_btn_secondary())

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setStyleSheet(_btn_secondary())

        self.btn_skip = QPushButton("Skip")
        self.btn_skip.setObjectName("ReviewSkipButton")
        self.btn_skip.setAccessibleName("Skip this review card")
        self.btn_skip.setStyleSheet(_btn_secondary())
        from ui.widgets.review_controls import harden_skip_button

        harden_skip_button(self.btn_skip)

        self.btn_check = QPushButton("Check")
        self.btn_check.setObjectName("ReviewCheckButton")
        self.btn_check.setAccessibleName("Check your answer")
        self.btn_check.setStyleSheet(_btn_colored("#1F5F3A", "#FFFFFF"))

        ctrl.addWidget(self.btn_backspace)
        ctrl.addWidget(self.btn_clear)
        ctrl.addStretch(1)
        ctrl.addWidget(self.btn_skip)
        ctrl.addWidget(self.btn_check)
        root.addLayout(ctrl)

        self.feedback_frame = QFrame()
        self.feedback_frame.setStyleSheet(
            """
            QFrame {
                background-color: #101010;
                border: 1px solid #2A2A2A;
                border-radius: 14px;
            }
            """
        )
        feedback_layout = QVBoxLayout(self.feedback_frame)
        feedback_layout.setContentsMargins(14, 12, 14, 12)
        feedback_layout.setSpacing(6)

        self.result_lbl = QLabel("")
        self.result_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_lbl.setWordWrap(True)
        self.result_lbl.setStyleSheet(
            "color:#D0D0D0; font-size:22px; font-weight:950; border:none;"
        )

        self.details_lbl = QLabel("")
        self.details_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_lbl.setWordWrap(True)
        self.details_lbl.setStyleSheet(
            "color:#AFAFAF; font-size:12px; font-weight:700; border:none;"
        )

        self.expected_lbl = QLabel("")
        self.expected_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.expected_lbl.setWordWrap(True)
        self.expected_lbl.setStyleSheet(
            "color:#E6E6E6; font-size:14px; font-weight:800; border:none;"
        )

        feedback_layout.addWidget(self.result_lbl)
        feedback_layout.addWidget(self.details_lbl)
        feedback_layout.addWidget(self.expected_lbl)

        audio_row = QHBoxLayout()
        audio_row.addStretch(1)
        self.audio_btn = AudioButton()
        self.audio_btn.set_available(False)
        audio_row.addWidget(self.audio_btn)
        audio_row.addStretch(1)
        feedback_layout.addLayout(audio_row)

        self.feedback_frame.hide()
        root.addWidget(self.feedback_frame)

        self.rating_frame = QFrame()
        self.rating_frame.setStyleSheet(
            """
            QFrame {
                background-color: #101010;
                border: 1px solid #2A2A2A;
                border-radius: 14px;
            }
            """
        )
        rate_outer = QVBoxLayout(self.rating_frame)
        rate_outer.setContentsMargins(12, 12, 12, 12)
        rate_outer.setSpacing(8)

        self.rate_title = QLabel("How did that feel?")
        self.rate_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rate_title.setStyleSheet(
            "color:#B8B8B8; font-size:12px; font-weight:900; border:none;"
        )

        rate_row = QHBoxLayout()
        rate_row.setSpacing(10)

        self.btn_again = QPushButton("Again")
        self.btn_hard = QPushButton("Hard")
        self.btn_good = QPushButton("Good")
        self.btn_easy = QPushButton("Easy")

        self.btn_again.setStyleSheet(_rating_style(0))
        self.btn_hard.setStyleSheet(_rating_style(1))
        self.btn_good.setStyleSheet(_rating_style(2))
        self.btn_easy.setStyleSheet(_rating_style(3))

        for btn in (self.btn_again, self.btn_hard, self.btn_good, self.btn_easy):
            btn.setMinimumHeight(40)
            btn.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            rate_row.addWidget(btn)

        rate_outer.addWidget(self.rate_title)
        rate_outer.addLayout(rate_row)
        root.addWidget(self.rating_frame)

        self.tip_btn.clicked.connect(self._reveal_tip)
        self.tr_btn.clicked.connect(self._reveal_translation)
        self.btn_backspace.clicked.connect(self._on_backspace)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_skip.clicked.connect(self.skipped.emit)
        self.btn_check.clicked.connect(self._emit_check)
        self.btn_again.clicked.connect(lambda: self.rated.emit(0))
        self.btn_hard.clicked.connect(lambda: self.rated.emit(1))
        self.btn_good.clicked.connect(lambda: self.rated.emit(2))
        self.btn_easy.clicked.connect(lambda: self.rated.emit(3))
        self.audio_btn.clicked.connect(self.audio_clicked.emit)

    _RATING_LABELS = {0: "Again", 1: "Hard", 2: "Good", 3: "Easy"}

    def _rating_button_map(self) -> dict:
        return {0: self.btn_again, 1: self.btn_hard, 2: self.btn_good, 3: self.btn_easy}

    def set_rating_intervals(self, labels: dict | None) -> None:
        """Show the interval each rating would schedule next, e.g. 'Good\\n9d'."""
        labels = labels or {}
        for r, btn in self._rating_button_map().items():
            base = self._RATING_LABELS[r]
            iv = labels.get(r) or labels.get(str(r)) or ""
            btn.setText(f"{base}\n{iv}" if iv else base)

    def clear_rating_intervals(self) -> None:
        for r, btn in self._rating_button_map().items():
            btn.setText(self._RATING_LABELS[r])

    def reset_for_next(self) -> None:
        self._checked = False
        self._locked = False
        self._result_ok = None
        self._words = []
        self._selected_tokens = []
        self._tip_text = None
        self._translation_text = None

        self.tip_lbl.clear()
        self.translation_lbl.clear()
        self.result_lbl.clear()
        self.details_lbl.clear()
        self.expected_lbl.clear()

        self.feedback_frame.hide()
        self.tip_panel.hide()
        self.translation_panel.hide()

        self.audio_btn.reset_state()
        self.audio_btn.set_available(False)

        self.tip_btn.setText("Reveal tip")
        self.tr_btn.setText("Reveal translation")

        self.tip_btn.setEnabled(False)
        self.tr_btn.setEnabled(False)

        self.btn_check.setEnabled(True)
        self.btn_skip.setEnabled(True)
        self.btn_backspace.setEnabled(False)
        self.btn_clear.setEnabled(False)

        self.btn_again.setEnabled(False)
        self.btn_hard.setEnabled(False)
        self.btn_good.setEnabled(False)
        self.btn_easy.setEnabled(False)
        self.clear_rating_intervals()

        self._clear_layout(self.bank_flow)
        self._clear_layout(self.built_flow)

        self._bank_buttons.clear()
        self._built_buttons.clear()

        self.empty_lbl.setText("Tap words below to build the sentence")
        self.empty_lbl.show()
        self._update_count()
        self._refresh_answer_area_style()

    def set_item(self, *, words: list[str], tip: str | None, translation: str | None) -> None:
        self.reset_for_next()

        self._words = list(words or [])
        self._tip_text = tip
        self._translation_text = translation

        self.tip_btn.setEnabled(bool(tip))
        self.tr_btn.setEnabled(bool(translation))

        for word in self._words:
            btn = QPushButton(word)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_chip_style(self.accent, used=False))
            btn.clicked.connect(lambda checked=False, b=btn: self._select_from_bank(b))
            self.bank_flow.addWidget(btn)
            self._bank_buttons.append(btn)

        self._update_count()
        self._refresh_answer_area_style()

    def typed_text(self) -> str:
        return self._join_tokens(self._selected_tokens)

    def show_result(self, ok: bool, expected: str = "", details: str = "") -> None:
        self._checked = True
        self._result_ok = bool(ok)

        if ok:
            self.result_lbl.setText("✓ Perfect")
            self.result_lbl.setStyleSheet(
                "color:#66E39A; font-size:22px; font-weight:950; border:none;"
            )
            self.feedback_frame.setStyleSheet(
                """
                QFrame {
                    background-color: #101010;
                    border: 1px solid #2D6A4F;
                    border-radius: 14px;
                }
                """
            )
        else:
            has_details = bool(details)
            self.result_lbl.setText("⚠ Needs Attention" if has_details else "✗ Incorrect")
            self.result_lbl.setStyleSheet(
                "color:#FFB020; font-size:22px; font-weight:950; border:none;"
                if has_details
                else "color:#FF6B6B; font-size:22px; font-weight:950; border:none;"
            )
            self.feedback_frame.setStyleSheet(
                """
                QFrame {
                    background-color: #101010;
                    border: 1px solid #5A2A2A;
                    border-radius: 14px;
                }
                """
            )

        self.details_lbl.setText(details or "")
        self.expected_lbl.setText(f"Expected: {expected}" if expected else "")
        self.feedback_frame.show()

        self.btn_check.setEnabled(False)
        self.btn_skip.setEnabled(False)

        self.btn_again.setEnabled(True)
        self.btn_hard.setEnabled(True)
        self.btn_good.setEnabled(True)
        self.btn_easy.setEnabled(True)

        # The correct sentence is now on screen — let the learner hear it.
        self.audio_btn.set_available(True)

        self._refresh_answer_area_style()

    def lock_after_finish(self, message: str) -> None:
        self.reset_for_next()
        self._locked = True

        self.result_lbl.setText(message)
        self.result_lbl.setStyleSheet(
            "color:#E6E6E6; font-size:22px; font-weight:950; border:none;"
        )
        self.feedback_frame.show()

        self.empty_lbl.setText("No sentence reviews available.")
        self.empty_lbl.show()
        self.count_lbl.setText("0 / 0 words used")

        self.btn_check.setEnabled(False)
        self.btn_skip.setEnabled(False)
        self.btn_backspace.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.tip_btn.setEnabled(False)
        self.tr_btn.setEnabled(False)

        self.btn_again.setEnabled(False)
        self.btn_hard.setEnabled(False)
        self.btn_good.setEnabled(False)
        self.btn_easy.setEnabled(False)

        self._refresh_answer_area_style()

    def _join_tokens(self, tokens: list[str]) -> str:
        text = " ".join(token.strip() for token in tokens if token is not None).strip()
        text = text.replace(" .", ".")
        text = text.replace(" ,", ",")
        text = text.replace(" !", "!")
        text = text.replace(" ?", "?")
        text = text.replace(" ;", ";")
        text = text.replace(" :", ":")
        return text.strip()

    def _select_from_bank(self, btn: QPushButton) -> None:
        if self._locked or self._checked:
            return

        token = btn.text()
        btn.setVisible(False)
        btn.setEnabled(False)
        btn.setStyleSheet(_chip_style(self.accent, used=True))

        built_btn = QPushButton(token)
        built_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        built_btn.setStyleSheet(self._built_chip_style())
        built_btn.clicked.connect(
            lambda checked=False, b=built_btn: self._remove_built_chip(b)
        )
        self.built_flow.addWidget(built_btn)

        self._built_buttons.append(built_btn)
        self._selected_tokens.append(token)

        self.empty_lbl.setVisible(len(self._selected_tokens) == 0)
        self._update_count()
        self._refresh_answer_area_style()

    def _remove_built_chip(self, built_btn: QPushButton) -> None:
        if self._locked or self._checked:
            return

        idx = self._built_buttons.index(built_btn) if built_btn in self._built_buttons else -1
        if idx < 0:
            return

        token = built_btn.text()

        self._built_buttons.pop(idx)
        if idx < len(self._selected_tokens):
            self._selected_tokens.pop(idx)

        built_btn.setParent(None)
        built_btn.deleteLater()

        self._restore_one_bank_button(token)
        self.empty_lbl.setVisible(len(self._selected_tokens) == 0)
        self._update_count()
        self._refresh_answer_area_style()

    def _restore_one_bank_button(self, token: str) -> None:
        for btn in self._bank_buttons:
            if btn.text() == token and not btn.isVisible():
                btn.setVisible(True)
                btn.setEnabled(True)
                btn.setStyleSheet(_chip_style(self.accent, used=False))
                return

    def _on_backspace(self) -> None:
        if self._locked or self._checked or not self._built_buttons:
            return
        self._remove_built_chip(self._built_buttons[-1])

    def _on_clear(self) -> None:
        if self._locked or self._checked or not self._selected_tokens:
            return

        while self._built_buttons:
            self._remove_built_chip(self._built_buttons[-1])

    def _reveal_tip(self) -> None:
        if not self._tip_text:
            return
        self.tip_panel.show()
        self.tip_lbl.setText(self._tip_text)
        self.tip_btn.setText("Tip revealed")
        self.tip_btn.setEnabled(False)
        self.tip_clicked.emit()

    def _reveal_translation(self) -> None:
        if not self._translation_text:
            return
        self.translation_panel.show()
        self.translation_lbl.setText(self._translation_text)
        self.tr_btn.setText("Translation revealed")
        self.tr_btn.setEnabled(False)
        self.translation_clicked.emit()

    def _emit_check(self) -> None:
        if self._locked or self._checked:
            return
        self.check_clicked.emit(self.typed_text())

    def _built_chip_style(self) -> str:
        return """
        QPushButton {
            background-color: #244B36;
            color: #F4FFF7;
            border: 1px solid #4CAF50;
            border-radius: 18px;
            padding: 10px 16px;
            font-weight: 900;
            font-size: 16px;
            min-height: 42px;
        }
        QPushButton:hover {
            background-color: #2B5B41;
            border: 1px solid #7AE582;
        }
        QPushButton:pressed {
            background-color: #214734;
        }
        """

    def _update_count(self) -> None:
        used = len(self._selected_tokens)
        total = len(self._words)
        self.count_lbl.setText(f"{used} / {total} words used")
        self.btn_backspace.setEnabled((used > 0) and (not self._locked) and (not self._checked))
        self.btn_clear.setEnabled((used > 0) and (not self._locked) and (not self._checked))

    def _refresh_answer_area_style(self) -> None:
        if self._locked:
            border = "#2A2A2A"
            bg = "#101010"
        elif self._checked and self._result_ok is True:
            border = "#2D6A4F"
            bg = "#0F1713"
        elif self._checked and self._result_ok is False:
            border = "#7A4D1D" if self._selected_tokens else "#5A2A2A"
            bg = "#17120D" if self._selected_tokens else "#170F0F"
        else:
            border = "#3A3A3A" if self._selected_tokens else "#2E2E2E"
            bg = "#111111" if self._selected_tokens else "#101010"

        self.answer_frame.setStyleSheet(
            f"""
            QFrame {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 18px;
            }}
            """
        )

    def _clear_layout(self, layout: Any) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue

            widget = item.widget()
            child_layout = item.layout()

            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)
