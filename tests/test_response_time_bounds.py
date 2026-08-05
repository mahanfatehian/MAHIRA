from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "response-times.db"
    init_db(db_path)
    return Repo(db_path)


def _session_shell(repo):
    from core.session import AppState, SessionService

    session = object.__new__(SessionService)
    session.repo = repo
    session.state = AppState()
    session.plan = SimpleNamespace(limit=10)
    session.ml = None
    session._undo = None
    session.study_answered = 0
    session.study_next_milestone = 30
    return session


def _submit(repo, objective: str, response_ms):
    session = _session_shell(repo)

    if objective in {"vocab", "lab"}:
        deck_id, _changed = repo.upsert_deck(
            "A1", "vocab", "response-vocab.csv", "response-vocab-sha"
        )
        item_id = repo.insert_vocab(
            deck_id, "noun", "Haus", "das", "n", "Häuser", "house"
        )
        item = repo.get_vocab_by_id(item_id)
        if objective == "lab":
            session.submit_vocab_production(
                item,
                "das Haus",
                practice_mode="production",
                response_ms=response_ms,
            )
        else:
            session.submit_vocab(
                item,
                "house",
                "n",
                "Häuser",
                rating=2,
                tip_used=False,
                gender_tip_used=False,
                was_checked=True,
                was_skipped=False,
                response_ms=response_ms,
            )
        return "reviews"

    if objective == "grammar":
        deck_id, _changed = repo.upsert_deck(
            "A1", "grammar", "response-grammar.csv", "response-grammar-sha"
        )
        item_id = repo.insert_grammar(
            deck_id, "Ich ___ Deutsch.", "lerne", "lernen", None, None, None
        )
        session.submit_grammar(
            repo.get_grammar_by_id(item_id),
            "lerne",
            rating=2,
            meaning_tip_used=False,
            hint_used=False,
            grammar_tip_used=False,
            was_checked=True,
            was_skipped=False,
            response_ms=response_ms,
        )
        return "grammar_reviews"

    if objective == "sentences":
        deck_id, _changed = repo.upsert_deck(
            "A1", "sentences", "response-sentences.csv", "response-sentences-sha"
        )
        item_id = repo.insert_sentence(
            deck_id,
            "Ich lerne Deutsch.",
            "I learn German.",
            None,
            '["Ich", "lerne", "Deutsch", "."]',
        )
        session.submit_sentence(
            repo.get_sentence_by_id(item_id),
            "Ich lerne Deutsch.",
            rating=2,
            tip_used=False,
            translation_used=False,
            was_checked=True,
            was_skipped=False,
            response_ms=response_ms,
        )
        return "sentence_reviews"

    if objective == "listening":
        deck_id, _changed = repo.upsert_deck(
            "A1", "listening", "response-listening.csv", "response-listening-sha"
        )
        item_id = repo.insert_listening(
            deck_id,
            "Ich lerne heute Deutsch.",
            "Was lerne ich?",
            "Deutsch",
            '["Englisch", "Mathematik"]',
            None,
            None,
        )
        session.submit_listening(
            repo.get_listening_by_id(item_id),
            "Deutsch",
            was_checked=True,
            was_skipped=False,
            response_ms=response_ms,
            replay_count=1,
            rating=2,
        )
        return "listening_reviews"

    raise AssertionError(f"Unsupported objective: {objective}")


@pytest.mark.parametrize(
    ("response_ms", "expected"),
    ((-500, 0), (10**30, 3_600_000), (None, None)),
)
@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentences", "listening", "lab")
)
def test_review_response_times_are_bounded(repo, objective, response_ms, expected):
    table = _submit(repo, objective, response_ms)

    with repo._conn() as conn:
        stored = conn.execute(
            f"SELECT response_ms FROM {table} ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0]

    assert stored == expected
