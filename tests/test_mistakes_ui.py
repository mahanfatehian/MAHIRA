from __future__ import annotations

import os
import time
from dataclasses import replace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _items():
    from core.insights import TroubleItem

    return [
        TroubleItem(
            "vocab",
            1,
            "der Termin",
            "appointment",
            4,
            9,
            False,
            1,
            "a1",
            "starten_wir",
            7,
            practice_mode="recognition",
        ),
        TroubleItem(
            "grammar",
            2,
            "Wann arbeitest du?",
            "Ich arbeite um acht Uhr.",
            3,
            6,
            True,
            2,
            "a1",
            "starten_wir",
            7,
            practice_mode="production",
        ),
    ]


def _recent_items():
    from core.insights import RecentFailure

    return [
        RecentFailure(
            objective='vocab',
            item_id=11,
            prompt='die Zeitung',
            answer='newspaper',
            lapses=4,
            reps=8,
            suspended=False,
            deck_id=31,
            level='A1',
            book_slug='starten_wir',
            lektion_number=2,
            practice_mode='recognition',
            error_tags='meaning,gender',
            failure_count=4,
            last_failed_at=1000,
            is_leech=True,
            leech_window_days=30,
        ),
        RecentFailure(
            objective='vocab',
            item_id=12,
            prompt='das Foto',
            answer='photo',
            lapses=2,
            reps=5,
            suspended=True,
            deck_id=31,
            level='A1',
            book_slug='starten_wir',
            lektion_number=2,
            practice_mode='recognition',
            error_tags='plural',
            failure_count=2,
            last_failed_at=900,
            is_leech=False,
            leech_window_days=30,
        ),
        RecentFailure(
            objective='grammar',
            item_id=21,
            prompt='Ich bin hier.',
            answer='Ich bin hier.',
            lapses=3,
            reps=4,
            suspended=False,
            deck_id=41,
            level='A1',
            book_slug='starten_wir',
            lektion_number=4,
            practice_mode='production',
            error_tags='word_order',
            failure_count=3,
            last_failed_at=800,
            is_leech=True,
            leech_window_days=30,
        ),
    ]


class _InsightsStub:
    def __init__(self) -> None:
        self.items = _items()
        self.suspended_calls: list[tuple[str, int, bool]] = []
        self.bury_calls: list[tuple[str, int]] = []

    def trouble_items(self):
        return list(self.items)

    def set_suspended(self, objective: str, item_id: int, suspended: bool) -> None:
        self.suspended_calls.append((objective, item_id, suspended))
        self.items = [
            replace(item, suspended=suspended)
            if (item.objective, item.item_id) == (objective, item_id)
            else item
            for item in self.items
        ]

    def bury(self, objective: str, item_id: int) -> int:
        self.bury_calls.append((objective, item_id))
        self.items = [
            item
            for item in self.items
            if (item.objective, item.item_id) != (objective, item_id)
        ]
        return int(time.time()) + 3600


class _RecentInsightsStub:
    def __init__(self, items, trouble_items=None) -> None:
        self.items = list(items)
        self.trouble = list(trouble_items or [])
        self.calls: list[dict] = []

    def recent_failures(self, **kwargs):
        self.calls.append(dict(kwargs))
        rows = list(self.items)
        lesson = (
            kwargs.get('level'),
            kwargs.get('book_slug'),
            kwargs.get('lektion_number'),
        )
        if all(value is not None for value in lesson):
            rows = [
                item
                for item in rows
                if (item.level, item.book_slug, item.lektion_number) == lesson
            ]
        if kwargs.get('objective') is not None:
            rows = [
                item
                for item in rows
                if item.objective == kwargs['objective']
                and item.practice_mode == kwargs['practice_mode']
            ]
        if kwargs.get('tag') is not None:
            selected = kwargs['tag']
            rows = [
                item
                for item in rows
                if selected in {tag.strip() for tag in item.error_tags.split(',')}
            ]
        return rows[: int(kwargs.get('limit', 20))]

    def trouble_items(self):
        return list(self.trouble)


class _SessionStub:
    def __init__(self) -> None:
        self.repo = object()
        self.excluded: list[tuple[str, int]] = []

    def exclude_from_queue(self, objective: str, item_id: int) -> bool:
        self.excluded.append((objective, item_id))
        return True


