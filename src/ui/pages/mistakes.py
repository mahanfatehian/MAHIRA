from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.insights import InsightsService, TroubleItem
from ui.theme import (
    BUTTON_STYLE,
    COLORS,
    SYSTEM_BUTTON_STYLE,
    TOP_BAR_STYLE,
    set_feature_font,
)


_RENDER_BATCH = 24


def _set_font(widget: QWidget, size: int, weight: QFont.Weight) -> None:
    set_feature_font(widget, size, weight)


class MistakesPage(QWidget):
    practice_requested = Signal(str, str, str, int)
    lab_requested = Signal(str, str, int, str)

    def __init__(self, session, _nav=None):
        super().__init__()
        self.setObjectName("MistakesPage")
        self.setProperty("mahiraFeaturePage", True)
        self.session = session
        self.insights = InsightsService(session.repo)
        self._items: list[TroubleItem] = []
        self._render_generation = 0
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
        title = QLabel("Mistakes")
        _set_font(title, 15, QFont.Weight.Black)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        _set_font(self.caption, 9, QFont.Weight.DemiBold)
        self.caption.setStyleSheet(f"color:{COLORS['muted']};")
        title_col.addWidget(title)
        title_col.addWidget(self.caption)

        self.count_chip = QLabel("0 items")
        self.count_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _set_font(self.count_chip, 9, QFont.Weight.Bold)
        self.count_chip.setStyleSheet(
            "QLabel { color:#FFFFFF; background:#1A1A1A; border:1px solid #2E2E2E; "
            "border-radius:8px; padding:6px 10px; }"
        )
        top_layout.addLayout(title_col, 1)
        top_layout.addWidget(self.count_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(top_bar)

        self.status = QLabel()
        self.status.setObjectName("MistakesStatus")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        root.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("MistakesScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.rows_widget = QWidget()
        self.rows_widget.setObjectName("MistakeRows")
        self.rows_widget.setStyleSheet("QWidget#MistakeRows { background:transparent; }")
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.rows_widget)
        root.addWidget(self.scroll, 1)

    def on_show(self) -> None:
        self._reload(clear_status=True)

    def _reload(self, *, clear_status: bool) -> None:
        if clear_status:
            self.status.clear()
            self.status.hide()

        self._items = self.insights.trouble_items()
        count = len(self._items)
        self.count_chip.setText(f"{count} item{'s' if count != 1 else ''}")
        self.caption.setText(
            "Review recurring errors, pause an unsuitable card, or hide it until tomorrow."
            if count
            else "Recurring errors will appear here after review."
        )
        self._render_rows()

    def _clear_rows(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Detach immediately so accessibility lookups and subsequent
                # actions cannot discover a stale row before deleteLater runs.
                widget.setParent(None)
                widget.deleteLater()

    def _render_rows(self) -> None:
        self._render_generation += 1
        generation = self._render_generation
        self._clear_rows()

        if not self._items:
            self.rows_layout.addWidget(self._empty_state())
            return

        def add_batch(start: int) -> None:
            if generation != self._render_generation:
                return
            stop = min(len(self._items), start + _RENDER_BATCH)
            self.rows_widget.setUpdatesEnabled(False)
            try:
                for item in self._items[start:stop]:
                    self.rows_layout.addWidget(self._row_card(item))
            finally:
                self.rows_widget.setUpdatesEnabled(True)
                self.rows_widget.update()
            if stop < len(self._items):
                QTimer.singleShot(0, lambda next_start=stop: add_batch(next_start))

        add_batch(0)

    def _empty_state(self) -> QFrame:
        card = QFrame()
        card.setObjectName("MistakesEmptyState")
        card.setMinimumHeight(220)
        card.setStyleSheet(
            "QFrame#MistakesEmptyState { background:#141414; border:1px solid #2A2A2A; "
            "border-radius:14px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = QLabel("Nothing needs attention")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _set_font(heading, 13, QFont.Weight.Black)
        copy = QLabel("Keep reviewing. Repeated lapses and flagged cards will collect here.")
        copy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copy.setWordWrap(True)
        copy.setStyleSheet(f"color:{COLORS['muted']};")
        layout.addWidget(heading)
        layout.addWidget(copy)
        return card

    def _row_card(self, item: TroubleItem) -> QFrame:
        card = QFrame()
        card.setObjectName("MistakeRow")
        card.setAccessibleName(
            f"{item.objective.title()} {item.practice_mode.title()} mistake: "
            f"{item.prompt}"
        )
        card.setStyleSheet(
            "QFrame#MistakeRow { background:#141414; border:1px solid #2A2A2A; "
            "border-radius:14px; }"
            "QFrame#MistakeRow:hover { background:#161616; border-color:#3A3A3A; }"
            "QFrame#MistakeRow QLabel { background:transparent; border:none; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(8)

        meta = QHBoxLayout()
        meta.setSpacing(7)
        lane_name = (
            f"{item.objective.title()} · {item.practice_mode.title()}"
        )
        lane = self._chip(lane_name, "#1A1A1A", "#BDBDBD")
        lapses = self._chip(
            f"{item.lapses} lapse{'s' if item.lapses != 1 else ''}",
            "#24191B",
            "#FFB4BC",
        )
        state = self._chip(
            "Suspended" if item.suspended else "Active",
            "#202020" if item.suspended else "#17271E",
            "#9A9A9A" if item.suspended else "#7AE582",
        )
        meta.addWidget(lane)
        meta.addWidget(lapses)
        meta.addStretch(1)
        meta.addWidget(state)
        layout.addLayout(meta)

        prompt = QLabel(item.prompt or "Untitled card")
        prompt.setWordWrap(True)
        prompt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        _set_font(prompt, 11, QFont.Weight.Black)
        answer = QLabel(item.answer or "No answer stored")
        answer.setWordWrap(True)
        answer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        answer.setStyleSheet(f"color:{COLORS['muted']};")
        layout.addWidget(prompt)
        layout.addWidget(answer)
        if item.error_tags:
            tag_labels = {
                "capitalization": "capitalization",
                "article_missing": "missing article",
                "article": "article or case",
                "word_order": "word order",
                "punctuation": "punctuation",
                "spelling": "spelling",
                "different_answer": "answer mismatch",
            }
            issues = [
                tag_labels.get(tag.strip(), tag.strip().replace("_", " "))
                for tag in item.error_tags.split(",")
                if tag.strip()
            ]
            if issues:
                focus = QLabel("Focus: " + " · ".join(issues))
                focus.setWordWrap(True)
                focus.setStyleSheet(f"color:{COLORS['danger_text']};")
                _set_font(focus, 9, QFont.Weight.DemiBold)
                layout.addWidget(focus)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        practice = QPushButton("Practice")
        practice.setObjectName("MistakePracticeButton")
        practice.setAccessibleName(f"Practice {item.prompt}")
        practice.setStyleSheet(SYSTEM_BUTTON_STYLE)
        practice.setMinimumWidth(84)
        practice.clicked.connect(
            lambda _checked=False, target=item: self._study(target)
        )

        tomorrow = QPushButton("Tomorrow")
        tomorrow.setObjectName("MistakeTomorrowButton")
        tomorrow.setAccessibleName(f"Hide {item.prompt} until tomorrow")
        tomorrow.setToolTip("Hide this card until the next local day")
        tomorrow.setStyleSheet(BUTTON_STYLE)
        tomorrow.setMinimumWidth(94)
        tomorrow.setEnabled(not item.suspended)
        tomorrow.clicked.connect(
            lambda _checked=False, target=item: self._bury(target)
        )

        suspend = QPushButton("Resume" if item.suspended else "Suspend")
        suspend.setObjectName("MistakeSuspendButton")
        suspend.setAccessibleName(f"{suspend.text()} {item.prompt}")
        suspend.setMinimumWidth(86)
        suspend.setStyleSheet(
            BUTTON_STYLE
            if item.suspended
            else f"""
                QPushButton {{ background:{COLORS['danger']}; color:{COLORS['danger_text']};
                    border:1px solid #6B303A; border-radius:10px; padding:8px 12px;
                    min-height:18px; font-weight:800; }}
                QPushButton:hover {{ background:{COLORS['danger_hover']}; border-color:{COLORS['danger_text']}; }}
                QPushButton:focus {{ border-color:{COLORS['action_focus']}; }}
            """
        )
        suspend.clicked.connect(
            lambda _checked=False, target=item: self._toggle(target)
        )

        actions.addWidget(practice)
        actions.addWidget(tomorrow)
        actions.addWidget(suspend)
        layout.addLayout(actions)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return card

    @staticmethod
    def _chip(text: str, background: str, color: str) -> QLabel:
        chip = QLabel(text)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _set_font(chip, 8, QFont.Weight.Bold)
        chip.setStyleSheet(
            f"QLabel {{ background:{background}; color:{color}; border:1px solid #2E2E2E; "
            "border-radius:7px; padding:4px 8px; }"
        )
        return chip

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.status.setText(message)
        if error:
            self.status.setStyleSheet(
                f"QLabel {{ background:#24191B; color:{COLORS['danger_text']}; "
                "border:1px solid #6B303A; border-radius:10px; padding:9px 12px; }"
            )
        else:
            self.status.setStyleSheet(
                f"QLabel {{ background:#17271E; color:{COLORS['action_focus']}; "
                "border:1px solid #315F42; border-radius:10px; padding:9px 12px; }"
            )
        self.status.show()

    def _toggle(self, item: TroubleItem) -> None:
        try:
            suspended = not item.suspended
            self.insights.set_suspended(item.objective, item.item_id, suspended)
            if suspended:
                self.session.exclude_from_queue(item.objective, item.item_id)
            self._set_status(
                f"{'Suspended' if suspended else 'Resumed'}: {item.prompt}"
            )
            self._reload(clear_status=False)
        except Exception as exc:
            self._set_status(f"Could not update this card: {exc}", error=True)

    def _bury(self, item: TroubleItem) -> None:
        try:
            buried_until = self.insights.bury(item.objective, item.item_id)
            self.session.exclude_from_queue(item.objective, item.item_id)
            visible_time = datetime.fromtimestamp(buried_until).strftime("%A at %H:%M")
            self._set_status(f"Hidden until {visible_time}: {item.prompt}")
            self._reload(clear_status=False)
        except Exception as exc:
            self._set_status(f"Could not hide this card: {exc}", error=True)

    def _study(self, item: TroubleItem) -> None:
        if item.practice_mode in {"production", "dictation"}:
            self.lab_requested.emit(
                item.level,
                item.book_slug,
                item.lektion_number,
                item.practice_mode,
            )
            return
        self.practice_requested.emit(
            item.objective,
            item.level,
            item.book_slug,
            item.lektion_number,
        )
