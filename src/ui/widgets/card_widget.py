from __future__ import annotations

from dataclasses import dataclass
from html import escape

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFont
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

from ui.widgets.audio_button import AudioButton
from ui.widgets.redact import mask_hidden


@dataclass
class VocabCheckPayload:
    meaning_ok: bool | None
    expected_meaning: str | None
    typed_meaning: str
    gender_ok: bool | None
    expected_gender: str | None
    typed_gender: str
    plural_ok: bool | None
    expected_plural: str | None
    typed_plural: str
    meaning_label: str = "Meaning"


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


def _body_label_style(size: int = 12) -> str:
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


class GlowBadge(QLabel):
    def __init__(self, text: str = " ", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(26)
        self.setMinimumWidth(70)

        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        font.setCapitalization(QFont.Capitalization.AllUppercase)
        self.setFont(font)

        self.update_color_based_on_text(text)

    def update_color_based_on_text(self, text: str):
        text = (text or " ").upper()
        color_map = {
            "NOUN": QColor("#00BCD4"),
            "VERB": QColor("#FF4081"),
            "ADJ": QColor("#FF9800"),
            "ADV": QColor("#9C27B0"),
            "PREP": QColor("#F44336"),
            "PRON": QColor("#4CAF50"),
            "CONJ": QColor("#795548"),
            "PHRASE": QColor("#607D8B"),
            "OTHER": QColor("#9E9E9E"),
        }
        color = color_map.get(text, QColor("#8C7BFF"))
        self.setStyleSheet(
            f"""
            QLabel {{
                background-color: #181818;
                color: {color.name()};
                border: 1px solid {color.name()}66;
                border-radius: 13px;
                padding: 4px 10px;
                font-size: 10px;
                font-weight: 900;
                letter-spacing: 0.5px;
            }}
            """
        )


class CardWidget(QWidget):
    check_clicked = Signal(str, str, str)
    rated = Signal(int)
    skipped = Signal()
    tip_clicked = Signal()
    gender_tip_clicked = Signal()
    audio_clicked = Signal()

    def __init__(self, accent: str = "#66E39A", parent=None):
        super().__init__(parent)

        self._accent = accent
        # While hidden these hold the REAL text (truthy = still masked); on
        # reveal we swap the masked bullets back to this and clear the slot.
        self._meaning_blur: str | None = None
        self._example_blur: str | None = None
        self._gender_tip_blur: str | None = None
        self._gender_tip_text: str | None = None
        self._recommended_rating: int | None = None
        self._active_input: QLineEdit | None = None

        self.setObjectName("CardWidget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet("CardWidget { background-color: transparent; border: none; }")

        self._setup_ui()
        self._connect_signals()
        self.reset_for_next()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(0, 0, 0, 0)

        # ===== Word card =====
        self.word_frame = QFrame()
        self.word_frame.setObjectName("WordCard")
        self.word_frame.setStyleSheet(_card_style(border="#2A2A2A", bg="#141414", radius=18))
        self.word_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        word_layout = QHBoxLayout(self.word_frame)
        word_layout.setContentsMargins(18, 16, 14, 16)
        word_layout.setSpacing(12)

        self.prompt_label = QLabel(" ")
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setStyleSheet(
            "QLabel { "
            "color:#FFFFFF; "
            "font-size:25px; "
            "font-weight:950; "
            "border:none; "
            "background:transparent; "
            "}"
        )
        word_layout.addWidget(self.prompt_label, 1)

        self.pos_badge = GlowBadge(" ")
        self.pos_badge.setVisible(False)
        word_layout.addWidget(self.pos_badge)

        self.audio_btn = AudioButton()
        word_layout.addWidget(self.audio_btn)

        root.addWidget(self.word_frame)

        # ===== Grammar-style tips row =====
        self.tips_row_widget = QWidget()
        tips_row = QHBoxLayout(self.tips_row_widget)
        tips_row.setContentsMargins(0, 0, 0, 0)
        tips_row.setSpacing(10)

        (
            self.meaning_card,
            self.meaning_tip_label,
            self.btn_reveal_meaning,
        ) = self._make_reveal_card("Meaning")

        (
            self.example_card,
            self.example_tip_label,
            self.btn_reveal_example,
        ) = self._make_reveal_card("Example")

        (
            self.gender_tip_card,
            self.gender_tip_label,
            self.btn_reveal_gender_tip,
        ) = self._make_reveal_card("Gender tip")

        tips_row.addWidget(self.meaning_card)
        tips_row.addWidget(self.example_card)
        tips_row.addWidget(self.gender_tip_card)

        root.addWidget(self.tips_row_widget)

        # ===== Input card =====
        self.input_frame = QFrame()
        self.input_frame.setObjectName("InputCard")
        self.input_frame.setStyleSheet(_card_style(border="#2A2A2A", bg="#141414", radius=18))

        input_layout = QVBoxLayout(self.input_frame)
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

        self.meaning_row = self._make_input_row("Meaning", "Type the answer...")
        self._meaning_label_widget, self.in_meaning = self._row_label_and_input(self.meaning_row)
        input_layout.addWidget(self.meaning_row)

        self.gender_row = self._make_input_row("Gender", "m / f / n or der / die / das")
        self._gender_label_widget, self.in_gender = self._row_label_and_input(self.gender_row)
        input_layout.addWidget(self.gender_row)

        self.plural_row = self._make_input_row("Plural", "Plural form...")
        self._plural_label_widget, self.in_plural = self._row_label_and_input(self.plural_row)
        input_layout.addWidget(self.plural_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.check_btn = QPushButton("Check")
        self.check_btn.setMinimumHeight(40)
        self.check_btn.setStyleSheet(self._primary_btn_style())
        action_row.addWidget(self.check_btn, 1)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setMinimumHeight(40)
        self.skip_btn.setStyleSheet(self._secondary_btn_style())
        action_row.addWidget(self.skip_btn, 1)

        input_layout.addLayout(action_row)
        root.addWidget(self.input_frame)

        # ===== Results card =====
        self.results_frame = QFrame()
        self.results_frame.setObjectName("ResultsCard")
        self.results_frame.setVisible(False)
        self.results_frame.setStyleSheet(_card_style(border="#2A2A2A", bg="#141414", radius=18))

        self.results_layout = QVBoxLayout(self.results_frame)
        self.results_layout.setContentsMargins(16, 12, 16, 12)
        self.results_layout.setSpacing(8)

        results_title = QLabel("Result")
        results_title.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:13px; font-weight:950; background:transparent; border:none; }"
        )
        self.results_layout.addWidget(results_title)

        self._res_rows: dict[str, tuple[QFrame, QLabel, QLabel]] = {}
        self._add_result_row("meaning", "Meaning")
        self._add_result_row("gender", "Gender")
        self._add_result_row("plural", "Plural")

        root.addWidget(self.results_frame)

        # ===== Rating card =====
        self.rating_frame = QFrame()
        self.rating_frame.setObjectName("RatingCard")
        self.rating_frame.setVisible(False)
        self.rating_frame.setStyleSheet(_card_style(border="#2A2A2A", bg="#141414", radius=18))

        rating_layout = QVBoxLayout(self.rating_frame)
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
        root.addWidget(self.rating_frame)

        root.addStretch(1)

        for field in (self.in_meaning, self.in_gender, self.in_plural):
            field.installEventFilter(self)

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

    def _make_input_row(self, label: str, placeholder: str) -> QFrame:
        row = QFrame()
        row.setObjectName("InputRow")
        row.setStyleSheet("QFrame#InputRow { background: transparent; border: none; }")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        lbl = QLabel(label, objectName="InputLabel")
        lbl.setFixedWidth(86)
        lbl.setStyleSheet(
            "QLabel { color: #B0B0B0; font-size: 11px; font-weight: 900; background: transparent; border: none; }"
        )
        layout.addWidget(lbl)

        line = QLineEdit(objectName="InputField")
        line.setPlaceholderText(placeholder)
        line.setMinimumHeight(36)
        line.setStyleSheet(self._input_style())
        layout.addWidget(line, 1)

        return row

    @staticmethod
    def _row_label_and_input(row: QFrame) -> tuple[QLabel, QLineEdit]:
        return (
            row.findChild(QLabel, "InputLabel"),
            row.findChild(QLineEdit, "InputField"),
        )

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
            QPushButton:hover { background-color: #232323; border: 1px solid #66E39A; color:#FFFFFF; }
            QPushButton:disabled { background-color: #151515; color: #6B6B6B; border: 1px solid #252525; }
        """

    def _input_style(self) -> str:
        return """
            QLineEdit {
                background-color: #1B1B1B;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 12px;
                padding: 8px 12px;
                font-size: 13px;
                font-weight: 700;
            }
            QLineEdit:focus { border: 1px solid #4A9EFF; background-color: #202020; }
            QLineEdit:disabled { background-color: #151515; color: #8C8C8C; border: 1px solid #252525; }
        """

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

    def _add_result_row(self, key: str, title: str) -> None:
        row = QFrame()
        row.setObjectName("ResultRow")
        row.setStyleSheet(
            "QFrame#ResultRow { background-color:#1A1A1A; border:1px solid #2D2D2D; border-radius:10px; }"
        )

        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(9)

        name = QLabel(title)
        name.setFixedWidth(74)
        name.setStyleSheet(
            "QLabel { font-size: 11px; font-weight: 900; color: #B0B0B0; background: transparent; border: none; }"
        )
        layout.addWidget(name)

        status = QLabel(" ")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.setFixedWidth(44)
        layout.addWidget(status)

        detail = QLabel(" ")
        detail.setWordWrap(True)
        detail.setStyleSheet(
            "QLabel { font-size: 12px; color: #E6E6E6; background: transparent; border: none; }"
        )
        layout.addWidget(detail, 1)

        self.results_layout.addWidget(row)
        self._res_rows[key] = (row, status, detail)

    def _status_style(self, ok: bool) -> str:
        if ok:
            return (
                "QLabel { color:#66E39A; border:1px solid #2D6A45; "
                "border-radius:8px; padding:3px 6px; font-size:11px; "
                "font-weight:950; background:#13251B; }"
            )

        return (
            "QLabel { color:#FF6B6B; border:1px solid #6A2D2D; "
            "border-radius:8px; padding:3px 6px; font-size:11px; "
            "font-weight:950; background:#261515; }"
        )

    def _set_result_row(
        self,
        key: str,
        ok: bool | None,
        typed: str | None,
        expected: str | None,
    ) -> None:
        row, status, detail = self._res_rows[key]

        if ok is None:
            row.setVisible(False)
            return

        row.setVisible(True)
        status.setText("OK" if ok else "NO")
        status.setStyleSheet(self._status_style(bool(ok)))

        typed_show = escape((typed or "").strip() or "—")
        expected_show = escape((expected or "").strip() or "—")

        if ok:
            detail.setText(
                f"<span style='color:#FFFFFF; font-weight:900;'>{expected_show}</span>"
            )
            return

        detail.setText(
            f"<span style='color:#AFAFAF;'>You:</span> <b>{typed_show}</b>"
            f" &nbsp; <span style='color:#AFAFAF;'>Expected:</span> "
            f"<span style='color:#FFFFFF; font-weight:900;'>{expected_show}</span>"
        )

    @staticmethod
    def _recommend_from_checks(
        meaning_ok: bool | None,
        gender_ok: bool | None,
        plural_ok: bool | None,
    ) -> int:
        vals = [meaning_ok, gender_ok, plural_ok]
        applicable = [v for v in vals if v is not None]

        if not applicable:
            return 2

        correct = sum(1 for v in applicable if v is True)
        ratio = correct / max(1, len(applicable))

        if ratio >= 1.0:
            return 3
        if ratio >= 0.67:
            return 2
        if ratio >= 0.34:
            return 1
        return 0

    # ---------- Public API ----------
    def set_prompt(self, text: str) -> None:
        self.prompt_label.setText(text or " ")

    def set_pos(self, pos: str | None) -> None:
        pos = (pos or " ").strip().upper()

        if not pos:
            self.pos_badge.setText(" ")
            self.pos_badge.setVisible(False)
            return

        self.pos_badge.setText(pos)
        self.pos_badge.update_color_based_on_text(pos)
        self.pos_badge.setVisible(True)

    def set_audio_enabled(self, enabled: bool) -> None:
        self.audio_btn.set_available(bool(enabled))

    def set_audio_busy(self, busy: bool) -> None:
        self.audio_btn.set_busy(bool(busy))

    def set_audio_playing(self, playing: bool) -> None:
        self.audio_btn.set_playing(bool(playing))

    def reset_audio_state(self) -> None:
        self.audio_btn.reset_state()

    def set_meaning_blurred(self, text: str | None) -> None:
        text = (text or "").strip()

        if not text:
            self.meaning_tip_label.setText("No meaning available")
            self._meaning_blur = None
            self.btn_reveal_meaning.setEnabled(False)
            self.btn_reveal_meaning.setVisible(False)
            return

        self._meaning_blur = text
        self.meaning_tip_label.setText(mask_hidden(text))
        self.btn_reveal_meaning.setText("Reveal")
        self.btn_reveal_meaning.setEnabled(True)
        self.btn_reveal_meaning.setVisible(True)

    def set_example_blurred(self, de_text: str | None, en_text: str | None) -> None:
        de_text = (de_text or "").strip()
        en_text = (en_text or "").strip() if en_text else ""

        if de_text and en_text:
            display = f"{de_text}\n{en_text}"
        else:
            display = de_text or en_text

        if not display:
            self.example_tip_label.setText("No example available")
            self._example_blur = None
            self.btn_reveal_example.setEnabled(False)
            self.btn_reveal_example.setVisible(False)
            return

        self._example_blur = display
        self.example_tip_label.setText(mask_hidden(display))
        self.btn_reveal_example.setText("Reveal")
        self.btn_reveal_example.setEnabled(True)
        self.btn_reveal_example.setVisible(True)

    def set_example_de_visible_en_blurred(self, de_text: str, en_text: str | None) -> None:
        # Backwards-compatible wrapper for older page code.
        self.set_example_blurred(de_text, en_text)

    def set_gender_tip(self, tip: str | None) -> None:
        tip = (tip or "").strip()
        self._gender_tip_text = tip or None

        if not self._gender_tip_text:
            self.gender_tip_label.setText("No gender tip available")
            self._gender_tip_blur = None
            self.btn_reveal_gender_tip.setEnabled(False)
            self.btn_reveal_gender_tip.setVisible(False)
            return

        self._gender_tip_blur = self._gender_tip_text
        self.gender_tip_label.setText(mask_hidden(self._gender_tip_text))
        self.btn_reveal_gender_tip.setText("Reveal")
        self.btn_reveal_gender_tip.setEnabled(True)
        self.btn_reveal_gender_tip.setVisible(True)

    def configure_fields(self, ask_gender: bool, ask_plural: bool) -> None:
        self.gender_row.setVisible(bool(ask_gender))
        self.plural_row.setVisible(bool(ask_plural))

        self.in_gender.setEnabled(bool(ask_gender))
        self.in_plural.setEnabled(bool(ask_plural))

        if not ask_gender:
            self.in_gender.clear()
        if not ask_plural:
            self.in_plural.clear()

    def set_meaning_label(self, label: str) -> None:
        self._meaning_label_widget.setText(label or "Meaning")

    def set_helper(self, text: str) -> None:
        pass

    def apply_check_results(self, payload: VocabCheckPayload) -> int:
        self.set_meaning_label(payload.meaning_label)

        self._set_result_row(
            "meaning",
            payload.meaning_ok,
            payload.typed_meaning,
            payload.expected_meaning,
        )
        self._set_result_row(
            "gender",
            payload.gender_ok,
            payload.typed_gender,
            payload.expected_gender,
        )
        self._set_result_row(
            "plural",
            payload.plural_ok,
            payload.typed_plural,
            payload.expected_plural,
        )

        self.tips_row_widget.setVisible(False)
        self.input_frame.setVisible(False)
        self.results_frame.setVisible(True)
        self.rating_frame.setVisible(True)

        rec = self._recommend_from_checks(
            payload.meaning_ok,
            payload.gender_ok,
            payload.plural_ok,
        )
        self.set_recommended_rating(rec)
        return rec

    def set_recommended_rating(self, rating: int | None) -> None:
        self._recommended_rating = rating
        for r, btn in self._rating_buttons:
            btn.setStyleSheet(self._rating_style(r, recommended=(rating == r)))

    def reset_for_next(self) -> None:
        self._recommended_rating = None

        self.results_frame.setVisible(False)
        self.rating_frame.setVisible(False)
        self.input_frame.setVisible(True)
        self.tips_row_widget.setVisible(True)

        self.set_prompt(" ")
        self.set_pos(None)

        self.set_audio_busy(False)
        self.set_audio_playing(False)
        self.set_audio_enabled(False)

        self._active_input = self.in_meaning

        self.in_meaning.setEnabled(True)
        self.in_gender.setEnabled(True)
        self.in_plural.setEnabled(True)

        self.meaning_row.setVisible(True)
        self.gender_row.setVisible(True)
        self.plural_row.setVisible(True)

        self.check_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)

        for r, b in self._rating_buttons:
            b.setEnabled(False)
            b.setStyleSheet(self._rating_style(r, recommended=False))

        self.in_meaning.clear()
        self.in_gender.clear()
        self.in_plural.clear()

        self.meaning_tip_label.setText("No meaning available")
        self._meaning_blur = None
        self.btn_reveal_meaning.setEnabled(False)
        self.btn_reveal_meaning.setVisible(False)

        self.example_tip_label.setText("No example available")
        self._example_blur = None
        self.btn_reveal_example.setEnabled(False)
        self.btn_reveal_example.setVisible(False)

        self.gender_tip_label.setText("No gender tip available")
        self._gender_tip_blur = None
        self._gender_tip_text = None
        self.btn_reveal_gender_tip.setEnabled(False)
        self.btn_reveal_gender_tip.setVisible(False)

        for row, _, _ in self._res_rows.values():
            row.setVisible(False)

        self.in_meaning.setFocus()

    def lock_after_check(self) -> None:
        self.in_meaning.setEnabled(False)
        self.in_gender.setEnabled(False)
        self.in_plural.setEnabled(False)

        self.check_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)

        for r, b in self._rating_buttons:
            b.setEnabled(True)

        if self._recommended_rating is not None:
            self.set_recommended_rating(self._recommended_rating)

    def insert_special_char(self, ch: str) -> None:
        target = self._active_input

        if target and target.isEnabled() and target.isVisible():
            target.insert(ch)
            target.setFocus()
            return

        if self.in_meaning.isEnabled():
            self.in_meaning.insert(ch)
            self.in_meaning.setFocus()

    # ---------- Events/signals ----------
    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.FocusIn and watched in (
            self.in_meaning,
            self.in_gender,
            self.in_plural,
        ):
            self._active_input = watched

        return super().eventFilter(watched, event)

    def _connect_signals(self):
        self.check_btn.clicked.connect(self._emit_check)

        self.in_meaning.returnPressed.connect(self._emit_check)
        self.in_gender.returnPressed.connect(self._emit_check)
        self.in_plural.returnPressed.connect(self._emit_check)

        self.skip_btn.clicked.connect(self._emit_skip)

        self.btn_again.clicked.connect(lambda: self.rated.emit(0))
        self.btn_hard.clicked.connect(lambda: self.rated.emit(1))
        self.btn_good.clicked.connect(lambda: self.rated.emit(2))
        self.btn_easy.clicked.connect(lambda: self.rated.emit(3))

        self.btn_reveal_meaning.clicked.connect(self._on_reveal_meaning)
        self.btn_reveal_example.clicked.connect(self._on_reveal_example)
        self.btn_reveal_gender_tip.clicked.connect(self._on_reveal_gender_tip)

        self.audio_btn.clicked.connect(self.audio_clicked.emit)

    def _emit_skip(self) -> None:
        self.skipped.emit()
        self.rated.emit(0)

    def _emit_check(self) -> None:
        if not self.check_btn.isEnabled():
            return

        self.check_clicked.emit(
            self.in_meaning.text().strip(),
            self.in_gender.text().strip(),
            self.in_plural.text().strip(),
        )

    def _on_reveal_meaning(self) -> None:
        if self._meaning_blur:
            self.meaning_tip_label.setText(self._meaning_blur)
            self._meaning_blur = None
            self.btn_reveal_meaning.setEnabled(False)
            self.tip_clicked.emit()

    def _on_reveal_example(self) -> None:
        if self._example_blur:
            self.example_tip_label.setText(self._example_blur)
            self._example_blur = None
            self.btn_reveal_example.setEnabled(False)
            self.tip_clicked.emit()

    def _on_reveal_gender_tip(self) -> None:
        if self._gender_tip_blur and self._gender_tip_text:
            self.gender_tip_label.setText(self._gender_tip_text)
            self._gender_tip_blur = None
            self.btn_reveal_gender_tip.setEnabled(False)
            self.gender_tip_clicked.emit()