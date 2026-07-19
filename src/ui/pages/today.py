from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.insights import InsightsService
from ui.theme import (
    BUTTON_STYLE,
    COLORS,
    PRIMARY_BUTTON_STYLE,
    TOP_BAR_STYLE,
    card_style,
    set_feature_font,
)


_LABELS = {
    "vocab": ("Wortschatz", "Words, articles and plurals"),
    "grammar": ("Grammatik", "Forms and sentence patterns"),
    "sentences": ("Sätze", "Word order and production"),
    "listening": ("Hören", "Comprehension by ear"),
}


def _set_font(widget: QWidget, size: int, weight: QFont.Weight) -> None:
    set_feature_font(widget, size, weight)


class TodayPage(QWidget):
    practice_requested = Signal(str, str, str, int)
    open_mistakes = Signal()

    def __init__(self, session, _nav=None):
        super().__init__()
        self.setObjectName("TodayPage")
        self.setProperty("mahiraFeaturePage", True)
        self.session = session
        self.insights = InsightsService(session.repo)
        self._lane_widgets: dict[str, tuple[QLabel, QPushButton]] = {}
        self._recommended_context: tuple[str, str, str, int] | None = None
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)

        top_bar = QFrame()
        top_bar.setObjectName("TopBarCard")
        top_bar.setStyleSheet(TOP_BAR_STYLE)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 12, 16, 12)
        top_layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Today")
        _set_font(title, 15, QFont.Weight.Black)
        title.setStyleSheet("color:#FFFFFF;")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        _set_font(self.summary, 9, QFont.Weight.DemiBold)
        self.summary.setStyleSheet(f"color:{COLORS['muted']};")
        title_col.addWidget(title)
        title_col.addWidget(self.summary)

        self.goal_chip = QLabel()
        self.goal_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _set_font(self.goal_chip, 9, QFont.Weight.Bold)
        self.goal_chip.setStyleSheet(
            "QLabel { color:#FFFFFF; background:#1A1A1A; border:1px solid #2E2E2E; "
            "border-radius:8px; padding:6px 10px; }"
        )
        top_layout.addLayout(title_col, 1)
        top_layout.addWidget(self.goal_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(top_bar)

        progress_card = QFrame()
        progress_card.setObjectName("DailyProgressCard")
        progress_card.setStyleSheet(card_style())
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(16, 13, 16, 14)
        progress_layout.setSpacing(8)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        progress_label = QLabel("Daily review goal")
        _set_font(progress_label, 10, QFont.Weight.Bold)
        self.goal_value = QLabel()
        _set_font(self.goal_value, 10, QFont.Weight.Black)
        self.goal_value.setStyleSheet(f"color:{COLORS['action_focus']};")
        progress_row.addWidget(progress_label)
        progress_row.addStretch(1)
        progress_row.addWidget(self.goal_value)
        self.goal_bar = QProgressBar()
        self.goal_bar.setTextVisible(False)
        self.goal_bar.setAccessibleName("Daily review progress")
        progress_layout.addLayout(progress_row)
        progress_layout.addWidget(self.goal_bar)
        root.addWidget(progress_card)

        lanes_card = QFrame()
        lanes_card.setObjectName("StudyLanesCard")
        lanes_card.setStyleSheet(card_style())
        lanes_layout = QVBoxLayout(lanes_card)
        lanes_layout.setContentsMargins(16, 14, 16, 14)
        lanes_layout.setSpacing(0)

        lanes_title = QLabel("Study lanes")
        _set_font(lanes_title, 11, QFont.Weight.Black)
        lanes_layout.addWidget(lanes_title)
        lanes_layout.addSpacing(7)
        for index, objective in enumerate(_LABELS):
            lanes_layout.addWidget(self._lane_row(objective))
            if index < len(_LABELS) - 1:
                lanes_layout.addWidget(self._divider())
        next_card = QFrame()
        next_card.setObjectName("NextStepsCard")
        next_card.setStyleSheet(card_style())
        next_layout = QVBoxLayout(next_card)
        next_layout.setContentsMargins(16, 12, 16, 12)
        next_layout.setSpacing(0)

        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 6, 0, 10)
        path_layout.setSpacing(12)
        path_text = QVBoxLayout()
        path_text.setSpacing(2)
        path_title = QLabel("Recommended lesson")
        _set_font(path_title, 10, QFont.Weight.Bold)
        self.path_caption = QLabel()
        self.path_caption.setWordWrap(True)
        self.path_caption.setStyleSheet(f"color:{COLORS['muted']};")
        path_text.addWidget(path_title)
        path_text.addWidget(self.path_caption)
        path_layout.addLayout(path_text, 1)
        self.path_button = QPushButton("Continue")
        self.path_button.setAccessibleName("Continue recommended lesson")
        self.path_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.path_button.setMinimumWidth(100)
        self.path_button.clicked.connect(self._start_recommended)
        path_layout.addWidget(
            self.path_button,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        next_layout.addWidget(path_row)
        next_layout.addWidget(self._divider())

        trouble_row = QWidget()
        trouble_layout = QHBoxLayout(trouble_row)
        trouble_layout.setContentsMargins(0, 10, 0, 6)
        trouble_layout.setSpacing(12)
        trouble_text = QVBoxLayout()
        trouble_text.setSpacing(2)
        trouble_title = QLabel("Mistake notebook")
        _set_font(trouble_title, 10, QFont.Weight.Bold)
        self.trouble_caption = QLabel()
        self.trouble_caption.setWordWrap(True)
        self.trouble_caption.setStyleSheet(f"color:{COLORS['muted']};")
        trouble_text.addWidget(trouble_title)
        trouble_text.addWidget(self.trouble_caption)
        open_button = QPushButton("Open")
        open_button.setAccessibleName("Open mistake notebook")
        open_button.setStyleSheet(BUTTON_STYLE)
        open_button.setMinimumWidth(84)
        open_button.clicked.connect(self.open_mistakes.emit)
        trouble_layout.addLayout(trouble_text, 1)
        trouble_layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignVCenter)
        next_layout.addWidget(trouble_row)
        root.addWidget(next_card)
        root.addWidget(lanes_card)
        root.addStretch(1)

    @staticmethod
    def _divider() -> QFrame:
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background:{COLORS['divider']};border:none;")
        return divider

    def _lane_row(self, objective: str) -> QWidget:
        title, caption = _LABELS[objective]
        row = QWidget()
        row.setMinimumHeight(66)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 9, 0, 9)
        layout.setSpacing(12)

        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(title)
        _set_font(name, 11, QFont.Weight.Black)
        detail = QLabel(caption)
        detail.setWordWrap(True)
        detail.setStyleSheet(f"color:{COLORS['muted']};")
        text.addWidget(name)
        text.addWidget(detail)

        start = QPushButton("Study")
        start.setAccessibleName(f"Study {title}")
        start.setStyleSheet(PRIMARY_BUTTON_STYLE)
        start.setMinimumWidth(84)
        start.clicked.connect(lambda _checked=False, key=objective: self._start(key))

        layout.addLayout(text, 1)
        layout.addWidget(start, 0, Qt.AlignmentFlag.AlignVCenter)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._lane_widgets[objective] = (detail, start)
        return row

    def _start(self, objective: str) -> None:
        context = self.insights.recommended_context(objective)
        if context is None:
            state = self.session.state
            context = (state.level, state.book_slug, state.lektion_number)
        level, book, lesson = context
        self.practice_requested.emit(objective, level, book, lesson)

    def _start_recommended(self) -> None:
        if self._recommended_context is None:
            return
        self.practice_requested.emit(*self._recommended_context)

    def on_show(self) -> None:
        lanes = self.insights.lanes()
        reviewed = self.insights.reviewed_today()
        settings = getattr(self.session, "settings", None)
        prefs = getattr(settings, "value", None)
        goal = int(getattr(prefs, "daily_goal", 30))
        configured_new = getattr(
            prefs,
            "new_card_limit",
            getattr(getattr(self.session, "plan", None), "new_limit", 8),
        )
        try:
            new_limit = max(0, int(configured_new))
        except (TypeError, ValueError):
            new_limit = 8
        self.goal_chip.setText(f"{reviewed} / {goal}")
        self.goal_value.setText(f"{min(reviewed, goal)} of {goal}")
        self.goal_bar.setRange(0, max(1, goal))
        self.goal_bar.setValue(min(reviewed, goal))

        due_total = sum(lane.due for lane in lanes)
        self.summary.setText(
            f"{due_total} review{'s' if due_total != 1 else ''} ready across your library."
            if due_total
            else "You are caught up. Choose a lane to learn something new."
        )

        trouble_total = 0
        for lane in lanes:
            trouble_total += lane.trouble
            detail, button = self._lane_widgets[lane.objective]
            lane_health = (
                f"{lane.trouble} trouble spot{'s' if lane.trouble != 1 else ''}"
                if lane.trouble
                else "on track"
            )
            available_new = min(lane.unseen, new_limit)
            new_copy = (
                "no new cards"
                if not lane.unseen
                else (
                    f"up to {available_new} new"
                    if available_new
                    else "new cards paused"
                )
            )
            detail.setText(
                f"{_LABELS[lane.objective][1]} · {lane.due} due · "
                f"{new_copy} · {lane_health}"
            )
            button.setText("Review" if lane.due else "Learn")

        self.trouble_caption.setText(
            f"{trouble_total} recurring item{'s' if trouble_total != 1 else ''} need attention."
            if trouble_total
            else "Recurring errors will collect here automatically."
        )

        state = self.session.state
        self._recommended_context = None
        self.path_button.setEnabled(False)
        path = self.insights.lesson_path(state.level, state.book_slug)
        if not path:
            self.path_caption.setText("Choose a book and lesson in Setup to build your path.")
            return

        current = next((lesson for lesson in path if lesson.number == state.lektion_number), path[0])
        recommended = next(
            (lesson for lesson in path if lesson.unlocked and lesson.mastery < 80),
            current,
        )
        self.path_caption.setText(
            f"Lektion {recommended.number} · {recommended.title} · {recommended.mastery}% mastered"
        )
        objective = str(getattr(state, "objective", "") or "").strip().lower()
        if objective not in _LABELS:
            objective = "vocab"
        self._recommended_context = (
            objective,
            str(state.level or ""),
            str(state.book_slug or ""),
            int(recommended.number),
        )
        self.path_button.setAccessibleName(
            f"Continue {recommended.title}, Lektion {recommended.number}"
        )
        self.path_button.setEnabled(True)