def _page(font_scale: int, width: int = 860):
    from PySide6.QtWidgets import QApplication

    from ui.pages.mistakes import MistakesPage
    from ui.theme import app_stylesheet

    app = _qapp()
    app.setStyleSheet(app_stylesheet(font_scale))
    session = _SessionStub()
    page = MistakesPage(session)
    page.insights = _InsightsStub()
    page.source_filter.setCurrentIndex(page.source_filter.findData('recurring'))
    page.resize(width, 720)
    page.on_show()
    page.show()
    page.ensurePolished()
    page.layout().activate()
    QApplication.processEvents()
    return page, session


def _recent_page(items=None, *, trouble_items=None):
    from PySide6.QtWidgets import QApplication

    from ui.pages.mistakes import MistakesPage

    _qapp()
    session = _SessionStub()
    page = MistakesPage(session)
    page.insights = _RecentInsightsStub(
        items or _recent_items(),
        trouble_items=trouble_items,
    )
    page.resize(860, 720)
    page.on_show()
    page.show()
    page.ensurePolished()
    page.layout().activate()
    QApplication.processEvents()
    return page


@pytest.mark.parametrize("font_scale", [85, 100, 115, 130, 140])
@pytest.mark.parametrize("width", [680, 860, 1024])
def test_mistake_row_actions_are_readable_and_not_clipped(font_scale, width):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics, QPixmap
    from PySide6.QtWidgets import QFrame, QPushButton, QStyle, QStyleOptionButton

    page, _session = _page(font_scale, width)
    try:
        pixmap = QPixmap(page.size())
        page.render(pixmap)

        rows = page.rows_widget.findChildren(
            QFrame,
            "MistakeRow",
            options=Qt.FindChildOption.FindDirectChildrenOnly,
        )
        assert len(rows) == 2
        for row_index, row in enumerate(rows):
            buttons = {
                button.objectName(): button
                for button in row.findChildren(QPushButton)
            }
            assert set(buttons) == {
                "MistakePracticeButton",
                "MistakeTomorrowButton",
                "MistakeSuspendButton",
            }
            assert buttons["MistakeSuspendButton"].text() == (
                "Suspend" if row_index == 0 else "Resume"
            )
            assert buttons["MistakeTomorrowButton"].isEnabled() is (row_index == 0)

            for button in buttons.values():
                assert button.text().strip()
                assert button.width() >= button.minimumWidth()
                assert button.height() >= button.minimumSizeHint().height()
                option = QStyleOptionButton()
                button.initStyleOption(option)
                text_rect = button.style().subElementRect(
                    QStyle.SubElement.SE_PushButtonContents,
                    option,
                    button,
                )
                metrics = QFontMetrics(button.font())
                assert text_rect.width() >= metrics.horizontalAdvance(button.text())
                assert text_rect.height() >= metrics.height()
    finally:
        page.close()
        page.deleteLater()


def test_mistake_actions_update_visible_state_and_session_queue():
    from PySide6.QtWidgets import QApplication, QPushButton

    page, session = _page(100)
    stub = page.insights
    try:
        tomorrow = page.rows_widget.findChild(
            QPushButton,
            "MistakeTomorrowButton",
        )
        tomorrow.click()
        QApplication.processEvents()
        assert stub.bury_calls == [("vocab", 1)]
        assert session.excluded == [("vocab", 1)]
        assert page.status.isVisible()
        assert "Hidden until" in page.status.text()
        assert len(page._items) == 1

        suspend = page.rows_widget.findChild(
            QPushButton,
            "MistakeSuspendButton",
        )
        assert suspend.text() == "Resume"
        suspend.click()
        QApplication.processEvents()
        assert stub.suspended_calls == [("grammar", 2, False)]
    finally:
        page.close()
        page.deleteLater()


def test_practice_action_is_discoverable_and_emits_context():
    from PySide6.QtWidgets import QLabel, QPushButton

    page, _session = _page(100)
    received: list[tuple[str, str, str, int]] = []
    page.practice_requested.connect(lambda *args: received.append(args))
    try:
        labels = [
            label.text()
            for label in page.rows_widget.findChildren(QLabel)
        ]
        assert "Vocab · Recognition" in labels
        assert "Grammar · Production" in labels

        practice = page.rows_widget.findChild(
            QPushButton,
            "MistakePracticeButton",
        )
        practice.click()
        assert received == [("vocab", "a1", "starten_wir", 7)]
    finally:
        page.close()
        page.deleteLater()


