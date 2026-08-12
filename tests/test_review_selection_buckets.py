from __future__ import annotations

import pytest


NOW = 2_000_000_000
PRIMARY_OBJECTIVES = ("vocab", "grammar", "sentences", "listening")


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "review-selection-buckets.db"
    init_db(db_path)
    return Repo(db_path)


def _session_shell(repo):
    from core.session import AppState, SessionService

    session = object.__new__(SessionService)
    session.repo = repo
    session.state = AppState()
    session.ml = None
    session._queue = []
    session._undo = None
    session.study_answered = 0
    session.study_next_milestone = 30
    return session


def _case(repo, objective: str):
    deck_id, _changed = repo.upsert_deck(
        "A1", objective, f"{objective}.csv", f"{objective}-sha"
    )

    if objective == "vocab":
        item_id = repo.insert_vocab(
            deck_id, "noun", "Haus", "das", "n", "Haeuser", "house"
        )
        item = repo.get_vocab_by_id(item_id)
        return {
            "item": item,
            "review_table": "reviews",
            "state_table": "vocab_states",
            "state_fk": "vocab_id",
            "practice_mode": "recognition",
            "get_state": lambda: repo.get_state(item_id),
            "ensure_state": lambda: repo.ensure_state(item_id),
            "update_state": "update_state",
            "insert_review": "insert_review",
            "submit": lambda session: session.submit_vocab(
                item,
                "house",
                "n",
                "Haeuser",
                rating=2,
                tip_used=False,
                gender_tip_used=False,
                was_checked=True,
                was_skipped=False,
                response_ms=300,
            ),
        }

    if objective == "grammar":
        item_id = repo.insert_grammar(
            deck_id, "Ich ___ Deutsch.", "lerne", "lernen", None, None, None
        )
        item = repo.get_grammar_by_id(item_id)
        return {
            "item": item,
            "review_table": "grammar_reviews",
            "state_table": "grammar_states",
            "state_fk": "grammar_id",
            "practice_mode": "production",
            "get_state": lambda: repo.get_grammar_state(item_id),
            "ensure_state": lambda: repo.ensure_grammar_state(item_id),
            "update_state": "update_grammar_state",
            "insert_review": "insert_grammar_review",
            "submit": lambda session: session.submit_grammar(
                item,
                "lerne",
                rating=2,
                meaning_tip_used=False,
                hint_used=False,
                grammar_tip_used=False,
                was_checked=True,
                was_skipped=False,
                response_ms=300,
            ),
        }

    if objective == "sentences":
        item_id = repo.insert_sentence(
            deck_id,
            "Ich lerne Deutsch.",
            "I learn German.",
            None,
            '["Ich", "lerne", "Deutsch", "."]',
        )
        item = repo.get_sentence_by_id(item_id)
        return {
            "item": item,
            "review_table": "sentence_reviews",
            "state_table": "sentence_states",
            "state_fk": "sentence_id",
            "practice_mode": "builder",
            "get_state": lambda: repo.get_sentence_state(item_id),
            "ensure_state": lambda: repo.ensure_sentence_state(item_id),
            "update_state": "update_sentence_state",
            "insert_review": "insert_sentence_review",
            "submit": lambda session: session.submit_sentence(
                item,
                "Ich lerne Deutsch.",
                rating=2,
                tip_used=False,
                translation_used=False,
                was_checked=True,
                was_skipped=False,
                response_ms=300,
            ),
        }

    if objective == "listening":
        item_id = repo.insert_listening(
            deck_id,
            "Ich lerne heute Deutsch.",
            "Was lerne ich?",
            "Deutsch",
            '["Englisch", "Mathematik"]',
            None,
            None,
        )
        item = repo.get_listening_by_id(item_id)
        return {
            "item": item,
            "review_table": "listening_reviews",
            "state_table": "listening_states",
            "state_fk": "listening_id",
            "practice_mode": "comprehension",
            "get_state": lambda: repo.get_listening_state(item_id),
            "ensure_state": lambda: repo.ensure_listening_state(item_id),
            "update_state": "update_listening_state",
            "insert_review": "insert_listening_review",
            "submit": lambda session: session.submit_listening(
                item,
                "Deutsch",
                was_checked=True,
                was_skipped=False,
                response_ms=300,
                replay_count=1,
                rating=2,
            ),
        }

    raise AssertionError(f"unsupported objective: {objective}")


