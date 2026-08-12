from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from ui.theme import BUTTON_STYLE, COLORS, set_feature_font


class NumberStepper(QWidget):
    """Compact, non-editable integer control with accessible buttons."""

    valueChanged = Signal(int)

    def __init__(
        self,
        minimum: int,
        maximum: int,
        step: int,
        accessible_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._minimum = int(minimum)
        self._maximum = max(self._minimum, int(maximum))
        self._step = max(1, int(step))
        self._value = self._minimum
        self.setAccessibleName(accessible_name)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.minus = QPushButton("−")
        self.minus.setAccessibleName(f"Decrease {accessible_name}")
        self.minus.setMinimumSize(44, 36)
        self.minus.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Fixed,
        )
        self.minus.setStyleSheet(BUTTON_STYLE)
        self.minus.clicked.connect(lambda: self.setValue(self._value - self._step))

        self.value_label = QLabel()
        self.value_label.setAccessibleName(f"Current {accessible_name}")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setMinimumWidth(64)
        self.value_label.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Fixed,
        )
        self.value_label.setStyleSheet(
            f"QLabel {{ color:{COLORS['text_primary']}; "
            f"background:{COLORS['surface_sunken']}; "
            f"border:1px solid {COLORS['outline']}; "
            "border-radius:9px; padding:8px 10px; }"
        )
        set_feature_font(self.value_label, 10, QFont.Weight.Black)

        self.plus = QPushButton("+")
        self.plus.setAccessibleName(f"Increase {accessible_name}")
        self.plus.setMinimumSize(44, 36)
        self.plus.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Fixed,
        )
        self.plus.setStyleSheet(BUTTON_STYLE)
        self.plus.clicked.connect(lambda: self.setValue(self._value + self._step))

        layout.addWidget(self.minus)
        layout.addWidget(self.value_label)
        layout.addWidget(self.plus)
        self._sync()

    def minimum(self) -> int:
        return self._minimum

    def maximum(self) -> int:
        return self._maximum

    def singleStep(self) -> int:
        return self._step

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        bounded = max(self._minimum, min(self._maximum, int(value)))
        if bounded == self._value:
            self._sync()
            return
        self._value = bounded
        self._sync()
        self.valueChanged.emit(self._value)

    def _sync(self) -> None:
        self.value_label.setText(str(self._value))
        self.minus.setEnabled(self._value > self._minimum)
        self.plus.setEnabled(self._value < self._maximum)
