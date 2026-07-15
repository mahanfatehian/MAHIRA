from __future__ import annotations

import os
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_scoped_theme_keeps_valid_point_fonts_and_legacy_hierarchy():
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    from ui.theme import apply_application_theme

    app = _qapp()
    messages: list[str] = []
    previous = qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(str(message))
    )
    feature = legacy = None
    try:
        apply_application_theme(app, 115, "graphite")
        assert app.font().pointSizeF() > 0
        assert app.font().pixelSize() == -1

        feature = QWidget()
        feature.setProperty("mahiraFeaturePage", True)
        feature_layout = QVBoxLayout(feature)
        feature_label = QLabel("Feature text")
        feature_layout.addWidget(feature_label)
        feature.show()
        feature.ensurePolished()

        legacy = QWidget()
        legacy_label = QLabel("Legacy text", legacy)
        explicit = QFont(legacy_label.font())
        explicit.setPointSize(17)
        legacy_label.setFont(explicit)
        legacy.show()
        legacy.ensurePolished()
        QApplication.processEvents()

        assert feature_label.font().pointSizeF() > 0
        assert legacy_label.font().pointSize() == 17
        assert not [m for m in messages if "QFont::setPointSize" in m]
        assert not [m for m in messages if "Could not parse stylesheet" in m]
    finally:
        if feature is not None:
            feature.close()
            feature.deleteLater()
        if legacy is not None:
            legacy.close()
            legacy.deleteLater()
        qInstallMessageHandler(previous)


@pytest.mark.parametrize("font_scale", [85, 100, 115, 130, 140])
def test_today_semantic_type_scale_preserves_hierarchy_and_cta_text(font_scale):
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    from core.insights import LessonReadiness, StudyLane
    from ui.pages.today import TodayPage
    from ui.theme import apply_application_theme

    app = _qapp()
    apply_application_theme(app, font_scale, "graphite")
    session = SimpleNamespace(
        repo=object(),
        settings=SimpleNamespace(value=SimpleNamespace(daily_goal=30)),
        state=SimpleNamespace(level="A1", book_slug="starten_wir", lektion_number=7),
    )
    page = TodayPage(session)
    page.insights = SimpleNamespace(
        lanes=lambda: [
            StudyLane(objective, 12, 5, 3)
            for objective in ("vocab", "grammar", "sentences", "listening")
        ],
        reviewed_today=lambda: 11,
        lesson_path=lambda *_args: [
            LessonReadiness(7, "Mein Tag und Termine", 62, True)
        ],
    )
    page.resize(674, 700)  # 860px window minus nav, margins, and gutter
    page.on_show()
    page.show()
    try:
        QApplication.processEvents()
        labels = {label.text(): label for label in page.findChildren(QLabel)}
        title_size = labels["Today"].font().pointSizeF()
        section_size = labels["Study lanes"].font().pointSizeF()
        lane_size = labels["Wortschatz"].font().pointSizeF()
        body_label = next(
            label
            for label in page.findChildren(QLabel)
            if label.text().startswith("Words, articles and plurals")
        )
        body_size = body_label.font().pointSizeF()

        assert title_size == pytest.approx(15 * font_scale / 100, abs=0.05)
        assert section_size == pytest.approx(11 * font_scale / 100, abs=0.05)
        assert title_size > section_size == lane_size > body_size

        lane_buttons = [
            button
            for button in page.findChildren(QPushButton)
            if button.text() == "Review"
        ]
        assert len(lane_buttons) == 4
        for button in lane_buttons:
            assert button.width() >= button.sizeHint().width()
            assert button.maximumWidth() > button.minimumWidth()
    finally:
        page.close()
        page.deleteLater()