def _set_pre_review_state(repo, case, state_kind: str) -> None:
    if state_kind == "missing":
        assert case["get_state"]() is None
        return

    case["ensure_state"]()
    timestamps = {
        "due": (NOW - 60, NOW - (12 * 60 * 60) - 1),
        "future": (NOW + 60, NOW - (24 * 60 * 60)),
        "recent": (NOW - 60, NOW - (12 * 60 * 60) + 1),
    }
    due_at, last_review_at = timestamps[state_kind]
    with repo._conn() as conn:
        conn.execute(
            f"UPDATE {case['state_table']} "
            f"SET due_at=?, last_review_at=? WHERE {case['state_fk']}=?",
            (due_at, last_review_at, case["item"].id),
        )


def _stored_review(repo, case):
    with repo._conn() as conn:
        return tuple(
            conn.execute(
                f"SELECT practice_mode, selection_bucket, "
                f"was_checked, was_skipped FROM {case['review_table']}"
            ).fetchone()
        )


@pytest.mark.parametrize("objective", PRIMARY_OBJECTIVES)
@pytest.mark.parametrize(
    ("state_kind", "expected_bucket"),
    (
        ("missing", "new"),
        ("due", "due"),
        ("future", "extra"),
        ("recent", "extra"),
    ),
)
def test_primary_submit_classifies_the_pre_review_state(
    repo, monkeypatch, objective, state_kind, expected_bucket
):
    import core.session as session_module

    monkeypatch.setattr(session_module.time, "time", lambda: NOW)
    case = _case(repo, objective)
    _set_pre_review_state(repo, case, state_kind)

    case["submit"](_session_shell(repo))

    assert _stored_review(repo, case) == (
        case["practice_mode"],
        expected_bucket,
        1,
        0,
    )


@pytest.mark.parametrize("practice_mode", ("production", "dictation"))
def test_vocab_lab_reviews_remain_legacy(repo, monkeypatch, practice_mode):
    import core.session as session_module

    monkeypatch.setattr(session_module.time, "time", lambda: NOW)
    case = _case(repo, "vocab")

    _session_shell(repo).submit_vocab_production(
        case["item"],
        "das Haus",
        practice_mode=practice_mode,
        response_ms=300,
    )

    assert _stored_review(repo, case) == (practice_mode, "legacy", 1, 0)


@pytest.mark.parametrize("objective", PRIMARY_OBJECTIVES)
def test_review_insert_failure_rolls_back_an_unseen_state(
    repo, monkeypatch, objective
):
    case = _case(repo, objective)
    original_insert = getattr(repo, case["insert_review"])

    def fail_after_insert(*args, **kwargs):
        original_insert(*args, **kwargs)
        raise RuntimeError("injected review insert failure")

    monkeypatch.setattr(repo, case["insert_review"], fail_after_insert)

    with pytest.raises(RuntimeError, match="injected review insert failure"):
        case["submit"](_session_shell(repo))

    assert case["get_state"]() is None
    with repo._conn() as conn:
        assert conn.execute(
            f"SELECT COUNT(*) FROM {case['review_table']}"
        ).fetchone()[0] == 0


@pytest.mark.parametrize("objective", PRIMARY_OBJECTIVES)
def test_state_update_failure_rolls_back_review_and_scheduler_state(
    repo, monkeypatch, objective
):
    case = _case(repo, objective)
    _set_pre_review_state(repo, case, "due")
    state_before = case["get_state"]()
    original_update = getattr(repo, case["update_state"])

    def fail_after_update(state):
        original_update(state)
        raise RuntimeError("injected scheduler update failure")

    monkeypatch.setattr(repo, case["update_state"], fail_after_update)

    with pytest.raises(RuntimeError, match="injected scheduler update failure"):
        case["submit"](_session_shell(repo))

    assert case["get_state"]() == state_before
    with repo._conn() as conn:
        assert conn.execute(
            f"SELECT COUNT(*) FROM {case['review_table']}"
        ).fetchone()[0] == 0
