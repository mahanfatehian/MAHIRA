"""Every real tab may scroll for its own content and for nothing else.

`tests/test_page_scroll_single_scrollbar.py` proves the mechanism on a
two-page fixture. This file proves the property the reader actually sees, on
the real MainWindow with all thirteen pages in it: a tab gets an outer
scrollbar if and only if its own content is taller than the viewport, and the
stack is never stretched to some other page's height. The bug these guard
against was a 910 px phantom scrollbar on Vocab Table - a second bar over the
top of the table's own, which dragged the column headers out of view.
"""

from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

WINDOW_W, WINDOW_H = 1080, 820
# Qt rounds layout heights; anything inside this band is "the same height".
SLACK = 2


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(tmp_path):
    """The real MainWindow, all thirteen pages, on a throwaway library."""
    from core.session import AppState, SessionService
    from core.settings import SettingsService
    from db.init_db import init_db
    from db.repo import Repo
    from ui.main_window import MainWindow

    app = _qapp()
    db_path = tmp_path / "scroll.db"
    init_db(db_path)
    repo = Repo(db_path)
    book_id = repo.ensure_book("scroll_book", "Scroll Book")
    lektion_id = repo.ensure_lektion(book_id, "A1", 1, "Scroll Lesson")
    deck_id, _changed = repo.upsert_deck(
        "A1", "vocab", "scroll.csv", "scroll-sha", lektion_id=lektion_id
    )
    # More rows than the table can show at once, so its own inner scrollbar is
    # live and a second, outer one is unmistakable.
    for i in range(60):
        repo.insert_vocab(deck_id, "noun", f"Wort{i}", "das", "n", f"Plural{i}", f"meaning {i}")

    settings = SettingsService(tmp_path / "settings.json")
    settings.update(
        level="A1",
        book_slug="scroll_book",
        lektion_number=1,
        objective="vocab",
        strict_answers=True,
        audio_autoplay=False,
    )
    session = SessionService(repo, AppState("A1", "vocab", "scroll_book", 1))
    session.settings = settings
    session.enable_ml_ranking = False

    win = MainWindow(session, start_page="today")
    win.resize(WINDOW_W, WINDOW_H)
    win.show()
    for _ in range(4):
        app.processEvents()
    yield win
    win.close()
    win.deleteLater()
    app.processEvents()


def _own_height(page, width: int) -> int:
    """How tall this page's own content is, asked of the page and no one else.

    Several pages have no width-dependent height and answer -1; their size
    hint is the honest number. The minimum hint is folded in because a page
    can be laid out below its size hint but never below its minimum.
    """
    needed = page.heightForWidth(width)
    if needed < 0:
        needed = page.sizeHint().height()
    return max(needed, page.minimumSizeHint().height())


def _show(app, window, key: str):
    """Put a page on screen the way the nav does, and let layout settle."""
    window._show(key)
    for _ in range(4):
        app.processEvents()
    return window.pages[key]


def test_every_page_has_an_outer_scrollbar_only_if_its_own_content_overflows(window):
    from ui.main_window import PAGE_KEYS

    app = _qapp()
    scroll = window.page_scroll
    wrong: list[str] = []
    overflowing: list[str] = []

    for key in PAGE_KEYS:
        page = _show(app, window, key)
        viewport_w = scroll.viewport().width()
        viewport_h = scroll.viewport().height()
        needed = _own_height(page, viewport_w)
        travel = scroll.verticalScrollBar().maximum()

        if needed > viewport_h + SLACK:
            overflowing.append(key)
            if travel == 0:
                wrong.append(
                    f"{key}: needs {needed}px in a {viewport_h}px viewport "
                    f"but has no outer scrollbar, so the tail is unreachable"
                )
        elif needed < viewport_h - SLACK:
            if travel > 0:
                wrong.append(
                    f"{key}: needs only {needed}px of a {viewport_h}px viewport "
                    f"but was given {travel}px of outer scroll it has no content for"
                )

    assert not wrong, "\n".join(wrong)
    # Guard the guard: a run where nothing overflowed would pass vacuously.
    assert overflowing, "no page overflowed the viewport; this test proved nothing"


