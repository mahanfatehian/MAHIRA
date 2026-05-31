from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFormLayout,
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


class GlowBadge(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(28)
        self.setMinimumWidth(74)

        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        font.setCapitalization(QFont.Capitalization.AllUppercase)
        self.setFont(font)

        self.update_color_based_on_text(text)

    def update_color_based_on_text(self, text: str):
        text = (text or "").upper()
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
                border-radius: 14px;
                padding: 4px 10px;
                font-size: 10px;
                font-weight: 900;
                letter-spacing: 0.5px;
            }}
            """
        )


@dataclass(frozen=True)
class VocabCheckPayload:
    meaning_ok: bool | None
    expected_meaning: str | None
    typed_meaning: str | None

    gender_ok: bool | None
    expected_gender: str | None
    typed_gender: str | None

    plural_ok: bool | None
    expected_plural: str | None
    typed_plural: str | None

    meaning_label: str = "Meaning"


class CardWidget(QWidget):
    check_clicked = Signal(str, str, str)
    rated = Signal(int)
    tip_clicked = Signal()
    gender_tip_clicked = Signal()
    skipped = Signal()

    def __init__(self):
        super().__init__()

        self._active_input: QLineEdit | None = None
        self._blur_en: QGraphicsBlurEffect | None = None
        self._blur_gt: QGraphicsBlurEffect | None = None
        self._gender_tip_text: str | None = None
        self._recommended_rating: int | None = None

        self.setObjectName("VocabCardWidget")
        self.setStyleSheet(
            """
            QWidget#VocabCardWidget {
                background-color: #141414;
                border: 1px solid #2A2A2A;
                border-radius: 16px;
            }
            QLabel {
                color: #E6E6E6;
                border: none;
            }
            """
        )

        self._setup_ui()

        self.in_meaning.focusInEvent = self._make_focus_handler(self.in_meaning)
        self.in_gender.focusInEvent = self._make_focus_handler(self.in_gender)
        self.in_plural.focusInEvent = self._make_focus_handler(self.in_plural)

        self._connect_signals()
        self.reset_for_next()

    def _make_focus_handler(self, widget: QLineEdit):
        def handler(event):
            self._active_input = widget
            QLineEdit.focusInEvent(widget, event)
        return handler

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(18, 18, 18, 18)

        header = QHBoxLayout()
        header.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        self.prompt_label = QLabel("")
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setStyleSheet(
            """
            QLabel {
                font-size: 24px;
                font-weight: 950;
                color: #FFFFFF;
                line-height: 1.15;
            }
            """
        )
        self.prompt_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self.prompt_sub = QLabel("Recall the meaning and any required noun details.")
        self.prompt_sub.setWordWrap(True)
        self.prompt_sub.setStyleSheet(
            """
            QLabel {
                font-size: 12px;
                font-weight: 700;
                color: #8E8E93;
            }
            """
        )

        title_col.addWidget(self.prompt_label)
        title_col.addWidget(self.prompt_sub)

        self.pos_badge = GlowBadge("")
        self.pos_badge.setVisible(False)
        self.pos_badge.setFixedWidth(86)

        header.addLayout(title_col, 1)
        header.addWidget(
            self.pos_badge,
            0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("QFrame { background-color: #262626; margin: 2px 0 4px 0; }")

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet(
            """
            QScrollArea { background: transparent; }
            QScrollBar:vertical {
                background: #111111;
                width: 10px;
                margin: 0;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #2E2E2E;
                min-height: 24px;
                border-radius: 5px;
            }
            """
        )

        self.content = QWidget()
        self.scroll.setWidget(self.content)

        content_layout = QVBoxLayout(self.content)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(0, 0, 0, 0)

        info_frame = self._section_frame()
        info_grid = QGridLayout(info_frame)
        info_grid.setContentsMargins(14, 14, 14, 14)
        info_grid.setHorizontalSpacing(10)
        info_grid.setVerticalSpacing(10)

        self.lab_de = self._section_label("Example")
        self.example_de = self._value_box(bright=True)

        self.lab_en = self._section_label("Translation")
        self.example_en = self._value_box(bright=False)
        self.reveal_en_btn = self._secondary_btn("Reveal")
        self.reveal_en_btn.setFixedWidth(100)

        self.lab_gt = self._section_label("Gender tip")
        self.gender_tip_label = self._value_box(bright=False)
        self.reveal_gender_tip_btn = self._secondary_btn("Show")
        self.reveal_gender_tip_btn.setFixedWidth(100)

        info_grid.addWidget(self.lab_de, 0, 0)
        info_grid.addWidget(self.example_de, 0, 1, 1, 2)

        info_grid.addWidget(self.lab_en, 1, 0)
        info_grid.addWidget(self.example_en, 1, 1)
        info_grid.addWidget(self.reveal_en_btn, 1, 2)

        info_grid.addWidget(self.lab_gt, 2, 0)
        info_grid.addWidget(self.gender_tip_label, 2, 1)
        info_grid.addWidget(self.reveal_gender_tip_btn, 2, 2)

        form_frame = self._section_frame()
        form = QFormLayout(form_frame)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.in_meaning = QLineEdit()
        self.in_gender = QLineEdit()
        self.in_plural = QLineEdit()

        self.in_meaning.setPlaceholderText("Type the answer...")
        self.in_gender.setPlaceholderText("m / f / n or der / die / das")
        self.in_plural.setPlaceholderText("Plural form...")

        for w in (self.in_meaning, self.in_gender, self.in_plural):
            w.setMinimumHeight(40)
            w.setStyleSheet(self._input_style())

        self._meaning_label_widget = self._form_label("Meaning")
        self._gender_label_widget = self._form_label("Gender")
        self._plural_label_widget = self._form_label("Plural")

        form.addRow(self._meaning_label_widget, self.in_meaning)
        form.addRow(self._gender_label_widget, self.in_gender)
        form.addRow(self._plural_label_widget, self.in_plural)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.check_btn = self._primary_btn("Check")
        self.skip_btn = self._skip_btn("Skip")

        self.check_btn.setMinimumHeight(40)
        self.skip_btn.setMinimumHeight(40)

        action_row.addWidget(self.check_btn)
        action_row.addWidget(self.skip_btn)

        self.results_frame = self._section_frame()
        self.results_frame.setVisible(False)

        self.results_layout = QGridLayout(self.results_frame)
        self.results_layout.setContentsMargins(14, 14, 14, 14)
        self.results_layout.setHorizontalSpacing(10)
        self.results_layout.setVerticalSpacing(10)

        hdr = QLabel("Check results")
        hdr.setStyleSheet(
            "QLabel { font-size: 13px; font-weight: 950; color: #FFFFFF; }"
        )
        self.results_layout.addWidget(hdr, 0, 0, 1, 3)

        self._res_rows = {}
        self._add_result_row("Meaning", 1)
        self._add_result_row("Gender", 2)
        self._add_result_row("Plural", 3)

        self.helper = QLabel("")
        self.helper.setWordWrap(True)
        self.helper.setStyleSheet(self._helper_style())

        rating_frame = self._section_frame()
        rating_layout = QHBoxLayout(rating_frame)
        rating_layout.setContentsMargins(14, 14, 14, 14)
        rating_layout.setSpacing(8)

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
            b.setMinimumHeight(38)
            b.setStyleSheet(self._rating_style(r, recommended=False))
            rating_layout.addWidget(b)

        content_layout.addWidget(info_frame)
        content_layout.addWidget(form_frame)
        content_layout.addLayout(action_row)
        content_layout.addWidget(self.results_frame)
        content_layout.addWidget(self.helper)
        content_layout.addWidget(rating_frame)
        content_layout.addStretch(1)

        root.addLayout(header)
        root.addWidget(sep)
        root.addWidget(self.scroll, 1)

    def _section_frame(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            """
            QFrame {
                background-color: #101010;
                border: 1px solid #252525;
                border-radius: 14px;
            }
            """
        )
        return f

    def _section_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            """
            QLabel {
                font-size: 12px;
                font-weight: 900;
                color: #9D9D9D;
                min-width: 92px;
            }
            """
        )
        return l

    def _form_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            """
            QLabel {
                font-size: 12px;
                font-weight: 900;
                color: #C9C9C9;
                min-width: 84px;
            }
            """
        )
        return l

    def _value_box(self, bright: bool) -> QLabel:
        lab = QLabel("")
        lab.setWordWrap(True)
        lab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        fg = "#FFFFFF" if bright else "#D5D5D5"
        lab.setStyleSheet(
            f"""
            QLabel {{
                font-size: 13px;
                color: {fg};
                padding: 10px 12px;
                background-color: #1A1A1A;
                border: 1px solid #2D2D2D;
                border-radius: 10px;
                line-height: 1.35;
            }}
            """
        )
        return lab

    def _primary_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setStyleSheet(
            """
            QPushButton {
                background-color: #1F5F3A;
                color: #FFFFFF;
                border: 1px solid #2C6E47;
                border-radius: 12px;
                padding: 9px 18px;
                font-weight: 900;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #247248;
                border: 1px solid #FFFFFF;
            }
            QPushButton:disabled {
                background-color: #1A1A1A;
                color: #6B6B6B;
                border: 1px solid #252525;
            }
            """
        )
        return b

    def _skip_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setStyleSheet(
            """
            QPushButton {
                background-color: #163A5C;
                color: #FFFFFF;
                border: 1px solid #24537D;
                border-radius: 12px;
                padding: 9px 18px;
                font-weight: 900;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #1B4B78;
                border: 1px solid #FFFFFF;
            }
            QPushButton:disabled {
                background-color: #1A1A1A;
                color: #6B6B6B;
                border: 1px solid #252525;
            }
            """
        )
        return b

    def _secondary_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setStyleSheet(
            """
            QPushButton {
                background-color: #1B1B1B;
                color: #E6E6E6;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 8px 12px;
                font-weight: 850;
                font-size: 11px;
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
        return b

    @staticmethod
    def _input_style() -> str:
        return """
        QLineEdit {
            background-color: #1B1B1B;
            color: #FFFFFF;
            border: 1px solid #2E2E2E;
            border-radius: 10px;
            padding: 9px 12px;
            font-size: 13px;
        }
        QLineEdit:focus {
            border: 1px solid #4A9EFF;
            background-color: #202020;
        }
        QLineEdit:disabled {
            background-color: #151515;
            color: #8C8C8C;
            border: 1px solid #252525;
        }
        """

    @staticmethod
    def _helper_style() -> str:
        return """
        QLabel {
            font-size: 12px;
            color: #B8B8B8;
            padding: 10px 12px;
            background-color: #101010;
            border-radius: 12px;
            border: 1px solid #252525;
            line-height: 1.4;
        }
        """

    def _rating_style(self, rating: int, recommended: bool) -> str:
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
                    border-radius: 12px;
                    padding: 8px 12px;
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
                    border: 1px solid #252525;
                }}
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

    def _add_result_row(self, field: str, row: int) -> None:
        name = QLabel(field)
        name.setStyleSheet(
            "QLabel { font-size: 12px; font-weight: 900; color: #FFFFFF; }"
        )

        status = QLabel("")
        status.setStyleSheet("QLabel { font-size: 12px; font-weight: 950; }")

        detail = QLabel("")
        detail.setWordWrap(True)
        detail.setStyleSheet("QLabel { font-size: 12px; color: #E6E6E6; }")

        self.results_layout.addWidget(name, row, 0)
        self.results_layout.addWidget(status, row, 1)
        self.results_layout.addWidget(detail, row, 2)

        self._res_rows[field.lower()] = (status, detail)

    def _set_result_row(self, key: str, ok: bool | None, typed: str | None, expected: str | None) -> None:
        status, detail = self._res_rows[key]

        if ok is None:
            status.setText("N/A")
            status.setStyleSheet(
                "QLabel { font-size: 11px; font-weight: 900; color: #8E8E93; }"
            )
            detail.setText("Not required.")
            return

        if ok:
            status.setText("OK")
            status.setStyleSheet(
                "QLabel { font-size: 12px; font-weight: 950; color: #66E39A; }"
            )
        else:
            status.setText("NO")
            status.setStyleSheet(
                "QLabel { font-size: 12px; font-weight: 950; color: #FF6B6B; }"
            )

        typed_show = (typed or "").strip()
        expected_show = (expected or "").strip()

        detail.setText(
            "<div style='line-height:1.35;'>"
            f"<div style='color:#AFAFAF; font-size:11px;'>Your answer: <b>{typed_show if typed_show else '—'}</b></div>"
            f"<div style='color:#FFFFFF; font-size:13px; font-weight:950;'>Expected: {expected_show if expected_show else '—'}</div>"
            "</div>"
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

    def set_prompt(self, text: str) -> None:
        self.prompt_label.setText(text or "")

    def set_pos(self, pos: str | None) -> None:
        pos = (pos or "").strip().upper()
        if not pos:
            self.pos_badge.setText("")
            self.pos_badge.setVisible(False)
            return
        self.pos_badge.setText(pos)
        self.pos_badge.update_color_based_on_text(pos)
        self.pos_badge.setVisible(True)

    def set_example_de_visible_en_blurred(self, de_text: str, en_text: str | None) -> None:
        self.example_de.setText(de_text or "No example available")

        if not en_text:
            self.example_en.setText("No translation available")
            self.example_en.setGraphicsEffect(None)
            self._blur_en = None
            self.reveal_en_btn.setEnabled(False)
            self.reveal_en_btn.setVisible(False)
            return

        self.example_en.setText(en_text)
        self._blur_en = QGraphicsBlurEffect()
        self._blur_en.setBlurRadius(6.0)
        self.example_en.setGraphicsEffect(self._blur_en)
        self.reveal_en_btn.setEnabled(True)
        self.reveal_en_btn.setVisible(True)

    def set_gender_tip(self, tip: str | None) -> None:
        tip = (tip or "").strip()
        self._gender_tip_text = tip or None

        if not self._gender_tip_text:
            self.gender_tip_label.setText("No tip available")
            self.gender_tip_label.setGraphicsEffect(None)
            self._blur_gt = None
            self.reveal_gender_tip_btn.setEnabled(False)
            self.reveal_gender_tip_btn.setVisible(False)
            return

        self.gender_tip_label.setText(self._gender_tip_text)
        self._blur_gt = QGraphicsBlurEffect()
        self._blur_gt.setBlurRadius(6.0)
        self.gender_tip_label.setGraphicsEffect(self._blur_gt)
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
        self.helper.setText(text or "")
        self.helper.setVisible(bool((text or "").strip()))

    def apply_check_results(self, payload: VocabCheckPayload) -> int:
        self.results_frame.setVisible(True)

        self.set_meaning_label(payload.meaning_label)

        self._set_result_row("meaning", payload.meaning_ok, payload.typed_meaning, payload.expected_meaning)
        self._set_result_row("gender", payload.gender_ok, payload.typed_gender, payload.expected_gender)
        self._set_result_row("plural", payload.plural_ok, payload.typed_plural, payload.expected_plural)

        rec = self._recommend_from_checks(
            payload.meaning_ok,
            payload.gender_ok,
            payload.plural_ok,
        )
        self.set_recommended_rating(rec)

        self.set_helper("Choose a rating. The highlighted button is the recommended one.")
        self.scroll.ensureWidgetVisible(self.results_frame)
        return rec

    def set_recommended_rating(self, rating: int | None) -> None:
        self._recommended_rating = rating
        for r, btn in self._rating_buttons:
            btn.setStyleSheet(self._rating_style(r, recommended=(rating == r)))

    def reset_for_next(self) -> None:
        self._recommended_rating = None
        self.results_frame.setVisible(False)

        self.set_prompt("")
        self.set_pos(None)
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

        self.example_de.setText("")
        self.example_en.setText("")
        self.example_en.setGraphicsEffect(None)
        self._blur_en = None
        self.reveal_en_btn.setEnabled(False)
        self.reveal_en_btn.setVisible(True)

        self.gender_tip_label.setText("")
        self.gender_tip_label.setGraphicsEffect(None)
        self._blur_gt = None
        self._gender_tip_text = None
        self.reveal_gender_tip_btn.setEnabled(False)
        self.reveal_gender_tip_btn.setVisible(True)

        self.set_helper("")

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
        if self._blur_en:
            self.example_en.setGraphicsEffect(None)
            self._blur_en = None
            self.reveal_en_btn.setEnabled(False)
            self.tip_clicked.emit()

    def _on_reveal_gender_tip(self) -> None:
        if self._blur_gt and self._gender_tip_text:
            self.gender_tip_label.setGraphicsEffect(None)
            self._blur_gt = None
            self.reveal_gender_tip_btn.setEnabled(False)
            self.gender_tip_clicked.emit()
