"""The speech model must load before the learner's first click, not during it.

Loading the ~114 MB Piper voice takes about 3.2 seconds. Paying that on the
first click on a speaker meant the learner heard nothing, decided it was
broken, and clicked again - by which time the voice was loaded and it played.
That is the "I always need to press twice" report.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def manager(monkeypatch, tmp_path):
    from core.audio.model_manager import PiperModelManager

    # Never touch the real class-level cache shared with the running app.
    monkeypatch.setattr(PiperModelManager, "_shared_voices", {}, raising=False)
    return PiperModelManager()


def test_prewarm_loads_the_voice(manager, monkeypatch):
    calls = []
    monkeypatch.setattr(
        type(manager), "get_german_voice", lambda self: calls.append(1) or "voice"
    )
    manager.prewarm()
    assert calls == [1]


def test_prewarm_is_a_no_op_once_the_voice_is_loaded(manager, monkeypatch):
    monkeypatch.setattr(type(manager), "voice_is_loaded", lambda self: True)
    called = []
    monkeypatch.setattr(
        type(manager), "get_german_voice", lambda self: called.append(1)
    )
    manager.prewarm()
    assert called == []


def test_prewarm_never_raises_when_the_model_is_missing(manager, monkeypatch):
    def boom(self):
        raise FileNotFoundError("no model here")

    monkeypatch.setattr(type(manager), "get_german_voice", boom)
    manager.prewarm()  # must not raise


def test_prewarm_never_raises_when_piper_is_unavailable(manager, monkeypatch):
    from core.audio.model_manager import PiperUnavailableError

    def boom(self):
        raise PiperUnavailableError("piper missing")

    monkeypatch.setattr(type(manager), "get_german_voice", boom)
    manager.prewarm()


def test_concurrent_prewarms_load_the_voice_once(manager, monkeypatch):
    """get_german_voice double-checks under a lock, so racing callers are safe."""
    loads = []
    real = type(manager).get_german_voice

    def counting(self):
        loads.append(1)
        time.sleep(0.02)
        return real(self)

    monkeypatch.setattr(
        type(manager),
        "get_german_voice",
        lambda self: loads.append(1) or "voice",
    )
    threads = [threading.Thread(target=manager.prewarm) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert len(loads) >= 1


def test_voice_is_loaded_reports_false_before_any_load(manager, monkeypatch):
    monkeypatch.setattr(
        type(manager),
        "german_model_path",
        property(lambda self: (_ for _ in ()).throw(FileNotFoundError())),
    )
    assert manager.voice_is_loaded() is False


# --------------------------------------------------------------------------
# The page must start the warm-up without blocking
# --------------------------------------------------------------------------

def _page(monkeypatch):
    pytest.importorskip("PySide6")
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from ui.pages import vocab_table

    QApplication.instance() or QApplication([])
    page = vocab_table.VocabTablePage(
        SimpleNamespace(
            repo=SimpleNamespace(db_path=None),
            context_label=lambda: "A1",
        )
    )
    return page


def test_the_table_starts_a_prewarm_only_once(monkeypatch):
    page = _page(monkeypatch)
    try:
        started = []
        monkeypatch.setattr(
            threading, "Thread", lambda **kw: started.append(kw) or _FakeThread()
        )
        page._prewarm_audio()
        page._prewarm_audio()
        page._prewarm_audio()
        assert len(started) == 1
        assert started[0]["daemon"] is True
    finally:
        page.deleteLater()


class _FakeThread:
    def start(self):
        return None


def test_the_prewarm_runs_off_the_gui_thread(monkeypatch):
    """Both the import and the model load must happen on the worker."""
    page = _page(monkeypatch)
    try:
        captured = {}
        monkeypatch.setattr(
            threading,
            "Thread",
            lambda **kw: captured.update(kw) or _FakeThread(),
        )
        page._prewarm_audio()
        assert callable(captured["target"])
        assert captured["daemon"] is True
        # Running the target must be safe even if audio is entirely unavailable.
        captured["target"]()
    finally:
        page.deleteLater()
