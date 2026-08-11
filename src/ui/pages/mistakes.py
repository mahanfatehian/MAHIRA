from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
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
from core.mistake_rules import (
    TAG_LABELS,
    error_tags,
    learn_reference_for_tags,
    tag_label,
)
from ui.theme import (
    BUTTON_STYLE,
    COLORS,
    SYSTEM_BUTTON_STYLE,
    TOP_BAR_STYLE,
    set_feature_font,
)
from ui.widgets.flow_layout import FlowLayout


_RENDER_BATCH = 24
_FACET_LIMIT = 500
_LAST_LIMITS = (10, 20, 50)
_KNOWN_LEVELS = ('A1', 'A2', 'B1', 'B2', 'C1', 'C2')
_KNOWN_LANES = (
    ('vocab', 'recognition'),
    ('vocab', 'production'),
    ('vocab', 'dictation'),
    ('grammar', 'production'),
    ('sentences', 'builder'),
    ('listening', 'comprehension'),
)
_FILTER_SEPARATOR = '\x1f'


@dataclass(frozen=True)
class MistakeDrillRequest:
    objective: str
    practice_mode: str
    deck_id: int
    level: str
    book_slug: str
    lektion_number: int
    item_ids: tuple[int, ...]


def _set_font(widget: QWidget, size: int, weight: QFont.Weight) -> None:
    set_feature_font(widget, size, weight)


def _book_label(slug: str) -> str:
    return ' '.join(
        part.capitalize()
        for part in str(slug or '').replace('-', '_').split('_')
        if part
    )


def _lane_key(item) -> tuple[str, str]:
    return (
        str(getattr(item, 'objective', '') or '').strip().lower(),
        str(getattr(item, 'practice_mode', '') or '').strip().lower(),
    )


def _lane_label(lane: tuple[str, str]) -> str:
    objective, mode = lane
    objectives = {
        'vocab': 'Vocab',
        'grammar': 'Grammar',
        'sentences': 'Sentences',
        'listening': 'Listening',
    }
    modes = {
        'recognition': 'Recognition',
        'production': 'Production',
        'dictation': 'Dictation',
        'builder': 'Builder',
        'comprehension': 'Comprehension',
    }
    return '{} · {}'.format(
        objectives.get(objective, objective.title()),
        modes.get(mode, mode.title()),
    )


def _lesson_key(item) -> tuple[str, str, int]:
    return (
        str(getattr(item, 'level', '') or '').strip().upper(),
        str(getattr(item, 'book_slug', '') or '').strip(),
        int(getattr(item, 'lektion_number', 0) or 0),
    )


def _lesson_label(lesson: tuple[str, str, int]) -> str:
    level, book_slug, number = lesson
    parts = [part for part in (level, _book_label(book_slug)) if part]
    if number:
        parts.append('Lektion {}'.format(number))
    return ' · '.join(parts) or 'Unassigned lesson'


def _lesson_context_is_valid(item) -> bool:
    level, book_slug, number = _lesson_key(item)
    return bool(level) and bool(book_slug) == bool(number)


def _lesson_filter_value(lesson: tuple[str, str, int]) -> str:
    level, book_slug, number = lesson
    return _FILTER_SEPARATOR.join(
        ('lesson', str(level), str(book_slug), str(int(number)))
    )


def _lane_filter_value(lane: tuple[str, str]) -> str:
    objective, practice_mode = lane
    return _FILTER_SEPARATOR.join(('lane', str(objective), str(practice_mode)))


def _parse_lesson_filter(value) -> tuple[str, str, int] | None:
    parts = str(value or '').split(_FILTER_SEPARATOR)
    if len(parts) != 4 or parts[0] != 'lesson':
        return None
    try:
        return parts[1], parts[2], int(parts[3])
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_lane_filter(value) -> tuple[str, str] | None:
    parts = str(value or '').split(_FILTER_SEPARATOR)
    if len(parts) != 3 or parts[0] != 'lane':
        return None
    return parts[1], parts[2]


