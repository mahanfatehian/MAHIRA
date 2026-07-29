from __future__ import annotations

import pytest


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "undo-reviews.db"
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
    deck_objective = "sentences" if objective == "sentence" else objective
    deck_id, _changed = repo.upsert_deck(
        "A1", deck_objective, f"{deck_objective}.csv", "undo-test-sha"
    )

    if objective == "vocab":
        item_id = repo.insert_vocab(
            deck_id, "noun", "Haus", "das", "n", "Hauser", "house"
        )
        item = repo.get_vocab_by_id(item_id)
        return {
            "item": item,
            "get_state": lambda: repo.get_state(item_id),
            "delete_state": "delete_state",
            "update_state": "update_state",
            "review_table": "reviews",
            "submit": lambda session, skipped: session.submit_vocab(
                item,
                "" if skipped else "house",
                "" if skipped else "n",
                "" if skipped else "Hauser",
                rating=2,
                tip_used=False,
                gender_tip_used=False,
                was_checked=not skipped,
                was_skipped=skipped,
                response_ms=500,
            ),
        }

    if objective == "grammar":
        item_id = repo.insert_grammar(
            deck_id, "Ich ___ Deutsch.", "lerne", "lernen", None, None, None
        )
        item = repo.get_grammar_by_id(item_id)
        return {
            "item": item,
            "get_state": lambda: repo.get_grammar_state(item_id),
            "delete_state": "delete_grammar_state",
            "update_state": "update_grammar_state",
            "review_table": "grammar_reviews",
            "submit": lambda session, skipped: session.submit_grammar(
                item,
                "" if skipped else "lerne",
                rating=2,
                meaning_tip_used=False,
                hint_used=False,
                grammar_tip_used=False,
                was_checked=not skipped,
                was_skipped=skipped,
                response_ms=500,
            ),
        }

    if objective == "sentence":
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
            "get_state": lambda: repo.get_sentence_state(item_id),
            "delete_state": "delete_sentence_state",
            "update_state": "update_sentence_state",
            "review_table": "sentence_reviews",
            "submit": lambda session, skipped: session.submit_sentence(
                item,
                "" if skipped else "Ich lerne Deutsch.",
                rating=2,
                tip_used=False,
                translation_used=False,
                was_checked=not skipped,
                was_skipped=skipped,
                response_ms=500,
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
            "get_state": lambda: repo.get_listening_state(item_id),
            "delete_state": "delete_listening_state",
            "update_state": "update_listening_state",
            "review_table": "listening_reviews",
            "submit": lambda session, skipped: session.submit_listening(
                item,
                "" if skipped else "Deutsch",
                was_checked=not skipped,
                was_skipped=skipped,
                response_ms=500,
                replay_count=1,
                rating=2,
            ),
        }

    raise AssertionError(f"unsupported objective: {objective}")


def _review_count(repo, table: str) -> int:
    with repo._conn() as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentence", "listening")
)
def test_undo_first_review_restores_unseen_state_and_progress(repo, objective):
    case = _case(repo, objective)
    session = _session_shell(repo)
    session.study_answered = 29
    session.study_next_milestone = 30

    assert case["get_state"]() is None
    case["submit"](session, False)
    assert session.record_item_answered() is True
    assert session.study_progress() == (30, 60)
    assert case["get_state"]() is not None
    assert _review_count(repo, case["review_table"]) == 1

    assert session.undo_last() == case["item"]

    assert case["get_state"]() is None
    assert _review_count(repo, case["review_table"]) == 0
    assert session.study_progress() == (29, 30)
    assert session._queue[-1] == case["item"].id


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentence", "listening")
)
def test_undo_skip_preserves_prior_review_and_state(repo, objective):
    case = _case(repo, objective)
    session = _session_shell(repo)

    case["submit"](session, False)
    session.record_item_answered()
    state_before_skip = case["get_state"]()

    case["submit"](session, True)
    session.record_item_answered()
    assert _review_count(repo, case["review_table"]) == 1
    assert session.study_progress() == (2, 30)

    assert session.undo_last() == case["item"]

    assert case["get_state"]() == state_before_skip
    assert _review_count(repo, case["review_table"]) == 1
    assert session.study_progress() == (1, 30)


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentence", "listening")
)
def test_failed_undo_rolls_back_and_keeps_snapshot(
    repo, monkeypatch, objective
):
    case = _case(repo, objective)
    session = _session_shell(repo)

    case["submit"](session, False)
    session.record_item_answered()
    original_delete = getattr(repo, case["delete_state"])

    def fail_after_delete(item_id):
        original_delete(item_id)
        raise RuntimeError("injected undo failure")

    monkeypatch.setattr(repo, case["delete_state"], fail_after_delete)

    assert session.undo_last() is None
    assert session.can_undo() is True
    assert case["get_state"]() is not None
    assert _review_count(repo, case["review_table"]) == 1
    assert session.study_progress() == (1, 30)
    assert session._queue == []


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentence", "listening")
)
def test_failed_first_submission_does_not_create_seen_state(
    repo, monkeypatch, objective
):
    case = _case(repo, objective)
    session = _session_shell(repo)
    original_update = getattr(repo, case["update_state"])

    def fail_after_update(state):
        original_update(state)
        raise RuntimeError("injected submission failure")

    monkeypatch.setattr(repo, case["update_state"], fail_after_update)

    with pytest.raises(RuntimeError, match="injected submission failure"):
        case["submit"](session, False)

    assert case["get_state"]() is None
    assert _review_count(repo, case["review_table"]) == 0
    assert session.can_undo() is False
