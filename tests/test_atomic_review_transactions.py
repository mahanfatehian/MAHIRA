from __future__ import annotations

import pytest


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "atomic-reviews.db"
    init_db(db_path)
    return Repo(db_path)


def _session_shell(repo):
    from core.session import AppState, SessionService

    session = object.__new__(SessionService)
    session.repo = repo
    session.state = AppState()
    session.ml = None
    session._undo = None
    return session


def _case(repo, objective: str):
    deck_id, _changed = repo.upsert_deck(
        "A1", objective, f"{objective}.csv", "atomic-test-sha"
    )

    if objective == "vocab":
        item_id = repo.insert_vocab(
            deck_id, "noun", "Haus", "das", "n", "Häuser", "house"
        )
        item = repo.get_vocab_by_id(item_id)
        state_before = repo.ensure_state(item_id)
        return {
            "item": item,
            "state_before": state_before,
            "state_reader": lambda: repo.ensure_state(item_id),
            "update_name": "update_state",
            "review_table": "reviews",
            "submit": lambda session: session.submit_vocab(
                item,
                "house",
                "n",
                "Häuser",
                rating=2,
                tip_used=False,
                gender_tip_used=False,
                was_checked=True,
                was_skipped=False,
                response_ms=500,
            ),
        }

    if objective == "grammar":
        item_id = repo.insert_grammar(
            deck_id, "Ich ___ Deutsch.", "lerne", "lernen", None, None, None
        )
        item = repo.get_grammar_by_id(item_id)
        state_before = repo.ensure_grammar_state(item_id)
        return {
            "item": item,
            "state_before": state_before,
            "state_reader": lambda: repo.ensure_grammar_state(item_id),
            "update_name": "update_grammar_state",
            "review_table": "grammar_reviews",
            "submit": lambda session: session.submit_grammar(
                item,
                "lerne",
                rating=2,
                meaning_tip_used=False,
                hint_used=False,
                grammar_tip_used=False,
                was_checked=True,
                was_skipped=False,
                response_ms=500,
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
        state_before = repo.ensure_sentence_state(item_id)
        return {
            "item": item,
            "state_before": state_before,
            "state_reader": lambda: repo.ensure_sentence_state(item_id),
            "update_name": "update_sentence_state",
            "review_table": "sentence_reviews",
            "submit": lambda session: session.submit_sentence(
                item,
                "Ich lerne Deutsch.",
                rating=2,
                tip_used=False,
                translation_used=False,
                was_checked=True,
                was_skipped=False,
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
        state_before = repo.ensure_listening_state(item_id)
        return {
            "item": item,
            "state_before": state_before,
            "state_reader": lambda: repo.ensure_listening_state(item_id),
            "update_name": "update_listening_state",
            "review_table": "listening_reviews",
            "submit": lambda session: session.submit_listening(
                item,
                "Deutsch",
                was_checked=True,
                was_skipped=False,
                response_ms=500,
                replay_count=1,
                rating=2,
            ),
        }

    raise AssertionError(f"Unsupported objective: {objective}")


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentences", "listening")
)
def test_review_and_fsrs_update_roll_back_together(repo, monkeypatch, objective):
    case = _case(repo, objective)
    session = _session_shell(repo)
    original_update = getattr(repo, case["update_name"])

    def fail_after_state_write(state):
        original_update(state)
        raise RuntimeError("injected failure after FSRS write")

    monkeypatch.setattr(repo, case["update_name"], fail_after_state_write)

    with pytest.raises(RuntimeError, match="injected failure"):
        case["submit"](session)

    assert case["state_reader"]() == case["state_before"]
    with repo._conn() as conn:
        assert conn.execute(
            f"SELECT COUNT(*) FROM {case['review_table']}"
        ).fetchone()[0] == 0
    assert session._undo is None