def test_lab_mistake_routes_back_to_its_isolated_mode():
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    page, _session = _page(100)
    lab_item = replace(
        _items()[0],
        practice_mode="dictation",
        error_tags="capitalization,article_missing",
    )
    page.insights.items = [lab_item]
    page._reload(clear_status=True)
    QApplication.processEvents()
    received: list[tuple[str, str, int, str]] = []
    page.lab_requested.connect(lambda *args: received.append(args))
    try:
        labels = [label.text() for label in page.rows_widget.findChildren(QLabel)]
        assert "Vocab · Dictation" in labels
        assert any("missing article" in text for text in labels)

        page.rows_widget.findChild(QPushButton, "MistakePracticeButton").click()
        assert received == [("a1", "starten_wir", 7, "dictation")]
    finally:
        page.close()
        page.deleteLater()


def test_tomorrow_button_persists_real_burial_and_removes_row(tmp_path):
    from PySide6.QtWidgets import QApplication, QPushButton

    from db.init_db import init_db
    from db.repo import Repo
    from ui.pages.mistakes import MistakesPage

    _qapp()
    db = tmp_path / "real-mistakes.db"
    init_db(db)
    repo = Repo(db)
    deck_id, _changed = repo.upsert_deck("A1", "vocab", "mistakes.csv", "sha")
    vocab_id = repo.insert_vocab(
        deck_id,
        "noun",
        "Termin",
        "der",
        "m",
        "Termine",
        "appointment",
    )
    repo.ensure_state(vocab_id)
    with repo._conn() as conn:
        conn.execute(
            "UPDATE vocab_states SET lapses=4, reps=7 WHERE vocab_id=?",
            (vocab_id,),
        )

    session = _SessionStub()
    session.repo = repo
    page = MistakesPage(session)
    page.source_filter.setCurrentIndex(page.source_filter.findData('recurring'))
    page.resize(860, 680)
    page.show()
    try:
        page.on_show()
        QApplication.processEvents()
        button = page.rows_widget.findChild(QPushButton, "MistakeTomorrowButton")
        assert button is not None and button.isEnabled()
        button.click()
        QApplication.processEvents()

        with repo._conn() as conn:
            buried_until = conn.execute(
                "SELECT buried_until FROM vocab_states WHERE vocab_id=?",
                (vocab_id,),
            ).fetchone()["buried_until"]
        assert int(buried_until) > int(time.time())
        assert page.rows_widget.findChild(
            QPushButton,
            "MistakeTomorrowButton",
        ) is None
        assert "Hidden until" in page.status.text()
    finally:
        page.close()
        page.deleteLater()


def test_filters_call_recent_failures_with_exact_server_side_context_and_persist():
    page = _recent_page()
    stub = page.insights
    try:
        tag_index = page.error_filter.findData('gender')
        lesson_index = next(
            index
            for index in range(page.lesson_filter.count())
            if 'Lektion 2' in page.lesson_filter.itemText(index)
        )
        lane_index = next(
            index
            for index in range(page.lane_filter.count())
            if 'Vocab' in page.lane_filter.itemText(index)
            and 'Recognition' in page.lane_filter.itemText(index)
        )
        assert min(tag_index, lesson_index, lane_index) >= 0

        page.error_filter.setCurrentIndex(tag_index)
        page.lesson_filter.setCurrentIndex(lesson_index)
        page.lane_filter.setCurrentIndex(lane_index)
        page.last_filter.setCurrentIndex(page.last_filter.findData(50))
        selected_lesson = page.lesson_filter.currentData()
        selected_lane = page.lane_filter.currentData()

        assert stub.calls[-1] == {
            'limit': 50,
            'level': 'A1',
            'book_slug': 'starten_wir',
            'lektion_number': 2,
            'objective': 'vocab',
            'practice_mode': 'recognition',
            'tag': 'gender',
        }
        assert [item.item_id for item in page._items] == [11]

        page._reload(clear_status=False, refresh_facets=True)
        assert page.error_filter.currentData() == 'gender'
        assert page.lesson_filter.currentData() == selected_lesson
        assert page.lane_filter.currentData() == selected_lane
        assert page.last_filter.currentData() == 50
        assert stub.calls[-1] == {
            'limit': 50,
            'level': 'A1',
            'book_slug': 'starten_wir',
            'lektion_number': 2,
            'objective': 'vocab',
            'practice_mode': 'recognition',
            'tag': 'gender',
        }
    finally:
        page.close()
        page.deleteLater()


