"""Text that will not fit must stay reachable, never be quietly cut.

The window can be resized down to 860x680, and below roughly 1090 px the
widest tabs genuinely need more width than they are given. The outer page
area used to answer that by forcing its horizontal scrollbar off and telling
the stack it could be any width at all, so pages squeezed their children
below the width of their own text. A QLabel resolves that by drawing part of
a word and abandoning the rest - no ellipsis, no bar, nothing to say the
sentence continued.
"""

from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DEFAULT_W, DEFAULT_H = 1080, 820
MIN_W, MIN_H = 860, 680


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(tmp_path):
    from core.session import AppState, SessionService
    from core.settings import SettingsService
    from db.init_db import init_db
    from db.repo import Repo
    from ui.main_window import MainWindow
    from ui.theme import apply_application_theme

    app = _qapp()
    # Pin the type scale these assertions are measured against. The theme is
    # applied to the whole QApplication and outlives the test that set it, and
    # one suite deliberately applies 140% - past the 90-130 the settings screen
    # allows - which leaves every later layout measurement reading a size no
    # reader can actually select.
    apply_application_theme(app, 100, "graphite")
    db_path = tmp_path / "reach.db"
    init_db(db_path)
    repo = Repo(db_path)
    book_id = repo.ensure_book("reach_book", "Reach Book")
    lektion_id = repo.ensure_lektion(book_id, "A1", 1, "Reach Lesson")
    deck_id, _changed = repo.upsert_deck(
        "A1", "vocab", "reach.csv", "reach-sha", lektion_id=lektion_id
    )
    for i in range(40):
        repo.insert_vocab(deck_id, "noun", f"Wort{i}", "das", "n", f"Plural{i}", f"meaning {i}")

    settings = SettingsService(tmp_path / "settings.json")
    settings.update(
        level="A1",
        book_slug="reach_book",
        lektion_number=1,
        objective="vocab",
        strict_answers=True,
        audio_autoplay=False,
    )
    session = SessionService(repo, AppState("A1", "vocab", "reach_book", 1))
    session.settings = settings
    session.enable_ml_ranking = False

    win = MainWindow(session, start_page="today")
    win.resize(DEFAULT_W, DEFAULT_H)
    win.show()
    for _ in range(4):
        app.processEvents()
    yield win
    win.close()
    win.deleteLater()
    app.processEvents()


def _show(app, window, key):
    window._show(key)
    for _ in range(4):
        app.processEvents()
    return window.pages[key]


def test_the_default_window_needs_no_sideways_scrolling_anywhere(window):
    """Offering a bar must not mean showing one at the size people run."""
    from ui.main_window import PAGE_KEYS

    app = _qapp()
    bar = window.page_scroll.horizontalScrollBar()
    sideways = []
    for key in PAGE_KEYS:
        _show(app, window, key)
        if bar.maximum() > 0:
            sideways.append(f"{key} ({bar.maximum()} px)")
    assert not sideways, (
        f"these tabs ask to be scrolled sideways at the default "
        f"{DEFAULT_W}x{DEFAULT_H} window: {', '.join(sideways)}"
    )


def test_a_page_too_wide_for_the_window_can_be_scrolled_to(window):
    """At the smallest window the widest tabs overflow - reachably."""
    from ui.main_window import PAGE_KEYS

    app = _qapp()
    window.resize(MIN_W, MIN_H)
    for _ in range(4):
        app.processEvents()

    scroll = window.page_scroll
    overflowed = []
    unreachable = []
    for key in PAGE_KEYS:
        page = _show(app, window, key)
        viewport_w = scroll.viewport().width()
        needed = page.minimumSizeHint().width()
        travel = scroll.horizontalScrollBar().maximum()
        if needed <= viewport_w:
            continue
        overflowed.append(key)
        if travel <= 0:
            unreachable.append(
                f"{key}: needs {needed}px in a {viewport_w}px viewport with no bar"
            )
        elif travel < needed - viewport_w - 2:
            unreachable.append(
                f"{key}: scrolls {travel}px of a {needed - viewport_w}px overflow"
            )

    assert not unreachable, "\n".join(unreachable)
    assert overflowed, (
        f"nothing overflowed at {MIN_W}x{MIN_H}; this test proved nothing"
    )


def test_the_stack_reports_the_width_its_page_needs(window):
    """Answering zero is what let a page be squeezed under its own text."""
    app = _qapp()
    for key in ("progress", "vocab_table", "settings"):
        page = _show(app, window, key)
        assert window.stack.minimumSizeHint().width() == page.minimumSizeHint().width()
        assert window.stack.minimumSizeHint().width() > 0


def test_no_label_anywhere_is_narrower_than_its_own_text(window):
    """The property all of this exists to produce, swept over every tab.

    An explicit minimum width replaces the one Qt works out from a widget's
    own contents rather than raising it, so a floor set below what the text
    needs does not protect the widget - it licenses the layout to cut it. The
    review pages each carried a 78 px floor under a 102 px "New set", and the
    Vocab Review counter a 60 px floor under a chip that never needs less
    than 82. Those are the last labels that were still being cut at the
    smallest window once the page could scroll sideways to reach them.
    """
    from PySide6.QtWidgets import QLabel, QPushButton

    from ui.main_window import PAGE_KEYS

    app = _qapp()
    cut = []
    checked = 0
    for width, height in ((MIN_W, MIN_H), (DEFAULT_W, DEFAULT_H), (1280, 900)):
        window.resize(width, height)
        for _ in range(4):
            app.processEvents()
        for key in PAGE_KEYS:
            page = _show(app, window, key)
            widgets = list(page.findChildren(QLabel)) + list(page.findChildren(QPushButton))
            for widget in widgets:
                text = widget.text()
                if not widget.isVisible() or not text:
                    continue
                if isinstance(widget, QLabel) and widget.wordWrap():
                    continue
                checked += 1
                over = (widget.fontMetrics().horizontalAdvance(text)
                        - widget.contentsRect().width())
                if over > 1:
                    cut.append(f"{width}x{height} {key}: {text!r} cut by {over} px")

    assert not cut, chr(10).join(cut)
    assert checked > 200, f"only {checked} labels examined; the sweep is not reaching them"
