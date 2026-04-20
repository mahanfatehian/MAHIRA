from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QSpacerItem, QSizePolicy


class NavBar(QWidget):
    go = Signal(str)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("MAHIRA")
        title.setStyleSheet("font-size:16px; font-weight:800; color:#FFFFFF; margin-bottom: 10px; background: transparent;")
        layout.addWidget(title)

        self._btn_style = """
            QPushButton {
                background-color: #1B1B1B;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 10px;
                font-weight: 800;
                font-size: 13px;
                text-align: left;
                padding-left: 12px;
            }
            QPushButton:hover {
                background-color: #232323;
                border: 1px solid #3A3A3A;
            }
        """

        self._btn_style_active = """
            QPushButton {
                background-color: #101010;
                color: #9E9E9E;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 10px;
                font-weight: 800;
                font-size: 13px;
                text-align: left;
                padding-left: 12px;
            }
        """

        self.btn_setup = QPushButton("Setup")
        self.btn_practice = QPushButton("Practice")
        self.btn_learn = QPushButton("Learn")
        self.btn_progress = QPushButton("Progress")

        for b in (self.btn_setup, self.btn_practice, self.btn_learn, self.btn_progress):
            b.setStyleSheet(self._btn_style)

        self.btn_setup.clicked.connect(lambda: self.go.emit("setup"))
        self.btn_practice.clicked.connect(lambda: self.go.emit("practice"))
        self.btn_learn.clicked.connect(lambda: self.go.emit("learn"))
        self.btn_progress.clicked.connect(lambda: self.go.emit("progress"))

        layout.addWidget(self.btn_setup)
        layout.addWidget(self.btn_practice)
        layout.addWidget(self.btn_learn)
        layout.addWidget(self.btn_progress)

        layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        self._active = None
        self.set_active("setup")

    def set_active(self, nav_key: str) -> None:
        nav_key = (nav_key or "").strip().lower()
        self._active = nav_key

        mapping = {
            "setup": self.btn_setup,
            "practice": self.btn_practice,
            "learn": self.btn_learn,
            "progress": self.btn_progress,
        }

        for k, btn in mapping.items():
            is_active = (k == nav_key)
            btn.setEnabled(not is_active)
            btn.setStyleSheet(self._btn_style_active if is_active else self._btn_style)
