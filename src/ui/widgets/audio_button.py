from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPushButton


class AudioButton(QPushButton):
    """
    Small pronunciation button with stable visual states.

    States:
    - idle: visible/clickable 🔊
    - busy: generating audio, disabled …
    - playing: stealth disabled 🔈 until audio finishes
    """

    def __init__(self, parent=None) -> None:
        super().__init__("🔊", parent)

        self._idle_text = "🔊"
        self._busy_text = "…"
        self._playing_text = "🔈"

        self._available = True
        self._busy = False
        self._playing = False

        self.setToolTip("Play pronunciation")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 42)
        self.setObjectName("AudioButton")
        icon_font = QFont(self.font())
        # Point units avoid the pointSize == -1 state produced by a pixel-sized
        # QSS font while keeping the established 18px-equivalent icon scale.
        icon_font.setPointSize(13)
        icon_font.setWeight(QFont.Weight.Black)
        self.setFont(icon_font)

        self._sync_state()

    def set_available(self, available: bool) -> None:
        self._available = bool(available)
        self._sync_state()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        if self._busy:
            self._playing = False
        self._sync_state()

    def set_playing(self, playing: bool) -> None:
        self._playing = bool(playing)
        if self._playing:
            self._busy = False
        self._sync_state()

    def reset_state(self) -> None:
        self._busy = False
        self._playing = False
        self._sync_state()

    def _sync_state(self) -> None:
        if self._busy:
            self.setText(self._busy_text)
            self.setToolTip("Preparing pronunciation...")
        elif self._playing:
            self.setText(self._playing_text)
            self.setToolTip("Playing pronunciation...")
        else:
            self.setText(self._idle_text)
            self.setToolTip("Play pronunciation")

        self.setEnabled(self._available and not self._busy and not self._playing)

        if self._playing:
            self.setStyleSheet(
                """
                QPushButton#AudioButton {
                    background-color: #111111;
                    color: #8A8A8A;
                    border: 1px solid #242424;
                    border-radius: 12px;
                }
                QPushButton#AudioButton:focus { border: 1px solid #7AE582; }
                QPushButton#AudioButton:disabled {
                    background-color: #111111;
                    color: #8A8A8A;
                    border: 1px solid #242424;
                }
                """
            )
            return

        if self._busy:
            self.setStyleSheet(
                """
                QPushButton#AudioButton {
                    background-color: #151515;
                    color: #8A8A8A;
                    border: 1px solid #252525;
                    border-radius: 12px;
                }
                QPushButton#AudioButton:focus { border: 1px solid #7AE582; }
                QPushButton#AudioButton:disabled {
                    background-color: #151515;
                    color: #8A8A8A;
                    border: 1px solid #252525;
                }
                """
            )
            return

        self.setStyleSheet(
            """
            QPushButton#AudioButton {
                background-color: #1B1B1B;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 12px;
            }
            QPushButton#AudioButton:hover {
                background-color: #232323;
                border: 1px solid #FFFFFF;
            }
            QPushButton#AudioButton:pressed {
                background-color: #111111;
            }
            QPushButton#AudioButton:focus {
                border: 1px solid #7AE582;
            }
            QPushButton#AudioButton:disabled {
                background-color: #151515;
                color: #6B6B6B;
                border: 1px solid #252525;
            }
            """
        )
