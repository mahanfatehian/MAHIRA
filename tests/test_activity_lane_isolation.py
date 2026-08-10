from __future__ import annotations

from types import SimpleNamespace


def _session(repo):
    from core.session import AppState, SessionService

    session = object.__new__(SessionService)
    session.repo = repo
    session.state = AppState(level="A1", objective="vocab")
    session.settings = SimpleNamespace(
        value=SimpleNamespace(strict_answers=True)
    )
    session.ml = None
    session._undo = None
    session.study_answered = 0
    session.study_next_milestone = 30
    return session


def test_lab_session_leaves_recognition_dashboard_unchanged(tmp_path):
    from core.insights import InsightsService
    from db.init_db import init_db
    from db.repo import Repo
    from ui.pages.progress import ProgressPage

    db_path = tmp_path / "activity-lanes.db"
    init_db(db_path)
    repo = Repo(db_path)
    deck_id, _changed = repo.upsert_deck(
        "A1", "vocab", "activity.csv", "activity-sha"
    )
    item_id = repo.insert_vocab(
        deck_id, "noun", "Haus", "das", "n", "Häuser", "house"
    )
    item = repo.get_vocab_by_id(item_id)
    assert item is not None
    recognition_before = repo.ensure_state(item_id)
    progress = SimpleNamespace(_conn=repo._conn)

    before = {
        "due": repo.due_count(deck_id, cooldown_hours=12),
        "mastery": ProgressPage._calculate_mastery(progress, deck_id, 1),
        "reviews_24h": repo.reviewed_last_24h(deck_id),
        "activity": sum(repo.daily_review_counts(0).values()),
        "today": InsightsService(repo).reviewed_today(),
    }

    session = _session(repo)
    session.submit_vocab_production(
        item,
        "das Haus",
        practice_mode="production",
        response_ms=500,
    )
    session.submit_vocab_production(
        item,
        "falsch",
        practice_mode="dictation",
        response_ms=700,
    )

    assert repo.ensure_state(item_id) == recognition_before
    assert repo.due_count(deck_id, cooldown_hours=12) == before["due"]
    assert ProgressPage._calculate_mastery(progress, deck_id, 1) == before["mastery"]
    assert repo.reviewed_last_24h(deck_id) == before["reviews_24h"]
    assert sum(repo.daily_review_counts(0).values()) == before["activity"]
    assert InsightsService(repo).reviewed_today() == before["today"]

    session.submit_vocab(
        item,
        typed_meaning="house",
        typed_gender="n",
        typed_plural="Häuser",
        rating=2,
        tip_used=False,
        gender_tip_used=False,
        was_checked=True,
        was_skipped=False,
        response_ms=900,
    )

    assert repo.reviewed_last_24h(deck_id) == before["reviews_24h"] + 1
    assert sum(repo.daily_review_counts(0).values()) == before["activity"] + 1
    assert InsightsService(repo).reviewed_today() == before["today"] + 1
