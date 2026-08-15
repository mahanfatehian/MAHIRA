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


def test_legacy_typography_scale_is_reversible_and_non_compounding():
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

    from ui.theme import apply_typography_scale

    _qapp()
    root = QWidget()
    layout = QVBoxLayout(root)
    styled = QLabel("Styled")
    styled.setStyleSheet("QLabel { font-size: 13px; color: #FFFFFF; }")
    explicit = QLabel("Explicit")
    explicit_font = QFont(explicit.font())
    explicit_font.setPointSizeF(10.0)
    explicit.setFont(explicit_font)
    layout.addWidget(styled)
    layout.addWidget(explicit)

    apply_typography_scale(root, 140)
    assert "font-size: 18.20px" in styled.styleSheet()
    assert explicit.font().pointSizeF() == pytest.approx(14.0, abs=0.05)

    apply_typography_scale(root, 100)
    assert "font-size: 13.00px" in styled.styleSheet()
    assert explicit.font().pointSizeF() == pytest.approx(10.0, abs=0.05)

    apply_typography_scale(root, 140)
    assert "font-size: 18.20px" in styled.styleSheet()
    assert explicit.font().pointSizeF() == pytest.approx(14.0, abs=0.05)


def test_navigation_typography_uses_the_same_scale_preference():
    from ui.navigation import NavBar
    from ui.theme import apply_typography_scale

    _qapp()
    nav = NavBar()
    apply_typography_scale(nav, 140)

    assert "font-size: 18.20px" in nav.btn_today.styleSheet()


def test_navigation_exposes_a_clear_current_page_state():
    from ui.navigation import NavBar

    _qapp()
    nav = NavBar()

    assert nav.btn_today.property("current") is True
    assert nav.btn_today.accessibleDescription() == "Current page"
    assert nav.btn_today.toolTip() == "Current page"
    assert not nav.btn_today.isEnabled()
    assert "#4CAF50" in nav.btn_today.styleSheet()
    assert "#F4FFF7" in nav.btn_today.styleSheet()
    assert "#9E9E9E" not in nav.btn_today.styleSheet()

    nav.set_objective_states({"vocab"})
    nav.set_active("vocab")

    assert nav.btn_today.property("current") is False
    assert nav.btn_today.accessibleDescription() == ""
    assert nav.btn_today.isEnabled()
    assert nav.btn_vocab.property("current") is True
    assert nav.btn_vocab.accessibleDescription() == "Current page"
    assert not nav.btn_vocab.isEnabled()
    assert nav.btn_grammar.accessibleDescription() == "Unavailable for the selected lesson"
    assert not nav.btn_grammar.isEnabled()


def test_activity_heatmap_fits_a_narrow_progress_column():
    import datetime as dt

    from PySide6.QtWidgets import QApplication

    from ui.widgets.activity_heatmap import ActivityHeatmap

    _qapp()
    heatmap = ActivityHeatmap(weeks=53)
    heatmap.resize(610, heatmap.heightForWidth(610))
    heatmap.set_data({}, goal=20, today=dt.date(2026, 7, 20))
    heatmap.show()
    try:
        QApplication.processEvents()
        assert heatmap._hot
        assert max(rect.right() for rect, _day, _count in heatmap._hot) <= heatmap.width()
    finally:
        heatmap.close()
        heatmap.deleteLater()


def test_progress_activity_uses_all_time_streaks_and_calendar_year_counts(monkeypatch):
    import datetime as dt

    import ui.pages.progress as progress_module

    class FixedDate(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 1)

    old_streak = {
        (dt.date(2024, 1, 1) + dt.timedelta(days=offset)).isoformat(): 1
        for offset in range(10)
    }
    counts = old_streak | {
        "2025-08-01": 7,
        "2026-07-31": 1,
        "2026-08-01": 1,
    }
    requested_since: list[int] = []

    class Repo:
        def daily_review_counts(self, since):
            requested_since.append(since)
            return counts

    session = SimpleNamespace(
        repo=Repo(),
        settings=SimpleNamespace(value=SimpleNamespace(daily_goal=30)),
    )
    monkeypatch.setattr(progress_module._dt, "date", FixedDate)
    _qapp()
    page = progress_module.ProgressPage(session)
    try:
        page._refresh_activity()

        assert requested_since == [0]
        assert page.longest_value.text() == "10"
        assert page.streak_value.text() == "2"
        assert "2 reviews this year" in page.activity_caption.text()
        assert "2 active days" in page.activity_caption.text()
        assert "9 reviews this year" not in page.activity_caption.text()
    finally:
        page.close()
        page.deleteLater()


