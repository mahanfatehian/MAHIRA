"""Shared review-lane button hardening."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


def harden_skip_button(button: QPushButton) -> None:
    """Keep Skip clickable without letting Space fire it by accident.

    QPushButton activates on Space whenever it has keyboard focus. In the
    listening and sentence lanes there is no text field to hold focus, so the
    first focusable control is often Skip — and a single Space silently lapses
    the card. TabFocus still lets keyboard users reach Skip on purpose; a mouse
    click activates without stealing focus for the next Space press.
    """
    button.setAutoDefault(False)
    button.setDefault(False)
    button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
