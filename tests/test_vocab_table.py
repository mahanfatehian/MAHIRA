"""Vocab Table study grid: repo rows, session resolution, and the page's
column-hide / tap-to-reveal logic."""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "src" / "db" / "schema.sql"


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo
    from db.seed_loader import load_all_seeds

    db_path = tmp_path / "mahira.db"
    init_db(db_path, SCHEMA)
    r = Repo(db_path)
    load_all_seeds(r, REPO_ROOT)
    return r


def _session(repo):
    from core.session import SessionService, AppState

    s = SessionService(repo, AppState())
    s.set_context("A1", "vocab", book_slug="starten_wir", lektion_number=1)
    return s


# --------------------------------------------------------------------- repo
def test_article_from_gender_mapping():
    from db.repo import Repo

    assert Repo._article_from_gender("m") == "der"
    assert Repo._article_from_gender("f") == "die"
    assert Repo._article_from_gender("n") == "das"
    # Already an article -> passthrough; unknown/empty -> "".
    assert Repo._article_from_gender("die") == "die"
    assert Repo._article_from_gender("") == ""
    assert Repo._article_from_gender(None) == ""
    assert Repo._article_from_gender("???") == ""


def test_vocab_table_rows_shape_order_and_articles(repo):
    s = _session(repo)
    rows = s.vocab_table_rows()
    assert rows, "expected vocab rows for A1 / starten_wir / Lektion 1"

    # Every row exposes the four study columns plus the informational POS,
    # with a real headword.
    for r in rows:
        assert {"word", "article", "plural", "meaning", "pos"} <= set(r.keys())
        assert r["word"], "headword must never be blank"

    # The part-of-speech tag is populated for at least some entries.
    assert any(r["pos"] for r in rows)

    # Ordered case-insensitively by the word.
    words = [r["word"].lower() for r in rows]
    assert words == sorted(words)

    # At least one noun surfaces a usable article (stored or gender-derived).
    assert any(r["article"] in ("der", "die", "das") for r in rows)


def test_vocab_table_rows_empty_without_deck(repo):
    from core.session import SessionService, AppState

    s = SessionService(repo, AppState())
    s.state.level = "A1"
    s.state.book_slug = "no_such_book"
    s.state.lektion_number = 99
    assert s.vocab_deck_id() is None
    assert s.vocab_table_rows() == []


# --------------------------------------------------------------------- page
def _qapp():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def vocab_table_rows(self):
        return list(self._rows)

    def context_label(self):
        return "A1 · Test · Lektion 1"


def test_page_hide_reveal_and_empty_cells():
    _qapp()
    from PySide6.QtCore import Qt, QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    from ui.pages.vocab_table import VocabTablePage

    rows = [
        {"word": "Auto", "article": "das", "plural": "Autos", "meaning": "car", "pos": "noun"},
        {"word": "Haus", "article": "das", "plural": "Häuser", "meaning": "house", "pos": "noun"},
        {"word": "laufen", "article": "", "plural": "", "meaning": "to run", "pos": "verb"},
    ]
    page = VocabTablePage(_FakeSession(rows))
    try:
        # Three rows materialized in every quiz column, plus the static POS column.
        for key in ("word", "article", "plural", "meaning"):
            assert len(page._cells[key]) == 3
        assert len(page._pos_cells) == 3
        assert page.count_chip.text() == "3 words"

        # POS is informational only: no hide toggle, no maskable cell list.
        assert "pos" not in page._toggle_btns
        assert "pos" not in page._cells

        # Hide the Meaning column -> every populated cell is blanked, and the
        # top button flips to "Show Meaning".
        page._toggle_column("meaning")
        assert page._masked["meaning"] is True
        assert page._toggle_btns["meaning"].text() == "Show Meaning"
        assert all(c._hidden_now() for c in page._cells["meaning"])

        # An empty article/plural cell ('laufen') must never blank — there is
        # nothing to recall there.
        page._toggle_column("article")
        empty_article = page._cells["article"][2]
        assert empty_article._has is False
        assert empty_article._hidden_now() is False

        # Tapping a single hidden Meaning cell reveals just that one entry.
        cell = page._cells["meaning"][0]
        cell.resize(120, 40)
        ev = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(5, 5), QPointF(5, 5),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        cell.mouseReleaseEvent(ev)
        assert cell._hidden_now() is False
        assert cell._lbl.text() == "car"
        # Siblings stay hidden.
        assert page._cells["meaning"][1]._hidden_now() is True

        # "Show all" clears every mask and restores real text.
        page._show_all()
        assert not any(page._masked.values())
        assert page._cells["meaning"][1]._lbl.text() == "house"
        assert page._toggle_btns["meaning"].text() == "Hide Meaning"
    finally:
        page.deleteLater()