def test_progress_activity_uses_snapshot_local_date_for_all_daily_views(monkeypatch):
    import datetime as dt

    import ui.pages.progress as progress_module

    snapshot_day = dt.date(2025, 12, 31)
    captured_at = int(dt.datetime(2025, 12, 31, 12, 0).timestamp())

    class LaterSystemDate(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 1, 2)

    counts = {
        "2025-12-29": 1,
        "2025-12-30": 1,
        "2025-12-31": 2,
    }
    session = SimpleNamespace(
        repo=SimpleNamespace(daily_review_counts=lambda _since: counts),
        settings=SimpleNamespace(value=SimpleNamespace(daily_goal=30)),
    )
    snapshot = SimpleNamespace(
        captured_at=captured_at,
        completed_total=2,
        goal=5,
    )
    monkeypatch.setattr(progress_module._dt, "date", LaterSystemDate)

    _qapp()
    page = progress_module.ProgressPage(session)
    try:
        page._refresh_activity(snapshot)

        assert page.heatmap._today == snapshot_day
        assert page.streak_value.text() == "3"
        assert page.today_value.text() == "2 / 5"
        assert "4 reviews this year" in page.activity_caption.text()
        assert "3 active days" in page.activity_caption.text()
    finally:
        page.close()
        page.deleteLater()


def test_progress_activity_failure_is_explicit_not_a_plausible_zero():
    import ui.pages.progress as progress_module

    class Repo:
        def daily_review_counts(self, _since):
            raise RuntimeError("database read failed")

    session = SimpleNamespace(
        repo=Repo(),
        settings=SimpleNamespace(value=SimpleNamespace(daily_goal=30)),
    )
    _qapp()
    page = progress_module.ProgressPage(session)
    try:
        page._refresh_activity()

        assert page.streak_value.text() == "--"
        assert page.longest_value.text() == "--"
        assert "unavailable" in page.activity_caption.text().casefold()
        assert "reviews were not changed" in page.activity_caption.text().casefold()
    finally:
        page.close()
        page.deleteLater()


@pytest.mark.parametrize(
    ("checks", "expected"),
    [
        ((True, True, True), 3),
        ((True, True, False), 2),
        ((True, False, False), 1),
        ((False, False, False), 0),
        ((None, None, None), 2),
    ],
)
def test_vocab_card_rating_matches_correct_field_count(checks, expected):
    from ui.widgets.card_widget import CardWidget

    assert CardWidget._recommend_from_checks(*checks) == expected


def test_review_actions_have_clear_labels_and_visual_hierarchy():
    from ui.pages.grammar_review import GrammarReviewPage
    from ui.pages.listening_review import ListeningReviewPage
    from ui.pages.sentence_review import SentenceReviewPage
    from ui.pages.vocab_review import VocabReviewPage

    _qapp()
    pages = [
        VocabReviewPage(SimpleNamespace()),
        GrammarReviewPage(SimpleNamespace()),
        SentenceReviewPage(SimpleNamespace()),
        ListeningReviewPage(SimpleNamespace()),
    ]
    try:
        for page in pages:
            assert page.start_btn.text() == "New set"
            assert page.start_btn.objectName() == "NewReviewSetButton"
            assert page.start_btn.accessibleName() == "Start a new review set"
            assert page.start_btn.minimumWidth() >= 78
            assert page.stats_btn.objectName() == "ReviewStatsButton"
            assert page.stats_btn.accessibleName() == "Open review statistics"

        checks = [
            pages[0].card.check_btn,
            pages[1].card.btn_check,
            pages[2].card.btn_check,
        ]
        skips = [
            pages[0].card.skip_btn,
            pages[1].card.btn_skip,
            pages[2].card.btn_skip,
            pages[3].skip_btn,
        ]
        for button in checks:
            assert button.objectName() == "ReviewCheckButton"
            assert button.accessibleName() == "Check your answer"
            assert "#1F5F3A" in button.styleSheet() or "#244B36" in button.styleSheet()
        for button in skips:
            assert button.objectName() == "ReviewSkipButton"
            assert button.accessibleName() == "Skip this review card"
            assert "#1B1B1B" in button.styleSheet()
            assert "#163A5C" not in button.styleSheet()
    finally:
        for page in pages:
            page.close()
            page.deleteLater()


