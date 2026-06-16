from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.redact import mask_hidden


def _card_style(border: str = "#2A2A2A", bg: str = "#141414", radius: int = 16) -> str:
    return (
        "QFrame { "
        f"background-color: {bg}; "
        f"border: 1px solid {border}; "
        f"border-radius: {radius}px; "
        "}"
    )


def _muted_label_style(size: int = 11) -> str:
    return (
        "QLabel { "
        "color:#9A9A9A; "
        f"font-size:{size}px; "
        "font-weight:850; "
        "border:none; "
        "background:transparent; "
        "}"
    )


def _body_label_style(size: int = 13) -> str:
    return (
        "QLabel { "
        "color:#E6E6E6; "
        f"font-size:{size}px; "
        "font-weight:650; "
        "border:none; "
        "background:transparent; "
        "line-height:1.35; "
        "}"
    )


class GrammarCardWidget(QWidget):
    check_clicked = Signal(str)
    rated = Signal(int)
    skipped = Signal()
    meaning_tip_clicked = Signal()
    hint_clicked = Signal()
    grammar_tip_clicked = Signal()
    accepted = Signal()  # "Accept my answer" override

    def __init__(self, parent=None):
        super().__init__(parent)
        # While hidden these hold the REAL text (truthy = still masked); on
        # reveal we swap the masked bullets back to this and clear the slot.
        self._meaning_blur: str | None = None
        self._hint_blur: str | None = None
        self._grammar_blur: str | None = None
        self._hint_label_raw: str | None = None
        self._hint_detail: str | None = None
        self._recommended_rating: int | None = None

        self.setObjectName("GrammarCardWidget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet("GrammarCardWidget { background-color: transparent; border: none; }")

        self._setup_ui()
        self._connect()
        self.reset_for_next()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(0, 0, 0, 0)

        prompt_frame = QFrame()
        prompt_frame.setObjectName("PromptCard")
        prompt_frame.setStyleSheet(_card_style(border="#2A2A2A", bg="#141414", radius=18))
        prompt_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        prompt_layout = QVBoxLayout(prompt_frame)
        prompt_layout.setContentsMargins(18, 16, 18, 16)
        prompt_layout.setSpacing(10)

        prompt_kicker = QLabel("Fill the blank")
        prompt_kicker.setStyleSheet(_muted_label_style())
        prompt_layout.addWidget(prompt_kicker)

        self.prompt = QLabel(" ")
        self.prompt.setWordWrap(True)
        self.prompt.setTextFormat(Qt.TextFormat.RichText)
        self.prompt.setMinimumHeight(70)
        self.prompt.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.prompt.setStyleSheet(
            "QLabel { "
            "color:#FFFFFF; "
            "font-size:21px; "
            "font-weight:950; "
            "border:none; "
            "background:transparent; "
            "line-height:1.25; "
            "}"
        )
        prompt_layout.addWidget(self.prompt)

        root.addWidget(prompt_frame)

        tips_row = QHBoxLayout()
        tips_row.setSpacing(10)

        (
            self.meaning_card,
            self.meaning_label,
            self.btn_reveal_meaning,
        ) = self._make_reveal_card("Meaning")

        (
            self.hint_card,
            self.hint_label,
            self.btn_reveal_hint,
        ) = self._make_reveal_card("Hint")

        (
            self.grammar_tip_card,
            self.grammar_tip_label,
            self.btn_reveal_grammar,
        ) = self._make_reveal_card("Grammar tip")

        tips_row.addWidget(self.meaning_card)
        tips_row.addWidget(self.hint_card)
        tips_row.addWidget(self.grammar_tip_card)

        root.addLayout(tips_row)

        input_frame = QFrame()
        input_frame.setObjectName("InputCard")
        input_frame.setStyleSheet(_card_style(border="#2A2A2A", bg="#141414", radius=18))

        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 14, 16, 14)
        input_layout.setSpacing(10)

        answer_title = QLabel("Your answer")
        answer_title.setStyleSheet(
            "QLabel { "
            "color:#FFFFFF; "
            "font-size:13px; "
            "font-weight:900; "
            "background:transparent; "
            "border:none; "
            "}"
        )
        input_layout.addWidget(answer_title)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.in_blank = QLineEdit()
        self.in_blank.setPlaceholderText("Type the missing word...")
        self.in_blank.setMinimumHeight(42)
        self.in_blank.setStyleSheet(
            "QLineEdit { "
            "background-color: #1B1B1B; "
            "color: #FFFFFF; "
            "border: 1px solid #2E2E2E; "
            "border-radius: 12px; "
            "padding: 9px 12px; "
            "font-size: 14px; "
            "font-weight: 700; "
            "}"
            "QLineEdit:focus { border: 1px solid #FFB020; background-color: #202020; }"
            "QLineEdit:disabled { background-color: #151515; color: #8C8C8C; border: 1px solid #252525; }"
        )
        input_row.addWidget(self.in_blank, 1)

        self.btn_check = QPushButton("Check")
        self.btn_check.setMinimumHeight(42)
        self.btn_check.setStyleSheet(self._primary_btn_style())
        input_row.addWidget(self.btn_check)

        self.btn_skip = QPushButton("Skip")
        self.btn_skip.setMinimumHeight(42)
        self.btn_skip.setStyleSheet(self._secondary_btn_style())
        input_row.addWidget(self.btn_skip)

        input_layout.addLayout(input_row)
        root.addWidget(input_frame)

        self.feedback = QLabel(" ")
        self.feedback.setWordWrap(True)
        self.feedback.setVisible(False)
        self.feedback.setStyleSheet(self._feedback_style(ok=None))
        root.addWidget(self.feedback)

        # "Accept my answer" override — shown only when the answer was wrong.
        self.accept_btn = QPushButton("✓  Accept my answer")
        self.accept_btn.setMinimumHeight(34)
        self.accept_btn.setVisible(False)
        self.accept_btn.setStyleSheet(self._accept_btn_style())
        root.addWidget(self.accept_btn)

        rating_frame = QFrame()
        rating_frame.setObjectName("RatingCard")
        rating_frame.setStyleSheet(_card_style(border="#2A2A2A", bg="#141414", radius=18))

        rating_layout = QVBoxLayout(rating_frame)
        rating_layout.setContentsMargins(16, 12, 16, 12)
        rating_layout.setSpacing(9)

        rating_title = QLabel("How did that feel?")
        rating_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rating_title.setStyleSheet(_muted_label_style())
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

        for rating, button in self._rating_buttons:
            button.setMinimumHeight(40)
            button.setEnabled(False)
            button.setStyleSheet(self._rating_style(rating, recommended=False))
            rating_row.addWidget(button)

        rating_layout.addLayout(rating_row)
        root.addWidget(rating_frame)

    def _make_reveal_card(self, title: str) -> tuple[QFrame, QLabel, QPushButton]:
        frame = QFrame()
        frame.setStyleSheet(_card_style(border="#2A2A2A", bg="#101010", radius=14))
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)

        title_label = QLabel(title)
        title_label.setStyleSheet(_muted_label_style())
        top.addWidget(title_label, 1)

        button = QPushButton("Reveal")
        button.setFixedWidth(74)
        button.setMinimumHeight(28)
        button.setStyleSheet(self._reveal_btn_style())
        top.addWidget(button)

        value = QLabel(" ")
        value.setWordWrap(True)
        value.setMinimumHeight(48)
        value.setStyleSheet(_body_label_style(12))

        layout.addLayout(top)
        layout.addWidget(value)

        return frame, value, button

    def _primary_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #244B36;
                color: #F4FFF7;
                border: 1px solid #4CAF50;
                border-radius: 16px;
                padding: 10px 16px;
                font-weight: 900;
                font-size: 13px;
                min-width: 82px;
            }
            QPushButton:hover { background-color: #2B5B41; border: 1px solid #7AE582; }
            QPushButton:pressed { background-color: #214734; }
            QPushButton:disabled { background-color: #1A1A1A; color: #6B6B6B; border: 1px solid #252525; }
        """

    def _secondary_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #163A5C;
                color: #FFFFFF;
                border: 1px solid #24537D;
                border-radius: 16px;
                padding: 10px 16px;
                font-weight: 900;
                font-size: 13px;
                min-width: 76px;
            }
            QPushButton:hover { background-color: #1B4B78; border: 1px solid #FFFFFF; }
            QPushButton:pressed { background-color: #123050; }
            QPushButton:disabled { background-color: #1A1A1A; color: #6B6B6B; border: 1px solid #252525; }
        """

    def _accept_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #17314A;
                color: #BBD7FF;
                border: 1px solid #2F567E;
                border-radius: 12px;
                padding: 7px 12px;
                font-weight: 900;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #1D3E5E; border: 1px solid #6B9FFF; color: #FFFFFF; }
            QPushButton:pressed { background-color: #15293D; }
        """

    def _reveal_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #1B1B1B;
                color: #E6E6E6;
                border: 1px solid #2E2E2E;
                border-radius: 9px;
                padding: 5px 8px;
                font-weight: 850;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #232323; border: 1px solid #FFB020; color:#FFFFFF; }
            QPushButton:disabled { background-color: #151515; color: #6B6B6B; border: 1px solid #252525; }
        """

    def _feedback_style(self, ok: bool | None) -> str:
        if ok is True:
            bg = "#0E1A12"
            border = "#2D6A4F"
            accent = "#66E39A"
        elif ok is False:
            bg = "#1A0E0E"
            border = "#5A2A2A"
            accent = "#FF6B6B"
        else:
            bg = "#141414"
            border = "#2A2A2A"
            accent = "#FFB020"

        return (
            "QLabel { "
            "color: #E6E6E6; "
            "font-size: 13px; "
            "font-weight: 650; "
            "padding: 12px 16px; "
            f"background-color: {bg}; "
            "border-radius: 14px; "
            f"border: 1px solid {border}; "
            f"border-left: 4px solid {accent}; "
            "line-height: 1.4; "
            "}"
        )

    def _rating_style(self, rating: int, recommended: bool = False) -> str:
        color_map = {
            0: ("#3A1F1F", "#FF6B6B"),
            1: ("#3A2A16", "#FFB020"),
            2: ("#1F3427", "#66E39A"),
            3: ("#17314A", "#6B9FFF"),
        }
        bg, accent = color_map.get(rating, ("#1B1B1B", "#FFFFFF"))

        if recommended:
            return (
                "QPushButton { "
                f"background-color: {bg}; "
                "color: #FFFFFF; "
                f"border: 2px solid {accent}; "
                "border-radius: 14px; "
                "padding: 9px 12px; "
                "font-weight: 950; "
                "font-size: 12px; "
                "}"
                "QPushButton:hover { border: 2px solid #FFFFFF; }"
                "QPushButton:disabled { background-color: #101010; color: #6B6B6B; border: 1px solid #252525; }"
            )

        return (
            "QPushButton { "
            "background-color: #1B1B1B; "
            f"color: {accent}; "
            "border: 1px solid #2E2E2E; "
            "border-radius: 14px; "
            "padding: 9px 12px; "
            "font-weight: 900; "
            "font-size: 12px; "
            "}"
            f"QPushButton:hover {{ background-color: #232323; border: 1px solid {accent}; color: #FFFFFF; }}"
            "QPushButton:disabled { background-color: #101010; color: #6B6B6B; border: 1px solid #252525; }"
        )

    def set_prompt(self, text: str) -> None:
        raw = (text or " ").strip() or " "
        safe = html.escape(raw)
        safe = safe.replace(
            "_____",
            "<span style='color:#FFB020; letter-spacing:1px;'>_____</span>",
            1,
        )
        self.prompt.setText(safe)

    def set_meaning_blurred(self, text: str | None) -> None:
        text = (text or "").strip()
        if not text:
            self.meaning_label.setText("No meaning available")
            self._meaning_blur = None
            self.btn_reveal_meaning.setEnabled(False)
            self.btn_reveal_meaning.setVisible(False)
            return

        self._meaning_blur = text
        self.meaning_label.setText(mask_hidden(text))
        self.btn_reveal_meaning.setText("Reveal")
        self.btn_reveal_meaning.setEnabled(True)
        self.btn_reveal_meaning.setVisible(True)

    def set_hint_blurred(self, verb: str | None, tip: str | None) -> None:
        self._hint_label_raw = (verb or "").strip() or None
        self._hint_detail = (tip or "").strip() or None

        if self._hint_label_raw and self._hint_detail:
            display = f"{self._hint_label_raw} — {self._hint_detail}"
        else:
            display = self._hint_label_raw or self._hint_detail or ""

        if not display:
            self.hint_label.setText("No hint available")
            self._hint_blur = None
            self.btn_reveal_hint.setEnabled(False)
            self.btn_reveal_hint.setVisible(False)
            return

        self._hint_blur = display
        self.hint_label.setText(mask_hidden(display))
        self.btn_reveal_hint.setText("Reveal")
        self.btn_reveal_hint.setEnabled(True)
        self.btn_reveal_hint.setVisible(True)

    def set_grammar_tip_blurred(self, text: str | None) -> None:
        text = (text or "").strip()
        if not text:
            self.grammar_tip_label.setText("No grammar tip available")
            self._grammar_blur = None
            self.btn_reveal_grammar.setEnabled(False)
            self.btn_reveal_grammar.setVisible(False)
            return

        self._grammar_blur = text
        self.grammar_tip_label.setText(mask_hidden(text))
        self.btn_reveal_grammar.setText("Reveal")
        self.btn_reveal_grammar.setEnabled(True)
        self.btn_reveal_grammar.setVisible(True)

    def set_result(self, ok: bool, expected: str, typed: str) -> None:
        self.feedback.setVisible(True)
        self._recommended_rating = 2 if ok else 0

        typed_display = (typed or "").strip() or "—"
        expected_display = (expected or "").strip() or "—"

        if ok:
            self.feedback.setStyleSheet(self._feedback_style(ok=True))
            self.feedback.setText(f"Correct!\n\nYour answer: {typed_display}")
        else:
            self.feedback.setStyleSheet(self._feedback_style(ok=False))
            self.feedback.setText(
                f"Incorrect.\n\nYour answer: {typed_display}\nCorrect answer: {expected_display}"
            )

        self.accept_btn.setVisible(not ok)

        for rating, button in self._rating_buttons:
            button.setStyleSheet(
                self._rating_style(
                    rating,
                    recommended=(rating == self._recommended_rating),
                )
            )

    def mark_accepted(self) -> None:
        """Flip the result to correct after the learner overrides."""
        self._recommended_rating = 2
        self.feedback.setStyleSheet(self._feedback_style(ok=True))
        self.feedback.setText("Accepted ✓  (counted as correct)")
        self.accept_btn.setVisible(False)
        for rating, button in self._rating_buttons:
            button.setStyleSheet(
                self._rating_style(
                    rating,
                    recommended=(rating == self._recommended_rating),
                )
            )

    def lock_after_check(self) -> None:
        self.in_blank.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.btn_skip.setEnabled(False)

        for rating, button in self._rating_buttons:
            button.setEnabled(True)
            button.setStyleSheet(
                self._rating_style(
                    rating,
                    recommended=(rating == self._recommended_rating),
                )
            )

    def lock_for_empty_state(self) -> None:
        self.accept_btn.setVisible(False)
        self.in_blank.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.btn_skip.setEnabled(False)

        for rating, button in self._rating_buttons:
            button.setEnabled(False)
            button.setStyleSheet(self._rating_style(rating, recommended=False))

    _RATING_LABELS = {0: "Again", 1: "Hard", 2: "Good", 3: "Easy"}

    def set_rating_intervals(self, labels: dict | None) -> None:
        """Show the interval each rating would schedule next, e.g. 'Good\\n9d'."""
        labels = labels or {}
        for r, btn in self._rating_buttons:
            base = self._RATING_LABELS.get(r, "")
            iv = labels.get(r) or labels.get(str(r)) or ""
            btn.setText(f"{base}\n{iv}" if iv else base)

    def clear_rating_intervals(self) -> None:
        for r, btn in self._rating_buttons:
            btn.setText(self._RATING_LABELS.get(r, btn.text()))

    def reset_for_next(self) -> None:
        self._recommended_rating = None
        self.clear_rating_intervals()
        self.accept_btn.setVisible(False)
        self.feedback.setVisible(False)
        self.feedback.setText(" ")
        self.feedback.setStyleSheet(self._feedback_style(ok=None))

        self.set_prompt(" ")
        self.set_meaning_blurred(None)
        self.set_hint_blurred(None, None)
        self.set_grammar_tip_blurred(None)

        self.in_blank.setEnabled(True)
        self.in_blank.clear()
        self.in_blank.setFocus()

        self.btn_check.setEnabled(True)
        self.btn_skip.setEnabled(True)

        for rating, button in self._rating_buttons:
            button.setEnabled(False)
            button.setStyleSheet(self._rating_style(rating, recommended=False))

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

        self.accept_btn.clicked.connect(self.accepted.emit)

        self.btn_reveal_meaning.clicked.connect(self._reveal_meaning)
        self.btn_reveal_hint.clicked.connect(self._reveal_hint)
        self.btn_reveal_grammar.clicked.connect(self._reveal_grammar)

    def _emit_check(self) -> None:
        if not self.btn_check.isEnabled():
            return
        self.check_clicked.emit(self.in_blank.text().strip())

    def _emit_skip(self) -> None:
        if not self.btn_skip.isEnabled():
            return
        self.skipped.emit()
        self.rated.emit(0)

    def _reveal_meaning(self) -> None:
        if self._meaning_blur:
            self.meaning_label.setText(self._meaning_blur)
            self._meaning_blur = None
            self.btn_reveal_meaning.setText("Shown")
            self.btn_reveal_meaning.setEnabled(False)
            self.meaning_tip_clicked.emit()

    def _reveal_hint(self) -> None:
        if self._hint_blur:
            self.hint_label.setText(self._hint_blur)
            self._hint_blur = None
            self.btn_reveal_hint.setText("Shown")
            self.btn_reveal_hint.setEnabled(False)
            self.hint_clicked.emit()

    def _reveal_grammar(self) -> None:
        if self._grammar_blur:
            self.grammar_tip_label.setText(self._grammar_blur)
            self._grammar_blur = None
            self.btn_reveal_grammar.setText("Shown")
            self.btn_reveal_grammar.setEnabled(False)
            self.grammar_tip_clicked.emit()
