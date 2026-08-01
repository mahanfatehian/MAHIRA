from __future__ import annotations

import os
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_page_constructor_type_error_is_not_retried(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QWidget

    import ui.main_window as main_window_module

    app = QApplication.instance() or QApplication([])
    calls = 0

    class BrokenPage(QWidget):
        def __init__(self, _session, _nav=None):
            nonlocal calls
            calls += 1
            raise TypeError("page setup failed")

    monkeypatch.setattr(main_window_module, "TodayPage", BrokenPage)

    with pytest.raises(TypeError, match="page setup failed"):
        main_window_module.MainWindow(SimpleNamespace())

    assert calls == 1
    app.processEvents()