@pytest.mark.parametrize("objective", ("vocab", "grammar", "sentences"))
@pytest.mark.parametrize(("current_deck", "should_resume"), ((7, True), (8, False)))
def test_review_page_reentry_only_keeps_same_deck_card(
    objective,
    current_deck,
    should_resume,
):
    from ui.pages.grammar_review import GrammarReviewPage
    from ui.pages.sentence_review import SentenceReviewPage
    from ui.pages.vocab_review import VocabReviewPage

    calls: list[str] = []
    session = SimpleNamespace(
        active_deck_id=lambda: 7,
        context_label=lambda: "A1 lesson",
        remaining=lambda: calls.append("remaining") or 2,
        start_new_session=lambda: calls.append("start"),
    )
    page = SimpleNamespace(
        session=session,
        current_item=SimpleNamespace(deck_id=current_deck),
        special_kbd=SimpleNamespace(
            set_language=lambda _language: calls.append("language")
        ),
        page_subtitle=SimpleNamespace(
            setText=lambda _text: calls.append("subtitle")
        ),
        main_shell=SimpleNamespace(show=lambda: calls.append("show")),
        empty_card=SimpleNamespace(hide=lambda: calls.append("hide")),
        _active_deck_id=lambda: 7,
        _show_main=lambda: calls.append("show"),
        _update_counter=lambda: calls.append("counter"),
        _load_next=lambda: calls.append("load"),
    )
    page_class = {
        "vocab": VocabReviewPage,
        "grammar": GrammarReviewPage,
        "sentences": SentenceReviewPage,
    }[objective]

    page_class.on_show(page)

    assert "start" not in calls
    if should_resume:
        assert "show" in calls
        assert "counter" in calls
        assert "remaining" not in calls
        assert "load" not in calls
    else:
        assert "remaining" in calls
        assert "load" in calls


