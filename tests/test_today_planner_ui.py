from __future__ import annotations

import os
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


OBJECTIVES = ("vocab", "grammar", "sentences", "listening")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _snapshot(*, empty: bool = False, capped: bool = False):
    from core.planner import DailyPlanSnapshot, ObjectivePlan, PlanSegment

    if empty:
        rows = tuple(
            ObjectivePlan(objective, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            for objective in OBJECTIVES
        )
        return DailyPlanSnapshot(
            1_700_000_000,
            1_699_920_000,
            1_700_006_400,
            10,
            0,
            0,
            0,
            0,
            0,
            0,
            rows,
            (),
        )
    if capped:
        rows = (
            ObjectivePlan("vocab", 0, 0, 0, 5, 0, 0, 0, 5, 0),
            *(
                ObjectivePlan(objective, 0, 0, 0, 0, 0, 0, 0, 0, 0)
                for objective in OBJECTIVES[1:]
            ),
        )
        return DailyPlanSnapshot(
            1_700_000_000,
            1_699_920_000,
            1_700_006_400,
            10,
            0,
            0,
            5,
            0,
            5,
            0,
            rows,
            (),
        )

    segments = (
        PlanSegment("vocab", 10, "A1", "menschen", 1, (11, 12, 13), 2, 1, 1, 3),
        PlanSegment("vocab", 10, "A1", "menschen", 1, (14, 15), 2, 0, 2, 3),
        PlanSegment("grammar", 11, "A1", "menschen", 1, (21, 22), 2, 0, 3, 3),
    )
    rows = (
        ObjectivePlan("vocab", 2, 1, 1, 8, 2, 4, 1, 4, 1),
        ObjectivePlan("grammar", 1, 1, 0, 4, 1, 2, 0, 2, 1),
        ObjectivePlan("sentences", 0, 0, 0, 0, 0, 0, 0, 0, 0),
        ObjectivePlan("listening", 0, 0, 0, 0, 0, 0, 0, 0, 0),
    )
    return DailyPlanSnapshot(
        1_700_000_000,
        1_699_920_000,
        1_700_006_400,
        10,
        3,
        7,
        12,
        3,
        6,
        2,
        rows,
        segments,
    )


class _Snapshots:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def snapshot(self, now=None):
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


def _page(monkeypatch, snapshots: _Snapshots):
    import core.planner as planner_module
    import ui.pages.today as today_module

    factory = lambda *_args, **_kwargs: snapshots
    monkeypatch.setattr(planner_module, "DailyPlannerService", factory)
    monkeypatch.setattr(today_module, "DailyPlannerService", factory, raising=False)

    session = SimpleNamespace(
        repo=object(),
        settings=SimpleNamespace(
            value=SimpleNamespace(
                daily_goal=10,
                new_card_limit=8,
                session_limit=3,
                planner_due_caps={objective: 30 for objective in OBJECTIVES},
                planner_new_caps={objective: 8 for objective in OBJECTIVES},
                planner_weights={objective: 1 for objective in OBJECTIVES},
                planner_weighted_mix=False,
            )
        ),
        state=SimpleNamespace(
            level="A1",
            objective="vocab",
            book_slug="menschen",
            lektion_number=1,
        ),
        ml=None,
    )
    page = today_module.TodayPage(session)
    for name in ("planner", "_planner", "planner_service", "_daily_planner"):
        setattr(page, name, snapshots)
    page.insights = SimpleNamespace(
        lanes=lambda: [],
        reviewed_today=lambda: 0,
        lesson_path=lambda *_args: [],
        recommended_context=lambda *_args: None,
    )
    return page


def _copy(widget) -> str:
    from PySide6.QtWidgets import QGroupBox, QLabel

    parts = [label.text() for label in widget.findChildren(QLabel)]
    parts.extend(group.title() for group in widget.findChildren(QGroupBox))
    return " ".join(parts).casefold()


def _button(widget, phrase: str):
    from PySide6.QtWidgets import QPushButton

    matches = [
        button
        for button in widget.findChildren(QPushButton)
        if phrase in button.text().casefold()
        or phrase in button.accessibleName().casefold()
    ]
    assert matches, f"no button containing {phrase!r}"
    return matches[0]


def test_today_renders_completed_plan_ready_backlog_and_split_truthfully(monkeypatch):
    from PySide6.QtWidgets import QApplication

    _qapp()
    page = _page(monkeypatch, _Snapshots(_snapshot()))
    page.resize(760, 900)
    page.show()
    try:
        page.on_show()
        QApplication.processEvents()
        text = _copy(page)

        assert "today's plan" in text
        assert "3 completed" in text
        assert "7 planned" in text
        assert "12 due" in text
        assert "3 new" in text
        assert "6 more due" in text
        assert "3 focused sets" in text
        for heading in ("wortschatz", "grammatik", "sätze", "hören"):
            assert heading in text
    finally:
        page.close()
        page.deleteLater()


def test_today_actions_emit_the_exact_next_and_objective_segments(monkeypatch):
    from PySide6.QtWidgets import QApplication, QPushButton

    _qapp()
    snapshot = _snapshot()
    page = _page(monkeypatch, _Snapshots(snapshot))
    emitted = []
    page.plan_segment_requested.connect(emitted.append)
    page.show()
    try:
        page.on_show()
        QApplication.processEvents()

        _button(page, "start next set").click()
        objective_buttons = [
            button
            for button in page.findChildren(QPushButton)
            if "wortschatz" in button.accessibleName().casefold()
            and "start next set" not in button.accessibleName().casefold()
        ]
        assert objective_buttons, "vocabulary plan row has no accessible action"
        objective_buttons[0].click()

        assert emitted[0] is snapshot.segments[0]
        assert emitted[1] is snapshot.segments[0]
    finally:
        page.close()
        page.deleteLater()


@pytest.mark.parametrize(
    ("snapshot", "message"),
    [
        (_snapshot(empty=True), "caught up"),
        (_snapshot(capped=True), "5 more due"),
    ],
)
def test_today_zero_work_states_do_not_start_an_unplanned_queue(
    monkeypatch,
    snapshot,
    message,
):
    from PySide6.QtWidgets import QApplication

    _qapp()
    page = _page(monkeypatch, _Snapshots(snapshot))
    page.show()
    try:
        page.on_show()
        QApplication.processEvents()

        assert message in _copy(page)
        assert not _button(page, "start next set").isEnabled()
    finally:
        page.close()
        page.deleteLater()


def test_today_error_is_visible_and_each_show_refreshes_the_snapshot(monkeypatch):
    from PySide6.QtWidgets import QApplication

    _qapp()
    snapshots = _Snapshots(_snapshot(), _snapshot(empty=True))
    page = _page(monkeypatch, snapshots)
    page.show()
    try:
        page.on_show()
        page.show_plan_error("That set changed. Refresh today's plan.")
        QApplication.processEvents()
        assert "that set changed" in _copy(page)

        page.on_show()
        QApplication.processEvents()
        assert snapshots.calls == 2
        assert "caught up" in _copy(page)
        assert not _button(page, "start next set").isEnabled()
    finally:
        page.close()
        page.deleteLater()


def test_accepting_adjust_plan_refreshes_today_immediately(monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog

    import ui.pages.today as today_module

    _qapp()
    snapshots = _Snapshots(_snapshot(), _snapshot(empty=True))
    page = _page(monkeypatch, snapshots)

    class AcceptedDialog:
        def __init__(self, settings_service, parent=None):
            assert settings_service is page.session.settings
            assert parent is page

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(today_module, "DailyPlanDialog", AcceptedDialog, raising=False)
    page.show()
    try:
        page.on_show()
        _button(page, "adjust plan").click()
        QApplication.processEvents()

        assert snapshots.calls == 2
        assert "caught up" in _copy(page)
    finally:
        page.close()
        page.deleteLater()


def test_today_snapshot_failure_disables_all_stale_plan_actions(monkeypatch):
    from PySide6.QtWidgets import QApplication, QPushButton

    class BrokenPlanner:
        def snapshot(self, now=None):
            raise RuntimeError("database unavailable")

    _qapp()
    page = _page(monkeypatch, _Snapshots(_snapshot()))
    page.show()
    try:
        page.on_show()
        QApplication.processEvents()
        assert "3 completed" in _copy(page)
        assert any(
            button.isEnabled()
            for button in page.findChildren(QPushButton)
            if "planned set" in button.accessibleName().casefold()
        )

        page.planner = BrokenPlanner()
        page.on_show()
        QApplication.processEvents()

        assert "plan unavailable" in _copy(page)
        assert "3 completed" not in _copy(page)
        actions = [
            button
            for button in page.findChildren(QPushButton)
            if "planned set" in button.accessibleName().casefold()
            or "start next set" in button.accessibleName().casefold()
        ]
        assert actions
        assert all(not button.isEnabled() for button in actions)
    finally:
        page.close()
        page.deleteLater()
