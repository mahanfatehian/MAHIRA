from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QSpacerItem, QSizePolicy


# The four practice objectives are peers in the nav. They are only enabled once a
# concrete Lektion is selected (and only for objectives that actually have a deck
# in that Lektion), so they are inert while the user is still choosing in Setup.
OBJECTIVE_KEYS = ("vocab", "grammar", "sentences", "listening")


class NavBar(QWidget):
    go = Signal(str)

    def __init__(self):
        super().__init__()
        # Match the original navigation footprint so feature pages do not lose
        # content width on compact windows or enlarged text settings.
        self.setFixedWidth(160)
        self.setAccessibleName("Main navigation")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("MAHIRA")
        title.setStyleSheet(
            "font-size:16px; font-weight:800; color:#FFFFFF; margin-bottom: 6px; background: transparent;"
        )
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

        # Gated-off objective: visibly inert (no concrete Lektion / no deck yet).
        self._btn_style_disabled = """
            QPushButton {
                background-color: #141414;
                color: #5A5A5A;
                border: 1px solid #232323;
                border-radius: 10px;
                padding: 10px;
                font-weight: 800;
                font-size: 13px;
                text-align: left;
                padding-left: 12px;
            }
        """

        group_lbl_style = (
            "color:#6B6B6B; font-size:10px; font-weight:900; letter-spacing:1px; "
            "padding: 6px 0 2px 12px; background: transparent;"
        )

        self.btn_today = QPushButton("Today")
        self.btn_setup = QPushButton("Setup")

        practice_lbl = QLabel("PRACTICE")
        practice_lbl.setStyleSheet(group_lbl_style)

        self.btn_vocab = QPushButton("Vocab")
        self.btn_grammar = QPushButton("Grammar")
        self.btn_sentences = QPushButton("Sentences")
        self.btn_listening = QPushButton("Listening")

        self.btn_learn = QPushButton("Learn")
        self.btn_progress = QPushButton("Progress")
        self.btn_mistakes = QPushButton("Mistakes")
        self.btn_lab = QPushButton("Lab")
        self.btn_settings = QPushButton("Settings")

        insights_lbl = QLabel("INSIGHTS")
        insights_lbl.setStyleSheet(group_lbl_style)

        # key -> button (used for active/enabled state)
        self._buttons = {
            "today": self.btn_today,
            "setup": self.btn_setup,
            "vocab": self.btn_vocab,
            "grammar": self.btn_grammar,
            "sentences": self.btn_sentences,
            "listening": self.btn_listening,
            "learn": self.btn_learn,
            "progress": self.btn_progress,
            "mistakes": self.btn_mistakes,
            "lab": self.btn_lab,
            "settings": self.btn_settings,
        }

        for key, btn in self._buttons.items():
            btn.setStyleSheet(self._btn_style)
            btn.clicked.connect(lambda _=False, k=key: self.go.emit(k))

        layout.addWidget(self.btn_today)
        layout.addWidget(self.btn_setup)
        layout.addWidget(practice_lbl)
        layout.addWidget(self.btn_vocab)
        layout.addWidget(self.btn_grammar)
        layout.addWidget(self.btn_sentences)
        layout.addWidget(self.btn_listening)
        layout.addWidget(self.btn_lab)
        layout.addWidget(insights_lbl)
        layout.addWidget(self.btn_learn)
        layout.addWidget(self.btn_progress)
        layout.addWidget(self.btn_mistakes)

        layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        layout.addWidget(self.btn_settings)

        self._active = "today"
        self._enabled_objectives: set[str] = set()
        self._render()

    def set_objective_states(self, enabled: set[str]) -> None:
        """Enable exactly the objective tabs that have a deck for the current
        Lektion; disable the rest (and all of them when there is no Lektion)."""
        self._enabled_objectives = {k for k in (enabled or set()) if k in OBJECTIVE_KEYS}
        self._render()

    def set_active(self, nav_key: str) -> None:
        self._active = (nav_key or "").strip().lower()
        self._render()

    def _render(self) -> None:
        for key, btn in self._buttons.items():
            is_active = (key == self._active)
            if key in OBJECTIVE_KEYS:
                enabled = key in self._enabled_objectives
            else:
                enabled = True

            # The active button is left unclickable to read as "current page".
            btn.setEnabled(enabled and not is_active)

            if is_active:
                btn.setStyleSheet(self._btn_style_active)
            elif not enabled:
                btn.setStyleSheet(self._btn_style_disabled)
            else:
                btn.setStyleSheet(self._btn_style)
