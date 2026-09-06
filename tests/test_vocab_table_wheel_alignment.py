"""A wheel notch over the shipped vocabulary page lands on whole rows.

`tests/test_vocab_table_row_alignment.py` covers the view in isolation and
calls updateGeometries() by hand. These cover the two things that leaves
open: the page the reader actually opens (VocabTablePage owns the view and
reloads its model on show), and the reader's own wheel setting - Qt scrolls
QApplication.wheelScrollLines() steps per notch, which is 3 by default but is
a Windows mouse setting and is commonly 1 or 5. The fix has to keep rows on
their boundaries at whatever that number is.
"""

from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROWS = 90
NOTCHES = 12


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def vocab_table_rows(self):
        return list(self._rows)

    def context_label(self):
        return "A1 · Test · Lektion 1"


@pytest.fixture()
def page():
    from ui.pages.vocab_table import VocabTablePage

    app = _qapp()
    rows = [
        {
            "word": f"Wort{i}",
            "article": "das",
            "pos": "noun",
            "meaning": f"meaning {i}",
            "plural": f"Plural{i}",
        }
        for i in range(ROWS)
    ]
    widget = VocabTablePage(_FakeSession(rows))
    widget.resize(940, 520)
    widget.show()
    for _ in range(3):
        app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def _wheel(app, view, notches: int = 1) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    event = QWheelEvent(
        QPointF(200, 200),
        QPointF(200, 200),
        QPoint(0, 0),
        QPoint(0, -120 * notches),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    app.sendEvent(view.viewport(), event)
    app.processEvents()


def test_the_shipped_page_steps_by_exactly_one_row(page):
    row_height = page.table.verticalHeader().defaultSectionSize()
    assert row_height > 0
    assert page.table.verticalScrollBar().singleStep() == row_height, (
        "Qt sizes the step from the viewport, not the rows; the page has to "
        "put it back or every notch stops part-way through a word"
    )


def test_a_notch_moves_whole_rows_at_the_readers_own_wheel_setting(page):
    from PySide6.QtWidgets import QApplication

    app = _qapp()
    view = page.table
    row_height = view.verticalHeader().defaultSectionSize()
    bar = view.verticalScrollBar()
    assert bar.maximum() > row_height * 4, "fixture must be long enough to scroll"

    per_notch = row_height * QApplication.wheelScrollLines()
    bar.setValue(0)
    stops = []
    for _ in range(NOTCHES):
        _wheel(app, view)
        stops.append(bar.value())

    # The tail is clamped rather than stepped, so only judge the free stops.
    stepped = [v for v in stops if v < bar.maximum()]
    assert stepped, "the fixture must be long enough to scroll"
    misaligned = [v for v in stepped if v % row_height]
    assert not misaligned, (
        f"row height {row_height}, step {bar.singleStep()}, stops {stops}"
    )
    # No accumulating drift either: the nth notch is n whole notches down.
    assert stepped == [per_notch * (i + 1) for i in range(len(stepped))]


def test_alignment_survives_the_page_reloading_its_rows(page):
    """on_show() resets the model, and a model reset makes Qt recompute the
    step. The fix has to be re-applied there, not only at construction."""
    app = _qapp()
    row_height = page.table.verticalHeader().defaultSectionSize()

    page.session._rows = [
        {"word": f"Neu{i}", "article": "die", "pos": "noun", "meaning": f"new {i}", "plural": ""}
        for i in range(ROWS)
    ]
    page._loaded_context = None  # force the reload rather than the cached path
    page.on_show()
    for _ in range(3):
        app.processEvents()

    assert page.table.verticalScrollBar().singleStep() == row_height


def test_alignment_survives_a_window_resize(page):
    app = _qapp()
    row_height = page.table.verticalHeader().defaultSectionSize()

    for size in ((1200, 700), (880, 460), (1024, 900)):
        page.resize(*size)
        for _ in range(3):
            app.processEvents()
        assert page.table.verticalScrollBar().singleStep() == row_height, (
            f"the step drifted back to Qt's viewport-derived value at {size}"
        )
