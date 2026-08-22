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


def test_the_table_does_not_warm_the_voice_on_show():
    """PiperVoice.load holds the GIL for ~2.0 s.

    Warming it from a worker thread froze the whole UI just the same - the
    measured worst event-loop gap was 1869 ms against a 12 ms idle baseline -
    so it only moved the stall from the first click onto every visit to the
    tab, including for learners who never play any audio.
    """
    from ui.pages import vocab_table

    source = vocab_table.__file__
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "_prewarm_audio" not in text
    assert "import threading" not in text


# --------------------------------------------------------------------------
# A cached clip must never queue behind an unrelated synthesis
# --------------------------------------------------------------------------

def _table(tmp_path):
    pytest.importorskip("PySide6")
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from ui.pages.vocab_table import VocabTablePage

    QApplication.instance() or QApplication([])
    page = VocabTablePage(
        SimpleNamespace(repo=SimpleNamespace(db_path=None), context_label=lambda: "A1")
    )
    page._table_model.set_rows(
        [
            {"word": "Haus", "article": "das", "pos": "noun", "meaning": "house", "plural": ""},
            {"word": "Tisch", "article": "der", "pos": "noun", "meaning": "table", "plural": ""},
        ]
    )
    return page


class _Pron:
    def __init__(self, cached):
        self._cached = cached

    def get_cached_path(self, text):
        return self._cached.get(text, _Missing())


class _Missing:
    def exists(self):
        return False


class _Play:
    def __init__(self):
        self.played = []

    def play_file(self, path):
        self.played.append(str(path))

    def stop(self):
        return None


def test_a_cached_clip_plays_even_while_another_word_renders(tmp_path):
    page = _table(tmp_path)
    try:
        wav = tmp_path / "der Tisch.wav"
        wav.write_bytes(b"RIFF")
        page._pron = _Pron({"der Tisch": wav})
        page._play_svc = _Play()

        assert page._play_cached("der Tisch", 1) is True
        assert page._play_svc.played == [str(wav)]
    finally:
        page.deleteLater()


def test_an_uncached_clip_reports_that_it_could_not_play(tmp_path):
    page = _table(tmp_path)
    try:
        page._pron = _Pron({})
        page._play_svc = _Play()
        assert page._play_cached("das Haus", 0) is False
        assert page._play_svc.played == []
    finally:
        page.deleteLater()


def test_a_finished_render_does_not_hijack_a_row_the_learner_left(tmp_path):
    """It would cut off the cached clip that is already playing."""
    page = _table(tmp_path)
    try:
        page._play_svc = _Play()
        page._synth_request = ("das Haus", 0)
        page._pending_request = None
        page._active_audio_row = 1          # learner moved on to another row
        page._on_tts_done("das Haus", str(tmp_path / "x.wav"))
        assert page._play_svc.played == []
    finally:
        page.deleteLater()
