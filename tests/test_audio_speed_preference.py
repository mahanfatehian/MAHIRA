"""The Speaking speed setting must reach every review lane that plays audio."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.settings import AppSettings, SettingsService, preferred_audio_speed


def test_preferred_speed_defaults_to_normal():
    assert preferred_audio_speed(None) == 1.0
    assert preferred_audio_speed(AppSettings()) == 1.0


@pytest.mark.parametrize("speed", [0.75, 1.0, 1.25])
def test_preferred_speed_reads_app_settings(speed):
    assert preferred_audio_speed(AppSettings(audio_speed=speed)) == speed


def test_preferred_speed_reads_a_settings_service(tmp_path):
    service = SettingsService(tmp_path / "settings.json")
    service.update(audio_speed=0.75)
    assert preferred_audio_speed(service) == 0.75


def test_preferred_speed_reads_a_session_like_object(tmp_path):
    service = SettingsService(tmp_path / "settings.json")
    service.update(audio_speed=1.25)
    session = SimpleNamespace(settings=service)
    assert preferred_audio_speed(session) == 1.25


def test_preferred_speed_rejects_out_of_band_values():
    assert preferred_audio_speed(SimpleNamespace(audio_speed=2.0)) == 1.0
    assert preferred_audio_speed(SimpleNamespace(audio_speed="fast")) == 1.0


def test_vocab_review_applies_the_setting_on_show(tmp_path):
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ui.pages.vocab_review import VocabReviewPage

    QApplication.instance() or QApplication([])
    service = SettingsService(tmp_path / "settings.json")
    service.update(audio_speed=0.75)

    class _Session:
        settings = service

        def context_label(self):
            return ""

        def active_deck_id(self):
            return None

        def __getattr__(self, name):
            return lambda *_a, **_k: None

    page = VocabReviewPage(_Session())
    page.on_show()
    assert page._speed == 0.75
    page.deleteLater()


def test_listening_review_applies_the_setting_on_show(tmp_path):
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ui.pages.listening_review import ListeningReviewPage

    QApplication.instance() or QApplication([])

    service = SettingsService(tmp_path / "settings.json")
    service.update(audio_speed=1.25)

    class _Session:
        settings = service
        state = SimpleNamespace(objective="listening")

        def context_label(self):
            return ""

        def active_deck_id(self):
            return None

        def __getattr__(self, name):
            return lambda *a, **k: None

    page = ListeningReviewPage(_Session())
    page.on_show()
    assert page._speed == 1.25
    page.deleteLater()
