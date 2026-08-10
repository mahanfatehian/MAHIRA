from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class ReviewSaveError(QLabel):
    """Inline, retry-safe feedback for a failed review transaction."""

    MESSAGE = "Could not save this review. Your answer was not recorded. Try again."

    def __init__(self) -> None:
        super().__init__("")
        self.setObjectName("ReviewSaveError")
        self.setAccessibleName("Review save failed")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "QLabel#ReviewSaveError {"
            " background:#3A1F1F; color:#F7C8C8; border:1px solid #FF6B6B;"
            " border-radius:10px; padding:9px 12px; font-weight:800;"
            "}"
        )
        self.hide()

    def show_failure(self) -> None:
        self.setText(self.MESSAGE)
        self.show()

    def clear_failure(self) -> None:
        self.clear()
        self.hide()
