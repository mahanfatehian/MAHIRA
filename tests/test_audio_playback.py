"""PlaybackService — regression test for the stale-source bug.

The bug: switching from one clip to another (e.g. the word -> its example)
played the PREVIOUS clip on the first click, because QSoundEffect could still
report the old source as Ready right after setSource(). The fix never calls
play() until the NEW source reports Ready. These tests drive a fake effect so
the state machine can be checked deterministically without an audio device.
"""

import os
from pathlib import Path

import pytest


def _qapp():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _fake_effect_cls():
    from PySide6.QtMultimedia import QSoundEffect
    from PySide6.QtCore import QUrl

    READY = QSoundEffect.Status.Ready
    LOADING = QSoundEffect.Status.Loading

    class FakeEffect:
        def __init__(self):
            self._status = READY      # pretend a PREVIOUS clip is loaded + ready
            self._src = QUrl()
            self.plays = []
            self._playing = False

        def status(self): return self._status
        def source(self): return self._src
        def setSource(self, url):
            self._src = url
            self._status = LOADING    # a real effect leaves Ready while loading
        def play(self):
            self.plays.append(self._src.toLocalFile())
            self._playing = True
        def isPlaying(self): return self._playing
        def stop(self): self._playing = False
        def setLoopCount(self, *a): pass
        def setVolume(self, *a): pass

    return FakeEffect, READY


def test_new_clip_never_plays_a_stale_source(tmp_path):
    _qapp()
    from core.audio.playback_service import PlaybackService

    FakeEffect, READY = _fake_effect_cls()
    svc = PlaybackService()
    fake = FakeEffect()
    svc.effect = fake

    wav = tmp_path / "example.wav"
    wav.write_bytes(b"RIFFfake")

    # Switching to a new clip must NOT play while the effect could still be on
    # the previous source (status just went to Loading).
    svc.play_file(wav)
    assert fake.plays == [], "must not play the previous/stale clip on switch"

    # Only once the NEW source reports Ready does it play — exactly once.
    fake._status = READY
    svc._on_status_changed()
    assert len(fake.plays) == 1
    assert Path(fake.plays[0]) == wav.resolve()


def test_same_loaded_clip_replays_immediately(tmp_path):
    _qapp()
    from PySide6.QtCore import QUrl
    from core.audio.playback_service import PlaybackService

    FakeEffect, READY = _fake_effect_cls()
    svc = PlaybackService()
    fake = FakeEffect()
    svc.effect = fake

    wav = tmp_path / "w.wav"
    wav.write_bytes(b"RIFFfake")

    # The exact clip is already loaded and Ready -> replay without waiting.
    fake._src = QUrl.fromLocalFile(str(wav.resolve()))
    fake._status = READY
    svc.play_file(wav)
    assert len(fake.plays) == 1
    assert Path(fake.plays[0]) == wav.resolve()


def test_missing_file_emits_failed(tmp_path):
    _qapp()
    from core.audio.playback_service import PlaybackService

    FakeEffect, _ = _fake_effect_cls()
    svc = PlaybackService()
    svc.effect = FakeEffect()

    errors = []
    svc.failed.connect(lambda m: errors.append(m))
    svc.play_file(tmp_path / "does_not_exist.wav")
    assert errors and "does not exist" in errors[0].lower()


def test_directory_path_emits_failed_without_loading(tmp_path):
    _qapp()
    from core.audio.playback_service import PlaybackService

    FakeEffect, _ = _fake_effect_cls()
    svc = PlaybackService()
    fake = FakeEffect()
    svc.effect = fake

    errors = []
    svc.failed.connect(lambda message: errors.append(message))
    svc.play_file(tmp_path)

    assert errors and "not a file" in errors[0].lower()
    assert fake.source().isEmpty()


def test_stale_poll_callbacks_do_not_shorten_latest_timeout(tmp_path, monkeypatch):
    _qapp()
    from core.audio import playback_service as playback_module

    FakeEffect, _ = _fake_effect_cls()
    callbacks = []

    class FakeTimer:
        @staticmethod
        def singleShot(_delay, callback):
            callbacks.append(callback)

    monkeypatch.setattr(playback_module, "QTimer", FakeTimer)
    svc = playback_module.PlaybackService()
    svc.effect = FakeEffect()
    errors = []
    svc.failed.connect(lambda message: errors.append(message))

    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first.write_bytes(b"RIFFfirst")
    second.write_bytes(b"RIFFsecond")

    svc.play_file(first)
    stale_callback = callbacks.pop(0)
    svc.play_file(second)
    assert svc._poll_left == 60

    stale_callback()
    assert svc._poll_left == 60
    assert svc._pending_play is True
    assert errors == []

    for _ in range(60):
        callbacks.pop(0)()

    assert svc._pending_play is False
    assert errors == ["Audio took too long to load."]
    assert callbacks == []
