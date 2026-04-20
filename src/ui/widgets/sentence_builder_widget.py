from __future__ import annotations

import logging
import random

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QGraphicsBlurEffect,
)

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
    QPushButton:hover { border: 1px solid #FFFFFF; background-color:#232323; }
    QPushButton:disabled { background-color: #101010; color: #6B6B6B; border: 1px solid #252525; }
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
    QPushButton:hover {{ border: 1px solid #FFFFFF; }}
    QPushButton:disabled {{
        background-color:#101010;
        color:#6B6B6B;
        border:1px solid #252525;
    }}
    """


def _rating_style(rating: int) -> str:
    palette = {
        0: ("#2B2B14", "#FFD700"),  # Again
        1: ("#2B1414", "#FF6B6B"),  # Hard
        2: ("#14142B", "#6B9FFF"),  # Good
        3: ("#142B14", "#66E39A"),  # Easy
    }
    bg, accent = palette.get(rating, ("#1B1B1B", "#C8C8C8"))
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
        QPushButton:hover {{ border: 1px solid #FFFFFF; color: #FFFFFF; }}
        QPushButton:disabled {{
            background-color: #151515;
            color: #6B6B6B;
            border: 1px solid #252525;
        }}
    """


def _chip_style(accent: str, *, used: bool) -> str:
    if used:
        return """
        QPushButton {
            background-color: #101010;
            color: #9A9A9A;
            border: 1px solid #252525;
            border-radius: 16px;
            padding: 9px 14px;
            font-weight: 900;
            font-size: 14px;
            min-height: 38px;
        }
        QPushButton:hover { border: 1px solid #FFFFFF; }
        """
    return f"""
    QPushButton {{
        background-color: #151515;
        color: #FFFFFF;
        border: 1px solid #2E2E2E;
        border-radius: 16px;
        padding: 9px 14px;
        font-weight: 900;
        font-size: 14px;
        min-height: 38px;
    }}
    QPushButton:hover {{ border: 1px solid {accent}; }}
    """


class SentenceBuilderWidget(QWidget):
    check_clicked = Signal(str)
    rated = Signal(int)  # 0..3
    tip_clicked = Signal()
    translation_clicked = Signal()
    skipped = Signal()

    def __init__(self, accent: str = "#FFB020"):
        super().__init__()
        self._accent = accent

        self._bank: list[tuple[int, str]] = []
        self._used: set[int] = set()
        self._built: list[int] = []

        self._tip_text: str | None = None
        self._tr_text: str | None = None
        self._blur_tip: QGraphicsBlurEffect | None = None
        self._blur_tr: QGraphicsBlurEffect | None = None

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setStyleSheet("""
            SentenceBuilderWidget {
                background-color: #141414;
                border: 1px solid #2A2A2A;
                border-radius: 14px;
            }
            QLabel { color: #E6E6E6; }
        """)

        self._setup_ui()
        self.reset_for_next()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)  # Reduced from 6

        self.prompt = QLabel("Build the sentence")
        self.prompt.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        self.prompt.setStyleSheet("QLabel { color:#FFFFFF; }")
        root.addWidget(self.prompt)

        info_row = QHBoxLayout()
        info_row.setSpacing(10)

        self.tip_btn = QPushButton("Reveal tip")
        self.tip_btn.setFixedHeight(34)
        self.tip_btn.setStyleSheet(_btn_secondary())
        self.tip_btn.clicked.connect(self._on_tip)

        self.tr_btn = QPushButton("Reveal translation")
        self.tr_btn.setFixedHeight(34)
        self.tr_btn.setStyleSheet(_btn_secondary())
        self.tr_btn.clicked.connect(self._on_translation)

        info_row.addWidget(self.tip_btn)
        info_row.addWidget(self.tr_btn)
        info_row.addStretch(1)
        root.addLayout(info_row)

        self.tip_label = QLabel("")
        self.tip_label.setWordWrap(True)
        self.tip_label.setVisible(False)
        self.tip_label.setStyleSheet(
            "QLabel { background:#101010; border:1px solid #2A2A2A; border-radius:10px; padding:10px; }"
        )
        root.addWidget(self.tip_label)

        self.tr_label = QLabel("")
        self.tr_label.setWordWrap(True)
        self.tr_label.setVisible(False)
        self.tr_label.setStyleSheet(
            "QLabel { background:#101010; border:1px solid #2A2A2A; border-radius:10px; padding:10px; color:#B0B0B0; }"
        )
        root.addWidget(self.tr_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("QFrame { background-color:#2A2A2A; margin: 2px 0; }")
        root.addWidget(sep)

        built_title = QLabel("Your sentence (chips)")
        built_title.setStyleSheet("QLabel { font-weight: 900; color:#B0B0B0; }")
        built_title.setContentsMargins(0, 2, 0, 2)
        root.addWidget(built_title)

        self.built_wrap = QWidget()
        self.built_flow = FlowLayout(self.built_wrap, margin=0, hspacing=4, vspacing=4)
        self.built_wrap.setLayout(self.built_flow)
        self.built_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.built_scroll = QScrollArea()
        self.built_scroll.setWidgetResizable(True)
        self.built_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.built_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.built_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.built_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.built_scroll.setWidget(self.built_wrap)
        self.built_scroll.setMinimumHeight(52)
        self.built_scroll.setMaximumHeight(96)
        self.built_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self.built_scroll)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)
        ctrl.setContentsMargins(0, 2, 0, 2)  # Reduced vertical margins

        self.btn_backspace = QPushButton("Backspace")
        self.btn_backspace.setFixedHeight(38)
        self.btn_backspace.setStyleSheet(_btn_secondary())
        self.btn_backspace.clicked.connect(self._backspace)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setFixedHeight(38)
        self.btn_clear.setStyleSheet(_btn_secondary())
        self.btn_clear.clicked.connect(self.clear_sentence)

        ctrl.addWidget(self.btn_backspace)
        ctrl.addWidget(self.btn_clear)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        bank_title = QLabel("Word bank")
        bank_title.setStyleSheet("QLabel { font-weight: 900; color:#B0B0B0; }")
        bank_title.setContentsMargins(0, 2, 0, 2)
        root.addWidget(bank_title)

        self.bank_wrap = QWidget()
        self.bank_flow = FlowLayout(self.bank_wrap, margin=0, hspacing=4, vspacing=4)
        self.bank_wrap.setLayout(self.bank_flow)
        self.bank_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.bank_scroll = QScrollArea()
        self.bank_scroll.setWidgetResizable(True)
        self.bank_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.bank_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.bank_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.bank_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.bank_scroll.setWidget(self.bank_wrap)
        self.bank_scroll.setMinimumHeight(54)
        self.bank_scroll.setMaximumHeight(140)
        self.bank_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self.bank_scroll)

        action = QHBoxLayout()
        action.setSpacing(10)
        action.setContentsMargins(0, 4, 0, 4)

        self.btn_skip = QPushButton("Skip")
        self.btn_skip.setFixedHeight(56)
        self.btn_skip.setMinimumWidth(110)
        self.btn_skip.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
        self.btn_skip.setStyleSheet(
            _btn_colored("#6B9FFF", fg="#0B0B0B")
            + " QPushButton { padding-top: 7px; padding-bottom: 7px; }"
        )
        self.btn_skip.clicked.connect(self._emit_skip)

        self.btn_check = QPushButton("Check")
        self.btn_check.setFixedHeight(56)
        self.btn_check.setMinimumWidth(110)
        self.btn_check.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
        self.btn_check.setStyleSheet(
            _btn_colored("#66E39A", fg="#0B0B0B")
            + " QPushButton { padding-top: 7px; padding-bottom: 7px; }"
        )
        self.btn_check.clicked.connect(lambda: self.check_clicked.emit(self.typed_text()))

        action.addWidget(self.btn_skip)
        action.addStretch(1)
        action.addWidget(self.btn_check)
        root.addLayout(action)

        self.result = QLabel("Press Check to compare your built sentence.")
        self.result.setWordWrap(True)
        self.result.setStyleSheet(
            "QLabel { background:#101010; border:1px solid #2A2A2A; border-radius:10px; padding:10px; color:#B0B0B0; }"
        )
        root.addWidget(self.result)

        rate_row = QHBoxLayout()
        rate_row.setSpacing(10)
        rate_row.setContentsMargins(0, 4, 0, 0)  # Reduced bottom margin

        self.btn_again = QPushButton("Again")
        self.btn_hard = QPushButton("Hard")
        self.btn_good = QPushButton("Good")
        self.btn_easy = QPushButton("Easy")

        for i, b in enumerate([self.btn_again, self.btn_hard, self.btn_good, self.btn_easy]):
            b.setFixedHeight(38)
            b.setStyleSheet(_rating_style(i))
            b.setEnabled(False)
            rate_row.addWidget(b)

        self.btn_again.clicked.connect(lambda: self.rated.emit(0))
        self.btn_hard.clicked.connect(lambda: self.rated.emit(1))
        self.btn_good.clicked.connect(lambda: self.rated.emit(2))
        self.btn_easy.clicked.connect(lambda: self.rated.emit(3))

        root.addLayout(rate_row)
        
    def reset_for_next(self):
        self._bank = []
        self._used = set()
        self._built = []
        self._tip_text = None
        self._tr_text = None

        self.tip_label.setVisible(False)
        self.tr_label.setVisible(False)
        self.tip_label.setGraphicsEffect(None)
        self.tr_label.setGraphicsEffect(None)
        self._blur_tip = None
        self._blur_tr = None

        self.tip_btn.setEnabled(False)
        self.tr_btn.setEnabled(False)

        self.result.setText("Press Check to compare your built sentence.")

        self.btn_check.setEnabled(True)
        self.btn_skip.setEnabled(True)
        for b in (self.btn_again, self.btn_hard, self.btn_good, self.btn_easy):
            b.setEnabled(False)

        try:
            self.bank_flow.clear(delete_widgets=True)
            self.built_flow.clear(delete_widgets=True)
        except Exception:
            logging.exception("FlowLayout.clear() failed")

        self._fit_scroll_heights()

    def set_item(self, *, words: list[str], tip: str | None, translation: str | None):
        self.reset_for_next()
        self._bank = [(i, str(tok)) for i, tok in enumerate(words or [])]
        if len(self._bank) > 1:
            random.shuffle(self._bank)

        self._tip_text = (tip or "").strip() or None
        self._tr_text = (translation or "").strip() or None

        if self._tip_text:
            self.tip_label.setText(self._tip_text)
            self.tip_label.setVisible(True)
            self._blur_tip = QGraphicsBlurEffect()
            self._blur_tip.setBlurRadius(6.0)
            self.tip_label.setGraphicsEffect(self._blur_tip)
            self.tip_btn.setEnabled(True)

        if self._tr_text:
            self.tr_label.setText(self._tr_text)
            self.tr_label.setVisible(True)
            self._blur_tr = QGraphicsBlurEffect()
            self._blur_tr.setBlurRadius(6.0)
            self.tr_label.setGraphicsEffect(self._blur_tr)
            self.tr_btn.setEnabled(True)

        self._rebuild_bank()
        self._rebuild_built()
        self._fit_scroll_heights()

    def typed_text(self) -> str:
        toks = [self._token_for_id(i) for i in self._built]
        toks = [t for t in toks if t]
        return self._join_tokens(toks)

    @staticmethod
    def _join_tokens(tokens: list[str]) -> str:
        no_space_before = {".", ",", "!", "?", ";", ":", ")", "]", "}", "…"}
        no_space_after = {"(", "[", "{", "\"", "„", "“"}
        out: list[str] = []
        for i, tok in enumerate(tokens):
            if i == 0:
                out.append(tok)
                continue
            prev = tokens[i - 1]
            if tok in no_space_before:
                out.append(tok)
            elif prev in no_space_after:
                out.append(tok)
            else:
                out.append(" " + tok)
        return "".join(out)

    def show_result(self, *, ok: bool, expected: str, details: str | None = None):
        badge = "✅ Correct" if ok else "❌ Not quite"
        extra = f"\n\n{details.strip()}" if details and details.strip() else ""
        self.result.setText(f"{badge}\n\nExpected:\n{expected}{extra}")

        for b in (self.btn_again, self.btn_hard, self.btn_good, self.btn_easy):
            b.setEnabled(True)

        self.btn_check.setEnabled(False)
        self.btn_skip.setEnabled(False)
        for btn in self.bank_wrap.findChildren(QPushButton):
            btn.setEnabled(False)
        for btn in self.built_wrap.findChildren(QPushButton):
            btn.setEnabled(False)

    def lock_after_finish(self, message: str):
        self.reset_for_next()
        self.prompt.setText(message)
        self.btn_check.setEnabled(False)
        self.btn_skip.setEnabled(False)
        for b in (self.btn_again, self.btn_hard, self.btn_good, self.btn_easy):
            b.setEnabled(False)

    def _token_for_id(self, token_id: int) -> str:
        for i, t in self._bank:
            if i == token_id:
                return t
        return ""

    def _update_line(self):
        # No longer needed since we removed the QLineEdit
        pass

    def _flow_content_height(self, wrap: QWidget, fallback: int) -> int:
        try:
            wrap.adjustSize()
            hint = wrap.sizeHint()
            h = hint.height()
            if h and h > 0:
                return h
        except Exception:
            pass
        return fallback

    def _fit_scroll_heights(self):
        try:
            # Calculate heights based on content
            built_h = self._flow_content_height(self.built_wrap, 42) + 10
            built_h = max(52, min(built_h, 96))
            self.built_scroll.setFixedHeight(built_h)

            bank_h = self._flow_content_height(self.bank_wrap, 42) + 10
            bank_h = max(54, min(bank_h, 140))
            self.bank_scroll.setFixedHeight(bank_h)

            self.updateGeometry()
        except Exception:
            logging.exception("SentenceBuilderWidget._fit_scroll_heights failed")

    def _rebuild_bank(self):
        try:
            self.bank_flow.clear(delete_widgets=True)

            if not self._bank:
                hint = QLabel("No word bank loaded.", self.bank_wrap)
                hint.setStyleSheet("QLabel { color:#808080; padding: 6px; }")
                hint.setWordWrap(True)
                hint.show()
                self.bank_flow.addWidget(hint)
            else:
                for token_id, tok in self._bank:
                    b = QPushButton(tok, self.bank_wrap)
                    b.setCheckable(True)
                    b.setChecked(token_id in self._used)
                    b.setStyleSheet(_chip_style(self._accent, used=(token_id in self._used)))
                    b.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
                    b.setFocusPolicy(Qt.NoFocus)
                    b.show()
                    b.clicked.connect(lambda checked=False, tid=token_id: self._toggle_token(tid))
                    self.bank_flow.addWidget(b)

            self.bank_flow.invalidate()
            self.bank_wrap.updateGeometry()
            self.bank_wrap.update()
        except Exception:
            logging.exception("SentenceBuilderWidget._rebuild_bank failed")

    def _rebuild_built(self):
        try:
            self.built_flow.clear(delete_widgets=True)

            for token_id in self._built:
                tok = self._token_for_id(token_id)
                b = QPushButton(tok, self.built_wrap)
                b.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #1B1B1B;
                        color: #FFFFFF;
                        border: 1px solid {self._accent};
                        border-radius: 16px;
                        padding: 9px 14px;
                        font-weight: 900;
                        font-size: 14px;
                        min-height: 38px;
                    }}
                    QPushButton:hover {{ border: 1px solid #FFFFFF; }}
                """)
                b.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
                b.setFocusPolicy(Qt.NoFocus)
                b.show()
                b.clicked.connect(lambda checked=False, tid=token_id: self._remove_token(tid))
                self.built_flow.addWidget(b)

            # Removed _update_line() call since we removed the QLineEdit
            self.built_flow.invalidate()
            self.built_wrap.updateGeometry()
            self.built_wrap.update()
        except Exception:
            logging.exception("SentenceBuilderWidget._rebuild_built failed")

    def _toggle_token(self, token_id: int):
        if token_id in self._used:
            self._remove_token(token_id)
            return
        self._used.add(token_id)
        self._built.append(token_id)
        self._prevent_layout_jumps()  # Add this line
        self._rebuild_bank()
        self._rebuild_built()
        self._fit_scroll_heights()

    def _remove_token(self, token_id: int):
        if token_id in self._used:
            self._used.remove(token_id)
        self._built = [i for i in self._built if i != token_id]
        self._prevent_layout_jumps()  # Add this line
        self._rebuild_bank()
        self._rebuild_built()
        self._fit_scroll_heights()

    def _backspace(self):
        if self._built:
            self._prevent_layout_jumps()  # Add this line
            self._remove_token(self._built[-1])

    def clear_sentence(self):
        self._used = set()
        self._built = []
        self._prevent_layout_jumps()  # Add this line
        self._rebuild_bank()
        self._rebuild_built()
        self._fit_scroll_heights()


    def _on_tip(self):
        if self._blur_tip is not None:
            self.tip_label.setGraphicsEffect(None)
            self._blur_tip = None
            self.tip_btn.setEnabled(False)
        self.tip_clicked.emit()

    def _on_translation(self):
        if self._blur_tr is not None:
            self.tr_label.setGraphicsEffect(None)
            self._blur_tr = None
            self.tr_btn.setEnabled(False)
        self.translation_clicked.emit()

    def _emit_skip(self):
        self.skipped.emit()
        
    def _prevent_layout_jumps(self):
        """Prevent layout jumps by fixing heights temporarily"""
        # Store current heights
        built_height = self.built_scroll.height()
        bank_height = self.bank_scroll.height()
        
        # Fix heights to prevent jumping
        self.built_scroll.setFixedHeight(max(52, min(built_height, 96)))
        self.bank_scroll.setFixedHeight(max(54, min(bank_height, 140)))
