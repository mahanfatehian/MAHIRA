from __future__ import annotations


def _session_shell(repo):
    from core.session import AppState, SessionService

    session = object.__new__(SessionService)
    session.repo = repo
    session.state = AppState()
    session.ml = None
    session._undo = None
    session.study_answered = 0
    session.study_next_milestone = 30
    return session


def test_primary_submit_paths_persist_lane_and_error_tags(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db = tmp_path / "review-error-tags.db"
    init_db(db)
    repo = Repo(db)
    session = _session_shell(repo)

    vocab_deck, _ = repo.upsert_deck("A1", "vocab", "v.csv", "v")
    vocab_id = repo.insert_vocab(
        vocab_deck, "noun", "Haus", "das", "n", "Haeuser", "house"
    )
    vocab_result = session.submit_vocab(
        repo.get_vocab_by_id(vocab_id),
        "barn",
        "f",
        "Hauser",
        rating=2,
        tip_used=False,
        gender_tip_used=False,
        was_checked=True,
        was_skipped=False,
        response_ms=10,
    )

    grammar_deck, _ = repo.upsert_deck("A1", "grammar", "g.csv", "g")
    grammar_id = repo.insert_grammar(
        grammar_deck, "Ich ___ Deutsch.", "lerne", None, None, None, None
    )
    grammar_result = session.submit_grammar(
        repo.get_grammar_by_id(grammar_id),
        "spiele",
        rating=2,
        meaning_tip_used=False,
        hint_used=False,
        grammar_tip_used=False,
        was_checked=True,
        was_skipped=False,
        response_ms=10,
    )

    sentence_deck, _ = repo.upsert_deck("A1", "sentences", "s.csv", "s")
    sentence_id = repo.insert_sentence(
        sentence_deck, "Ich lerne Deutsch.", "I learn German.", None, None
    )
    sentence_result = session.submit_sentence(
        repo.get_sentence_by_id(sentence_id),
        "Ich spiele.",
        rating=2,
        tip_used=False,
        translation_used=False,
        was_checked=True,
        was_skipped=False,
        response_ms=10,
    )

    listening_deck, _ = repo.upsert_deck("A1", "listening", "l.csv", "l")
    listening_id = repo.insert_listening(
        listening_deck,
        "Ich lerne Deutsch.",
        "Was lerne ich?",
        "Deutsch",
        '["Englisch"]',
        None,
        None,
    )
    listening_result = session.submit_listening(
        repo.get_listening_by_id(listening_id),
        "Englisch",
        was_checked=True,
        was_skipped=False,
        response_ms=10,
        rating=2,
    )

    assert vocab_result["error_tags"] == ["meaning", "gender", "plural"]
    assert grammar_result["error_tags"]
    assert sentence_result["error_tags"]
    assert listening_result["error_tags"] == ["different_answer"]

    with repo._conn() as conn:
        stored = [
            tuple(
                conn.execute(
                    f"SELECT rating,practice_mode,error_tags FROM {table}"
                ).fetchone()
            )
            for table in (
                "reviews",
                "grammar_reviews",
                "sentence_reviews",
                "listening_reviews",
            )
        ]
    assert all(rating == 0 and tags for rating, _lane, tags in stored)
    assert [lane for _rating, lane, _tags in stored] == [
        "recognition",
        "production",
        "builder",
        "comprehension",
    ]
