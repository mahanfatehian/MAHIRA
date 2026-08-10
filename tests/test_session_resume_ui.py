from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _prepared_restart(tmp_path):
    from core.session import AppState, SessionService
    from core.settings import SettingsService
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / ".mahira" / "mahira.db"
    init_db(db_path)
    repo = Repo(db_path)
    book_id = repo.ensure_book("resume_book", "Resume Book")
    lesson_id = repo.ensure_lektion(book_id, "A1", 1, "Resume Lesson")
    deck_id, _changed = repo.upsert_deck(
        "A1",
        "vocab",
        "resume.csv",
        "resume-sha",
        lektion_id=lesson_id,
    )
    for word, meaning in (("lernen", "learn"), ("arbeiten", "work")):
        repo.insert_vocab(deck_id, "verb", word, "", "", "", meaning)

    settings = SettingsService(tmp_path / ".mahira" / "settings.json")
    settings.update(
        level="A1",
        objective="vocab",
        book_slug="resume_book",
        lektion_number=1,
        last_page="vocab_review",
        audio_autoplay=False,
    )

    original = SessionService(
        repo,
        AppState("A1", "vocab", "resume_book", 1),
    )
    original.settings = settings
    original.set_context("A1", "vocab", "resume_book", 1)
    original.enable_ml_ranking = False
    original.plan.limit = 2
    original.plan.new_limit = 2
    assert original.start_new_session() is True
    current = original.next_item()
    assert current is not None

    restarted = SessionService(
        repo,
        AppState("A1", "vocab", "resume_book", 1),
    )
    restarted.settings = settings
    restarted.enable_ml_ranking = False
    restarted.plan.limit = 2
    restarted.plan.new_limit = 2
    return restarted, current.id, db_path.parent / "active_session.json"


def test_resume_banner_guards_startup_and_continues_exact_card(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    session, current_id, checkpoint = _prepared_restart(tmp_path)
    window = MainWindow(session, start_page="vocab_review")
    window.show()
    try:
        app.processEvents()
        assert window._current_page_key() == "today"
        assert window.resume_banner.isVisible()
        assert "Unfinished Vocabulary session" in window.resume_label.text()
        assert window.pages["vocab_review"].current_item is None
        assert checkpoint.exists()

        window.resume_continue_btn.click()
        app.processEvents()

        assert window._current_page_key() == "vocab_review"
        assert not window.resume_banner.isVisible()
        assert window.pages["vocab_review"].current_item.id == current_id
    finally:
        session.discard_pending_resume()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_resume_banner_discard_removes_only_open_queue(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    session, _current_id, checkpoint = _prepared_restart(tmp_path)
    window = MainWindow(session, start_page="vocab_review")
    window.show()
    try:
        app.processEvents()
        assert checkpoint.exists()

        window.resume_discard_btn.click()
        app.processEvents()

        assert window._current_page_key() == "today"
        assert not window.resume_banner.isVisible()
        assert not checkpoint.exists()
        assert session.remaining() == 0
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


@pytest.mark.parametrize(
    ("objective", "page_key"),
    (
        ("vocab", "vocab_review"),
        ("grammar", "grammar_review"),
        ("sentences", "sentence_review"),
        ("listening", "listening_review"),
    ),
)
def test_continue_routes_to_the_saved_objective(objective, page_key):
    from ui.main_window import MainWindow

    shown: list[str] = []
    state = SimpleNamespace(objective=objective)
    window = SimpleNamespace(
        session=SimpleNamespace(
            state=state,
            resume_pending=lambda: True,
        ),
        pages={},
        resume_banner=SimpleNamespace(hide=lambda: None),
        _last_nav_context="cached",
        _invalidate_review_pages=lambda: None,
        _show=lambda key: shown.append(key),
    )
    window._practice_page_key = lambda: MainWindow._practice_page_key(window)

    MainWindow._continue_resume(window)

    assert shown == [page_key]
    assert window._last_nav_context is None


def test_profile_switch_discards_current_profile_checkpoint(tmp_path):
    from core.settings import SettingsService
    from ui.pages.settings import SettingsPage

    settings = SettingsService(tmp_path / "settings.json")
    discarded: list[bool] = []
    notes: list[str] = []
    page = SimpleNamespace(
        settings=settings,
        session=SimpleNamespace(
            discard_pending_resume=lambda: discarded.append(True)
        ),
        profile_combo=SimpleNamespace(currentData=lambda: "second"),
        profile_note=SimpleNamespace(setText=lambda text: notes.append(text)),
    )

    SettingsPage._activate_profile(page)

    assert discarded == [True]
    assert settings.value.active_profile == "second"
    assert notes and "Restart MAHIRA" in notes[-1]


@pytest.mark.parametrize(
    ("objective", "page_class_name"),
    (
        ("vocab", "VocabReviewPage"),
        ("grammar", "GrammarReviewPage"),
        ("sentences", "SentenceReviewPage"),
    ),
)
def test_review_reentry_does_not_resurrect_a_card_the_session_no_longer_owns(
    objective,
    page_class_name,
):
    from ui.pages.grammar_review import GrammarReviewPage
    from ui.pages.sentence_review import SentenceReviewPage
    from ui.pages.vocab_review import VocabReviewPage

    calls: list[str] = []
    session = SimpleNamespace(
        state=SimpleNamespace(objective=objective),
        active_deck_id=lambda: 7,
        context_label=lambda: "A1 lesson",
        is_current_item=lambda _objective, _item_id: False,
        remaining=lambda: calls.append("remaining") or 2,
        start_new_session=lambda: calls.append("start"),
    )
    page = SimpleNamespace(
        session=session,
        current_item=SimpleNamespace(id=4, deck_id=7),
        special_kbd=SimpleNamespace(set_language=lambda _language: None),
        page_subtitle=SimpleNamespace(setText=lambda _text: None),
        main_shell=SimpleNamespace(show=lambda: calls.append("show")),
        empty_card=SimpleNamespace(hide=lambda: calls.append("hide")),
        _active_deck_id=lambda: 7,
        _show_main=lambda: calls.append("show"),
        _update_counter=lambda: calls.append("counter"),
        _load_next=lambda: calls.append("load"),
    )
    page_class = {
        "VocabReviewPage": VocabReviewPage,
        "GrammarReviewPage": GrammarReviewPage,
        "SentenceReviewPage": SentenceReviewPage,
    }[page_class_name]

    page_class.on_show(page)

    assert "remaining" in calls
    assert "load" in calls
