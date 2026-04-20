# src/ui/widgets/grammar_card_widget.py
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsBlurEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class GrammarCardWidget(QWidget):
    """Grammar review card (fill-in-the-blank) themed to match CardWidget (vocab)."""

    check_clicked = Signal(str)  # typed blank
    rated = Signal(int)  # 0..3
    skipped = Signal()

    meaning_tip_clicked = Signal()
    hint_clicked = Signal()
    grammar_tip_clicked = Signal()

    def __init__(self):
        super().__init__()

        # Match Vocab Card theme
        self.setStyleSheet(
            """
            GrammarCardWidget {
                background-color: #141414;
                border-radius: 12px;
                border: 1px solid #2A2A2A;
            }
            QLabel { color: #E6E6E6; }
            """
        )

        self._meaning_blur: QGraphicsBlurEffect | None = None
        self._hint_blur: QGraphicsBlurEffect | None = None
        self._grammar_blur: QGraphicsBlurEffect | None = None

        self._hint_label_raw: str | None = None
        self._hint_detail: str | None = None

        self._setup_ui()
        self._connect()
        self.reset_for_next()

    # ---------------- UI ----------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        self.prompt = QLabel("")
        self.prompt.setWordWrap(True)
        self.prompt.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.prompt.setStyleSheet(
            """
            QLabel {
                font-size: 20px;
                font-weight: 800;
                color: #FFFFFF;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            """
        )

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("QFrame { background-color: #2A2A2A; margin: 4px 0; }")

        # Scroll area prevents vertical squish when tips/feedback are long
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")

        content = QWidget()
        self.scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)

        # Tip blocks
        tips_frame = QFrame()
        tips_frame.setStyleSheet(
            """
            QFrame {
                background-color: #101010;
                border: 1px solid #2A2A2A;
                border-radius: 10px;
                padding: 10px;
            }
            """
        )
        tips_grid = QGridLayout(tips_frame)
        tips_grid.setContentsMargins(10, 10, 10, 10)
        tips_grid.setHorizontalSpacing(10)
        tips_grid.setVerticalSpacing(8)

        label_style = "QLabel { font-weight: 800; color: #B0B0B0; min-width: 90px; font-size: 12px; }"
        box_style = (
            "QLabel {"
            " font-size: 13px;"
            " color: #D0D0D0;"
            " padding: 8px;"
            " background-color: #1D1D1D;"
            " border: 1px solid #2E2E2E;"
            " border-radius: 8px;"
            " line-height: 1.35;"
            "}"
        )

        self.meaning_title = QLabel("Meaning")
        self.meaning_title.setStyleSheet(label_style)
        self.meaning_label = QLabel("")
        self.meaning_label.setWordWrap(True)
        self.meaning_label.setStyleSheet(box_style)
        self.btn_reveal_meaning = QPushButton("Reveal")
        self.btn_reveal_meaning.setFixedWidth(100)
        self.btn_reveal_meaning.setStyleSheet(self._btn_secondary_style())

        self.hint_title = QLabel("Hint")
        self.hint_title.setStyleSheet(label_style)
        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(box_style)
        self.btn_reveal_hint = QPushButton("Reveal")
        self.btn_reveal_hint.setFixedWidth(100)
        self.btn_reveal_hint.setStyleSheet(self._btn_secondary_style())

        self.grammar_tip_title = QLabel("Grammar tip")
        self.grammar_tip_title.setStyleSheet(label_style)
        self.grammar_tip_label = QLabel("")
        self.grammar_tip_label.setWordWrap(True)
        self.grammar_tip_label.setStyleSheet(box_style)
        self.btn_reveal_grammar = QPushButton("Reveal")
        self.btn_reveal_grammar.setFixedWidth(100)
        self.btn_reveal_grammar.setStyleSheet(self._btn_secondary_style())

        tips_grid.addWidget(self.meaning_title, 0, 0)
        tips_grid.addWidget(self.meaning_label, 0, 1)
        tips_grid.addWidget(self.btn_reveal_meaning, 0, 2)

        tips_grid.addWidget(self.hint_title, 1, 0)
        tips_grid.addWidget(self.hint_label, 1, 1)
        tips_grid.addWidget(self.btn_reveal_hint, 1, 2)

        tips_grid.addWidget(self.grammar_tip_title, 2, 0)
        tips_grid.addWidget(self.grammar_tip_label, 2, 1)
        tips_grid.addWidget(self.btn_reveal_grammar, 2, 2)

        # Answer input
        answer_frame = QFrame()
        answer_frame.setStyleSheet(
            """
            QFrame {
                background-color: #101010;
                border: 1px solid #2A2A2A;
                border-radius: 10px;
                padding: 10px;
            }
            """
        )
        row_in = QHBoxLayout(answer_frame)
        row_in.setContentsMargins(10, 10, 10, 10)
        row_in.setSpacing(8)

        self.in_blank = QLineEdit()
        self.in_blank.setPlaceholderText("Type the missing word...")
        self.in_blank.setMinimumHeight(36)
        self.in_blank.setStyleSheet(self._input_style())

        self.btn_check = QPushButton("Check")
        self.btn_check.setMinimumHeight(38)
        self.btn_check.setStyleSheet(self._btn_primary_style())

        self.btn_skip = QPushButton("Skip")
        self.btn_skip.setMinimumHeight(38)
        self.btn_skip.setStyleSheet(self._btn_skip_style())

        row_in.addWidget(self.in_blank, 1)
        row_in.addWidget(self.btn_check)
        row_in.addWidget(self.btn_skip)

        # Feedback
        self.feedback = QLabel("")
        self.feedback.setWordWrap(True)
        self.feedback.setStyleSheet(self._feedback_neutral_style())

        # Rating buttons
        rate_row = QHBoxLayout()
        rate_row.setSpacing(6)
        self.btn_again = QPushButton("Again")
        self.btn_hard = QPushButton("Hard")
        self.btn_good = QPushButton("Good")
        self.btn_easy = QPushButton("Easy")

        self._rating_buttons = [
            (0, self.btn_again),
            (1, self.btn_hard),
            (2, self.btn_good),
            (3, self.btn_easy),
        ]
        for r, b in self._rating_buttons:
            b.setEnabled(False)
            b.setMinimumHeight(36)
            b.setStyleSheet(self._rating_style(r, recommended=False))
            rate_row.addWidget(b)

        layout.addWidget(tips_frame)
        layout.addWidget(answer_frame)
        layout.addWidget(self.feedback)
        layout.addLayout(rate_row)
        layout.addStretch(1)

        root.addWidget(self.prompt)
        root.addWidget(sep)
        root.addWidget(self.scroll, 1)

    def _connect(self) -> None:
        self.btn_check.clicked.connect(self._emit_check)
        self.in_blank.returnPressed.connect(self._emit_check)

        self.btn_skip.clicked.connect(self._emit_skip)

        self.btn_reveal_meaning.clicked.connect(self._reveal_meaning)
        self.btn_reveal_hint.clicked.connect(self._reveal_hint)
        self.btn_reveal_grammar.clicked.connect(self._reveal_grammar)

        self.btn_again.clicked.connect(lambda: self.rated.emit(0))
        self.btn_hard.clicked.connect(lambda: self.rated.emit(1))
        self.btn_good.clicked.connect(lambda: self.rated.emit(2))
        self.btn_easy.clicked.connect(lambda: self.rated.emit(3))

    # ---------------- Styling helpers (aligned to CardWidget) ----------------
    @staticmethod
    def _input_style() -> str:
        return """
            QLineEdit {
                background-color: #1B1B1B;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 8px;
                padding: 8px 10px;
                font-size: 13px;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLineEdit:focus {
                border-color: #4A9EFF;
                background-color: #202020;
            }
            QLineEdit:disabled {
                background-color: #151515;
                color: #8C8C8C;
                border-color: #252525;
            }
        """

    @staticmethod
    def _btn_primary_style() -> str:
        return """
            QPushButton {
                background-color: #1F5F3A;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: 900;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #247248; }
            QPushButton:disabled {
                background-color: #1A1A1A;
                color: #6B6B6B;
                border: 1px solid #2A2A2A;
            }
        """

    @staticmethod
    def _btn_skip_style() -> str:
        return """
            QPushButton {
                background-color: #163A5C;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: 900;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #1B4B78; }
            QPushButton:disabled {
                background-color: #1A1A1A;
                color: #6B6B6B;
                border: 1px solid #2A2A2A;
            }
        """

    @staticmethod
    def _btn_secondary_style() -> str:
        return """
            QPushButton {
                background-color: #1B1B1B;
                color: #E6E6E6;
                border: 1px solid #2E2E2E;
                border-radius: 8px;
                padding: 6px 10px;
                font-weight: 800;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #232323;
                border: 1px solid #3A3A3A;
            }
            QPushButton:disabled {
                background-color: #151515;
                color: #6B6B6B;
                border: 1px solid #252525;
            }
        """

    @staticmethod
    def _feedback_neutral_style() -> str:
        return """
            QLabel {
                font-size: 12px;
                color: #B8B8B8;
                padding: 10px 12px;
                background-color: #101010;
                border-radius: 10px;
                border: 1px solid #2A2A2A;
                line-height: 1.4;
            }
        """

    @staticmethod
    def _rating_style(rating: int, recommended: bool) -> str:
        # Again(0)=Yellow, Hard(1)=Red, Good(2)=Blue, Easy(3)=Green
        palette = {
            0: ("#2B2B14", "#FFD700"),
            1: ("#2B1414", "#FF6B6B"),
            2: ("#14142B", "#6B9FFF"),
            3: ("#142B14", "#66E39A"),
        }
        bg, accent = palette.get(rating, ("#1B1B1B", "#C8C8C8"))

        if recommended:
            return f"""
                QPushButton {{
                    background-color: {QColor(bg).lighter(150).name()};
                    color: #FFFFFF;
                    border: 3px solid {accent};
                    border-radius: 9px;
                    padding: 6px 10px;
                    font-weight: 950;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: {QColor(bg).lighter(160).name()};
                    border: 3px solid #FFFFFF;
                }}
                QPushButton:disabled {{
                    background-color: {bg};
                    color: #6B6B6B;
                    border: 1px solid #2A2A2A;
                }}
            """

        return f"""
            QPushButton {{
                background-color: {bg};
                color: {accent};
                border: 1px solid {QColor(accent).darker(170).name()};
                border-radius: 9px;
                padding: 6px 10px;
                font-weight: 900;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border: 1px solid #FFFFFF;
                color: #FFFFFF;
            }}
            QPushButton:disabled {{
                background-color: #151515;
                color: #6B6B6B;
                border: 1px solid #252525;
            }}
        """

    # ---------------- public API ----------------
    def reset_for_next(self) -> None:
        self.in_blank.setEnabled(True)
        self.in_blank.clear()
        self.in_blank.setFocus()

        self.btn_check.setEnabled(True)
        self.btn_skip.setEnabled(True)

        for _, b in self._rating_buttons:
            b.setEnabled(False)

        self.feedback.setText("")
        self.feedback.setStyleSheet(self._feedback_neutral_style())

        # reset meaning
        self.meaning_label.setText("")
        self.meaning_label.setGraphicsEffect(None)
        self._meaning_blur = None
        self.btn_reveal_meaning.setEnabled(False)
        self.btn_reveal_meaning.setVisible(True)

        # reset hint
        self.hint_label.setText("")
        self.hint_label.setGraphicsEffect(None)
        self._hint_blur = None
        self._hint_label_raw = None
        self._hint_detail = None
        self.btn_reveal_hint.setEnabled(False)
        self.btn_reveal_hint.setVisible(True)

        # reset grammar tip
        self.grammar_tip_label.setText("")
        self.grammar_tip_label.setGraphicsEffect(None)
        self._grammar_blur = None
        self.btn_reveal_grammar.setEnabled(False)
        self.btn_reveal_grammar.setVisible(True)

    def set_prompt(self, text: str) -> None:
        self.prompt.setText(text)

    def set_meaning_blurred(self, meaning: str | None) -> None:
        m = (meaning or "").strip()
        if not m:
            self.meaning_label.setText("No meaning available")
            self.btn_reveal_meaning.setEnabled(False)
            self.btn_reveal_meaning.setVisible(False)
            return

        self.meaning_label.setText(m)
        self._meaning_blur = QGraphicsBlurEffect()
        self._meaning_blur.setBlurRadius(6.0)
        self.meaning_label.setGraphicsEffect(self._meaning_blur)
        self.btn_reveal_meaning.setEnabled(True)
        self.btn_reveal_meaning.setVisible(True)

    def set_hint_blurred(self, hint_label: str | None, hint_detail: str | None) -> None:
        hl = (hint_label or "").strip()
        hd = (hint_detail or "").strip()
        self._hint_label_raw = hl or None
        self._hint_detail = hd or None

        if not self._hint_label_raw:
            self.hint_label.setText("No hint available")
            self.btn_reveal_hint.setEnabled(False)
            self.btn_reveal_hint.setVisible(False)
            return

        self.hint_label.setText(self._hint_label_raw)
        self._hint_blur = QGraphicsBlurEffect()
        self._hint_blur.setBlurRadius(6.0)
        self.hint_label.setGraphicsEffect(self._hint_blur)
        self.btn_reveal_hint.setEnabled(True)
        self.btn_reveal_hint.setVisible(True)

    def set_grammar_tip_blurred(self, tip: str | None) -> None:
        t = (tip or "").strip()
        if not t:
            self.grammar_tip_label.setText("No grammar tip available")
            self.btn_reveal_grammar.setEnabled(False)
            self.btn_reveal_grammar.setVisible(False)
            return

        self.grammar_tip_label.setText(t)
        self._grammar_blur = QGraphicsBlurEffect()
        self._grammar_blur.setBlurRadius(6.0)
        self.grammar_tip_label.setGraphicsEffect(self._grammar_blur)
        self.btn_reveal_grammar.setEnabled(True)
        self.btn_reveal_grammar.setVisible(True)

    def lock_after_check(self) -> None:
        self.in_blank.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.btn_skip.setEnabled(False)

        for _, b in self._rating_buttons:
            b.setEnabled(True)

    def set_result(self, ok: bool, expected: str, typed: str) -> None:
        if ok:
            self.feedback.setStyleSheet(
                """
                QLabel {
                    font-size: 12px;
                    padding: 10px 12px;
                    background-color: #0E1A12;
                    border-radius: 10px;
                    border: 1px solid #2A2A2A;
                    border-left: 4px solid #66E39A;
                    color: #E6E6E6;
                    line-height: 1.4;
                }
                """
            )
            self.feedback.setText(f"Correct.\n\nYour answer: {typed}")
        else:
            self.feedback.setStyleSheet(
                """
                QLabel {
                    font-size: 12px;
                    padding: 10px 12px;
                    background-color: #1A0E0E;
                    border-radius: 10px;
                    border: 1px solid #2A2A2A;
                    border-left: 4px solid #FF6B6B;
                    color: #E6E6E6;
                    line-height: 1.4;
                }
                """
            )
            self.feedback.setText(f"Incorrect.\n\nYour answer: {typed}\nCorrect answer: {expected}")

    # ---------------- internal ----------------
    def _emit_check(self) -> None:
        self.check_clicked.emit(self.in_blank.text().strip())

    def _emit_skip(self) -> None:
        self.skipped.emit()
        self.rated.emit(0)

    def _reveal_meaning(self) -> None:
        if self._meaning_blur:
            self.meaning_label.setGraphicsEffect(None)
            self._meaning_blur = None
            self.btn_reveal_meaning.setEnabled(False)
            self.meaning_tip_clicked.emit()

    def _reveal_hint(self) -> None:
        if self._hint_blur:
            self.hint_label.setGraphicsEffect(None)
            self._hint_blur = None
            self.btn_reveal_hint.setEnabled(False)

            # once revealed, show extra detail if exists
            if self._hint_label_raw and self._hint_detail:
                self.hint_label.setText(f"{self._hint_label_raw} — {self._hint_detail}")

            self.hint_clicked.emit()

    def _reveal_grammar(self) -> None:
        if self._grammar_blur:
            self.grammar_tip_label.setGraphicsEffect(None)
            self._grammar_blur = None
            self.btn_reveal_grammar.setEnabled(False)
            self.grammar_tip_clicked.emit()