@pytest.mark.parametrize("font_scale", [85, 100, 115, 130, 140])
def test_today_semantic_type_scale_preserves_hierarchy_and_cta_text(font_scale):
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    from core.insights import LessonReadiness
    from core.planner import DailyPlanSnapshot, ObjectivePlan, PlanSegment
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
    objectives = ("vocab", "grammar", "sentences", "listening")
    rows = tuple(
        ObjectivePlan(objective, 0, 0, 0, 12, 5, 12, 5, 0, 0)
        for objective in objectives
    )
    segments = tuple(
        PlanSegment(
            objective,
            index + 1,
            "A1",
            "starten_wir",
            7,
            (index + 1,),
            1,
            0,
            index + 1,
            4,
        )
        for index, objective in enumerate(objectives)
    )
    snapshot = DailyPlanSnapshot(
        1, 0, 2, 30, 11, 19, 48, 20, 0, 0, rows, segments
    )
    page.planner = SimpleNamespace(snapshot=lambda: snapshot)
    page.insights = SimpleNamespace(
        trouble_items=lambda limit=100: [object(), object(), object()],
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
        section_size = labels["Today's plan"].font().pointSizeF()
        lane_size = labels["Wortschatz"].font().pointSizeF()
        body_label = next(
            label
            for label in page.findChildren(QLabel)
            if label.text().startswith("0 completed")
        )
        body_size = body_label.font().pointSizeF()

        assert title_size == pytest.approx(15 * font_scale / 100, abs=0.05)
        assert section_size == pytest.approx(11 * font_scale / 100, abs=0.05)
        assert title_size > section_size == lane_size > body_size

        lane_buttons = [
            button
            for button in page.findChildren(QPushButton)
            if button.text() == "Start"
        ]
        assert len(lane_buttons) == 4
        for button in lane_buttons:
            assert button.width() >= button.sizeHint().width()
            assert button.maximumWidth() > button.minimumWidth()
    finally:
        page.close()
        page.deleteLater()


def test_today_renders_bounded_plan_and_routes_recommended_lesson():
    from PySide6.QtWidgets import QApplication, QLabel

    from core.insights import LessonReadiness
    from core.planner import DailyPlanSnapshot, ObjectivePlan, PlanSegment
    from ui.pages.today import TodayPage

    _qapp()
    session = SimpleNamespace(
        repo=object(),
        settings=SimpleNamespace(
            value=SimpleNamespace(daily_goal=30, new_card_limit=8)
        ),
        state=SimpleNamespace(
            level="A1",
            objective="vocab",
            book_slug="menschen",
            lektion_number=1,
        ),
    )
    page = TodayPage(session)
    rows = (
        ObjectivePlan("vocab", 0, 0, 0, 160, 3899, 0, 8, 160, 3891),
        ObjectivePlan("grammar", 0, 0, 0, 0, 0, 0, 0, 0, 0),
        ObjectivePlan("sentences", 0, 0, 0, 0, 12, 0, 8, 0, 4),
        ObjectivePlan("listening", 0, 0, 0, 0, 0, 0, 0, 0, 0),
    )
    segments = (
        PlanSegment("vocab", 1, "A1", "menschen", 1, (1,), 0, 1, 1, 2),
        PlanSegment("sentences", 2, "A1", "menschen", 1, (2,), 0, 1, 2, 2),
    )
    page.planner = SimpleNamespace(
        snapshot=lambda: DailyPlanSnapshot(
            1, 0, 2, 30, 0, 16, 160, 3911, 160, 3895, rows, segments
        )
    )
    page.insights = SimpleNamespace(
        trouble_items=lambda limit=100: [object()],
        lesson_path=lambda *_args: [
            LessonReadiness(1, "Hallo!", 35, True),
        ],
    )
    requested: list[tuple] = []
    page.practice_requested.connect(lambda *args: requested.append(args))
    page.resize(760, 760)
    page.on_show()
    page.show()
    try:
        QApplication.processEvents()
        details = [label.text() for label in page.findChildren(QLabel)]
        plan_details = [text for text in details if text.startswith("0 completed")]

        assert sum("8 new" in text for text in plan_details) == 2
        assert all("3899 new" not in text for text in plan_details)
        assert any("0 planned" in text for text in plan_details)
        assert page.path_button.isEnabled()

        page.path_button.click()
        assert requested == [("vocab", "A1", "menschen", 1)]
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


def test_sentence_builder_restores_prompt_after_empty_state():
    from ui.widgets.sentence_builder_widget import SentenceBuilderWidget

    _qapp()
    widget = SentenceBuilderWidget()
    try:
        widget.lock_after_finish("Session complete")
        assert widget.empty_lbl.text() == "No sentence reviews available."

        widget.set_item(words=["Ich", "lerne"], tip=None, translation=None)

        assert widget.empty_lbl.text() == "Tap words below to build the sentence"
    finally:
        widget.close()
        widget.deleteLater()


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


def test_practice_lab_stops_audio_when_hidden(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from ui.pages.practice_lab import PracticeLabPage

    _qapp()
    page = PracticeLabPage(_PracticeSession())
    stops: list[bool] = []
    monkeypatch.setattr(page._playback, "stop", lambda: stops.append(True))
    page.play_btn.set_playing(True)
    page.show()
    try:
        QApplication.processEvents()
        page.hide()
        QApplication.processEvents()

        assert stops == [True]
        assert page.play_btn.text() == "🔊"
        assert page.play_btn.isEnabled()
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


def test_setup_due_reminder_waits_until_page_is_visible():
    from ui.pages.setup import SetupPage

    class Strip:
        def __init__(self):
            self.show_calls = 0
            self.hide_calls = 0

        def show(self):
            self.show_calls += 1

        def hide(self):
            self.hide_calls += 1

    calls: list[int] = []
    repo = SimpleNamespace(
        upcoming_due_counts=lambda horizon: (
            calls.append(horizon) or {"due_now": 2, "due_soon": 1}
        )
    )
    strip = Strip()
    page = SimpleNamespace(
        due_strip=strip,
        due_icon=SimpleNamespace(setText=lambda _text: None),
        due_lbl=SimpleNamespace(setText=lambda _text: None),
        session=SimpleNamespace(repo=repo),
        _due_strip_seen=False,
        isVisible=lambda: False,
    )

    SetupPage._refresh_due_strip(page)
    assert calls == []
    assert page._due_strip_seen is False
    assert strip.show_calls == 0

    page.isVisible = lambda: True
    SetupPage._refresh_due_strip(page)
    assert calls == [86400]
    assert page._due_strip_seen is True
    assert strip.show_calls == 1


def test_setup_deferred_and_first_show_do_not_rebuild_unchanged_structure(
    tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QApplication

    from db.init_db import init_db
    from db.repo import Repo
    from ui.pages.setup import SetupPage

    db_path = tmp_path / "setup-refresh.db"
    init_db(db_path)
    session = SimpleNamespace(
        repo=Repo(db_path),
        state=SimpleNamespace(
            level="A1", book_slug="", lektion_number=0, objective=""
        ),
    )
    _qapp()
    page = SetupPage(session)
    calls = {name: 0 for name in ("levels", "books", "lektions", "objectives")}
    monkeypatch.setattr(
        page,
        "_refresh_levels_enabled",
        lambda: calls.__setitem__("levels", calls["levels"] + 1),
    )
    monkeypatch.setattr(
        page,
        "_refresh_books",
        lambda: calls.__setitem__("books", calls["books"] + 1),
    )
    monkeypatch.setattr(
        page,
        "_refresh_lektions",
        lambda: calls.__setitem__("lektions", calls["lektions"] + 1),
    )
    monkeypatch.setattr(
        page,
        "_refresh_objectives",
        lambda: calls.__setitem__("objectives", calls["objectives"] + 1),
    )

    try:
        QApplication.processEvents()
        page.on_show()

        assert calls == {"levels": 0, "books": 0, "lektions": 0, "objectives": 0}
    finally:
        page.close()
        page.deleteLater()


def test_setup_context_change_rebuilds_structure_on_show(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from db.init_db import init_db
    from db.repo import Repo
    from ui.pages.setup import SetupPage

    db_path = tmp_path / "setup-context-change.db"
    init_db(db_path)
    session = SimpleNamespace(
        repo=Repo(db_path),
        state=SimpleNamespace(
            level="A1", book_slug="", lektion_number=0, objective=""
        ),
    )
    _qapp()
    page = SetupPage(session)
    calls = {name: 0 for name in ("levels", "books", "lektions", "objectives")}
    monkeypatch.setattr(
        page,
        "_refresh_levels_enabled",
        lambda: calls.__setitem__("levels", calls["levels"] + 1),
    )
    monkeypatch.setattr(
        page,
        "_refresh_books",
        lambda: calls.__setitem__("books", calls["books"] + 1),
    )
    monkeypatch.setattr(
        page,
        "_refresh_lektions",
        lambda: calls.__setitem__("lektions", calls["lektions"] + 1),
    )
    monkeypatch.setattr(
        page,
        "_refresh_objectives",
        lambda: calls.__setitem__("objectives", calls["objectives"] + 1),
    )

    try:
        QApplication.processEvents()
        session.state.level = "A2"
        page.on_show()

        assert calls == {"levels": 1, "books": 1, "lektions": 1, "objectives": 1}
    finally:
        page.close()
        page.deleteLater()


def test_book_card_treats_manifest_title_as_plain_text():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel
    from ui.pages.setup import BookCard

    _qapp()
    card = BookCard(
        title="<b>Local Course</b>",
        level="A1",
        lektion_count=1,
        vocab_n=1,
        grammar_n=0,
        sentences_n=0,
        accent="#66CCAA",
        selected=False,
        on_click=lambda: None,
    )

    title = card.findChild(QLabel, "BookTitle")
    assert title is not None
    assert title.text() == "<b>Local Course</b>"
    assert title.textFormat() == Qt.TextFormat.PlainText
