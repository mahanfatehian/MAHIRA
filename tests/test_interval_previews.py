from __future__ import annotations

import pytest


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "interval-previews.db"
    init_db(db_path)
    return Repo(db_path)


def _case(repo, session, objective: str):
    deck_id, _changed = repo.upsert_deck(
        "A1",
        objective,
        f"{objective}.csv",
        f"{objective}-preview-sha",
    )

    if objective == "vocab":
        item_id = repo.insert_vocab(
            deck_id,
            "noun",
            "Haus",
            "das",
            "n",
            "Haeuser",
            "house",
        )
        return (
            repo.get_vocab_by_id(item_id),
            repo.unseen_count,
            session.vocab_interval_labels,
            "vocab_states",
        )

    if objective == "grammar":
        item_id = repo.insert_grammar(
            deck_id,
            "Ich ___ hier.",
            "bin",
            "sein",
            None,
            None,
            None,
        )
        return (
            repo.get_grammar_by_id(item_id),
            repo.grammar_unseen_count,
            session.grammar_interval_labels,
            "grammar_states",
        )

    if objective == "sentences":
        item_id = repo.insert_sentence(
            deck_id,
            "Ich bin hier.",
            "I am here.",
            None,
            '["Ich", "bin", "hier", "."]',
        )
        return (
            repo.get_sentence_by_id(item_id),
            repo.sentence_unseen_count,
            session.sentence_interval_labels,
            "sentence_states",
        )

    if objective == "listening":
        item_id = repo.insert_listening(
            deck_id,
            "Ich bin hier.",
            "Wo bin ich?",
            "hier",
            '["dort", "weg"]',
            None,
            None,
        )
        return (
            repo.get_listening_by_id(item_id),
            repo.listening_unseen_count,
            session.listening_interval_labels,
            "listening_states",
        )

    raise AssertionError(f"Unsupported objective: {objective}")


@pytest.mark.parametrize(
    "objective",
    ("vocab", "grammar", "sentences", "listening"),
)
def test_interval_preview_does_not_mark_unseen_card_seen(repo, objective):
    from core.session import SessionService

    session = object.__new__(SessionService)
    session.repo = repo
    item, unseen_count, preview, state_table = _case(repo, session, objective)

    assert unseen_count(item.deck_id) == 1

    labels = preview(item)

    assert set(labels) == {0, 1, 2, 3}
    assert all(labels.values())
    assert unseen_count(item.deck_id) == 1
    with repo._conn() as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {state_table}").fetchone()[0] == 0
