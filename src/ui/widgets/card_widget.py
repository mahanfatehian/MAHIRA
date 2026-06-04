from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
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
        self._meaning_blur: QGraphicsBlurEffect | None = None
        self._gender_tip_blur: QGraphicsBlurEffect | None = None
        self._gender_tip_text: str | None = None
        self._recommended_rating: int | None = None
        self._active_input: QLineEdit | None = None

        self.setObjectName("CardWidget")
        self.setStyleSheet("CardWidget { background-color: transparent; border: none; }")

        self._setup_ui()
        self._connect_signals()
        self.reset_for_next()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 14, 16, 14)

        # ===== Word display card (matches grammar prompt card size) =====
        word_frame = QFrame()
        word_frame.setObjectName("WordCard")
        word_frame.setStyleSheet(
            "QFrame#WordCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 16px; }"
        )
        word_layout = QHBoxLayout(word_frame)
        word_layout.setContentsMargins(18, 14, 18, 14)
        word_layout.setSpacing(14)

        self.prompt_label = QLabel(" ")
        self.prompt_label.setStyleSheet(
            "QLabel { color: #FFFFFF; font-size: 24px; font-weight: 950; border: none; background: transparent; }"
        )
        word_layout.addWidget(self.prompt_label, 1)

        self.pos_badge = GlowBadge(" ")
        self.pos_badge.setVisible(False)
        word_layout.addWidget(self.pos_badge)

        # Audio button
        self.audio_btn = QPushButton("")
        self.audio_btn.setFixedWidth(42)
        self.audio_btn.setFixedHeight(42)
        self.audio_btn.setToolTip("Play pronunciation")
        self.audio_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1B1B1B;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 12px;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #232323;
                border: 1px solid #FFFFFF;
            }
            QPushButton:disabled {
                background-color: #151515;
                color: #6B6B6B;
                border: 1px solid #252525;
            }
            """
        )
        word_layout.addWidget(self.audio_btn)

        root.addWidget(word_frame)

        # ===== Hints/Tips section =====
        hints_frame = QFrame()
        hints_frame.setObjectName("HintsCard")
        hints_frame.setStyleSheet(
            "QFrame#HintsCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 16px; }"
        )
        hints_layout = QVBoxLayout(hints_frame)
        hints_layout.setContentsMargins(16, 12, 16, 12)
        hints_layout.setSpacing(10)

        # Example row
        example_row = QHBoxLayout()
        example_row.setSpacing(10)
        example_label = QLabel("Example")
        example_label.setStyleSheet(
            "QLabel { color: #B0B0B0; font-size: 12px; font-weight: 900; min-width: 84px; background: transparent; border: none; }"
        )
        example_row.addWidget(example_label)

        self.example_de = QLabel(" ")
        self.example_de.setWordWrap(True)
        self.example_de.setStyleSheet(
            "QLabel { color: #E6E6E6; font-size: 13px; padding: 8px 12px; background-color: #1A1A1A; border: 1px solid #2D2D2D; border-radius: 10px; line-height: 1.35; }"
        )
        example_row.addWidget(self.example_de, 1)
        hints_layout.addLayout(example_row)

        # Translation row (blurred)
        trans_row = QHBoxLayout()
        trans_row.setSpacing(10)
        trans_label = QLabel("Translation")
        trans_label.setStyleSheet(
            "QLabel { color: #B0B0B0; font-size: 12px; font-weight: 900; min-width: 84px; background: transparent; border: none; }"
        )
        trans_row.addWidget(trans_label)

        self.example_en = QLabel(" ")
        self.example_en.setWordWrap(True)
        self.example_en.setStyleSheet(
            "QLabel { color: #E6E6E6; font-size: 13px; padding: 8px 12px; background-color: #1A1A1A; border: 1px solid #2D2D2D; border-radius: 10px; line-height: 1.35; }"
        )
        trans_row.addWidget(self.example_en, 1)

        self.reveal_en_btn = QPushButton("Reveal")
        self.reveal_en_btn.setFixedWidth(90)
        self.reveal_en_btn.setStyleSheet(self._reveal_btn_style())
        trans_row.addWidget(self.reveal_en_btn)
        hints_layout.addLayout(trans_row)

        # Gender tip row (blurred)
        gt_row = QHBoxLayout()
        gt_row.setSpacing(10)
        gt_label = QLabel("Gender tip")
        gt_label.setStyleSheet(
            "QLabel { color: #B0B0B0; font-size: 12px; font-weight: 900; min-width: 84px; background: transparent; border: none; }"
        )
        gt_row.addWidget(gt_label)

        self.gender_tip_label = QLabel(" ")
        self.gender_tip_label.setWordWrap(True)
        self.gender_tip_label.setStyleSheet(
            "QLabel { color: #E6E6E6; font-size: 13px; padding: 8px 12px; background-color: #1A1A1A; border: 1px solid #2D2D2D; border-radius: 10px; line-height: 1.35; }"
        )
        gt_row.addWidget(self.gender_tip_label, 1)

        self.reveal_gender_tip_btn = QPushButton("Show")
        self.reveal_gender_tip_btn.setFixedWidth(90)
        self.reveal_gender_tip_btn.setStyleSheet(self._reveal_btn_style())
        gt_row.addWidget(self.reveal_gender_tip_btn)
        hints_layout.addLayout(gt_row)

        root.addWidget(hints_frame)

        # ===== Input section =====
        input_frame = QFrame()
        input_frame.setObjectName("InputCard")
        input_frame.setStyleSheet(
            "QFrame#InputCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 16px; }"
        )
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(10)

        input_title = QLabel("Your answer")
        input_title.setStyleSheet(
            "QLabel { color: #FFFFFF; font-size: 13px; font-weight: 900; background: transparent; border: none; }"
        )
        input_layout.addWidget(input_title)

        # Meaning input
        meaning_row = QHBoxLayout()
        meaning_row.setSpacing(10)
        meaning_label = QLabel("Meaning")
        meaning_label.setStyleSheet(
            "QLabel { color: #B0B0B0; font-size: 12px; font-weight: 900; min-width: 84px; background: transparent; border: none; }"
        )
        self._meaning_label_widget = meaning_label
        meaning_row.addWidget(meaning_label)

        self.in_meaning = QLineEdit()
        self.in_meaning.setPlaceholderText("Type the answer...")
        self.in_meaning.setMinimumHeight(38)
        self.in_meaning.setStyleSheet(self._input_style())
        meaning_row.addWidget(self.in_meaning, 1)
        input_layout.addLayout(meaning_row)

        # Gender input
        gender_row = QHBoxLayout()
        gender_row.setSpacing(10)
        gender_label = QLabel("Gender")
        gender_label.setStyleSheet(
            "QLabel { color: #B0B0B0; font-size: 12px; font-weight: 900; min-width: 84px; background: transparent; border: none; }"
        )
        self._gender_label_widget = gender_label
        gender_row.addWidget(gender_label)

        self.in_gender = QLineEdit()
        self.in_gender.setPlaceholderText("m / f / n or der / die / das")
        self.in_gender.setMinimumHeight(38)
        self.in_gender.setStyleSheet(self._input_style())
        gender_row.addWidget(self.in_gender, 1)
        input_layout.addLayout(gender_row)

        # Plural input
        plural_row = QHBoxLayout()
        plural_row.setSpacing(10)
        plural_label = QLabel("Plural")
        plural_label.setStyleSheet(
            "QLabel { color: #B0B0B0; font-size: 12px; font-weight: 900; min-width: 84px; background: transparent; border: none; }"
        )
        self._plural_label_widget = plural_label
        plural_row.addWidget(plural_label)

        self.in_plural = QLineEdit()
        self.in_plural.setPlaceholderText("Plural form...")
        self.in_plural.setMinimumHeight(38)
        self.in_plural.setStyleSheet(self._input_style())
        plural_row.addWidget(self.in_plural, 1)
        input_layout.addLayout(plural_row)

        root.addWidget(input_frame)

        # ===== Action buttons row =====
        action_frame = QFrame()
        action_frame.setObjectName("ActionCard")
        action_frame.setStyleSheet(
            "QFrame#ActionCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 16px; }"
        )
        action_layout = QHBoxLayout(action_frame)
        action_layout.setContentsMargins(16, 10, 16, 10)
        action_layout.setSpacing(10)

        self.check_btn = QPushButton("Check")
        self.check_btn.setMinimumHeight(40)
        self.check_btn.setStyleSheet(self._check_btn_style())
        action_layout.addWidget(self.check_btn, 1)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setMinimumHeight(40)
        self.skip_btn.setStyleSheet(self._skip_btn_style())
        action_layout.addWidget(self.skip_btn, 1)

        root.addWidget(action_frame)

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
            "QLabel { color: #B0B0B0; font-size: 11px; font-weight: 800; background: transparent; border: none; }"
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

        # ===== Results frame (hidden initially) =====
        self.results_frame = QFrame()
        self.results_frame.setObjectName("ResultsCard")
        self.results_frame.setVisible(False)
        self.results_frame.setStyleSheet(
            "QFrame#ResultsCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 16px; }"
        )
        self.results_layout = QVBoxLayout(self.results_frame)
        self.results_layout.setContentsMargins(16, 12, 16, 12)
        self.results_layout.setSpacing(8)
        self._res_rows: dict[str, tuple[QLabel, QLabel]] = {}

        self._add_result_row("Meaning", 0)
        self._add_result_row("Gender", 1)
        self._add_result_row("Plural", 2)

        root.addWidget(self.results_frame)

    # ---------- Styles ----------
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

    def _check_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #244B36;
                color: #F4FFF7;
                border: 1px solid #4CAF50;
                border-radius: 16px;
                padding: 10px 16px;
                font-weight: 900;
                font-size: 13px;
                min-height: 40px;
            }
            QPushButton:hover { background-color: #2B5B41; border: 1px solid #7AE582; }
            QPushButton:pressed { background-color: #214734; }
            QPushButton:disabled { background-color: #1A1A1A; color: #6B6B6B; border: 1px solid #252525; }
        """

    def _skip_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #163A5C;
                color: #FFFFFF;
                border: 1px solid #24537D;
                border-radius: 16px;
                padding: 10px 16px;
                font-weight: 900;
                font-size: 13px;
                min-height: 40px;
            }
            QPushButton:hover { background-color: #1B4B78; border: 1px solid #FFFFFF; }
            QPushButton:pressed { background-color: #123050; }
            QPushButton:disabled { background-color: #1A1A1A; color: #6B6B6B; border: 1px solid #252525; }
        """

    def _input_style(self) -> str:
        return """
            QLineEdit {
                background-color: #1B1B1B;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus { border: 1px solid #4A9EFF; background-color: #202020; }
            QLineEdit:disabled { background-color: #151515; color: #8C8C8C; border: 1px solid #252525; }
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

    # ---------- Result rows ----------
    def _add_result_row(self, field: str, row: int) -> None:
        name = QLabel(field)
        name.setStyleSheet("QLabel { font-size: 12px; font-weight: 900; color: #FFFFFF; background: transparent; border: none; }")
        status = QLabel(" ")
        status.setStyleSheet("QLabel { font-size: 12px; font-weight: 950; background: transparent; border: none; }")
        detail = QLabel(" ")
        detail.setWordWrap(True)
        detail.setStyleSheet("QLabel { font-size: 12px; color: #E6E6E6; background: transparent; border: none; }")

        row_layout = QHBoxLayout()
        row_layout.setSpacing(10)
        row_layout.addWidget(name, 0)
        row_layout.addWidget(status, 0)
        row_layout.addWidget(detail, 1)

        self.results_layout.addLayout(row_layout)
        self._res_rows[field.lower()] = (status, detail)

    def _set_result_row(self, key: str, ok: bool | None, typed: str | None, expected: str | None) -> None:
        status, detail = self._res_rows[key]
        if ok is None:
            status.setText("N/A")
            status.setStyleSheet("QLabel { font-size: 11px; font-weight: 900; color: #8E8E93; background: transparent; border: none; }")
            detail.setText("Not required.")
            return
        if ok:
            status.setText("OK")
            status.setStyleSheet("QLabel { font-size: 12px; font-weight: 950; color: #66E39A; background: transparent; border: none; }")
        else:
            status.setText("NO")
            status.setStyleSheet("QLabel { font-size: 12px; font-weight: 950; color: #FF6B6B; background: transparent; border: none; }")

        typed_show = (typed or " ").strip()
        expected_show = (expected or " ").strip()
        detail.setText(
            f"<div style='line-height:1.35;'>"
            f"<div style='color:#AFAFAF; font-size:11px;'>Your answer: <b>{typed_show if typed_show else '—'}</b></div>"
            f"<div style='color:#FFFFFF; font-size:13px; font-weight:950;'>Expected: {expected_show if expected_show else '—'}</div>"
            f"</div>"
        )

    @staticmethod
    def _recommend_from_checks(meaning_ok: bool | None, gender_ok: bool | None, plural_ok: bool | None) -> int:
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
        self.audio_btn.setEnabled(enabled)

    def set_example_de_visible_en_blurred(self, de_text: str, en_text: str | None) -> None:
        self.example_de.setText(de_text or "No example available")
        if not en_text:
            self.example_en.setText("No translation available")
            self.example_en.setGraphicsEffect(None)
            self._meaning_blur = None
            self.reveal_en_btn.setEnabled(False)
            self.reveal_en_btn.setVisible(False)
            return
        self.example_en.setText(en_text)
        self._meaning_blur = QGraphicsBlurEffect()
        self._meaning_blur.setBlurRadius(6.0)
        self.example_en.setGraphicsEffect(self._meaning_blur)
        self.reveal_en_btn.setEnabled(True)
        self.reveal_en_btn.setVisible(True)

    def set_gender_tip(self, tip: str | None) -> None:
        tip = (tip or " ").strip()
        self._gender_tip_text = tip or None
        if not self._gender_tip_text:
            self.gender_tip_label.setText("No tip available")
            self.gender_tip_label.setGraphicsEffect(None)
            self._gender_tip_blur = None
            self.reveal_gender_tip_btn.setEnabled(False)
            self.reveal_gender_tip_btn.setVisible(False)
            return
        self.gender_tip_label.setText(self._gender_tip_text)
        self._gender_tip_blur = QGraphicsBlurEffect()
        self._gender_tip_blur.setBlurRadius(6.0)
        self.gender_tip_label.setGraphicsEffect(self._gender_tip_blur)
        self.reveal_gender_tip_btn.setEnabled(True)
        self.reveal_gender_tip_btn.setVisible(True)

    def configure_fields(self, ask_gender: bool, ask_plural: bool) -> None:
        self.in_gender.setEnabled(ask_gender)
        self.in_plural.setEnabled(ask_plural)
        self._gender_label_widget.setVisible(True)
        self._plural_label_widget.setVisible(True)
        self.in_gender.setVisible(True)
        self.in_plural.setVisible(True)
        if not ask_gender:
            self.in_gender.clear()
        if not ask_plural:
            self.in_plural.clear()

    def set_meaning_label(self, label: str) -> None:
        self._meaning_label_widget.setText(label or "Meaning")

    def set_helper(self, text: str) -> None:
        pass

    def apply_check_results(self, payload: VocabCheckPayload) -> int:
        self.results_frame.setVisible(True)
        self.set_meaning_label(payload.meaning_label)
        self._set_result_row("meaning", payload.meaning_ok, payload.typed_meaning, payload.expected_meaning)
        self._set_result_row("gender", payload.gender_ok, payload.typed_gender, payload.expected_gender)
        self._set_result_row("plural", payload.plural_ok, payload.typed_plural, payload.expected_plural)
        rec = self._recommend_from_checks(payload.meaning_ok, payload.gender_ok, payload.plural_ok)
        self.set_recommended_rating(rec)
        return rec

    def set_recommended_rating(self, rating: int | None) -> None:
        self._recommended_rating = rating
        for r, btn in self._rating_buttons:
            btn.setStyleSheet(self._rating_style(r, recommended=(rating == r)))

    def reset_for_next(self) -> None:
        self._recommended_rating = None
        self.results_frame.setVisible(False)
        self.set_prompt(" ")
        self.set_pos(None)
        self.set_audio_enabled(False)
        self._active_input = self.in_meaning
        self.in_meaning.setEnabled(True)
        self.in_gender.setEnabled(True)
        self.in_plural.setEnabled(True)
        self.in_meaning.setVisible(True)
        self.in_gender.setVisible(True)
        self.in_plural.setVisible(True)
        self._gender_label_widget.setVisible(True)
        self._plural_label_widget.setVisible(True)
        self.check_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        for r, b in self._rating_buttons:
            b.setEnabled(False)
            b.setStyleSheet(self._rating_style(r, recommended=False))
        self.in_meaning.clear()
        self.in_gender.clear()
        self.in_plural.clear()
        self.in_meaning.setFocus()
        self.example_de.setText(" ")
        self.example_en.setText(" ")
        self.example_en.setGraphicsEffect(None)
        self._meaning_blur = None
        self.reveal_en_btn.setEnabled(False)
        self.reveal_en_btn.setVisible(True)
        self.gender_tip_label.setText(" ")
        self.gender_tip_label.setGraphicsEffect(None)
        self._gender_tip_blur = None
        self._gender_tip_text = None
        self.reveal_gender_tip_btn.setEnabled(False)
        self.reveal_gender_tip_btn.setVisible(True)

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
        if target and target.isEnabled():
            target.insert(ch)
            target.setFocus()
            return
        if self.in_meaning.isEnabled():
            self.in_meaning.insert(ch)
            self.in_meaning.setFocus()

    # ---------- Signals ----------
    def _connect_signals(self):
        self.check_btn.clicked.connect(self._emit_check)
        self.in_meaning.returnPressed.connect(self._emit_check)
        self.skip_btn.clicked.connect(self._emit_skip)
        self.btn_again.clicked.connect(lambda: self.rated.emit(0))
        self.btn_hard.clicked.connect(lambda: self.rated.emit(1))
        self.btn_good.clicked.connect(lambda: self.rated.emit(2))
        self.btn_easy.clicked.connect(lambda: self.rated.emit(3))
        self.reveal_en_btn.clicked.connect(self._on_reveal_en)
        self.reveal_gender_tip_btn.clicked.connect(self._on_reveal_gender_tip)
        self.audio_btn.clicked.connect(self.audio_clicked.emit)

    def _emit_skip(self) -> None:
        self.skipped.emit()
        self.rated.emit(0)

    def _emit_check(self) -> None:
        self.check_clicked.emit(
            self.in_meaning.text().strip(),
            self.in_gender.text().strip(),
            self.in_plural.text().strip(),
        )

    def _on_reveal_en(self) -> None:
        if self._meaning_blur:
            self.example_en.setGraphicsEffect(None)
            self._meaning_blur = None
            self.reveal_en_btn.setEnabled(False)
            self.tip_clicked.emit()

    def _on_reveal_gender_tip(self) -> None:
        if self._gender_tip_blur and self._gender_tip_text:
            self.gender_tip_label.setGraphicsEffect(None)
            self._gender_tip_blur = None
            self.reveal_gender_tip_btn.setEnabled(False)
            self.gender_tip_clicked.emit()