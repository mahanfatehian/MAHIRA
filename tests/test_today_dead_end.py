"""Today must stay actionable once the daily goal is spent.

When remaining_goal hits zero the planner emits no segments, so every Start
button disables - while the page simultaneously said "More practice remains
available after the plan." That told the learner work was waiting and offered
no way to reach it. The failure path also told them to "Refresh Today" when no
refresh control existed.
"""

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


def _snapshot(*, goal, completed, backlog_due, backlog_new, segments=()):
    from core.planner import DailyPlanSnapshot, ObjectivePlan

    return DailyPlanSnapshot(
        captured_at=1_800_000_000,
        day_start=1_800_000_000,
        day_end=1_800_086_400,
        goal=goal,
        completed_total=completed,
        planned_total=0,
        ready_due=backlog_due,
        ready_new=backlog_new,
        backlog_due=backlog_due,
        backlog_new=backlog_new,
        objectives=tuple(
            ObjectivePlan(
                objective=o,
                completed=0,
                completed_due=0,
                completed_new=0,
                ready_due=0,
                ready_new=0,
                planned_due=0,
                planned_new=0,
                backlog_due=0,
                backlog_new=0,
            )
            for o in OBJECTIVES
        ),
        segments=tuple(segments),
    )


def _session():
    return SimpleNamespace(
        repo=object(),
        settings=SimpleNamespace(value=SimpleNamespace(daily_goal=30)),
        state=SimpleNamespace(level="A1", book_slug="starten_wir", lektion_number=1),
    )


@pytest.fixture()
def page():
    from ui.pages.today import TodayPage

    _qapp()
    widget = TodayPage(_session())
    yield widget
    widget.deleteLater()


def test_today_has_a_refresh_control(page):
    """The failure copy tells the learner to refresh; the control must exist."""
    assert page.refresh_btn is not None
    assert page.refresh_btn.accessibleName() == "Rebuild today's plan"


def test_goal_reached_with_work_left_names_the_way_forward(page):
    page._render_plan(
        _snapshot(goal=30, completed=30, backlog_due=48, backlog_new=12)
    )
    summary = page.summary.text()
    assert "30 reached" in summary
    assert "48 due" in summary and "12 new" in summary
    assert "Adjust plan" in summary, "the dead end must name the control that fixes it"


def test_the_old_dead_end_wording_is_gone(page):
    page._render_plan(
        _snapshot(goal=30, completed=30, backlog_due=5, backlog_new=0)
    )
    assert page.summary.text() != "More practice remains available after the plan."


def test_being_genuinely_caught_up_still_reads_as_success(page):
    page._render_plan(
        _snapshot(goal=30, completed=30, backlog_due=0, backlog_new=0)
    )
    assert page.summary.text() == "You are caught up. The plan is complete."


def test_a_mid_day_plan_is_unaffected(page):
    """Goal not yet spent but no segment right now keeps the old wording."""
    page._render_plan(
        _snapshot(goal=30, completed=0, backlog_due=4, backlog_new=1)
    )
    assert page.summary.text() == "More practice remains available after the plan."


def test_refresh_survives_a_failed_plan(tmp_path, monkeypatch):
    """on_show's except branch disables the lanes; refresh must stay usable,
    otherwise the learner is told to refresh with no way to do it."""

    from pathlib import Path

    from db.init_db import init_db
    from db.repo import Repo
    from ui.pages.today import TodayPage

    _qapp()
    schema = Path(__file__).resolve().parents[1] / "src" / "db" / "schema.sql"
    init_db(tmp_path / "today.db", schema)
    session = _session()
    session.repo = Repo(tmp_path / "today.db")
    page = TodayPage(session)

    def boom():
        raise RuntimeError("planner unavailable")

    monkeypatch.setattr(page, "_planner_snapshot", boom)
    page.refresh_btn.setEnabled(False)
    page.on_show()

    assert page.summary.text() == "Today's plan is temporarily unavailable."
    assert all(not button.isEnabled() for _d, button in page._lane_widgets.values())
    assert page.refresh_btn.isEnabled()
    page.deleteLater()
