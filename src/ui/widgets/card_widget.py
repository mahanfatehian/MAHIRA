# ui/widgets/card_widget.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtWidgets import QApplication

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QFormLayout,
    QGraphicsBlurEffect,
    QFrame,
    QGridLayout,
    QScrollArea,
    QSizePolicy,
)


class GlowBadge(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(70, 28)

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
        color = color_map.get(text, QColor("#673AB7"))
        self.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(30, 30, 30, 220);
                color: {color.name()};
                border-radius: 14px;
                font-weight: 700;
                font-size: 10px;
                padding: 4px 8px;
                border: 1px solid {color.name()}80;
                min-width: 70px;
                min-height: 28px;
            }}
        """)


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
    """
    Vocab review card UI.

    Important:
    - Recommendation logic is inside this widget.
    - Results panel always renders (no more "not visible" bug).
    - Scroll area prevents compression when results appear.
    """

    check_clicked = Signal(str, str, str)   # meaning, gender, plural
    rated = Signal(int)                    # 0..3 Again/Hard/Good/Easy
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

        self.setStyleSheet("""
            CardWidget {
                background-color: #141414;
                border-radius: 12px;
                border: 1px solid #2A2A2A;
            }
            QLabel { color: #E6E6E6; }
        """)

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
    
    # ---------------- UI ----------------
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # Header
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        prompt_container = QVBoxLayout()
        prompt_container.setSpacing(2)

        self.prompt_label = QLabel("")
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setStyleSheet("""
            QLabel {
                font-size: 20px;
                font-weight: 800;
                color: #FFFFFF;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)
        self.prompt_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred
        )

        # ✅ THIS WAS MISSING
        prompt_container.addWidget(self.prompt_label)

        self.pos_badge = GlowBadge("")
        self.pos_badge.setFixedWidth(80)

        header_layout.addLayout(prompt_container, 1)
        header_layout.addWidget(self.pos_badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("QFrame { background-color: #2A2A2A; margin: 4px 0; }")

        # Scroll area to prevent layout compression
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self.content = QWidget()
        self.scroll.setWidget(self.content)

        content_layout = QVBoxLayout(self.content)
        content_layout.setSpacing(10)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Example + Translation + Gender Tip
        example_frame = QFrame()
        example_frame.setStyleSheet("""
            QFrame {
                background-color: #101010;
                border: 1px solid #2A2A2A;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        example_grid = QGridLayout(example_frame)
        example_grid.setContentsMargins(10, 10, 10, 10)
        example_grid.setHorizontalSpacing(10)
        example_grid.setVerticalSpacing(8)

        label_style = "QLabel { font-weight: 800; color: #B0B0B0; min-width: 90px; font-size: 12px; }"
        box_style = """
            QLabel {
                font-size: 13px;
                color: #FFFFFF;
                padding: 8px;
                background-color: #1D1D1D;
                border: 1px solid #2E2E2E;
                border-radius: 8px;
                line-height: 1.35;
            }
        """
        box_style_dim = """
            QLabel {
                font-size: 13px;
                color: #D0D0D0;
                padding: 8px;
                background-color: #1D1D1D;
                border: 1px solid #2E2E2E;
                border-radius: 8px;
                line-height: 1.35;
            }
        """

        self.lab_de = QLabel("Example")
        self.lab_de.setStyleSheet(label_style)
        self.example_de = QLabel("")
        self.example_de.setWordWrap(True)
        self.example_de.setStyleSheet(box_style)
        self.example_de.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.lab_en = QLabel("Translation")
        self.lab_en.setStyleSheet(label_style)
        self.example_en = QLabel("")
        self.example_en.setWordWrap(True)
        self.example_en.setStyleSheet(box_style_dim)
        self.example_en.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.reveal_en_btn = QPushButton("Reveal")
        self.reveal_en_btn.setFixedWidth(100)
        self.reveal_en_btn.setStyleSheet(self._btn_secondary_style())

        self.lab_gt = QLabel("Gender tip")
        self.lab_gt.setStyleSheet(label_style)
        self.gender_tip_label = QLabel("")
        self.gender_tip_label.setWordWrap(True)
        self.gender_tip_label.setStyleSheet(box_style_dim)
        self.gender_tip_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.reveal_gender_tip_btn = QPushButton("Show")
        self.reveal_gender_tip_btn.setFixedWidth(100)
        self.reveal_gender_tip_btn.setStyleSheet(self._btn_secondary_style())

        example_grid.addWidget(self.lab_de, 0, 0)
        example_grid.addWidget(self.example_de, 0, 1, 1, 2)

        example_grid.addWidget(self.lab_en, 1, 0)
        example_grid.addWidget(self.example_en, 1, 1)
        example_grid.addWidget(self.reveal_en_btn, 1, 2)

        example_grid.addWidget(self.lab_gt, 2, 0)
        example_grid.addWidget(self.gender_tip_label, 2, 1)
        example_grid.addWidget(self.reveal_gender_tip_btn, 2, 2)

        # Inputs
        form_frame = QFrame()
        form_frame.setStyleSheet("""
            QFrame {
                background-color: #101010;
                border: 1px solid #2A2A2A;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        form = QFormLayout(form_frame)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.in_meaning = QLineEdit()
        self.in_gender = QLineEdit()
        self.in_plural = QLineEdit()

        self.in_meaning.setPlaceholderText("Type the answer...")
        self.in_gender.setPlaceholderText("m / f / n (or der/die/das)")
        self.in_plural.setPlaceholderText("Plural form...")

        for w in (self.in_meaning, self.in_gender, self.in_plural):
            w.setStyleSheet(self._input_style())
            w.setMinimumHeight(36)

        def lab(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet("QLabel { font-weight: 800; color: #C8C8C8; font-size: 12px; min-width: 80px; }")
            return l

        self._meaning_label_widget = lab("Meaning")
        form.addRow(self._meaning_label_widget, self.in_meaning)
        form.addRow(lab("Gender"), self.in_gender)
        form.addRow(lab("Plural"), self.in_plural)

        # Buttons: Check / Skip
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)

        self.check_btn = QPushButton("Check")
        self.check_btn.setMinimumHeight(38)
        self.check_btn.setStyleSheet(self._btn_primary_style())

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setMinimumHeight(38)
        self.skip_btn.setStyleSheet(self._btn_skip_style())

        action_layout.addWidget(self.check_btn)
        action_layout.addWidget(self.skip_btn)

        # Rating buttons
        rating_layout = QHBoxLayout()
        rating_layout.setSpacing(6)

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
            rating_layout.addWidget(b)

        # Results panel
        self.results_frame = QFrame()
        self.results_frame.setVisible(False)
        self.results_frame.setStyleSheet("""
            QFrame {
                background-color: #0E0E0E;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        self.results_layout = QGridLayout(self.results_frame)
        self.results_layout.setContentsMargins(10, 10, 10, 10)
        self.results_layout.setHorizontalSpacing(10)
        self.results_layout.setVerticalSpacing(8)

        hdr = QLabel("Results")
        hdr.setStyleSheet("QLabel { font-size: 13px; font-weight: 900; color: #FFFFFF; }")
        self.results_layout.addWidget(hdr, 0, 0, 1, 3)

        self._res_rows = {}
        self._add_result_row("Meaning", 1)
        self._add_result_row("Gender", 2)
        self._add_result_row("Plural", 3)

        # Helper text
        self.helper = QLabel("")
        self.helper.setWordWrap(True)
        self.helper.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #B8B8B8;
                padding: 10px 12px;
                background-color: #101010;
                border-radius: 10px;
                border: 1px solid #2A2A2A;
            }
        """)

        # Assemble content
        content_layout.addWidget(example_frame)
        content_layout.addWidget(form_frame)
        content_layout.addLayout(action_layout)
        content_layout.addLayout(rating_layout)
        content_layout.addWidget(self.results_frame)
        content_layout.addWidget(self.helper)
        content_layout.addStretch(1)

        # Assemble root
        root.addLayout(header_layout)
        root.addWidget(sep)
        root.addWidget(self.scroll, 1)

    # ---------------- Styling helpers ----------------
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
        # Blue skip button (skipping is not "bad")
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

    def _rating_style(self, rating: int, recommended: bool) -> str:
        # Again(0)=Yellow, Hard(1)=Red, Good(2)=Blue, Easy(3)=Green
        palette = {
            0: ("#2B2B14", "#FFD700"),
            1: ("#2B1414", "#FF6B6B"),
            2: ("#14142B", "#6B9FFF"),
            3: ("#142B14", "#66E39A"),
        }
        bg, accent = palette.get(rating, ("#1B1B1B", "#C8C8C8"))

        if recommended:
            # strong highlight
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

    # ---------------- Results helpers ----------------
    def _add_result_row(self, field: str, row: int) -> None:
        name = QLabel(field)
        name.setStyleSheet("QLabel { font-size: 12px; font-weight: 900; color: #FFFFFF; }")

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
            status.setStyleSheet("QLabel { font-size: 11px; font-weight: 900; color: #9A9A9A; }")
            detail.setText("Not required.")
            return

        if ok:
            status.setText("OK")
            status.setStyleSheet("QLabel { font-size: 12px; font-weight: 950; color: #66E39A; }")
        else:
            status.setText("NO")
            status.setStyleSheet("QLabel { font-size: 12px; font-weight: 950; color: #FF6B6B; }")

        typed_show = (typed or "").strip()
        expected_show = (expected or "").strip()

        detail.setText(
            "<div style='line-height:1.35;'>"
            f"<div style='color:#B8B8B8; font-size:11px;'>Your answer: <b>{typed_show if typed_show else '—'}</b></div>"
            f"<div style='color:#FFFFFF; font-size:13px; font-weight:950;'>Expected: {expected_show if expected_show else '—'}</div>"
            "</div>"
        )

    # ---------------- Recommendation logic (inside widget) ----------------
    @staticmethod
    def _recommend_from_checks(meaning_ok: bool | None, gender_ok: bool | None, plural_ok: bool | None) -> int:
        vals = [meaning_ok, gender_ok, plural_ok]
        applicable = [v for v in vals if v is not None]
        if not applicable:
            return 2  # default to Good if nothing is applicable

        correct = sum(1 for v in applicable if v is True)
        ratio = correct / max(1, len(applicable))

        if ratio >= 1.0:
            return 3  # Easy
        if ratio >= 0.67:
            return 2  # Good
        if ratio >= 0.34:
            return 1  # Hard
        return 0      # Again

    # ---------------- Public API used by pages ----------------
    def set_prompt(self, text: str) -> None:
        self.prompt_label.setText(text or "")

    def set_pos(self, pos: str | None) -> None:
        pos = (pos or "").strip().upper()
        if not pos:
            self.pos_badge.setText("")
            self.pos_badge.setVisible(False)
            return
        self.pos_badge.setText(pos)
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
        if not ask_gender:
            self.in_gender.clear()
        if not ask_plural:
            self.in_plural.clear()

    def set_meaning_label(self, label: str) -> None:
        self._meaning_label_widget.setText(label)

    def set_helper(self, text: str) -> None:
        self.helper.setText(text or "")

    def apply_check_results(self, payload: VocabCheckPayload) -> int:
        """
        Called by VocabReviewPage after session.check_fields().
        Returns recommended rating 0..3, and highlights it.
        """
        self.results_frame.setVisible(True)

        # allow custom "meaning label"
        self.set_meaning_label(payload.meaning_label)

        self._set_result_row("meaning", payload.meaning_ok, payload.typed_meaning, payload.expected_meaning)
        self._set_result_row("gender", payload.gender_ok, payload.typed_gender, payload.expected_gender)
        self._set_result_row("plural", payload.plural_ok, payload.typed_plural, payload.expected_plural)

        rec = self._recommend_from_checks(payload.meaning_ok, payload.gender_ok, payload.plural_ok)
        self.set_recommended_rating(rec)

        # clearer instruction
        self.set_helper("Choose a rating. The highlighted button is the recommended one.")
        # scroll to results so user always sees them
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
        self._active_input = self.in_meaning

        self.in_meaning.setEnabled(True)
        self.in_gender.setEnabled(True)
        self.in_plural.setEnabled(True)

        self.check_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)

        for r, b in self._rating_buttons:
            b.setEnabled(False)
            b.setStyleSheet(self._rating_style(r, recommended=False))

        self.in_meaning.clear()
        self.in_gender.clear()
        self.in_plural.clear()
        self.in_meaning.setFocus()

        self.set_helper("")

        self.set_pos(None)

        self.example_de.setText("")
        self.example_en.setText("")
        self.example_en.setGraphicsEffect(None)
        self._blur_en = None
        self.reveal_en_btn.setEnabled(False)

        self.gender_tip_label.setText("")
        self.gender_tip_label.setGraphicsEffect(None)
        self._blur_gt = None
        self._gender_tip_text = None
        self.reveal_gender_tip_btn.setEnabled(False)

    def lock_after_check(self) -> None:
        self.in_meaning.setEnabled(False)
        self.in_gender.setEnabled(False)
        self.in_plural.setEnabled(False)

        self.check_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)

        for r, b in self._rating_buttons:
            b.setEnabled(True)

        # re-apply highlight after enabling
        if self._recommended_rating is not None:
            self.set_recommended_rating(self._recommended_rating)


    def insert_special_char(self, ch: str) -> None:
        """Insert into the last focused input field."""
        target = self._active_input

        if target and target.isEnabled():
            target.insert(ch)
            target.setFocus()
            return

        # fallback
        if self.in_meaning.isEnabled():
            self.in_meaning.insert(ch)
            self.in_meaning.setFocus()


    # ---------------- Signals ----------------
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
