"""Setup must rebuild its lists when the context changes, and only then.

on_show guarded the four-way rebuild with

    signature != self._last_structure_signature or not self._skip_unchanged_initial_show

but _post_init_refresh clears that flag immediately after construction, so from
the learner's first visit onward the second term was always true and the guard
never held. Measured on the real library: the rebuild ran on 6 of 6 visits with
a completely unchanged context, at ~90 ms and 28 SQLite connections each.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SCHEMA = Path(__file__).resolve().parents[1] / "src" / "db" / "schema.sql"


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(tmp_path, monkeypatch):
    from core.session import AppState, SessionService
    from db.init_db import init_db
    from db.repo import Repo
    from db.seed_loader import load_all_seeds
    from ui.pages.setup import SetupPage

    app = _qapp()
    db = tmp_path / "setup.db"
    init_db(db, SCHEMA)
    repo = Repo(db)
    load_all_seeds(repo, Path(__file__).resolve().parents[1])
    session = SessionService(
        repo,
        AppState(level="A1", objective="vocab", book_slug="starten_wir", lektion_number=1),
    )
    widget = SetupPage(session)
    app.processEvents()
    yield widget
    widget.deleteLater()


def _counter(page, monkeypatch):
    calls = []
    original = type(page)._refresh_structure
    monkeypatch.setattr(
        type(page),
        "_refresh_structure",
        lambda self: calls.append(1) or original(self),
    )
    return calls


def test_an_unchanged_context_does_not_rebuild(page, monkeypatch):
    calls = _counter(page, monkeypatch)
    for _ in range(5):
        page.on_show()
    assert calls == [], "the rebuild ran despite nothing changing"


def test_a_changed_lektion_rebuilds(page, monkeypatch):
    page.on_show()
    calls = _counter(page, monkeypatch)
    page.session.state.lektion_number = 4
    page.on_show()
    assert len(calls) == 1


def test_a_changed_level_rebuilds(page, monkeypatch):
    page.on_show()
    calls = _counter(page, monkeypatch)
    page.session.state.level = "A2"
    page.on_show()
    assert len(calls) == 1


def test_a_changed_book_rebuilds(page, monkeypatch):
    page.on_show()
    calls = _counter(page, monkeypatch)
    page.session.state.book_slug = "menschen"
    page.on_show()
    assert len(calls) == 1


def test_a_changed_objective_rebuilds(page, monkeypatch):
    page.on_show()
    calls = _counter(page, monkeypatch)
    page.session.state.objective = "grammar"
    page.on_show()
    assert len(calls) == 1


def test_it_rebuilds_once_per_change_not_once_per_visit(page, monkeypatch):
    page.on_show()
    calls = _counter(page, monkeypatch)
    page.session.state.lektion_number = 6
    page.on_show()
    page.on_show()
    page.on_show()
    assert len(calls) == 1


def test_returning_to_a_previous_context_still_rebuilds(page, monkeypatch):
    page.on_show()
    calls = _counter(page, monkeypatch)
    page.session.state.lektion_number = 2
    page.on_show()
    page.session.state.lektion_number = 1
    page.on_show()
    assert len(calls) == 2


def test_new_content_rebuilds_even_with_an_unchanged_context(tmp_path):
    """A page built before any content existed must still pick it up.

    This is what the old unconditional rebuild was really protecting, so the
    guard tracks the deck library as well as the chosen context.
    """
    from types import SimpleNamespace


    from db.init_db import init_db
    from db.repo import Repo
    from ui.pages.setup import SetupPage

    app = _qapp()
    db = tmp_path / "empty-then-filled.db"
    init_db(db, SCHEMA)
    repo = Repo(db)
    session = SimpleNamespace(
        repo=repo,
        state=SimpleNamespace(level="A1", book_slug="", lektion_number=0, objective=""),
    )
    page = SetupPage(session)
    try:
        assert page.level_buttons["A1"].isEnabled() is False
        app.processEvents()

        book_id = repo.ensure_book("fresh-book", "Fresh Book")
        lektion_id = repo.ensure_lektion(book_id, "A1", 1, "Fresh Lektion")
        repo.upsert_deck("A1", "vocab", "fresh.csv", "fresh-sha", lektion_id)

        page.on_show()
        assert page.level_buttons["A1"].isEnabled() is True

        # ...and a second visit with nothing new must not rebuild again.
        calls = []
        original = type(page)._refresh_structure
        type(page)._refresh_structure = lambda self: calls.append(1) or original(self)
        try:
            page.on_show()
            assert calls == []
        finally:
            type(page)._refresh_structure = original
    finally:
        page.close()
        page.deleteLater()
