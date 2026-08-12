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


def test_daily_activity_excludes_unchecked_vocab_review(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "unchecked-activity.db"
    init_db(db_path)
    repo = Repo(db_path)
    deck_id, _changed = repo.upsert_deck("A1", "vocab", "activity.csv", "sha")
    item_id = repo.insert_vocab(
        deck_id, "noun", "Haus", "das", "n", "Häuser", "house"
    )
    item = repo.get_vocab_by_id(item_id)
    assert item is not None

    _session(repo).submit_vocab(
        item,
        typed_meaning="house",
        typed_gender="n",
        typed_plural="Häuser",
        rating=2,
        tip_used=False,
        gender_tip_used=False,
        was_checked=False,
        was_skipped=False,
        response_ms=900,
    )

    assert sum(repo.daily_review_counts(0).values()) == 0


def test_daily_activity_filters_all_lanes_and_honors_until(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "primary-activity.db"
    init_db(db_path)
    repo = Repo(db_path)

    vocab_deck, _ = repo.upsert_deck("A1", "vocab", "v.csv", "v")
    grammar_deck, _ = repo.upsert_deck("A1", "grammar", "g.csv", "g")
    sentence_deck, _ = repo.upsert_deck("A1", "sentences", "s.csv", "s")
    listening_deck, _ = repo.upsert_deck("A1", "listening", "l.csv", "l")
    vocab_id = repo.insert_vocab(
        vocab_deck, "noun", "Haus", "das", "n", "Haeuser", "house"
    )
    grammar_id = repo.insert_grammar(
        grammar_deck, "Ich ___ Deutsch.", "lerne", None, None, None, None
    )
    sentence_id = repo.insert_sentence(
        sentence_deck, "Ich lerne Deutsch.", None, None, None
    )
    listening_id = repo.insert_listening(
        listening_deck, "Ich lerne.", "Was?", "Deutsch", None, None, None
    )

    specs = (
        ("reviews", "vocab_id", vocab_id, "recognition", "production"),
        ("grammar_reviews", "grammar_id", grammar_id, "production", "future"),
        ("sentence_reviews", "sentence_id", sentence_id, "builder", "future"),
        (
            "listening_reviews",
            "listening_id",
            listening_id,
            "comprehension",
            "future",
        ),
    )
    with repo._conn() as conn:
        for table, foreign_key, item_id, primary_mode, other_mode in specs:
            conn.executemany(
                f"""
                INSERT INTO {table}(
                    {foreign_key}, created_at, was_checked, was_skipped,
                    rating, practice_mode
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    (item_id, 120, 1, 0, 2, primary_mode),
                    (item_id, 130, 1, 0, 2, other_mode),
                    (item_id, 140, 0, 0, 2, primary_mode),
                    (item_id, 150, 1, 1, 2, primary_mode),
                    (item_id, 200, 1, 0, 2, primary_mode),
                ),
            )

    assert sum(repo.daily_review_counts(100, 200).values()) == 4


def test_deck_primary_review_count_is_lane_scoped_and_half_open(tmp_path):
    import pytest

    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "lesson-activity.db"
    init_db(db_path)
    repo = Repo(db_path)
    vocab_deck, _ = repo.upsert_deck("A1", "vocab", "v.csv", "v")
    grammar_deck, _ = repo.upsert_deck("A1", "grammar", "g.csv", "g")
    sentence_deck, _ = repo.upsert_deck("A1", "sentences", "s.csv", "s")
    listening_deck, _ = repo.upsert_deck("A1", "listening", "l.csv", "l")
    vocab_id = repo.insert_vocab(
        vocab_deck, "noun", "Haus", "das", "n", "Haeuser", "house"
    )
    grammar_id = repo.insert_grammar(
        grammar_deck, "Ich ___ Deutsch.", "lerne", None, None, None, None
    )
    sentence_id = repo.insert_sentence(
        sentence_deck, "Ich lerne Deutsch.", None, None, None
    )
    listening_id = repo.insert_listening(
        listening_deck, "Ich lerne.", "Was?", "Deutsch", None, None, None
    )
    specs = (
        ("vocab", "reviews", "vocab_id", vocab_id, vocab_deck, "recognition", "production"),
        ("grammar", "grammar_reviews", "grammar_id", grammar_id, grammar_deck, "production", "future"),
        ("sentences", "sentence_reviews", "sentence_id", sentence_id, sentence_deck, "builder", "future"),
        (
            "listening",
            "listening_reviews",
            "listening_id",
            listening_id,
            listening_deck,
            "comprehension",
            "future",
        ),
    )
    with repo._conn() as conn:
        for _objective, table, fk, item_id, _deck, primary, other in specs:
            conn.executemany(
                f"""
                INSERT INTO {table}(
                    {fk}, created_at, was_checked, was_skipped, rating, practice_mode
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    (item_id, 99, 1, 0, 2, primary),
                    (item_id, 120, 1, 0, 2, primary),
                    (item_id, 130, 1, 0, 2, other),
                    (item_id, 140, 0, 0, 2, primary),
                    (item_id, 150, 1, 1, 2, primary),
                    (item_id, 200, 1, 0, 2, primary),
                ),
            )

    for objective, _table, _fk, _item, deck, _primary, _other in specs:
        assert repo.deck_primary_review_count(objective, deck, 100, 200) == 1
    with pytest.raises(ValueError):
        repo.deck_primary_review_count("unknown", vocab_deck, 100, 200)
