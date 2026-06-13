from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)


# German-only app: the special-character set is fixed to German umlauts/ß.
GERMAN_CHARS: List[str] = ["ä", "ö", "ü", "ß", "Ä", "Ö", "Ü"]


def german_chars() -> List[str]:
    return list(GERMAN_CHARS)


class SpecialCharKeyboard(QWidget):
    """
    Small in-app keyboard for special characters.
    Clicking a key inserts into the currently focused input widget.
    """
    char_clicked = Signal(str)

    def __init__(self, chars: List[str] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._chars: List[str] = chars or []

        self.setObjectName("SpecialCharKeyboard")
        self.setStyleSheet("""
            #SpecialCharKeyboard {
                background: transparent;
            }
            QPushButton {
                background-color: #151515;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 6px 10px;
                font-weight: 800;
            }
            QPushButton:hover {
                border: 1px solid #FFFFFF;
                background-color: #1B1B1B;
            }
        """)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

        self._rebuild()

    def set_language(self, lang_code: str | None = None) -> None:
        # German-only app: always load the German character set.
        self.set_chars(german_chars())

    def set_chars(self, chars: List[str]) -> None:
        self._chars = list(chars or [])
        self._rebuild()

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild(self):
        self._clear()

        # Hide completely if no chars
        self.setVisible(bool(self._chars))
        if not self._chars:
            return

        for ch in self._chars:
            b = QPushButton(ch)
            b.setMinimumWidth(44)
            b.setFixedHeight(34)
            b.setFont(QFont("Segoe UI", 10, QFont.Weight.Black))

            # IMPORTANT: don't steal focus from the input field
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)


            b.clicked.connect(lambda checked=False, c=ch: self._insert_char(c))
            self._layout.addWidget(b)

        self._layout.addStretch(1)

    def _insert_char(self, ch: str) -> None:
        # Just emit the signal and let the card widgets handle the insertion!
        self.char_clicked.emit(ch)
