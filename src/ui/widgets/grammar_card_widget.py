from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsBlurEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class GrammarCardWidget(QWidget):
    check_clicked = Signal(str)
    rated = Signal(int)
    skipped = Signal()
    meaning_tip_clicked = Signal()
    hint_clicked = Signal()
    grammar_tip_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._meaning_blur: QGraphicsBlurEffect | None = None
        self._hint_blur: QGraphicsBlurEffect | None = None
        self._grammar_blur: QGraphicsBlurEffect | None = None
        self._hint_label_raw: str | None = None
        self._hint_detail: str | None = None
        self._recommended_rating: int | None = None

        self.setObjectName("GrammarCardWidget")
        self.setStyleSheet("GrammarCardWidget { background-color: transparent; border: none; }")

        self._setup_ui()
        self._connect()
        self.reset_for_next()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 14, 16, 14)

        # ===== Prompt card (compact - matches vocab word card) =====
        prompt_frame = QFrame()
        prompt_frame.setObjectName("PromptCard")
        prompt_frame.setStyleSheet(
            "QFrame#PromptCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 16px; }"
        )
        prompt_layout = QHBoxLayout(prompt_frame)
        prompt_layout.setContentsMargins(18, 14, 18, 14)
        prompt_layout.setSpacing(14)

        self.prompt = QLabel(" ")
        self.prompt.setWordWrap(True)
        self.prompt.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.prompt.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size: 24px; font-weight: 950; border:none; background:transparent; line-height:1.3; }"
        )
        prompt_layout.addWidget(self.prompt, 1)
        root.addWidget(prompt_frame)

        # ===== Hints/Tips section =====
        hints_frame = QFrame()
        hints_frame.setObjectName("HintsCard")
        hints_frame.setStyleSheet(
            "QFrame#HintsCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 16px; }"
        )
        hints_layout = QVBoxLayout(hints_frame)
        hints_layout.setContentsMargins(16, 12, 16, 12)
        hints_layout.setSpacing(10)

        # Meaning row
        meaning_row = QHBoxLayout()
        meaning_row.setSpacing(10)
        meaning_label = QLabel("Meaning")
        meaning_label.setStyleSheet(
            "QLabel { color:#B0B0B0; font-size:12px; font-weight:900; min-width:84px; background:transparent; border:none; }"
        )
        meaning_row.addWidget(meaning_label)
        self.meaning_label = QLabel(" ")
        self.meaning_label.setWordWrap(True)
        self.meaning_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.meaning_label.setStyleSheet(
            "QLabel { color:#E6E6E6; font-size:13px; padding:8px 12px; background-color:#1A1A1A; border:1px solid #2D2D2D; border-radius:10px; line-height:1.35; }"
        )
        meaning_row.addWidget(self.meaning_label, 1)
        self.btn_reveal_meaning = QPushButton("Reveal")
        self.btn_reveal_meaning.setFixedWidth(90)
        self.btn_reveal_meaning.setStyleSheet(self._reveal_btn_style())
        meaning_row.addWidget(self.btn_reveal_meaning)
        hints_layout.addLayout(meaning_row)

        # Hint row
        hint_row = QHBoxLayout()
        hint_row.setSpacing(10)
        hint_label = QLabel("Hint")
        hint_label.setStyleSheet(
            "QLabel { color:#B0B0B0; font-size:12px; font-weight:900; min-width:84px; background:transparent; border:none; }"
        )
        hint_row.addWidget(hint_label)
        self.hint_label = QLabel(" ")
        self.hint_label.setWordWrap(True)
        self.hint_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.hint_label.setStyleSheet(
            "QLabel { color:#E6E6E6; font-size:13px; padding:8px 12px; background-color:#1A1A1A; border:1px solid #2D2D2D; border-radius:10px; line-height:1.35; }"
        )
        hint_row.addWidget(self.hint_label, 1)
        self.btn_reveal_hint = QPushButton("Reveal")
        self.btn_reveal_hint.setFixedWidth(90)
        self.btn_reveal_hint.setStyleSheet(self._reveal_btn_style())
        hint_row.addWidget(self.btn_reveal_hint)
        hints_layout.addLayout(hint_row)

        # Grammar tip row
        gt_row = QHBoxLayout()
        gt_row.setSpacing(10)
        gt_label = QLabel("Grammar tip")
        gt_label.setStyleSheet(
            "QLabel { color:#B0B0B0; font-size:12px; font-weight:900; min-width:84px; background:transparent; border:none; }"
        )
        gt_row.addWidget(gt_label)
        self.grammar_tip_label = QLabel(" ")
        self.grammar_tip_label.setWordWrap(True)
        self.grammar_tip_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.grammar_tip_label.setStyleSheet(
            "QLabel { color:#E6E6E6; font-size:13px; padding:8px 12px; background-color:#1A1A1A; border:1px solid #2D2D2D; border-radius:10px; line-height:1.35; }"
        )
        gt_row.addWidget(self.grammar_tip_label, 1)
        self.btn_reveal_grammar = QPushButton("Reveal")
        self.btn_reveal_grammar.setFixedWidth(90)
        self.btn_reveal_grammar.setStyleSheet(self._reveal_btn_style())
        gt_row.addWidget(self.btn_reveal_grammar)
        hints_layout.addLayout(gt_row)

        root.addWidget(hints_frame)

        # ===== Answer input section =====
        input_frame = QFrame()
        input_frame.setObjectName("InputCard")
        input_frame.setStyleSheet(
            "QFrame#InputCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 16px; }"
        )
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(10)

        answer_title = QLabel("Your answer")
        answer_title.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:13px; font-weight:900; background:transparent; border:none; }"
        )
        input_layout.addWidget(answer_title)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.in_blank = QLineEdit()
        self.in_blank.setPlaceholderText("Type the missing word...")
        self.in_blank.setMinimumHeight(40)
        self.in_blank.setStyleSheet(
            "QLineEdit { background-color: #1B1B1B; color: #FFFFFF; border: 1px solid #2E2E2E; border-radius: 10px; padding: 9px 12px; font-size: 13px; }"
            "QLineEdit:focus { border: 1px solid #4A9EFF; background-color: #202020; }"
            "QLineEdit:disabled { background-color: #151515; color: #8C8C8C; border: 1px solid #252525; }"
        )
        input_row.addWidget(self.in_blank, 1)

        self.btn_check = QPushButton("Check")
        self.btn_check.setMinimumHeight(40)
        self.btn_check.setStyleSheet(
            "QPushButton { background-color: #244B36; color: #F4FFF7; border: 1px solid #4CAF50; border-radius: 16px; padding: 10px 16px; font-weight: 900; font-size: 13px; min-height: 40px; }"
            "QPushButton:hover { background-color: #2B5B41; border: 1px solid #7AE582; }"
            "QPushButton:pressed { background-color: #214734; }"
            "QPushButton:disabled { background-color: #1A1A1A; color: #6B6B6B; border: 1px solid #252525; }"
        )
        input_row.addWidget(self.btn_check)

        self.btn_skip = QPushButton("Skip")
        self.btn_skip.setMinimumHeight(40)
        self.btn_skip.setStyleSheet(
            "QPushButton { background-color: #163A5C; color: #FFFFFF; border: 1px solid #24537D; border-radius: 16px; padding: 10px 16px; font-weight: 900; font-size: 13px; min-height: 40px; }"
            "QPushButton:hover { background-color: #1B4B78; border: 1px solid #FFFFFF; }"
            "QPushButton:pressed { background-color: #123050; }"
            "QPushButton:disabled { background-color: #1A1A1A; color: #6B6B6B; border: 1px solid #252525; }"
        )
        input_row.addWidget(self.btn_skip)
        input_layout.addLayout(input_row)

        root.addWidget(input_frame)

        # ===== Feedback label =====
        self.feedback = QLabel(" ")
        self.feedback.setWordWrap(True)
        self.feedback.setVisible(False)
        self.feedback.setStyleSheet(
            "QLabel { color: #E6E6E6; font-size: 13px; padding: 12px 16px; background-color: #141414; border: 1px solid #2A2A2A; border-radius: 14px; line-height: 1.4; }"
        )
        root.addWidget(self.feedback)

        # ===== Rating section =====
        rating_frame = QFrame()
        rating_frame.setObjectName("RatingCard")
        rating_frame.setStyleSheet(
            "QFrame#RatingCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 16px; }"
        )
        rating_layout = QVBoxLayout(rating_frame)
        rating_layout.setContentsMargins(16, 10, 16, 10)
        rating_layout.setSpacing(8)

        rating_title = QLabel("How did that feel?")
        rating_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rating_title.setStyleSheet(
            "QLabel { color:#B0B0B0; font-size:11px; font-weight:800; background:transparent; border:none; }"
        )
        rating_layout.addWidget(rating_title)

        rating_row = QHBoxLayout()
        rating_row.setSpacing(8)

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
            b.setMinimumHeight(38)
            b.setEnabled(False)
            b.setStyleSheet(self._rating_style(r, recommended=False))
            rating_row.addWidget(b)
        rating_layout.addLayout(rating_row)
        root.addWidget(rating_frame)

    def _reveal_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #1B1B1B;
                color: #E6E6E6;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 7px 10px;
                font-weight: 850;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #232323; border: 1px solid #FFFFFF; }
            QPushButton:disabled { background-color: #151515; color: #6B6B6B; border: 1px solid #252525; }
        """

    def _rating_style(self, rating: int, recommended: bool = False) -> str:
        colors = {
            0: ("#5A2A2A", "#FF6B6B"),
            1: ("#5A4A1A", "#FFD166"),
            2: ("#1A3A2A", "#66E39A"),
            3: ("#1A2A4A", "#6B9FFF"),
        }
        bg, accent = colors.get(rating, ("#1B1B1B", "#9E9E9E"))
        if recommended:
            return f"""
                QPushButton {{
                    background-color: {QColor(bg).lighter(150).name()};
                    color: #FFFFFF;
                    border: 3px solid {accent};
                    border-radius: 12px;
                    padding: 8px 12px;
                    font-weight: 950;
                    font-size: 12px;
                }}
                QPushButton:hover {{ background-color: {QColor(bg).lighter(160).name()}; border: 3px solid #FFFFFF; }}
                QPushButton:disabled {{ background-color: {bg}; color: #6B6B6B; border: 1px solid #252525; }}
            """
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {accent};
                border: 1px solid {QColor(accent).darker(170).name()};
                border-radius: 12px;
                padding: 8px 12px;
                font-weight: 900;
                font-size: 12px;
            }}
            QPushButton:hover {{ border: 1px solid #FFFFFF; color: #FFFFFF; }}
            QPushButton:disabled {{ background-color: #151515; color: #6B6B6B; border: 1px solid #252525; }}
        """

    def set_prompt(self, text: str) -> None:
        self.prompt.setText(text or " ")

    def set_meaning_blurred(self, text: str | None) -> None:
        text = (text or " ").strip()
        if not text:
            self.meaning_label.setText("No meaning available")
            self.meaning_label.setGraphicsEffect(None)
            self._meaning_blur = None
            self.btn_reveal_meaning.setEnabled(False)
            self.btn_reveal_meaning.setVisible(False)
            return
        self.meaning_label.setText(text)
        self._meaning_blur = QGraphicsBlurEffect()
        self._meaning_blur.setBlurRadius(6.0)
        self.meaning_label.setGraphicsEffect(self._meaning_blur)
        self.btn_reveal_meaning.setEnabled(True)
        self.btn_reveal_meaning.setVisible(True)

    def set_hint_blurred(self, verb: str | None, tip: str | None) -> None:
        self._hint_label_raw = (verb or " ").strip() or None
        self._hint_detail = (tip or " ").strip() or None
        display = self._hint_label_raw or " "
        if self._hint_detail:
            display = f"{self._hint_label_raw} — {self._hint_detail}"
        if not self._hint_label_raw and not self._hint_detail:
            self.hint_label.setText("No hint available")
            self.hint_label.setGraphicsEffect(None)
            self._hint_blur = None
            self.btn_reveal_hint.setEnabled(False)
            self.btn_reveal_hint.setVisible(False)
            return
        self.hint_label.setText(display)
        self._hint_blur = QGraphicsBlurEffect()
        self._hint_blur.setBlurRadius(6.0)
        self.hint_label.setGraphicsEffect(self._hint_blur)
        self.btn_reveal_hint.setEnabled(True)
        self.btn_reveal_hint.setVisible(True)

    def set_grammar_tip_blurred(self, text: str | None) -> None:
        text = (text or " ").strip()
        if not text:
            self.grammar_tip_label.setText("No grammar tip available")
            self.grammar_tip_label.setGraphicsEffect(None)
            self._grammar_blur = None
            self.btn_reveal_grammar.setEnabled(False)
            self.btn_reveal_grammar.setVisible(False)
            return
        self.grammar_tip_label.setText(text)
        self._grammar_blur = QGraphicsBlurEffect()
        self._grammar_blur.setBlurRadius(6.0)
        self.grammar_tip_label.setGraphicsEffect(self._grammar_blur)
        self.btn_reveal_grammar.setEnabled(True)
        self.btn_reveal_grammar.setVisible(True)

    def set_result(self, ok: bool, expected: str, typed: str) -> None:
        self.feedback.setVisible(True)
        if ok:
            self.feedback.setStyleSheet(
                "QLabel { color: #E6E6E6; font-size: 13px; padding: 12px 16px; background-color: #0E1A12; border-radius: 14px; border: 1px solid #252525; border-left: 4px solid #66E39A; line-height: 1.4; }"
            )
            self.feedback.setText(f"Correct!\n\nYour answer: {typed}")
        else:
            self.feedback.setStyleSheet(
                "QLabel { color: #E6E6E6; font-size: 13px; padding: 12px 16px; background-color: #1A0E0E; border-radius: 14px; border: 1px solid #252525; border-left: 4px solid #FF6B6B; line-height: 1.4; }"
            )
            self.feedback.setText(f"Incorrect.\n\nYour answer: {typed}\nCorrect answer: {expected}")

    def lock_after_check(self) -> None:
        self.in_blank.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.btn_skip.setEnabled(False)
        for r, b in self._rating_buttons:
            b.setEnabled(True)

    def reset_for_next(self) -> None:
        self._recommended_rating = None
        self.feedback.setVisible(False)
        self.set_prompt(" ")
        self.set_meaning_blurred(None)
        self.set_hint_blurred(None, None)
        self.set_grammar_tip_blurred(None)
        self.in_blank.setEnabled(True)
        self.in_blank.clear()
        self.in_blank.setFocus()
        self.btn_check.setEnabled(True)
        self.btn_skip.setEnabled(True)
        for r, b in self._rating_buttons:
            b.setEnabled(False)
            b.setStyleSheet(self._rating_style(r, recommended=False))

    def insert_special_char(self, ch: str) -> None:
        if self.in_blank and self.in_blank.isEnabled():
            self.in_blank.insert(ch)
            self.in_blank.setFocus()

    def _connect(self) -> None:
        self.btn_check.clicked.connect(self._emit_check)
        self.in_blank.returnPressed.connect(self._emit_check)
        self.btn_skip.clicked.connect(self._emit_skip)
        self.btn_again.clicked.connect(lambda: self.rated.emit(0))
        self.btn_hard.clicked.connect(lambda: self.rated.emit(1))
        self.btn_good.clicked.connect(lambda: self.rated.emit(2))
        self.btn_easy.clicked.connect(lambda: self.rated.emit(3))
        self.btn_reveal_meaning.clicked.connect(self._reveal_meaning)
        self.btn_reveal_hint.clicked.connect(self._reveal_hint)
        self.btn_reveal_grammar.clicked.connect(self._reveal_grammar)

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
            if self._hint_label_raw and self._hint_detail:
                self.hint_label.setText(f"{self._hint_label_raw} — {self._hint_detail}")
            self.hint_clicked.emit()

    def _reveal_grammar(self) -> None:
        if self._grammar_blur:
            self.grammar_tip_label.setGraphicsEffect(None)
            self._grammar_blur = None
            self.btn_reveal_grammar.setEnabled(False)
            self.grammar_tip_clicked.emit()