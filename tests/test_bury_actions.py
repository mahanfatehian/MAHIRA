from __future__ import annotations

import time
from datetime import datetime, time as datetime_time, timedelta

import pytest


_OBJECTIVES = ("vocab", "grammar", "sentences", "listening")


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "bury-actions.db"
    init_db(db_path)
    return Repo(db_path)


def _make_trouble_card(repo, objective: str) -> tuple[int, int, str, str]:
    deck_id, _changed = repo.upsert_deck(
        "A1",
        objective,
        f"{objective}.csv",
        "test-sha",
    )

    if objective == "vocab":
        item_id = repo.insert_vocab(
            deck_id,
            "noun",
            "Termin",
            "der",
            "m",
            "Termine",
            "appointment",
        )
        repo.ensure_state(item_id)
        state_table, foreign_key = "vocab_states", "vocab_id"
    elif objective == "grammar":
        item_id = repo.insert_grammar(
            deck_id,
            "Ich ___ Deutsch.",
            "lerne",
            "lernen",
            None,
            None,
            None,
        )
        repo.ensure_grammar_state(item_id)
        state_table, foreign_key = "grammar_states", "grammar_id"
    elif objective == "sentences":
        item_id = repo.insert_sentence(
            deck_id,
            "Ich lerne Deutsch.",
            "I learn German.",
            None,
            '["Ich", "lerne", "Deutsch", "."]',
        )
        repo.ensure_sentence_state(item_id)
        state_table, foreign_key = "sentence_states", "sentence_id"
    elif objective == "listening":
        item_id = repo.insert_listening(
            deck_id,
            "Ich habe morgen einen Termin.",
            "Wann ist der Termin?",
            "Morgen",
            '["Heute", "Gestern"]',
            None,
            None,
        )
        repo.ensure_listening_state(item_id)
        state_table, foreign_key = "listening_states", "listening_id"
    else:  # pragma: no cover - the parametrization is intentionally closed.
        raise AssertionError(f"Unsupported test objective: {objective}")

    now = int(time.time())
    with repo._conn() as conn:
        conn.execute(
            f"UPDATE {state_table} "
            "SET lapses=3, reps=5, due_at=?, last_review_at=NULL, "
            "suspended=0, buried_until=NULL "
            f"WHERE {foreign_key}=?",
            (now - 60, item_id),
        )
    return deck_id, item_id, state_table, foreign_key


def _pick(repo, objective: str, deck_id: int, mode: str) -> list[int]:
    picker = {
        "vocab": repo.pick_session_vocab_ids,
        "grammar": repo.pick_session_grammar_ids,
        "sentences": repo.pick_session_sentence_ids,
        "listening": repo.pick_session_listening_ids,
    }[objective]
    return picker(deck_id, 10, mode=mode, cooldown_hours=0)


def _due_count(repo, objective: str, deck_id: int) -> int:
    counter = {
        "vocab": repo.due_count,
        "grammar": repo.grammar_due_count,
        "sentences": repo.sentence_due_count,
        "listening": repo.listening_due_count,
    }[objective]
    return counter(deck_id)


@pytest.mark.parametrize("objective", _OBJECTIVES)
def test_due_counters_exclude_buried_and_suspended_cards(repo, objective):
    deck_id, item_id, state_table, foreign_key = _make_trouble_card(
        repo,
        objective,
    )
    now = int(time.time())

    assert _due_count(repo, objective, deck_id) == 1
    assert repo.upcoming_due_counts(3600) == {"due_now": 1, "due_soon": 0}

    with repo._conn() as conn:
        conn.execute(
            f"UPDATE {state_table} SET buried_until=? WHERE {foreign_key}=?",
            (now + 3600, item_id),
        )
    assert _due_count(repo, objective, deck_id) == 0
    assert repo.upcoming_due_counts(3600) == {"due_now": 0, "due_soon": 0}

    with repo._conn() as conn:
        conn.execute(
            f"UPDATE {state_table} "
            "SET due_at=?, buried_until=NULL, suspended=0 "
            f"WHERE {foreign_key}=?",
            (now + 600, item_id),
        )
    assert _due_count(repo, objective, deck_id) == 0
    assert repo.upcoming_due_counts(3600) == {"due_now": 0, "due_soon": 1}

    with repo._conn() as conn:
        conn.execute(
            f"UPDATE {state_table} SET suspended=1 WHERE {foreign_key}=?",
            (item_id,),
        )
    assert _due_count(repo, objective, deck_id) == 0
    assert repo.upcoming_due_counts(3600) == {"due_now": 0, "due_soon": 0}


@pytest.mark.parametrize("objective", _OBJECTIVES)
def test_due_only_never_falls_back_to_future_cards(repo, objective):
    deck_id, item_id, state_table, foreign_key = _make_trouble_card(
        repo,
        objective,
    )
    now = int(time.time())

    with repo._conn() as conn:
        conn.execute(
            f"UPDATE {state_table} SET due_at=?, last_review_at=NULL "
            f"WHERE {foreign_key}=?",
            (now + 3600, item_id),
        )
    assert _pick(repo, objective, deck_id, "due_only") == []

    with repo._conn() as conn:
        conn.execute(
            f"UPDATE {state_table} SET due_at=? WHERE {foreign_key}=?",
            (now - 60, item_id),
        )
    assert _pick(repo, objective, deck_id, "due_only") == [item_id]


def test_grammar_unseen_only_never_falls_back_to_seen_cards(repo):
    deck_id, _item_id, _state_table, _foreign_key = _make_trouble_card(
        repo,
        "grammar",
    )

    assert repo.pick_session_grammar_ids(
        deck_id,
        10,
        mode="unseen_only",
        cooldown_hours=0,
    ) == []