def test_recent_source_never_mixes_non_failure_trouble_rows_into_show_n():
    page = _recent_page(
        [_recent_items()[0]],
        trouble_items=[_items()[0]],
    )
    stub = page.insights
    try:
        assert page.source_filter.currentData() == 'recent'
        assert [item.item_id for item in page._items] == [11]
        assert stub.calls == [{'limit': 500}]

        page.source_filter.setCurrentIndex(
            page.source_filter.findData('recurring')
        )
        assert [item.item_id for item in page._items] == [1]
        assert stub.calls == [{'limit': 500}]
    finally:
        page.close()
        page.deleteLater()


def test_bulk_drill_requires_one_deck_and_lane_and_ignores_suspended_rows():
    from PySide6.QtWidgets import QPushButton

    from ui.pages.mistakes import MistakeDrillRequest

    page = _recent_page()
    received: list[MistakeDrillRequest] = []
    page.drill_requested.connect(received.append)
    try:
        assert not page.practice_these.isEnabled()

        page.lesson_filter.setCurrentIndex(
            next(
                index
                for index in range(page.lesson_filter.count())
                if 'Lektion 2' in page.lesson_filter.itemText(index)
            )
        )
        page.lane_filter.setCurrentIndex(
            next(
                index
                for index in range(page.lane_filter.count())
                if 'Vocab' in page.lane_filter.itemText(index)
                and 'Recognition' in page.lane_filter.itemText(index)
            )
        )
        assert [item.item_id for item in page._items] == [11, 12]
        assert page.practice_these.isEnabled()
        page.practice_these.click()

        assert received == [
            MistakeDrillRequest(
                objective='vocab',
                practice_mode='recognition',
                deck_id=31,
                level='A1',
                book_slug='starten_wir',
                lektion_number=2,
                item_ids=(11,),
            )
        ]
        rows = page.rows_widget.findChildren(QPushButton, 'MistakePracticeButton')
        assert [button.isEnabled() for button in rows] == [True, False]
    finally:
        page.close()
        page.deleteLater()


def test_row_drill_is_typed_and_grammar_production_stays_primary():
    from PySide6.QtWidgets import QPushButton

    page = _recent_page([_recent_items()[2]])
    typed = []
    primary = []
    lab = []
    page.drill_requested.connect(typed.append)
    page.practice_requested.connect(lambda *args: primary.append(args))
    page.lab_requested.connect(lambda *args: lab.append(args))
    try:
        page.rows_widget.findChild(QPushButton, 'MistakePracticeButton').click()
        assert len(typed) == 1
        assert typed[0].objective == 'grammar'
        assert typed[0].practice_mode == 'production'
        assert typed[0].item_ids == (21,)
        assert primary == [('grammar', 'A1', 'starten_wir', 4)]
        assert lab == []
    finally:
        page.close()
        page.deleteLater()


def test_leech_guidance_is_suggestion_only_and_learn_links_are_strict():
    from PySide6.QtWidgets import QFrame, QLabel, QPushButton

    page = _recent_page([_recent_items()[0]])
    links = []
    page.learn_requested.connect(lambda *args: links.append(args))
    try:
        guidance = page.rows_widget.findChild(QFrame, 'MistakeLeechGuidance')
        assert guidance is not None
        guidance_text = ' '.join(
            label.text() for label in guidance.findChildren(QLabel)
        )
        assert '4 misses in 30 days' in guidance_text
        assert 'nothing is changed automatically' in guidance_text
        labels = [label.text() for label in page.rows_widget.findChildren(QLabel)]
        assert any('meaning' in text and 'noun gender' in text for text in labels)
        assert not any('gender_' in text for text in labels)

        learn = page.rows_widget.findChild(QPushButton, 'MistakeLearnButton')
        assert learn is not None
        learn.click()
        assert links == [('A1', '1.4')]
    finally:
        page.close()
        page.deleteLater()

    ambiguous = replace(_recent_items()[0], error_tags='article', is_leech=True)
    page = _recent_page([ambiguous])
    try:
        assert page.rows_widget.findChild(QFrame, 'MistakeLeechGuidance') is not None
        assert page.rows_widget.findChild(QPushButton, 'MistakeLearnButton') is None
    finally:
        page.close()
        page.deleteLater()
