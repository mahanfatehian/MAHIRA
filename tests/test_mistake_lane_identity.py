from __future__ import annotations


def test_primary_mistakes_report_their_real_practice_lanes(tmp_path):
    from core.insights import InsightsService
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "mistake-lanes.db"
    init_db(db_path)
    repo = Repo(db_path)

    vocab_deck, _changed = repo.upsert_deck(
        "A1", "vocab", "vocab.csv", "vocab-sha"
    )
    vocab_id = repo.insert_vocab(
        vocab_deck, "noun", "Haus", "das", "n", "Häuser", "house"
    )
    repo.ensure_state(vocab_id)

    grammar_deck, _changed = repo.upsert_deck(
        "A1", "grammar", "grammar.csv", "grammar-sha"
    )
    grammar_id = repo.insert_grammar(
        grammar_deck,
        "Ich ___ Deutsch.",
        "lerne",
        "lernen",
        None,
        None,
        None,
    )
    repo.ensure_grammar_state(grammar_id)

    sentence_deck, _changed = repo.upsert_deck(
        "A1", "sentences", "sentences.csv", "sentences-sha"
    )
    sentence_id = repo.insert_sentence(
        sentence_deck,
        "Ich lerne Deutsch.",
        "I learn German.",
        None,
        '["Ich", "lerne", "Deutsch", "."]',
    )
    repo.ensure_sentence_state(sentence_id)

    listening_deck, _changed = repo.upsert_deck(
        "A1", "listening", "listening.csv", "listening-sha"
    )
    listening_id = repo.insert_listening(
        listening_deck,
        "Ich lerne Deutsch.",
        "Was lerne ich?",
        "Deutsch",
        '["Englisch", "Mathematik"]',
        None,
        None,
    )
    repo.ensure_listening_state(listening_id)

    with repo._conn() as conn:
        for table in (
            "vocab_states",
            "grammar_states",
            "sentence_states",
            "listening_states",
        ):
            conn.execute(f"UPDATE {table} SET lapses=3, reps=4")

    lanes = {
        item.objective: item.practice_mode
        for item in InsightsService(repo).trouble_items()
    }

    assert lanes == {
        "vocab": "recognition",
        "grammar": "production",
        "sentences": "builder",
        "listening": "comprehension",
    }