@pytest.mark.parametrize("objective", _OBJECTIVES)
def test_tomorrow_bury_excludes_every_lane_until_next_local_day(repo, objective):
    from core.insights import InsightsService

    deck_id, item_id, state_table, foreign_key = _make_trouble_card(
        repo,
        objective,
    )
    insights = InsightsService(repo)

    assert item_id in {
        item.item_id
        for item in insights.trouble_items()
        if item.objective == objective
    }
    assert next(lane for lane in insights.lanes() if lane.objective == objective).trouble == 1

    # Keep the injected calendar safely ahead of the wall clock so this test
    # remains deterministic even when the suite happens to cross midnight.
    local_now = (datetime.now() + timedelta(days=2)).replace(
        hour=15,
        minute=6,
        second=44,
        microsecond=0,
    )
    injected_now = int(local_now.timestamp())
    expected_until = int(
        datetime.combine(
            local_now.date() + timedelta(days=1),
            datetime_time.min,
        ).timestamp()
    )

    buried_until = insights.bury(objective, item_id, now=injected_now)
    assert buried_until == expected_until
    local_until = datetime.fromtimestamp(buried_until)
    assert local_until.date() == local_now.date() + timedelta(days=1)
    assert local_until.time() == datetime_time.min

    with repo._conn() as conn:
        stored = conn.execute(
            f"SELECT buried_until FROM {state_table} WHERE {foreign_key}=?",
            (item_id,),
        ).fetchone()["buried_until"]
    assert int(stored) == expected_until

    assert item_id not in {
        item.item_id
        for item in insights.trouble_items()
        if item.objective == objective
    }
    assert next(lane for lane in insights.lanes() if lane.objective == objective).trouble == 0

    # Each picker previously reintroduced the only buried card through its
    # unfiltered `if not ids` fallback. All modes must now respect learner state.
    for mode in ("mixed", "due_only", "random_only"):
        assert _pick(repo, objective, deck_id, mode) == []

    # Expiry makes the item eligible again without altering its FSRS schedule.
    with repo._conn() as conn:
        conn.execute(
            f"UPDATE {state_table} SET buried_until=? WHERE {foreign_key}=?",
            (int(time.time()) - 1, item_id),
        )
    assert item_id in {
        item.item_id
        for item in insights.trouble_items()
        if item.objective == objective
    }
    for mode in ("mixed", "due_only", "random_only"):
        assert _pick(repo, objective, deck_id, mode) == [item_id]

    # Fallback selection must continue to preserve indefinite suspension too.
    with repo._conn() as conn:
        conn.execute(
            f"UPDATE {state_table} SET suspended=1 WHERE {foreign_key}=?",
            (item_id,),
        )
    for mode in ("mixed", "due_only", "random_only"):
        assert _pick(repo, objective, deck_id, mode) == []


def test_bury_reports_missing_or_unsupported_targets(repo):
    from core.insights import InsightsService

    insights = InsightsService(repo)
    with pytest.raises(LookupError):
        insights.bury("vocab", 999_999, now=time.time())
    with pytest.raises(ValueError):
        insights.bury("unknown", 1, now=time.time())


def test_active_queue_invalidation_is_objective_safe():
    from core.session import AppState, SessionService

    session = SessionService.__new__(SessionService)
    session.state = AppState(objective="vocab")
    session._queue = [3, 7, 3]

    assert session.exclude_from_queue("grammar", 3) is False
    assert session._queue == [3, 7, 3]

    assert session.exclude_from_queue("vocab", 3) is True
    assert session._queue == [7]
    assert session.exclude_from_queue("vocab", 3) is False
    assert session.exclude_from_queue("vocab", "not-an-id") is False

    session.state.objective = "sentences"
    session._queue = [7]
    assert session.exclude_from_queue("sentence", 7) is True
    assert session._queue == []


def test_lab_lane_failures_appear_in_mistakes_and_share_only_learner_controls(repo):
    from core.insights import InsightsService

    deck_id, _changed = repo.upsert_deck("A1", "vocab", "lab.csv", "lab-sha")
    item_id = repo.insert_vocab(
        deck_id,
        "noun",
        "Termin",
        "der",
        "m",
        "Termine",
        "appointment",
    )
    repo.ensure_vocab_practice_state(item_id, "production")
    with repo._conn() as conn:
        conn.execute(
            "UPDATE vocab_practice_states SET lapses=4, reps=6 "
            "WHERE vocab_id=? AND practice_mode='production'",
            (item_id,),
        )
        conn.execute(
            "INSERT INTO reviews(vocab_id, practice_mode, error_tags) "
            "VALUES (?, 'production', 'article_missing')",
            (item_id,),
        )

    insights = InsightsService(repo)
    trouble = [
        item
        for item in insights.trouble_items()
        if item.item_id == item_id and item.practice_mode == "production"
    ]
    assert len(trouble) == 1
    assert trouble[0].error_tags == "article_missing"
    assert next(lane for lane in insights.lanes() if lane.objective == "vocab").trouble == 1

    # A Lab-only item need not have recognition memory. Tomorrow creates only
    # the shared learner-control row and does not copy or mutate lane FSRS data.
    before = repo.ensure_vocab_practice_state(item_id, "production")
    until = insights.bury("vocab", item_id)
    assert until > int(time.time())
    assert not [item for item in insights.trouble_items() if item.item_id == item_id]
    assert repo.pick_vocab_practice_ids(
        deck_id,
        "production",
        10,
        mode="random_only",
        cooldown_hours=0,
    ) == []
    after = repo.ensure_vocab_practice_state(item_id, "production")
    assert after == before
