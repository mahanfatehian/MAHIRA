"""TTS is optional: a missing piper stack must not take the app down."""

from __future__ import annotations

import pytest


def test_importing_core_audio_does_not_import_piper(monkeypatch):
    """core.audio must load without the piper package being present."""
    import builtins
    import sys

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "piper" or name.startswith("piper."):
            raise ImportError("piper deliberately unavailable in this test")
        return real_import(name, *args, **kwargs)

    # Drop any already-loaded piper modules so the block is meaningful.
    for key in list(sys.modules):
        if key == "piper" or key.startswith("piper."):
            monkeypatch.delitem(sys.modules, key, raising=False)

    monkeypatch.setattr(builtins, "__import__", blocked)

    # Re-import the manager module under the blocked import.
    import importlib

    import core.audio.model_manager as manager_module

    importlib.reload(manager_module)

    manager = manager_module.PiperModelManager()
    assert manager.is_available() is False

    with pytest.raises(manager_module.PiperUnavailableError):
        manager.get_german_voice()

    # Restore a clean module state for later tests.
    monkeypatch.undo()
    importlib.reload(manager_module)


def test_review_pages_construct_when_piper_is_missing(monkeypatch):
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from core.audio import model_manager as manager_module

    def boom():
        raise manager_module.PiperUnavailableError("no piper")

    monkeypatch.setattr(manager_module, "_load_piper_voice_class", boom)

    QApplication.instance() or QApplication([])

    class _Session:
        def __getattr__(self, name):
            return lambda *a, **k: None

    from ui.pages.listening_review import ListeningReviewPage
    from ui.pages.sentence_review import SentenceReviewPage
    from ui.pages.vocab_review import VocabReviewPage

    session = _Session()
    pages = [
        VocabReviewPage(session),
        SentenceReviewPage(session),
        ListeningReviewPage(session),
    ]
    for page in pages:
        assert page is not None
        page.deleteLater()