def test_stepper_and_audio_controls_are_not_pixel_font_locked(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ui.pages.settings import SettingsPage
    from ui.theme import apply_application_theme
    from ui.widgets.audio_button import AudioButton

    app = _qapp()
    apply_application_theme(app, 140, "graphite")
    db_path = tmp_path / "mahira.db"
    db_path.touch()
    session = SimpleNamespace(
        repo=SimpleNamespace(db_path=db_path),
        settings=None,
    )
    page = SettingsPage(session)
    audio = AudioButton()
    page.resize(920, 1800)
    page.show()
    audio.show()
    try:
        QApplication.processEvents()
        for stepper in (page.daily_goal, page.session_limit, page.new_limit):
            for button in (stepper.minus, stepper.plus):
                assert button.width() >= button.sizeHint().width()
                assert button.maximumWidth() > button.minimumWidth()

        assert audio.font().pointSizeF() > 0
        assert audio.font().pixelSize() == -1
    finally:
        page._stop_background()
        page.close()
        page.deleteLater()
        audio.close()
        audio.deleteLater()


class _PracticeRepo:
    def __init__(self):
        from db.repo import VocabItem

        self.items = {
            1: VocabItem(1, 7, "noun", "Haus", "house", "das", "n", None, "Häuser"),
            2: VocabItem(2, 7, "verb", "lernen", "to learn", None, None, None, None),
        }

    def get_vocab_by_id(self, item_id: int):
        return self.items.get(item_id)


class _PracticeSession:
    def __init__(self):
        self.repo = _PracticeRepo()
        self.plan = SimpleNamespace(limit=10)
        self.settings = SimpleNamespace(
            value=SimpleNamespace(audio_autoplay=False, audio_speed=1.0)
        )
        self.picker_calls: list[str] = []
        self.submit_calls: list[tuple[int, str, str]] = []

    def vocab_deck_id(self):
        return 7

    def context_label(self):
        return "A1 · Starten Wir · Lektion 7"

    def pick_vocab_practice_ids(self, practice_mode: str, **_kwargs):
        self.picker_calls.append(practice_mode)
        return [1, 2]

    def submit_vocab_production(self, item, typed: str, *, practice_mode: str, **_kwargs):
        self.submit_calls.append((item.id, typed, practice_mode))
        return {
            "ok": True,
            "message": "Correct.",
            "expected": item.word,
        }


def test_practice_lab_exposes_modes_and_routes_to_isolated_lane():
    from PySide6.QtWidgets import QApplication

    from ui.pages.practice_lab import PracticeLabPage

    _qapp()
    session = _PracticeSession()
    page = PracticeLabPage(session)
    page.resize(860, 680)
    page.show()
    try:
        page.on_show()
        QApplication.processEvents()
        assert session.picker_calls == ["production"]
        assert page.mode_buttons["production"].isChecked()
        assert not page.play_btn.isVisible()

        page.mode_buttons["dictation"].click()
        QApplication.processEvents()
        assert session.picker_calls[-1] == "dictation"
        assert page.mode_buttons["dictation"].isChecked()
        assert page.play_btn.isVisible()

        page.mode_buttons["production"].click()
        page.answer.setText("lernen")
        page.action.click()
        assert session.submit_calls[-1] == (2, "lernen", "production")
        assert page.action.text() == "Next card"
        assert page.session_chip.text() == "1 practiced"
    finally:
        page._stop_audio()
        page.close()
        page.deleteLater()


def test_practice_lab_can_preselect_mode_without_double_loading():
    from ui.pages.practice_lab import PracticeLabPage

    _qapp()
    session = _PracticeSession()
    page = PracticeLabPage(session)
    try:
        assert page.select_mode("dictation", reload=False)
        assert page.mode_buttons["dictation"].isChecked()
        assert page.mode_label.text() == "AUDIO → GERMAN"
        assert session.picker_calls == []

        page.on_show()
        assert session.picker_calls == ["dictation"]

        assert not page.select_mode("unknown", reload=False)
        assert page.mode_buttons["dictation"].isChecked()
        assert session.picker_calls == ["dictation"]
    finally:
        page._stop_audio()
        page.close()
        page.deleteLater()


def test_settings_use_step_controls_and_save_inline(tmp_path):
    from PySide6.QtWidgets import QSpinBox

    from core.profiles import ProfileService
    from core.settings import SettingsService
    from ui.pages.settings import SettingsPage

    _qapp()
    db_path = tmp_path / "mahira.db"
    db_path.touch()
    settings = SettingsService(tmp_path / "settings.json")
    session = SimpleNamespace(
        repo=SimpleNamespace(db_path=db_path),
        settings=settings,
        profiles=ProfileService(tmp_path),
        plan=SimpleNamespace(limit=30, new_limit=8),
    )
    page = SettingsPage(session)
    page.resize(860, 1000)
    page.show()
    changed: list[bool] = []
    page.settings_changed.connect(lambda: changed.append(True))
    try:
        page.on_show()
        assert not page.findChildren(QSpinBox)
        assert page.daily_goal.value() == 30
        assert not page.save_button.isEnabled()

        page.daily_goal.plus.click()
        assert page.daily_goal.value() == 35
        assert page.save_button.isEnabled()
        assert page.save_status.text() == "Unsaved changes"

        page.save_button.click()
        assert changed == [True]
        assert settings.value.daily_goal == 35
        assert page.save_status.text() == "Saved"
        assert not page.save_button.isEnabled()
    finally:
        page._stop_background()
        page.close()
        page.deleteLater()