def test_no_page_is_stretched_to_another_pages_height(window):
    """The stacked widget is sized for the visible page, not the tallest one."""
    from ui.main_window import PAGE_KEYS

    app = _qapp()
    scroll = window.page_scroll
    stretched: list[str] = []

    for key in PAGE_KEYS:
        page = _show(app, window, key)
        viewport_h = scroll.viewport().height()
        needed = _own_height(page, scroll.viewport().width())
        laid_out = window.stack.height()
        # A page is allowed to fill the viewport, and to be as tall as it asks.
        if laid_out > max(needed, viewport_h) + SLACK:
            stretched.append(
                f"{key}: laid out {laid_out}px tall for {needed}px of content "
                f"in a {viewport_h}px viewport"
            )

    assert not stretched, "\n".join(stretched)


def test_the_vocab_table_has_one_scrollbar_and_not_two(window):
    """The reported bug, stated the way the reader met it."""
    app = _qapp()
    page = _show(app, window, "vocab_table")

    inner = page.table.verticalScrollBar()
    outer = window.page_scroll.verticalScrollBar()

    assert inner.maximum() > 0, "fixture needs more rows than the table can show at once"
    assert outer.maximum() == 0, (
        f"the page itself scrolls {outer.maximum()}px as well as the table: "
        "two bars, and the outer one carries the column headers off screen"
    )


def test_leaving_the_tall_page_gives_the_outer_scrollbar_back(window):
    """Settings really is taller than the viewport; the next page is not."""
    app = _qapp()
    scroll = window.page_scroll

    _show(app, window, "settings")
    assert scroll.verticalScrollBar().maximum() > 0, "Settings should overflow at 1080x820"

    _show(app, window, "vocab_table")
    assert scroll.verticalScrollBar().maximum() == 0, (
        "the outer scroll range outlived the page that needed it"
    )


def test_a_page_with_no_height_for_width_still_scrolls_when_it_overflows(window):
    """The other half of the invariant, and the older clipping regression.

    Setup, Conjugation, Grammar Review and Listening Review have no
    width-dependent height and answer -1 when asked for one. The stack must
    not pass that -1 on to the scroll area as "nothing to scroll": the page
    would be cut off at the bottom of the viewport with no bar to reach the
    rest. Listening Review clears a stock Windows viewport by only a handful
    of pixels, so the window is shrunk below the shipped minimum here to put
    each such page over the edge on purpose.
    """
    from ui.main_window import PAGE_KEYS

    app = _qapp()
    scroll = window.page_scroll
    window.setMinimumSize(400, 300)  # test-only: reach the overflow regime

    checked: list[str] = []
    for key in PAGE_KEYS:
        page = _show(app, window, key)
        if page.hasHeightForWidth():
            continue  # the invariant test above already covers these

        needed = _own_height(page, scroll.viewport().width())
        # Shrink until this page genuinely does not fit, then re-measure it.
        window.resize(WINDOW_W, max(300, needed - 120))
        page = _show(app, window, key)
        viewport_h = scroll.viewport().height()
        needed = _own_height(page, scroll.viewport().width())
        if needed <= viewport_h + SLACK:
            continue

        checked.append(key)
        travel = scroll.verticalScrollBar().maximum()
        assert travel > 0, (
            f"{key} has no height-for-width of its own and needs {needed}px in a "
            f"{viewport_h}px viewport, but got no outer scrollbar - the tail is "
            "cut off with no way to reach it"
        )
        assert travel >= needed - viewport_h - SLACK, (
            f"{key} scrolls only {travel}px of a {needed - viewport_h}px overflow"
        )
        window.resize(WINDOW_W, WINDOW_H)

    assert checked, (
        "no page without its own height-for-width could be made to overflow; "
        "the clipping regression this guards is not being exercised"
    )