def test_page_empty_state_when_no_rows():
    _qapp()
    from ui.pages.vocab_table import VocabTablePage

    page = VocabTablePage(_FakeSession([]))
    try:
        assert page.count_chip.text() == "0 words"
        # isHidden() reflects the explicit show/hide flag without needing the
        # widget to be on screen: the empty notice is shown, the table hidden.
        assert page.empty_lbl.isHidden() is False
        assert page.scroll.isHidden() is True
    finally:
        page.deleteLater()


def test_page_virtualizes_large_deck_and_skips_same_context_reload():
    app = _qapp()
    from PySide6.QtWidgets import QWidget
    from ui.pages.vocab_table import VocabTablePage

    class CountingSession(_FakeSession):
        def __init__(self, rows):
            super().__init__(rows)
            self.loads = 0

        def vocab_table_rows(self):
            self.loads += 1
            return super().vocab_table_rows()

    rows = [
        {
            "word": f"Wort {i}",
            "article": "das",
            "plural": f"Wörter {i}",
            "meaning": f"word {i}",
            "pos": "noun",
        }
        for i in range(500)
    ]
    session = CountingSession(rows)
    page = VocabTablePage(session)
    try:
        assert session.loads == 1
        assert page._table_model.rowCount() == 500
        # Model/view keeps QWidget count constant instead of creating five
        # frames and labels per row (which would exceed 5,000 here).
        assert len(page.findChildren(QWidget)) < 80

        page.on_show()
        app.processEvents()
        assert session.loads == 1, "returning from conjugation must reuse the unchanged deck"
    finally:
        page.deleteLater()


def test_word_pronunciation_is_keyboard_accessible_and_respects_masking():
    _qapp()
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from ui.pages.vocab_table import VocabTablePage, _COLUMN_INDEX

    word = "frühstücken"
    page = VocabTablePage(
        _FakeSession([
            {"word": word, "article": "", "plural": "", "meaning": "to have breakfast", "pos": "verb"}
        ])
    )
    try:
        spoken = []
        page.table.audio_requested.connect(lambda text, row: spoken.append((text, row)))
        index = page._table_model.index(0, _COLUMN_INDEX["word"])
        page.table.setCurrentIndex(index)
        assert word in str(index.data(Qt.ItemDataRole.AccessibleTextRole))
        assert "Space" in str(index.data(Qt.ItemDataRole.AccessibleTextRole))

        space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        page.table.keyPressEvent(space)
        assert spoken == [(word, 0)]

        # Hiding the headword also hides its listening action.  The first key
        # press reveals the word; only the next press is allowed to speak it.
        page._toggle_column("word")
        assert page._table_model.is_hidden(0, "word")
        page.table.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        )
        assert spoken == [(word, 0)]
        assert not page._table_model.is_hidden(0, "word")
        page.table.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        )
        assert spoken == [(word, 0), (word, 0)]
    finally:
        page.deleteLater()


def test_word_pronunciation_hit_target_emits_exact_visible_word():
    app = _qapp()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from ui.pages.vocab_table import VocabTablePage, _COLUMN_INDEX

    word = "aufstehen"
    page = VocabTablePage(
        _FakeSession([
            {"word": word, "article": "", "plural": "", "meaning": "to get up", "pos": "verb"}
        ])
    )
    try:
        page.resize(760, 520)
        page.show()
        QTest.qWait(25)
        app.processEvents()
        page._play_word = lambda _text, _row: None
        heard = []
        page.table.audio_requested.connect(lambda text, row: heard.append((text, row)))
        index = page._table_model.index(0, _COLUMN_INDEX["word"])
        target = page.table.itemDelegate().audio_rect(page.table.visualRect(index)).center()
        QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=target)
        assert heard == [(word, 0)]

        page._toggle_column("word")
        QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=target)
        assert heard == [(word, 0)], "the listening action must not reveal a masked answer by sound"
    finally:
        page.hide()
        page.deleteLater()
