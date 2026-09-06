"""No tab may hand a label less room than the words it is holding.

A QLabel given too little width does not shrink its text or mark the loss -
it simply stops drawing part-way through, mid-glyph. The longest strings in
the app are whole sentences, and on a single line they ran 138 px past the
card on Progress and 90 px past it on Learn at the shipped default window
size, so the reader lost the end of both.
"""

from __future__ import annotations

import os
import pathlib

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DEFAULT_W, DEFAULT_H = 1080, 820


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
    db_path = tmp_path / "fit.db"
    init_db(db_path)
    repo = Repo(db_path)
    book_id = repo.ensure_book("fit_book", "Fit Book")
    lektion_id = repo.ensure_lektion(book_id, "A1", 1, "Fit Lesson")
    deck_id, _changed = repo.upsert_deck(
        "A1", "vocab", "fit.csv", "fit-sha", lektion_id=lektion_id
    )
    for i in range(40):
        repo.insert_vocab(deck_id, "noun", f"Wort{i}", "das", "n", f"Plural{i}", f"meaning {i}")

    settings = SettingsService(tmp_path / "settings.json")
    settings.update(
        level="A1",
        book_slug="fit_book",
        lektion_number=1,
        objective="vocab",
        strict_answers=True,
        audio_autoplay=False,
    )
    session = SessionService(repo, AppState("A1", "vocab", "fit_book", 1))
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


LONGEST_TIP = "Tip: open a level, then pick a lesson to read the concept before you practice."


def _fully_visible(label) -> tuple[bool, str]:
    """Is every word of this label's text actually on screen?

    Unwrapped, a QLabel draws what fits and abandons the rest mid-glyph, so
    the question is whether the text is narrower than the box. Wrapped, it is
    allowed a second line, and the question becomes whether the layout gave
    the label the extra height that costs.
    """
    metrics = label.fontMetrics()
    if not label.wordWrap():
        over = metrics.horizontalAdvance(label.text()) - label.contentsRect().width()
        return over <= 0, f"{over} px of text past the right edge"
    needed = label.heightForWidth(label.width())
    return needed <= label.height(), (
        f"wraps to {needed} px tall but was given only {label.height()} px"
    )


def _worst_case_activity_caption(page) -> str:
    """The longest line this caption can hold, over every branch it has."""
    return max(
        (
            page._motivation_text(year, active, today, streak)
            for year, active, today, streak in (
                (1_234, 300, 12, 45),
                (1_234, 300, 12, 1),
                (1_234, 300, 0, 45),
                (1_234, 300, 0, 0),
                (0, 0, 0, 0),
            )
        ),
        key=len,
    )


def test_the_activity_caption_shows_all_of_itself(window):
    app = _qapp()
    page = _show(app, window, "progress")
    caption = page.activity_caption
    caption.setText(_worst_case_activity_caption(page))
    for _ in range(4):
        app.processEvents()
    assert len(caption.text()) > 60, "the worst case should be a whole sentence"
    ok, why = _fully_visible(caption)
    assert ok, f"activity caption: {why} - {caption.text()!r}"


def test_the_level_hint_shows_all_of_itself(window):
    app = _qapp()
    page = _show(app, window, "learn")
    hint = page.level_hint
    hint.setText(LONGEST_TIP)
    for _ in range(4):
        app.processEvents()
    ok, why = _fully_visible(hint)
    assert ok, f"level hint: {why} - {hint.text()!r}"


def test_the_shipped_tip_is_still_the_one_measured():
    """If the wording grows, the width above has to be re-measured."""
    source = (pathlib.Path("src") / "ui" / "pages" / "learn.py").read_text(encoding="utf-8")
    assert LONGEST_TIP in source
