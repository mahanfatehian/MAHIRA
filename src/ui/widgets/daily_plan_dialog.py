from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.planner import OBJECTIVES
from ui.theme import (
    BUTTON_STYLE,
    COLORS,
    PRIMARY_BUTTON_STYLE,
    card_style,
    set_feature_font,
)
from ui.widgets.number_stepper import NumberStepper


_OBJECTIVE_LABELS = {
    "vocab": "Vocabulary",
    "grammar": "Grammar",
    "sentences": "Sentences",
    "listening": "Listening",
}


class DailyPlanDialog(QDialog):
    """Edit persistent daily-planner caps in one atomic settings update."""

    def __init__(self, settings_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings_service
        self._due_controls: dict[str, NumberStepper] = {}
        self._new_controls: dict[str, NumberStepper] = {}
        self._weight_controls: dict[str, NumberStepper] = {}
        self._weight_rows: list[QWidget] = []
        self._loading = False

        self.setWindowTitle("Adjust today's plan")
        self.setAccessibleName("Daily plan settings")
        self.setModal(True)
        self.setProperty("mahiraFeaturePage", True)
        self.setMinimumSize(680, 520)
        self.resize(760, 620)
        self._build()
        self._load()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        heading = QLabel("Adjust today's plan")
        set_feature_font(heading, 15, QFont.Weight.Black)
        explanation = QLabel(
            "The daily goal sets how much work today holds in total. The "
            "per-skill limits below decide what that work is made of. Neither "
            "changes a card's schedule."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet(f"color:{COLORS['muted']};")
        root.addWidget(heading)
        root.addWidget(explanation)

        # The daily goal lives here as well as in Settings: it is the ceiling
        # that actually binds the plan, so a dialog called "Adjust today's
        # plan" that could not change it left every slider below inert.
        goal_card = QFrame()
        goal_card.setStyleSheet(card_style())
        goal_layout = QVBoxLayout(goal_card)
        goal_layout.setContentsMargins(14, 12, 14, 12)
        goal_layout.setSpacing(8)
        goal_title = QLabel("Daily goal")
        set_feature_font(goal_title, 11, QFont.Weight.Black)
        goal_layout.addWidget(goal_title)
        self.goal = NumberStepper(5, 200, 5, "daily goal")
        self.goal.valueChanged.connect(self._refresh_capacity)
        goal_layout.addWidget(self._control_row("Cards", self.goal))
        self.capacity_note = QLabel("")
        self.capacity_note.setWordWrap(True)
        self.capacity_note.setStyleSheet(f"color:{COLORS['muted']};")
        goal_layout.addWidget(self.capacity_note)
        root.addWidget(goal_card)

        self.balance = QCheckBox("Balance across skills")
        self.balance.setAccessibleDescription(
            "Use custom relative weights when sharing today's goal across skills"
        )
        self.balance.toggled.connect(self._set_weights_visible)
        root.addWidget(self.balance)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")

        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for index, objective in enumerate(OBJECTIVES):
            grid.addWidget(
                self._objective_card(objective),
                index // 2,
                index % 2,
            )
        grid.setRowStretch(2, 1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setAccessibleName("Cancel daily plan changes")
        cancel.setStyleSheet(BUTTON_STYLE)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save plan")
        save.setAccessibleName("Save daily plan changes")
        save.setDefault(True)
        save.setProperty("primary", True)
        save.setStyleSheet(PRIMARY_BUTTON_STYLE)
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)

    def _objective_card(self, objective: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(card_style())
        card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)

        title = QLabel(_OBJECTIVE_LABELS[objective])
        set_feature_font(title, 11, QFont.Weight.Black)
        layout.addWidget(title)

        due = NumberStepper(0, 200, 1, f"{objective} due cap")
        new = NumberStepper(0, 30, 1, f"{objective} new cap")
        weight = NumberStepper(1, 100, 1, f"{objective} weight")
        due.valueChanged.connect(self._refresh_capacity)
        new.valueChanged.connect(self._refresh_capacity)
        self._due_controls[objective] = due
        self._new_controls[objective] = new
        self._weight_controls[objective] = weight

        layout.addWidget(self._control_row("Due", due))
        layout.addWidget(self._control_row("New", new))
        weight_row = self._control_row("Weight", weight)
        self._weight_rows.append(weight_row)
        layout.addWidget(weight_row)
        return card

    @staticmethod
    def _control_row(label: str, control: NumberStepper) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        caption = QLabel(label)
        caption.setMinimumWidth(48)
        set_feature_font(caption, 9, QFont.Weight.DemiBold)
        layout.addWidget(caption)
        layout.addStretch(1)
        layout.addWidget(control)
        return row

    def _load(self) -> None:
        value = self.settings.value
        due_caps = value.planner_due_caps
        new_caps = value.planner_new_caps
        weights = value.planner_weights
        self._loading = True
        try:
            self.goal.setValue(int(getattr(value, "daily_goal", 30)))
            for objective in OBJECTIVES:
                self._due_controls[objective].setValue(due_caps[objective])
                self._new_controls[objective].setValue(new_caps[objective])
                self._weight_controls[objective].setValue(weights[objective])
            self.balance.setChecked(bool(value.planner_weighted_mix))
        finally:
            self._loading = False
        self._set_weights_visible(self.balance.isChecked())
        self._refresh_capacity()

    def capacity(self) -> int:
        """Largest plan the per-skill limits could ever produce."""
        return sum(
            self._due_controls[objective].value()
            + self._new_controls[objective].value()
            for objective in OBJECTIVES
        )

    def _refresh_capacity(self, *_args) -> None:
        """Say which of the two limits is the one actually deciding the plan.

        Without this the caps look authoritative while the goal quietly
        overrides them, which is exactly the confusion this dialog caused.
        """
        if self._loading:
            return
        goal = self.goal.value()
        capacity = self.capacity()
        if capacity <= 0:
            self.capacity_note.setText(
                "Every skill is set to zero, so today's plan will be empty."
            )
        elif capacity <= goal:
            self.capacity_note.setText(
                f"Your per-skill limits allow {capacity} cards, which is under "
                f"the goal of {goal}. The per-skill limits decide today's size; "
                "raise them to get a fuller plan."
            )
        else:
            self.capacity_note.setText(
                f"The goal of {goal} decides today's size. Your per-skill "
                f"limits allow up to {capacity}, so they shape the mix rather "
                "than the total."
            )

    def _set_weights_visible(self, visible: bool) -> None:
        for row in self._weight_rows:
            row.setVisible(bool(visible))

    def _save(self) -> None:
        changes = {
            "daily_goal": self.goal.value(),
            "planner_due_caps": {
                objective: self._due_controls[objective].value()
                for objective in OBJECTIVES
            },
            "planner_new_caps": {
                objective: self._new_controls[objective].value()
                for objective in OBJECTIVES
            },
            "planner_weights": {
                objective: self._weight_controls[objective].value()
                for objective in OBJECTIVES
            },
            "planner_weighted_mix": self.balance.isChecked(),
        }
        try:
            self.settings.update(**changes)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Plan not saved",
                f"Your settings were left unchanged.\n\n{exc}",
            )
            return
        self.accept()
