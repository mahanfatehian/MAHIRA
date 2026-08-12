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


def _find_stepper(dialog, objective: str, kind: str):
    from ui.widgets.number_stepper import NumberStepper

    matches = [
        control
        for control in dialog.findChildren(NumberStepper)
        if objective in control.accessibleName().casefold()
        and kind in control.accessibleName().casefold()
    ]
    assert len(matches) == 1, (
        f"expected one accessible {objective} {kind} control, got "
        f"{[control.accessibleName() for control in matches]}"
    )
    return matches[0]


def _button(dialog, word: str):
    from PySide6.QtWidgets import QPushButton

    matches = [
        button
        for button in dialog.findChildren(QPushButton)
        if word in button.text().casefold()
        or word in button.accessibleName().casefold()
    ]
    assert matches, f"no {word!r} button found"
    return matches[0]


def test_number_stepper_clamps_and_supports_mouse_keyboard_and_accessibility():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from ui.widgets.number_stepper import NumberStepper

    _qapp()
    stepper = NumberStepper(0, 10, 2, "vocab due cap")
    changes: list[int] = []
    stepper.valueChanged.connect(changes.append)
    try:
        assert stepper.accessibleName() == "vocab due cap"
        assert stepper.minus.accessibleName() == "Decrease vocab due cap"
        assert stepper.plus.accessibleName() == "Increase vocab due cap"
        assert stepper.value() == 0
        assert not stepper.minus.isEnabled()

        stepper.plus.click()
        assert stepper.value() == 2

        stepper.plus.setFocus()
        QTest.keyClick(stepper.plus, Qt.Key.Key_Space)
        assert stepper.value() == 4

        stepper.setValue(999)
        assert stepper.value() == 10
        assert not stepper.plus.isEnabled()

        stepper.setValue(-999)
        assert stepper.value() == 0
        assert changes == [2, 4, 10, 0]
    finally:
        stepper.close()
        stepper.deleteLater()


def test_settings_page_reuses_the_shared_number_stepper(tmp_path):
    from ui.pages.settings import SettingsPage
    from ui.widgets.number_stepper import NumberStepper

    _qapp()
    db_path = tmp_path / "mahira.db"
    db_path.touch()
    page = SettingsPage(SimpleNamespace(repo=SimpleNamespace(db_path=db_path), settings=None))
    try:
        assert isinstance(page.daily_goal, NumberStepper)
        assert isinstance(page.session_limit, NumberStepper)
        assert isinstance(page.new_limit, NumberStepper)
    finally:
        page._stop_background()
        page.close()
        page.deleteLater()


def test_daily_plan_dialog_loads_values_toggles_weights_and_saves_once(tmp_path):
    from PySide6.QtWidgets import QApplication, QCheckBox

    from core.settings import SettingsService
    from ui.widgets.daily_plan_dialog import DailyPlanDialog

    _qapp()
    path = tmp_path / "settings.json"
    initial = SettingsService(path)
    initial.update(
        planner_due_caps={
            "vocab": 11,
            "grammar": 12,
            "sentences": 13,
            "listening": 14,
        },
        planner_new_caps={
            "vocab": 1,
            "grammar": 2,
            "sentences": 3,
            "listening": 4,
        },
        planner_weights={
            "vocab": 4,
            "grammar": 3,
            "sentences": 2,
            "listening": 1,
        },
        planner_weighted_mix=False,
    )

    class RecordingSettings(SettingsService):
        def __init__(self, settings_path):
            super().__init__(settings_path)
            self.update_calls: list[dict] = []

        def update(self, **changes):
            self.update_calls.append(changes)
            return super().update(**changes)

    settings = RecordingSettings(path)
    dialog = DailyPlanDialog(settings)
    dialog.show()
    try:
        QApplication.processEvents()
        expected_due = dict(zip(OBJECTIVES, (11, 12, 13, 14)))
        expected_new = dict(zip(OBJECTIVES, (1, 2, 3, 4)))
        expected_weights = dict(zip(OBJECTIVES, (4, 3, 2, 1)))
        for objective in OBJECTIVES:
            assert _find_stepper(dialog, objective, "due").value() == expected_due[objective]
            assert _find_stepper(dialog, objective, "new").value() == expected_new[objective]
            assert _find_stepper(dialog, objective, "weight").value() == expected_weights[objective]

        balance = next(
            checkbox
            for checkbox in dialog.findChildren(QCheckBox)
            if "balance" in checkbox.text().casefold()
        )
        weight_controls = [
            _find_stepper(dialog, objective, "weight") for objective in OBJECTIVES
        ]
        assert not balance.isChecked()
        assert not any(control.isVisible() for control in weight_controls)

        balance.click()
        QApplication.processEvents()
        assert all(control.isVisible() for control in weight_controls)

        due_values = dict(zip(OBJECTIVES, (20, 30, 40, 50)))
        new_values = dict(zip(OBJECTIVES, (5, 6, 7, 8)))
        weight_values = dict(zip(OBJECTIVES, (1, 2, 3, 4)))
        for objective in OBJECTIVES:
            _find_stepper(dialog, objective, "due").setValue(due_values[objective])
            _find_stepper(dialog, objective, "new").setValue(new_values[objective])
            _find_stepper(dialog, objective, "weight").setValue(weight_values[objective])

        _button(dialog, "save").click()
        QApplication.processEvents()

        assert settings.update_calls == [
            {
                "planner_due_caps": due_values,
                "planner_new_caps": new_values,
                "planner_weights": weight_values,
                "planner_weighted_mix": True,
            }
        ]
        reloaded = SettingsService(path).value
        assert reloaded.planner_due_caps == due_values
        assert reloaded.planner_new_caps == new_values
        assert reloaded.planner_weights == weight_values
        assert reloaded.planner_weighted_mix is True
    finally:
        dialog.close()
        dialog.deleteLater()


def test_daily_plan_dialog_controls_enforce_ranges_and_cancel_is_read_only(tmp_path):
    from PySide6.QtWidgets import QApplication

    from core.settings import SettingsService
    from ui.widgets.daily_plan_dialog import DailyPlanDialog

    _qapp()
    path = tmp_path / "settings.json"
    settings = SettingsService(path)
    settings.save()
    before = path.read_bytes()
    before_value = settings.value

    dialog = DailyPlanDialog(settings)
    dialog.show()
    try:
        QApplication.processEvents()
        due = _find_stepper(dialog, "vocab", "due")
        new = _find_stepper(dialog, "vocab", "new")
        weight = _find_stepper(dialog, "vocab", "weight")

        due.setValue(-1)
        new.setValue(999)
        weight.setValue(0)
        assert due.value() == 0
        assert new.value() == 30
        assert weight.value() == 1

        _button(dialog, "cancel").click()
        QApplication.processEvents()

        assert path.read_bytes() == before
        assert settings.value == before_value
    finally:
        dialog.close()
        dialog.deleteLater()
