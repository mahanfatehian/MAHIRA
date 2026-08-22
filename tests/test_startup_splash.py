"""The startup banner must not cost a second of every launch.

QSplashScreen.show() blocks for a flat ~1.02 s on Windows with PySide6 6.11
(measured in isolation across repeated runs: 1002-1033 ms). That was roughly a
quarter of a ~4 s startup, spent showing a picture. A plain frameless widget
with the same pixmap paints in well under 20 ms.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_splash_is_not_a_qsplashscreen():
    """The whole point: QSplashScreen is the thing that blocks."""
    from PySide6.QtWidgets import QSplashScreen

    _qapp()
    from mahira.app import _startup_splash

    splash = _startup_splash()
    try:
        assert not isinstance(splash, QSplashScreen)
    finally:
        splash.close()


def test_showing_the_splash_is_fast():
    app = _qapp()
    from mahira.app import _startup_splash

    best = None
    for _ in range(3):
        splash = _startup_splash()
        start = time.perf_counter()
        splash.show()
        app.processEvents()
        elapsed = (time.perf_counter() - start) * 1000.0
        splash.close()
        best = elapsed if best is None else min(best, elapsed)
    assert best < 250.0, f"splash took {best:.1f} ms to show"


def test_it_keeps_the_api_the_startup_path_uses():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor

    app = _qapp()
    from mahira.app import _startup_splash

    splash = _startup_splash()
    try:
        splash.show()
        app.processEvents()
        splash.showMessage(
            "  Checking learner data…",
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            QColor("#9A9A9A"),
        )
        app.processEvents()
        splash.finish(None)
    finally:
        splash.close()


def test_showmessage_tolerates_being_called_without_a_colour():
    app = _qapp()
    from mahira.app import _startup_splash

    splash = _startup_splash()
    try:
        splash.show()
        splash.showMessage("working…")
        app.processEvents()
    finally:
        splash.close()


def test_finish_hides_the_banner():
    app = _qapp()
    from mahira.app import _startup_splash

    splash = _startup_splash()
    splash.show()
    app.processEvents()
    splash.finish(None)
    app.processEvents()
    assert not splash.isVisible()


def test_it_still_carries_its_accessible_name():
    _qapp()
    from mahira.app import _startup_splash

    splash = _startup_splash()
    try:
        assert splash.accessibleName() == "MAHIRA startup status"
    finally:
        splash.close()
