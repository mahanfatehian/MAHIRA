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
    page.resize(width, 720)
    page.on_show()
    page.show()
    page.ensurePolished()
    page.layout().activate()
    QApplication.processEvents()
    return page, session


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
