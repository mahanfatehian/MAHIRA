from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_window_defers_destruction_until_blocking_worker_finishes():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication, QMainWindow

    from ui.main_window import MainWindow

    # Bound deliberately: the QApplication must outlive this scope or Qt tears
    # down while the worker thread is still running.
    app = QApplication.instance() or QApplication([])  # noqa: F841

    class SlowWorkerThread(QThread):
        def run(self) -> None:
            time.sleep(0.20)

    class ShutdownHarness(MainWindow):
        def __init__(self, worker) -> None:
            QMainWindow.__init__(self)
            self.session = SimpleNamespace(settings=None)
            self.pages = {"slow": SimpleNamespace(_audio_thread=worker)}
            self._shutdown_started = False
            self._close_pending = False

    worker = SlowWorkerThread()
    window = ShutdownHarness(worker)
    window.show()
    worker.start()
    try:
        # The first close is ignored while the worker is genuinely executing;
        # the QThread remains parent-safe and the GUI event loop keeps running.
        assert window.close() is False
        assert window.isVisible()

        deadline = time.monotonic() + 2.0
        while window.isVisible() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

        assert not worker.isRunning()
        assert not window.isVisible()
    finally:
        worker.wait(1000)
        window.close()
        window.deleteLater()
        QApplication.processEvents()
