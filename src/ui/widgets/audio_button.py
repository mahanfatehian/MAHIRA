from __future__ import annotations

from PySide6.QtWidgets import QPushButton


class AudioButton(QPushButton):
    def __init__(self, parent=None) -> None:
        super().__init__("🔊", parent)
        self._idle_text = "🔊"
        self._busy_text = "…"
        self.setToolTip("Play pronunciation")
        self.setFixedWidth(42)
        self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)
        self.setText(self._busy_text if busy else self._idle_text)
