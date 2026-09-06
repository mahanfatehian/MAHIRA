"""The outer page scroll must not inherit the tallest hidden page's height.

MAHIRA stacks all thirteen pages in one QStackedWidget inside a single outer
QScrollArea. QStackedLayout answers every geometry question with the largest
page rather than the visible one, and QScrollArea sizes a resizable widget
from heightForWidth() in preference to either size hint. Together that gave
short pages a second, content-free scrollbar the height of the Settings page
- the reader scrolled the table with one bar and the whole page, header and
all, with the other. These tests fail on a stock QStackedWidget.
"""

from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SHORT_H = 120
TALL_H = 2000
VIEWPORT_H = 700


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _page(height: int):
    """A page whose layout advertises heightForWidth, as the real pages do."""
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    # A word-wrapped label is what makes a layout height-for-width, which is
    # the property QStackedLayout aggregates across every page.
    wrapped = QLabel("wrapped " * 12)
    wrapped.setWordWrap(True)
    wrapped.setFixedHeight(0)
    layout.addWidget(wrapped)
    body = QWidget()
    body.setFixedHeight(height)
    layout.addWidget(body)
    return page


def test_stack_reports_the_visible_page_height_not_the_tallest():
    from ui.main_window import CurrentPageStack

    _qapp()
    stack = CurrentPageStack()
    short = _page(SHORT_H)
    tall = _page(TALL_H)
    stack.addWidget(short)
    stack.addWidget(tall)
    try:
        stack.setCurrentWidget(short)
        assert stack.hasHeightForWidth()
        # A stock QStackedWidget answers TALL_H here for both pages.
        assert stack.heightForWidth(800) == pytest.approx(SHORT_H, abs=2)

        stack.setCurrentWidget(tall)
        assert stack.heightForWidth(800) == pytest.approx(TALL_H, abs=2)
    finally:
        stack.deleteLater()


def test_short_page_gets_no_outer_scrollbar_while_a_tall_page_exists():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea

    from ui.main_window import CurrentPageStack

    app = _qapp()
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    stack = CurrentPageStack()
    short = _page(SHORT_H)
    tall = _page(TALL_H)
    stack.addWidget(short)
    stack.addWidget(tall)
    area.setWidget(stack)
    area.resize(800, VIEWPORT_H)
    area.show()
    try:
        for _ in range(4):
            app.processEvents()

        stack.setCurrentWidget(short)
        for _ in range(4):
            app.processEvents()
        # The whole point: a page shorter than the viewport scrolls nowhere.
        assert area.verticalScrollBar().maximum() == 0
        assert stack.height() <= VIEWPORT_H

        stack.setCurrentWidget(tall)
        for _ in range(4):
            app.processEvents()
        # ...and a page that genuinely overflows still scrolls.
        assert area.verticalScrollBar().maximum() > 0
    finally:
        area.close()
        area.deleteLater()
