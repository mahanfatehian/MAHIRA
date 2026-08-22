"""The vocabulary table must not repaint everything to scroll or hover.

Measured on Windows with 192 rows in a 1090x636 viewport before this work:
scrolling repainted the full 693 kpx viewport on every step (14.4 ms/step) and
moving the pointer on or off a speaker repainted it again (13.6 ms/move).

Qt may blit the part of a scrolled viewport that did not move, but only when
the widget promises to paint every pixel it is handed. That promise is
WA_OpaquePaintEvent, and paintEvent has to keep it: the delegate draws
card-like cells and leaves the gutters between them uncovered.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = "#101010"


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
            for i in range(60)
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


def test_the_viewport_promises_to_paint_every_pixel(view):
    from PySide6.QtCore import Qt

    assert view.viewport().testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)


def test_the_promise_is_kept_so_the_background_is_still_drawn(view):
    """With the flag set and nothing clearing the viewport, gutters go stale."""
    from PySide6.QtGui import QColor

    image = view.viewport().grab().toImage()
    expected = QColor(BASE).rgb()
    # Bottom-right is below the last row and outside every cell card.
    corner = QColor(image.pixel(image.width() - 3, image.height() - 3)).rgb()
    assert corner == expected


def test_the_base_colour_comes_from_the_palette(view):
    from PySide6.QtGui import QColor, QPalette

    assert view.palette().color(QPalette.ColorRole.Base) == QColor(BASE)


def test_the_stylesheet_no_longer_sets_a_background(view):
    """It lives on the palette so paintEvent and the widget cannot drift."""
    assert "background:#101010" not in view.styleSheet()


# --------------------------------------------------------------------------
# Hover repaints
# --------------------------------------------------------------------------

def test_hover_repaints_only_the_cells_that_changed(view, monkeypatch):
    from ui.pages.vocab_table import _COLUMN_INDEX

    rects = []
    monkeypatch.setattr(view.viewport(), "update", lambda *a: rects.append(a))

    first = (0, _COLUMN_INDEX["word"])
    second = (4, _COLUMN_INDEX["word"])
    view._repaint_audio_cells(first, second)

    assert len(rects) == 2, "one targeted repaint per changed cell"
    for args in rects:
        assert args, "update() must be given a rect, not the whole viewport"
        rect = args[0]
        assert rect.height() < view.viewport().height()


def test_repainting_tolerates_a_missing_cell(view, monkeypatch):
    calls = []
    monkeypatch.setattr(view.viewport(), "update", lambda *a: calls.append(a))
    view._repaint_audio_cells(None, None)
    assert calls == []


def test_leaving_the_table_clears_the_hover_without_a_full_repaint(view, monkeypatch):
    from PySide6.QtCore import QEvent

    from ui.pages.vocab_table import _COLUMN_INDEX

    view._audio_hover = (2, _COLUMN_INDEX["word"])
    calls = []
    monkeypatch.setattr(view.viewport(), "update", lambda *a: calls.append(a))
    view.leaveEvent(QEvent(QEvent.Type.Leave))

    assert view._audio_hover is None
    assert calls, "the cell that lost hover must be repainted"
    assert all(args for args in calls), "never a bare full-viewport update"
