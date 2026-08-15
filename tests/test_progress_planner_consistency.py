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


def _snapshot():
    from core.planner import DailyPlanSnapshot, ObjectivePlan, PlanSegment

    rows = (
        ObjectivePlan("vocab", 2, 1, 1, 8, 2, 4, 1, 4, 1),
        ObjectivePlan("grammar", 1, 1, 0, 4, 1, 2, 0, 2, 1),
        ObjectivePlan("sentences", 0, 0, 0, 0, 0, 0, 0, 0, 0),
        ObjectivePlan("listening", 0, 0, 0, 0, 0, 0, 0, 0, 0),
    )
    segments = (
        PlanSegment("vocab", 10, "A1", "menschen", 1, (11, 12, 13), 2, 1, 1, 2),
        PlanSegment("grammar", 11, "A1", "menschen", 1, (21, 22), 2, 0, 2, 2),
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


class _Planner:
    def __init__(self, snapshot):
        self.value = snapshot
        self.calls = 0

    def snapshot(self, now=None):
        self.calls += 1
        return self.value


def _copy(widget) -> str:
    from PySide6.QtWidgets import QGroupBox, QLabel

    parts = [label.text() for label in widget.findChildren(QLabel)]
    parts.extend(group.title() for group in widget.findChildren(QGroupBox))
    return " ".join(parts).casefold()


def test_today_and_progress_render_identical_daily_plan_totals_and_clear_scopes(
    monkeypatch,
):
    from PySide6.QtWidgets import QApplication, QGroupBox

    import core.planner as planner_module
    import ui.pages.progress as progress_module
    import ui.pages.today as today_module

    _qapp()
    snapshot = _snapshot()
    planner = _Planner(snapshot)
    factory = lambda *_args, **_kwargs: planner
    monkeypatch.setattr(planner_module, "DailyPlannerService", factory)
    monkeypatch.setattr(today_module, "DailyPlannerService", factory, raising=False)
    monkeypatch.setattr(progress_module, "DailyPlannerService", factory, raising=False)

    repo = SimpleNamespace(daily_review_counts=lambda *_args, **_kwargs: {})
    session = SimpleNamespace(
        repo=repo,
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
        active_deck_id=lambda: None,
        ml=None,
    )
    today = today_module.TodayPage(session)
    progress = progress_module.ProgressPage(session)
    for page in (today, progress):
        for name in ("planner", "_planner", "planner_service", "_daily_planner"):
            setattr(page, name, planner)
    today.insights = SimpleNamespace(
        lanes=lambda: [],
        reviewed_today=lambda: 0,
        lesson_path=lambda *_args: [],
        recommended_context=lambda *_args: None,
    )
    today.show()
    progress.show()
    try:
        today.on_show()
        progress.on_show()
        QApplication.processEvents()

        today_text = _copy(today)
        progress_text = _copy(progress)
        for expected in ("3 completed", "7 planned", "6 due", "1 new"):
            assert expected in today_text
            assert expected in progress_text

        titles = {
            group.title().casefold() for group in progress.findChildren(QGroupBox)
        }
        assert "today's plan" in titles
        assert "current lesson" in titles
        assert "ready now" in titles
        assert "reviewed today" in titles
        assert "due now" not in titles
        assert "reviewed (24h)" not in titles
        assert planner.calls == 2
    finally:
        today.close()
        today.deleteLater()
        progress.close()
        progress.deleteLater()
