from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_today_review_progress_smoke_path(tmp_path):
    """Keep the learner's shortest useful journey wired end to end."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from core.session import AppState, SessionService
    from core.settings import SettingsService
    from db.init_db import init_db
    from db.repo import Repo
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    db_path = tmp_path / "smoke.db"
    init_db(db_path)
    repo = Repo(db_path)

    book_id = repo.ensure_book("smoke_book", "Smoke Book")
    lesson_id = repo.ensure_lektion(book_id, "A1", 1, "Smoke Lesson")
    deck_id, _changed = repo.upsert_deck(
        "A1",
        "vocab",
        "smoke.csv",
        "smoke-sha",
        lektion_id=lesson_id,
    )
    repo.insert_vocab(deck_id, "verb", "lernen", "", "", "", "learn")

    settings = SettingsService(tmp_path / "settings.json")
    settings.update(
        level="A1",
        book_slug="smoke_book",
        lektion_number=1,
        objective="vocab",
        strict_answers=True,
        audio_autoplay=False,
    )
    session = SessionService(
        repo,
        AppState("A1", "vocab", "smoke_book", 1),
    )
    session.settings = settings
    session.plan.limit = 1
    session.plan.new_limit = 1
    session.enable_ml_ranking = False

    window = MainWindow(session, start_page="today")
    window.show()
    try:
        app.processEvents()
        assert window._current_page_key() == "today"

        today = window.pages["today"]
        initial_snapshot = today._snapshot
        assert initial_snapshot.planned_total == 1
        assert initial_snapshot.segments[0].objective == "vocab"
        today._lane_widgets["vocab"][1].click()
        app.processEvents()

        assert window._current_page_key() == "vocab_review"
        review = window.pages["vocab_review"]
        assert review.current_item is not None
        review.card.in_meaning.setText("learn")
        review.card.check_btn.click()
        app.processEvents()
        review.card.btn_good.click()
        app.processEvents()

        assert repo.reviewed_last_24h(deck_id) == 1
        usage = repo.daily_plan_usage(
            initial_snapshot.day_start,
            initial_snapshot.day_end,
        )
        assert [(row.objective, row.completed, row.new) for row in usage] == [
            ("vocab", 1, 1)
        ]

        assert review.today_btn.isVisible()
        review.today_btn.click()
        app.processEvents()
        assert window._current_page_key() == "today"
        assert window.pages["today"]._snapshot.completed_total == 1
        assert window.pages["today"]._snapshot.planned_total == 0

        window.nav.btn_progress.click()
        app.processEvents()
        assert window._current_page_key() == "progress"
        assert window.pages["progress"].plan_completed_label.text() == "1 completed"
        assert window.pages["progress"].reviewed_today_card.value_label.text() == "1"
    finally:
        window.close()
        app.processEvents()
