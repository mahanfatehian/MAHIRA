"""A wheel notch over the vocabulary table must land on whole rows.

Qt derives the wheel step of a pixel-scrolled table from the viewport, not
from the rows, and settled on 47 against a 48 px row. Three of those is
141 px, so every notch stopped one pixel short of a row boundary and the
error accumulated: ten notches down the list the reader is looking at the
bottom half of one word and the top half of the next, with no whole row to
anchor on. Stepping by exactly one row height keeps rows on their own
boundaries however far down the list you go.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROWS = 120
NOTCHES = 15


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def view():
    from ui.pages.vocab_table import _VocabTableModel, _VocabTableView

    app = _qapp()
    model = _VocabTableModel({})
    model.set_rows(
        [
            {
                "word": f"Wort{i}",
                "article": "das",
                "pos": "noun",
                "meaning": f"meaning {i}",
                "plural": f"Pl{i}",
            }
            for i in range(ROWS)
        ]
    )
    widget = _VocabTableView()
    widget.setModel(model)
    widget.resize(900, 400)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()


def _wheel(app, view, notches=1):
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


def test_the_scroll_step_is_exactly_one_row(view):
    row_height = view.verticalHeader().defaultSectionSize()
    assert row_height > 0
    assert view.verticalScrollBar().singleStep() == row_height


def test_the_step_survives_qt_recomputing_the_geometry(view):
    row_height = view.verticalHeader().defaultSectionSize()
    # Qt rewrites the step in updateGeometries, which a resize and a model
    # reset both trigger. Setting it once at construction would not survive.
    view.resize(1100, 520)
    view.updateGeometries()
    assert view.verticalScrollBar().singleStep() == row_height

    view.model().set_rows([{"word": "Haus", "article": "das", "pos": "noun"}])
    view.updateGeometries()
    assert view.verticalScrollBar().singleStep() == row_height


def test_every_wheel_notch_stops_on_a_row_boundary(view):
    app = _qapp()
    row_height = view.verticalHeader().defaultSectionSize()
    bar = view.verticalScrollBar()
    bar.setValue(0)

    offsets = []
    for _ in range(NOTCHES):
        _wheel(app, view)
        offsets.append(bar.value())

    # Stop once the list bottoms out; the tail is clamped, not stepped.
    stepped = [o for o in offsets if o < bar.maximum()]
    assert stepped, "the fixture must be long enough to scroll"
    assert all(o % row_height == 0 for o in stepped), offsets
    # And no drift: the nth notch is exactly n whole rows down.
    assert stepped == [row_height * 3 * (i + 1) for i in range(len(stepped))]