class MistakesPage(QWidget):
    # Compatibility signals remain public for existing embedders. MainWindow
    # intentionally connects only the typed drill signal below.
    drill_requested = Signal(object)
    learn_requested = Signal(str, str)
    practice_requested = Signal(str, str, str, int)
    lab_requested = Signal(str, str, int, str)

    def __init__(self, session, _nav=None):
        super().__init__()
        self.setObjectName("MistakesPage")
        self.setProperty("mahiraFeaturePage", True)
        self.session = session
        self.insights = InsightsService(session.repo)
        self._items: list[TroubleItem] = []
        self._catalog_items: list[TroubleItem] = []
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

        filters = QFrame()
        filters.setObjectName('MistakesFilters')
        filters.setStyleSheet(
            'QFrame#MistakesFilters { background:#111111; border:1px solid #292929; '
            'border-radius:12px; }'
        )
        filter_flow = FlowLayout(filters, margin=10, hspacing=8, vspacing=8)

        self.source_filter = QComboBox()
        self.source_filter.setObjectName('MistakeSourceFilter')
        self.source_filter.addItem('Recent failures', 'recent')
        self.source_filter.addItem('Recurring & flagged', 'recurring')
        filter_flow.addWidget(
            self._filter_control('View', self.source_filter, minimum_width=164)
        )

        self.error_filter = QComboBox()
        self.error_filter.setObjectName('MistakeErrorFilter')
        self.error_filter.addItem('All error types', None)
        filter_flow.addWidget(
            self._filter_control('Error', self.error_filter, minimum_width=164)
        )

        self.lesson_filter = QComboBox()
        self.lesson_filter.setObjectName('MistakeLessonFilter')
        self.lesson_filter.addItem('All lessons', None)
        filter_flow.addWidget(
            self._filter_control('Lektion', self.lesson_filter, minimum_width=184)
        )

        self.lane_filter = QComboBox()
        self.lane_filter.setObjectName('MistakeLaneFilter')
        self.lane_filter.addItem('All lanes', None)
        filter_flow.addWidget(
            self._filter_control('Lane', self.lane_filter, minimum_width=164)
        )

        self.last_filter = QComboBox()
        self.last_filter.setObjectName('MistakeLastFilter')
        for limit in _LAST_LIMITS:
            self.last_filter.addItem('Show {}'.format(limit), limit)
        self.last_filter.setCurrentIndex(1)
        filter_flow.addWidget(
            self._filter_control('History', self.last_filter, minimum_width=112)
        )

        self.practice_these = QPushButton('Practice these')
        self.practice_these.setObjectName('MistakePracticeTheseButton')
        self.practice_these.setAccessibleName('Practice visible mistake cards')
        self.practice_these.setStyleSheet(SYSTEM_BUTTON_STYLE)
        self.practice_these.setMinimumWidth(150)
        self.practice_these.clicked.connect(self._study_visible)
        filter_flow.addWidget(self.practice_these)
        root.addWidget(filters)

        self.drill_hint = QLabel()
        self.drill_hint.setObjectName('MistakeDrillHint')
        self.drill_hint.setWordWrap(True)
        self.drill_hint.setStyleSheet('color:{};'.format(COLORS['muted']))
        _set_font(self.drill_hint, 8, QFont.Weight.DemiBold)
        root.addWidget(self.drill_hint)

        self.source_filter.currentIndexChanged.connect(self._source_changed)
        for combo in (
            self.error_filter,
            self.lesson_filter,
            self.lane_filter,
            self.last_filter,
        ):
            combo.currentIndexChanged.connect(self._filters_changed)

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

    @staticmethod
    def _filter_control(
        label_text: str,
        control: QComboBox,
        *,
        minimum_width: int,
    ) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        label = QLabel(label_text)
        label.setStyleSheet('color:{};'.format(COLORS['muted']))
        _set_font(label, 8, QFont.Weight.Bold)
        control.setMinimumWidth(minimum_width)
        control.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(label)
        layout.addWidget(control)
        return holder

    def on_show(self) -> None:
        self._reload(clear_status=True, refresh_facets=True)

    def _source_changed(self, _index: int = -1) -> None:
        self._reload(clear_status=True, refresh_facets=True)

    def _filters_changed(self, _index: int = -1) -> None:
        self._reload(clear_status=True, refresh_facets=False)

    def _query_items(self, *, catalog: bool) -> list[TroubleItem]:
        limit = _FACET_LIMIT if catalog else int(self.last_filter.currentData() or 20)
        raw_lesson = None if catalog else self.lesson_filter.currentData()
        raw_lane = None if catalog else self.lane_filter.currentData()
        lesson = _parse_lesson_filter(raw_lesson)
        lane = _parse_lane_filter(raw_lane)
        if raw_lesson is not None and lesson is None:
            raise ValueError('Invalid lesson filter')
        if raw_lane is not None and lane is None:
            raise ValueError('Invalid lane filter')
        tag = None if catalog else self.error_filter.currentData()
        source = str(self.source_filter.currentData() or 'recent')

        if source == 'recurring':
            trouble = getattr(self.insights, 'trouble_items', None)
            items = list(trouble()) if callable(trouble) else []
            if lesson is not None:
                items = [item for item in items if _lesson_key(item) == lesson]
            if lane is not None:
                items = [item for item in items if _lane_key(item) == lane]
            if tag is not None:
                items = [
                    item
                    for item in items
                    if str(tag) in error_tags(item.error_tags)
                ]
            return items[:limit]
        if source != 'recent':
            return []

        recent = getattr(self.insights, 'recent_failures', None)
        if callable(recent):
            kwargs = {'limit': limit}
            if lesson is not None:
                level, book_slug, lektion_number = lesson
                kwargs.update(
                    level=level,
                    book_slug=book_slug,
                    lektion_number=int(lektion_number),
                )
            if lane is not None:
                objective, practice_mode = lane
                kwargs.update(
                    objective=objective,
                    practice_mode=practice_mode,
                )
            if tag is not None:
                kwargs['tag'] = str(tag)
            return list(recent(**kwargs))[:limit]
        return []

    @staticmethod
    def _restore_combo(
        combo: QComboBox,
        all_label: str,
        options: Iterable[tuple[str, object]],
    ) -> None:
        selected = combo.currentData()
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(all_label, None)
            selected_index = 0
            for label, value in options:
                combo.addItem(label, value)
                if selected is not None and value == selected:
                    selected_index = combo.count() - 1
            combo.setCurrentIndex(selected_index)
        finally:
            combo.blockSignals(False)

    def _library_lessons(self) -> set[tuple[str, str, int]]:
        repo = getattr(self.session, 'repo', None)
        get_books = getattr(repo, 'get_books_for_level', None)
        get_lessons = getattr(repo, 'get_lektions_for_book_level', None)
        if not callable(get_books) or not callable(get_lessons):
            return set()
        result: set[tuple[str, str, int]] = set()
        for level in _KNOWN_LEVELS:
            try:
                books = get_books(level)
            except Exception:
                continue
            for book in books:
                try:
                    lessons = get_lessons(int(book.id), level)
                except Exception:
                    continue
                for lesson in lessons:
                    number = int(getattr(lesson, 'number', 0) or 0)
                    slug = str(getattr(book, 'slug', '') or '').strip()
                    if slug and number > 0:
                        result.add((level, slug, number))
        return result

    def _populate_facets(self) -> None:
        lessons = sorted(
            self._library_lessons()
            | {
                _lesson_key(item)
                for item in self._catalog_items
                if all(_lesson_key(item))
            }
        )
        lanes = sorted(
            set(_KNOWN_LANES)
            | {
                _lane_key(item)
                for item in self._catalog_items
                if all(_lane_key(item))
            },
            key=_lane_label,
        )
        tags = sorted(
            set(TAG_LABELS)
            | {
                tag
                for item in self._catalog_items
                for tag in error_tags(item.error_tags)
            },
            key=tag_label,
        )
        self._restore_combo(
            self.error_filter,
            'All error types',
            ((tag_label(tag).capitalize(), tag) for tag in tags),
        )
        self._restore_combo(
            self.lesson_filter,
            'All lessons',
            (
                (_lesson_label(lesson), _lesson_filter_value(lesson))
                for lesson in lessons
            ),
        )
        self._restore_combo(
            self.lane_filter,
            'All lanes',
            ((_lane_label(lane), _lane_filter_value(lane)) for lane in lanes),
        )

    def _has_active_facet_filter(self) -> bool:
        return any(
            combo.currentData() is not None
            for combo in (
                self.error_filter,
                self.lesson_filter,
                self.lane_filter,
            )
        )

    def _reload(self, *, clear_status: bool, refresh_facets: bool = True) -> None:
        if clear_status:
            self.status.clear()
            self.status.hide()
        try:
            if refresh_facets:
                self._catalog_items = self._query_items(catalog=True)
                self._populate_facets()
            if self._has_active_facet_filter():
                self._items = self._query_items(catalog=False)
            else:
                limit = int(self.last_filter.currentData() or 20)
                self._items = list(self._catalog_items[:limit])
        except Exception as exc:
            self._items = []
            self._set_status('Could not load recent mistakes: {}'.format(exc), error=True)

        count = len(self._items)
        self.count_chip.setText('{} item{}'.format(count, '' if count == 1 else 's'))
        if self.source_filter.currentData() == 'recurring':
            self.caption.setText(
                'Manage recurring lapses and learner-flagged cards.'
                if count
                else 'No recurring or flagged cards need attention.'
            )
        else:
            self.caption.setText(
                'Filter recent failed answers, then practice a safe one-off queue.'
                if count
                else 'Recent failed answers will appear here after review.'
            )
        self._update_drill_action()
        self._render_rows()

    @staticmethod
    def _cohort_key(item: TroubleItem) -> tuple[int, str, str]:
        objective, practice_mode = _lane_key(item)
        return int(item.deck_id), objective, practice_mode

    def _request_for(
        self,
        items: Iterable[TroubleItem],
    ) -> MistakeDrillRequest | None:
        active = [item for item in items if not bool(item.suspended)]
        if not active or len({self._cohort_key(item) for item in active}) != 1:
            return None
        first = active[0]
        level, book_slug, lektion_number = _lesson_key(first)
        objective, practice_mode = _lane_key(first)
        if (
            not _lesson_context_is_valid(first)
            or not objective
            or not practice_mode
        ):
            return None
        item_ids = tuple(dict.fromkeys(int(item.item_id) for item in active))
        if not item_ids:
            return None
        return MistakeDrillRequest(
            objective=objective,
            practice_mode=practice_mode,
            deck_id=int(first.deck_id),
            level=level,
            book_slug=book_slug,
            lektion_number=lektion_number,
            item_ids=item_ids,
        )

    def _update_drill_action(self) -> None:
        request = self._request_for(self._items)
        self.practice_these.setEnabled(request is not None)
        active_count = sum(not bool(item.suspended) for item in self._items)
        self.practice_these.setText(
            'Practice these ({})'.format(active_count)
            if active_count
            else 'Practice these'
        )
        if request is not None:
            self.drill_hint.setText(
                'One-off queue: {} active card{} from one deck and lane.'.format(
                    active_count,
                    '' if active_count == 1 else 's',
                )
            )
        elif not active_count:
            self.drill_hint.setText('No active visible cards are available to practice.')
        elif any(
            not _lesson_context_is_valid(item)
            for item in self._items
            if not bool(item.suspended)
        ):
            self.drill_hint.setText(
                'Cards with only part of a Lektion context can still be hidden or '
                'suspended, but cannot start a targeted drill.'
            )
        else:
            self.drill_hint.setText(
                'Choose one Lektion and one lane to enable a safe one-off queue.'
            )

    def _study_visible(self) -> None:
        request = self._request_for(self._items)
        if request is not None:
            self.drill_requested.emit(request)

    def show_drill_error(self, message: str) -> None:
        self._set_status(message, error=True)

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
        card.setObjectName('MistakeRow')
        card.setAccessibleName(
            '{} {} mistake: {}'.format(
                item.objective.title(), item.practice_mode.title(), item.prompt
            )
        )
        card.setStyleSheet(
            'QFrame#MistakeRow { background:#141414; border:1px solid #2A2A2A; '
            'border-radius:14px; }'
            'QFrame#MistakeRow:hover { background:#161616; border-color:#3A3A3A; }'
            'QFrame#MistakeRow QLabel { background:transparent; border:none; }'
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(8)

        meta_host = QWidget()
        meta = FlowLayout(meta_host, margin=0, hspacing=7, vspacing=6)
        meta.addWidget(self._chip(_lane_label(_lane_key(item)), '#1A1A1A', '#BDBDBD'))
        failure_count = int(getattr(item, 'failure_count', 0) or 0)
        mistake_count = failure_count or int(item.lapses)
        count_text = (
            '{} recent miss{}'.format(mistake_count, '' if mistake_count == 1 else 'es')
            if failure_count
            else '{} lapse{}'.format(mistake_count, '' if mistake_count == 1 else 's')
        )
        meta.addWidget(self._chip(count_text, '#24191B', '#FFB4BC'))
        meta.addWidget(
            self._chip(
                'Suspended' if item.suspended else 'Active',
                '#202020' if item.suspended else '#17271E',
                '#9A9A9A' if item.suspended else '#7AE582',
            )
        )
        layout.addWidget(meta_host)

        prompt = QLabel(item.prompt or 'Untitled card')
        prompt.setWordWrap(True)
        prompt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        _set_font(prompt, 11, QFont.Weight.Black)
        answer = QLabel(item.answer or 'No answer stored')
        answer.setWordWrap(True)
        answer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        answer.setStyleSheet('color:{};'.format(COLORS['muted']))
        layout.addWidget(prompt)
        layout.addWidget(answer)

        lesson = QLabel(_lesson_label(_lesson_key(item)))
        lesson.setWordWrap(True)
        lesson.setStyleSheet('color:{};'.format(COLORS['muted']))
        _set_font(lesson, 8, QFont.Weight.DemiBold)
        layout.addWidget(lesson)

        tags = error_tags(item.error_tags)
        if tags:
            focus = QLabel('Focus: ' + ' \u00b7 '.join(tag_label(tag) for tag in tags))
            focus.setWordWrap(True)
            focus.setStyleSheet('color:{};'.format(COLORS['danger_text']))
            _set_font(focus, 9, QFont.Weight.DemiBold)
            layout.addWidget(focus)

        if bool(getattr(item, 'is_leech', False)):
            guidance = QFrame()
            guidance.setObjectName('MistakeLeechGuidance')
            guidance.setStyleSheet(
                'QFrame#MistakeLeechGuidance { background:#211B12; '
                'border:1px solid #66522C; border-radius:10px; }'
            )
            guidance_layout = QVBoxLayout(guidance)
            guidance_layout.setContentsMargins(11, 8, 11, 8)
            guidance_layout.setSpacing(2)
            guidance_title = QLabel('This one keeps returning')
            _set_font(guidance_title, 9, QFont.Weight.Black)
            guidance_copy = QLabel(
                '{} misses in {} days. Review the rule or consider suspending '
                'the card; nothing is changed automatically.'.format(
                    failure_count,
                    int(getattr(item, 'leech_window_days', 30) or 30),
                )
            )
            guidance_copy.setWordWrap(True)
            guidance_copy.setStyleSheet('color:#D8C9A6;')
            guidance_layout.addWidget(guidance_title)
            guidance_layout.addWidget(guidance_copy)
            layout.addWidget(guidance)

        actions_host = QWidget()
        actions = FlowLayout(actions_host, margin=0, hspacing=8, vspacing=8)
        reference = learn_reference_for_tags(item.error_tags)
        if reference is not None:
            learn = QPushButton(reference.label)
            learn.setObjectName('MistakeLearnButton')
            learn.setAccessibleName('{} for {}'.format(reference.label, item.prompt))
            learn.setStyleSheet(BUTTON_STYLE)
            learn.clicked.connect(
                lambda _checked=False, target=reference: self.learn_requested.emit(
                    target.level, target.order_token
                )
            )
            actions.addWidget(learn)

        row_request = self._request_for((item,))
        practice = QPushButton('Practice this')
        practice.setObjectName('MistakePracticeButton')
        practice.setAccessibleName('Practice {}'.format(item.prompt))
        if item.suspended:
            practice.setToolTip('Resume this card before practicing it')
        elif row_request is None:
            practice.setToolTip(
                'This card has only part of a Lektion context; suspend or hide it here.'
            )
        else:
            practice.setToolTip('Start a one-off drill with this card')
        practice.setStyleSheet(SYSTEM_BUTTON_STYLE)
        practice.setMinimumWidth(104)
        practice.setEnabled(row_request is not None)
        practice.clicked.connect(lambda _checked=False, target=item: self._study(target))

        tomorrow = QPushButton('Tomorrow')
        tomorrow.setObjectName('MistakeTomorrowButton')
        tomorrow.setAccessibleName('Hide {} until tomorrow'.format(item.prompt))
        tomorrow.setToolTip('Hide this card until the next local day')
        tomorrow.setStyleSheet(BUTTON_STYLE)
        tomorrow.setMinimumWidth(94)
        tomorrow.setEnabled(not item.suspended)
        tomorrow.clicked.connect(lambda _checked=False, target=item: self._bury(target))

        suspend = QPushButton('Resume' if item.suspended else 'Suspend')
        suspend.setObjectName('MistakeSuspendButton')
        suspend.setAccessibleName('{} {}'.format(suspend.text(), item.prompt))
        suspend.setMinimumWidth(86)
        suspend.setStyleSheet(BUTTON_STYLE)
        suspend.clicked.connect(lambda _checked=False, target=item: self._toggle(target))

        actions.addWidget(practice)
        actions.addWidget(tomorrow)
        actions.addWidget(suspend)
        layout.addWidget(actions_host)
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
        if item.suspended:
            self._set_status('Resume this card before practicing it.', error=True)
            return
        request = self._request_for((item,))
        if request is None:
            self._set_status('This card no longer has a valid drill context.', error=True)
            return
        self.drill_requested.emit(request)

        # Compatibility signals are retained for external embedders. Grammar
        # production is a primary review lane, not a Vocabulary Lab mode.
        if item.objective == 'vocab' and item.practice_mode in {'production', 'dictation'}:
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
