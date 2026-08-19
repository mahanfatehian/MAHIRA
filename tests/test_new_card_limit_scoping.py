"""The two "new cards" controls govern different things and must say so.

Settings' new_card_limit feeds session.plan.new_limit, which the focused
per-deck review path reads. The daily planner never reads it - it reads
planner_new_caps, which new_card_limit only seeds on first migration. Open
Adjust plan once and the two diverge permanently, so a control labelled "New
cards per session" stopped describing what Today actually does.
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


def test_the_planner_does_not_read_new_card_limit():
    """The premise of the relabel: these really are separate knobs."""
    import inspect

    from core import planner

    assert "new_card_limit" not in inspect.getsource(planner)


def test_new_card_limit_only_seeds_the_planner_caps_on_legacy_load(tmp_path):
    """Seeding is a one-off migration, not an ongoing link."""
    import json

    from core.settings import SettingsService

    path = tmp_path / "settings.json"
    # A file written before planner caps existed.
    path.write_text(json.dumps({"new_card_limit": 3}), encoding="utf-8")
    assert all(SettingsService(path).value.planner_new_caps[o] == 3 for o in OBJECTIVES)


def test_the_two_limits_are_independent_thereafter(tmp_path):
    from core.settings import SettingsService

    service = SettingsService(tmp_path / "settings.json")
    service.update(planner_new_caps={o: 9 for o in OBJECTIVES})
    service.update(new_card_limit=1)

    assert service.value.new_card_limit == 1
    assert all(service.value.planner_new_caps[o] == 9 for o in OBJECTIVES), (
        "changing the focused-set limit must not silently rewrite Today's plan"
    )


def test_the_settings_control_is_scoped_to_focused_sets(tmp_path):
    from core.settings import SettingsService
    from ui.pages.settings import SettingsPage

    _qapp()
    session = SimpleNamespace(
        repo=SimpleNamespace(db_path=tmp_path / "x.db"),
        settings=SettingsService(tmp_path / "settings.json"),
        plan=SimpleNamespace(limit=30, new_limit=8),
    )
    page = SettingsPage(session)
    try:
        assert page.new_limit.accessibleName() == "new cards per focused set"
        labels = _visible_text(page)
        assert "New cards per focused set" in labels
        assert "New cards per session" not in labels
        # It must point the learner at where Today's new limits actually live.
        assert "Adjust plan" in labels
    finally:
        page.deleteLater()


def _visible_text(widget) -> str:
    from PySide6.QtWidgets import QLabel

    return "\n".join(label.text() for label in widget.findChildren(QLabel))


def test_the_daily_goal_row_points_at_adjust_plan(tmp_path):
    from core.settings import SettingsService
    from ui.pages.settings import SettingsPage

    _qapp()
    session = SimpleNamespace(
        repo=SimpleNamespace(db_path=tmp_path / "y.db"),
        settings=SettingsService(tmp_path / "settings.json"),
        plan=SimpleNamespace(limit=30, new_limit=8),
    )
    page = SettingsPage(session)
    try:
        text = _visible_text(page)
        assert "all four skills" in text
    finally:
        page.deleteLater()
