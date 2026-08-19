from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
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
from core.planner import DailyPlannerService
from ui.widgets.daily_plan_dialog import DailyPlanDialog
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
    plan_segment_requested = Signal(object)
    open_mistakes = Signal()

    def __init__(self, session, _nav=None):
        super().__init__()
        self.setObjectName("TodayPage")
        self.setProperty("mahiraFeaturePage", True)
        self.session = session
        self.insights = InsightsService(session.repo)
        self._lane_widgets: dict[str, tuple[QLabel, QPushButton]] = {}
        self._recommended_context: tuple[str, str, str, int] | None = None
        self._snapshot = None
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

        plan_header = QHBoxLayout()
        lanes_title = QLabel("Today's plan")
        _set_font(lanes_title, 11, QFont.Weight.Black)
        # The plan is otherwise only rebuilt by navigating away and back, even
        # though the failure copy tells the learner to "Refresh Today".
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setAccessibleName("Rebuild today's plan")
        self.refresh_btn.setStyleSheet(BUTTON_STYLE)
        self.refresh_btn.clicked.connect(self.on_show)
        self.adjust_plan_btn = QPushButton("Adjust plan...")
        self.adjust_plan_btn.setAccessibleName("Adjust daily plan")
        self.adjust_plan_btn.setStyleSheet(BUTTON_STYLE)
        self.adjust_plan_btn.clicked.connect(self._adjust_plan)
        plan_header.addWidget(lanes_title)
        plan_header.addStretch(1)
        plan_header.addWidget(self.refresh_btn)
        plan_header.addWidget(self.adjust_plan_btn)
        lanes_layout.addLayout(plan_header)

        self.plan_totals = QLabel()
        self.plan_totals.setWordWrap(True)
        _set_font(self.plan_totals, 10, QFont.Weight.Black)
        self.plan_ready = QLabel()
        self.plan_ready.setWordWrap(True)
        self.plan_ready.setStyleSheet(f"color:{COLORS['muted']};")
        self.plan_backlog = QLabel()
        self.plan_backlog.setWordWrap(True)
        self.plan_backlog.setStyleSheet(f"color:{COLORS['muted']};")
        self.plan_segments = QLabel()
        self.plan_segments.setWordWrap(True)
        self.plan_segments.setStyleSheet(f"color:{COLORS['muted']};")
        self.plan_error = QLabel()
        self.plan_error.setWordWrap(True)
        self.plan_error.setStyleSheet(
            "QLabel { color:#FF9B9B; background:#261515; border:1px solid #5A2929; "
            "border-radius:8px; padding:8px; font-weight:750; }"
        )
        self.plan_error.hide()
        lanes_layout.addWidget(self.plan_totals)
        lanes_layout.addWidget(self.plan_ready)
        lanes_layout.addWidget(self.plan_backlog)
        lanes_layout.addWidget(self.plan_segments)
        lanes_layout.addWidget(self.plan_error)

        self.start_next_btn = QPushButton("Start next set")
        self.start_next_btn.setAccessibleName("Start next set from today's plan")
        self.start_next_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.start_next_btn.clicked.connect(self._start_next_segment)
        lanes_layout.addWidget(self.start_next_btn)
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
        root.addWidget(lanes_card)
        root.addWidget(next_card)
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
        segment = self._segment_for_objective(objective)
        if segment is not None:
            self.plan_segment_requested.emit(segment)

    def _start_next_segment(self) -> None:
        segments = tuple(getattr(self._snapshot, "segments", ()) or ())
        if segments:
            self.plan_segment_requested.emit(segments[0])

    def _segment_for_objective(self, objective: str):
        for segment in tuple(getattr(self._snapshot, "segments", ()) or ()):
            if segment.objective == objective:
                return segment
        return None

    def _adjust_plan(self) -> None:
        settings = getattr(self.session, "settings", None)
        if settings is None:
            self.show_plan_error("Planner settings are not available.")
            return
        if DailyPlanDialog(settings, self).exec() == QDialog.DialogCode.Accepted:
            self.on_show()

    def _planner_snapshot(self):
        for name in ("planner", "_planner", "planner_service", "_daily_planner"):
            service = getattr(self, name, None)
            if service is not None and callable(getattr(service, "snapshot", None)):
                return service.snapshot()
        settings = getattr(getattr(self.session, "settings", None), "value", None)
        if settings is None:
            raise RuntimeError("Planner settings are unavailable")
        ranker = (
            getattr(self.session, "ml", None)
            if bool(getattr(self.session, "enable_ml_ranking", True))
            else None
        )
        return DailyPlannerService(
            self.session.repo,
            settings,
            ranker=ranker,
        ).snapshot()

    def show_plan_error(self, message: str) -> None:
        self.plan_error.setText(str(message or "Today's plan could not be started."))
        self.plan_error.show()

    def _render_plan(self, snapshot) -> None:
        self._snapshot = snapshot
        self.plan_error.clear()
        self.plan_error.hide()
        goal = max(0, int(snapshot.goal))
        completed = max(0, int(snapshot.completed_total))
        planned = max(0, int(snapshot.planned_total))
        self.goal_chip.setText(f"{completed} / {goal}")
        self.goal_value.setText(f"{completed} completed · {planned} planned")
        self.goal_bar.setRange(0, max(1, goal))
        self.goal_bar.setValue(min(completed, goal))
        self.plan_totals.setText(f"{completed} completed · {planned} planned")

        planned_due = sum(
            max(0, int(row.planned_due)) for row in snapshot.objectives
        )
        planned_new = sum(
            max(0, int(row.planned_new)) for row in snapshot.objectives
        )
        self.plan_ready.setText(
            f'{planned_due} due - {planned_new} new in plan'
        )
        self.plan_backlog.setText(
            'More practice remains available after the plan.'
            if snapshot.backlog_due or snapshot.backlog_new
            else 'No additional practice is available right now.'
        )
        count = len(snapshot.segments)
        self.plan_segments.setText(
            f"{count} focused set{'s' if count != 1 else ''}"
            if count
            else "No focused set is planned right now."
        )
        self.start_next_btn.setEnabled(bool(snapshot.segments))

        rows = {row.objective: row for row in snapshot.objectives}
        for objective in _LABELS:
            detail, button = self._lane_widgets[objective]
            row = rows.get(objective)
            segment = self._segment_for_objective(objective)
            if row is None:
                detail.setText("0 completed · 0 planned")
            else:
                detail.setText(
                    f"{row.completed} completed · {row.planned} planned · "
                    f"{row.planned_due} due + {row.planned_new} new"
                )
            button.setEnabled(segment is not None)
            button.setText("Start" if segment is not None else "No set")
            button.setAccessibleName(
                f"Start {_LABELS[objective][0]} planned set"
            )

        if snapshot.segments:
            self.summary.setText('Your focused plan is ready to study.')
        elif snapshot.backlog_due or snapshot.backlog_new:
            # Goal spent, work left. Saying "more practice remains" while every
            # button is disabled is a dead end, so name the control that opens
            # it back up - Adjust plan now owns the daily goal.
            if snapshot.remaining_goal <= 0:
                self.summary.setText(
                    f"Daily goal of {snapshot.goal} reached - nicely done. "
                    f"{snapshot.backlog_due} due and {snapshot.backlog_new} new "
                    "cards are still waiting; raise the goal in Adjust plan to "
                    "keep going today."
                )
            else:
                self.summary.setText(
                    'More practice remains available after the plan.'
                )
        else:
            self.summary.setText('You are caught up. The plan is complete.')

    def _start_recommended(self) -> None:
        if self._recommended_context is None:
            return
        self.practice_requested.emit(*self._recommended_context)

    def on_show(self) -> None:
        try:
            self._render_plan(self._planner_snapshot())
        except Exception:
            self._snapshot = None
            self.start_next_btn.setEnabled(False)
            self.summary.setText("Today's plan is temporarily unavailable.")
            self.goal_chip.setText("-- / --")
            self.goal_value.setText("Plan unavailable")
            self.goal_bar.setRange(0, 1)
            self.goal_bar.setValue(0)
            self.plan_totals.setText("Plan unavailable")
            self.plan_ready.clear()
            self.plan_backlog.clear()
            self.plan_segments.clear()
            for detail, button in self._lane_widgets.values():
                detail.setText("Refresh Today to rebuild this plan.")
                button.setEnabled(False)
                button.setText("Unavailable")
            self.refresh_btn.setEnabled(True)
            self.show_plan_error("Today's plan could not be refreshed.")

        try:
            if callable(getattr(self.insights, "trouble_items", None)):
                trouble_total = len(self.insights.trouble_items(limit=100))
            else:
                trouble_total = sum(
                    lane.trouble for lane in self.insights.lanes()
                )
        except Exception:
            trouble_total = 0

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
