"""Saving a setting must not repolish the entire application.

MainWindow._apply_settings rebuilds the application stylesheet and walks every
widget to rescale typography. It ran on every Save, so changing a daily goal or
a review preference - neither of which changes how anything looks - froze the
UI. Measured over 1375 widgets on the real window: 627 ms median.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Window:
    """Exercises the guard without building a whole MainWindow."""

    from ui.main_window import MainWindow as _MW

    _applied_appearance = None
    _appearance_signature = _MW._appearance_signature
    _apply_settings = _MW._apply_settings

    def __init__(self, font_scale=100, theme="graphite"):
        self.session = SimpleNamespace(
            settings=SimpleNamespace(
                value=SimpleNamespace(font_scale=font_scale, theme=theme)
            )
        )
        self._applied_appearance = self._appearance_signature()


@pytest.fixture(autouse=True)
def _themed(monkeypatch):
    _qapp()
    from ui import main_window

    applied = []
    monkeypatch.setattr(
        main_window, "apply_application_theme", lambda *a: applied.append(a)
    )
    monkeypatch.setattr(
        main_window, "apply_typography_scale", lambda *a: applied.append(a)
    )
    return applied


def test_saving_without_an_appearance_change_does_nothing(_themed):
    window = _Window()
    window._apply_settings()
    window._apply_settings()
    assert _themed == [], "the whole app was repolished for an unrelated setting"


def test_a_font_scale_change_still_reapplies(_themed):
    window = _Window(font_scale=100)
    window.session.settings.value.font_scale = 115
    window._apply_settings()
    assert _themed, "a real appearance change must be applied"


def test_a_theme_change_still_reapplies(_themed):
    window = _Window(theme="graphite")
    window.session.settings.value.theme = "high_contrast"
    window._apply_settings()
    assert _themed


def test_it_reapplies_once_per_change(_themed):
    window = _Window(font_scale=100)
    window.session.settings.value.font_scale = 130
    window._apply_settings()
    count = len(_themed)
    window._apply_settings()
    window._apply_settings()
    assert len(_themed) == count, "repeat saves must not repolish again"


def test_changing_back_reapplies(_themed):
    window = _Window(font_scale=100)
    window.session.settings.value.font_scale = 115
    window._apply_settings()
    window.session.settings.value.font_scale = 100
    window._apply_settings()
    assert len(_themed) >= 2


def test_missing_settings_are_tolerated(_themed):
    window = _Window()
    window.session = SimpleNamespace(settings=None)
    window._apply_settings()
    assert _themed == []
