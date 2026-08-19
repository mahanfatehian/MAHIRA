"""The Adjust plan dialog must be able to change the limit that actually binds.

Today renders "Daily review goal - N / M" directly beside an "Adjust plan..."
button, but the dialog only ever wrote planner_due_caps / planner_new_caps /
planner_weights / planner_weighted_mix. daily_goal lived in Settings.

At the defaults the goal is 30 while the per-skill caps allow 4 x (30 + 8) =
152, so the goal is the binding constraint and raising every slider in the
dialog to its maximum changed the plan by zero cards.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OBJECTIVES = ("vocab", "grammar", "sentences", "listening")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def service(tmp_path):
    from core.settings import SettingsService

    return SettingsService(tmp_path / "settings.json")


@pytest.fixture()
def dialog(service):
    from ui.widgets.daily_plan_dialog import DailyPlanDialog

    _qapp()
    widget = DailyPlanDialog(service)
    yield widget
    widget.deleteLater()


def test_the_dialog_exposes_the_daily_goal(dialog):
    assert dialog.goal is not None
    assert dialog.goal.accessibleName() == "daily goal"


def test_it_loads_the_saved_goal(service):
    from ui.widgets.daily_plan_dialog import DailyPlanDialog

    _qapp()
    service.update(daily_goal=95)
    widget = DailyPlanDialog(service)
    try:
        assert widget.goal.value() == 95
    finally:
        widget.deleteLater()


def test_saving_persists_the_goal(dialog, service):
    dialog.goal.setValue(120)
    dialog._save()
    assert service.value.daily_goal == 120


def test_saving_still_persists_the_per_skill_limits(dialog, service):
    dialog.goal.setValue(60)
    for objective in OBJECTIVES:
        dialog._due_controls[objective].setValue(11)
        dialog._new_controls[objective].setValue(3)
    dialog._save()

    value = service.value
    assert value.daily_goal == 60
    assert all(value.planner_due_caps[o] == 11 for o in OBJECTIVES)
    assert all(value.planner_new_caps[o] == 3 for o in OBJECTIVES)


def test_the_goal_respects_the_settings_band(dialog, service):
    dialog.goal.setValue(10_000)
    dialog._save()
    assert service.value.daily_goal <= 200


# --------------------------------------------------------------------------
# The capacity hint - it explains which limit is doing the work
# --------------------------------------------------------------------------

def test_it_says_the_goal_binds_when_caps_exceed_it(dialog):
    dialog.goal.setValue(30)
    for objective in OBJECTIVES:
        dialog._due_controls[objective].setValue(30)
        dialog._new_controls[objective].setValue(8)
    note = dialog.capacity_note.text()
    assert dialog.capacity() == 152
    assert "goal of 30 decides" in note
    assert "152" in note


def test_it_says_the_caps_bind_when_they_fall_short(dialog):
    dialog.goal.setValue(120)
    for objective in OBJECTIVES:
        dialog._due_controls[objective].setValue(5)
        dialog._new_controls[objective].setValue(0)
    note = dialog.capacity_note.text()
    assert dialog.capacity() == 20
    assert "per-skill limits decide" in note


def test_it_warns_when_everything_is_zeroed(dialog):
    dialog.goal.setValue(30)
    for objective in OBJECTIVES:
        dialog._due_controls[objective].setValue(0)
        dialog._new_controls[objective].setValue(0)
    assert "empty" in dialog.capacity_note.text()


def test_the_hint_tracks_edits_live(dialog):
    dialog.goal.setValue(30)
    first = dialog.capacity_note.text()
    dialog.goal.setValue(200)
    assert dialog.capacity_note.text() != first
