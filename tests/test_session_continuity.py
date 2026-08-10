from __future__ import annotations

from pathlib import Path

import pytest


def _library(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / ".mahira" / "mahira.db"
    init_db(db_path)
    repo = Repo(db_path)
    book_id = repo.ensure_book("continuity", "Continuity")
    lesson_id = repo.ensure_lektion(book_id, "A1", 1, "One")
    second_lesson_id = repo.ensure_lektion(book_id, "A1", 2, "Two")

    decks: dict[str, int] = {}
    decks["vocab"], _changed = repo.upsert_deck(
        "A1", "vocab", "vocab.csv", "vocab-sha", lektion_id=lesson_id
    )
    for word, meaning in (("Haus", "house"), ("Tag", "day"), ("Buch", "book")):
        repo.insert_vocab(decks["vocab"], "noun", word, "das", "n", f"{word}e", meaning)

    decks["grammar"], _changed = repo.upsert_deck(
        "A1", "grammar", "grammar.csv", "grammar-sha", lektion_id=lesson_id
    )
    for number, answer in enumerate(("lerne", "lernst", "lernt"), 1):
        repo.insert_grammar(
            decks["grammar"],
            f"Person {number} null Deutsch.",
            answer,
            "lernen",
            None,
            "learns German",
            None,
        )

    decks["sentences"], _changed = repo.upsert_deck(
        "A1", "sentences", "sentences.csv", "sentences-sha", lektion_id=lesson_id
    )
    for number in range(1, 4):
        repo.insert_sentence(
            decks["sentences"],
            f"Ich lerne Deutsch {number}.",
            f"I learn German {number}.",
            None,
            None,
        )

    decks["listening"], _changed = repo.upsert_deck(
        "A1", "listening", "listening.csv", "listening-sha", lektion_id=lesson_id
    )
    for number in range(1, 4):
        repo.insert_listening(
            decks["listening"],
            f"Text Nummer {number}.",
            f"Welche Nummer ist das, {number}?",
            str(number),
            "[]",
            f"Text number {number}.",
            None,
        )

    second_deck, _changed = repo.upsert_deck(
        "A1", "vocab", "vocab-2.csv", "vocab-2-sha", lektion_id=second_lesson_id
    )
    repo.insert_vocab(second_deck, "noun", "Stadt", "die", "f", "Städte", "city")
    return repo, decks


def _session(repo, objective: str, *, limit: int = 3):
    from core.session import AppState, SessionService

    session = SessionService(
        repo,
        AppState("A1", objective, "continuity", 1),
    )
    if session.pending_resume() is None:
        session.set_context("A1", objective, "continuity", 1)
    session.enable_ml_ranking = False
    session.plan.limit = limit
    session.plan.new_limit = limit
    return session


@pytest.mark.parametrize(
    "objective",
    ("vocab", "grammar", "sentences", "listening"),
)
def test_cold_restart_restores_same_card_and_remaining_order(tmp_path, objective):
    repo, _decks = _library(tmp_path)
    original = _session(repo, objective)
    assert original.start_new_session() is True

    current = original.next_item()
    assert current is not None
    remaining = list(original._queue)

    restarted = _session(repo, objective)
    candidate = restarted.pending_resume()
    assert candidate is not None
    assert candidate.current_item_id == current.id
    assert list(candidate.queue) == remaining

    assert restarted.resume_pending() is True
    resumed = restarted.next_item()
    assert resumed is not None
    assert resumed.id == current.id
    assert restarted._queue == remaining
    assert restarted.can_undo() is False


def test_deck_switch_removes_open_session_checkpoint(tmp_path):
    repo, _decks = _library(tmp_path)
    session = _session(repo, "vocab")
    session.start_new_session()
    session.next_item()
    checkpoint = Path(repo.db_path).parent / "active_session.json"
    assert checkpoint.exists()

    session.set_context("A1", "vocab", "continuity", 2)

    assert session.remaining() == 0
    assert not checkpoint.exists()
    assert session.pending_resume() is None


def test_last_successful_review_clears_checkpoint(tmp_path):
    repo, _decks = _library(tmp_path)
    session = _session(repo, "grammar", limit=1)
    session.start_new_session()
    item = session.next_item()
    assert item is not None
    checkpoint = Path(repo.db_path).parent / "active_session.json"
    assert checkpoint.exists()

    session.submit_grammar(
        item=item,
        typed_blank=item.answer,
        rating=2,
        meaning_tip_used=False,
        hint_used=False,
        grammar_tip_used=False,
        was_checked=True,
        was_skipped=False,
        response_ms=500,
    )

    assert not checkpoint.exists()


def test_restart_does_not_repeat_card_committed_before_checkpoint_advance(
    tmp_path,
    monkeypatch,
):
    repo, _decks = _library(tmp_path)
    session = _session(repo, "grammar", limit=2)
    session.start_new_session()
    current = session.next_item()
    assert current is not None
    expected_next = session._queue[-1]

    # Simulate process death in the narrow gap after SQLite commits but before
    # the JSON checkpoint can replace its previous version.
    monkeypatch.setattr(session, "_checkpoint_session", lambda: None)
    session.submit_grammar(
        item=current,
        typed_blank=current.answer,
        rating=2,
        meaning_tip_used=False,
        hint_used=False,
        grammar_tip_used=False,
        was_checked=True,
        was_skipped=False,
        response_ms=500,
    )

    restarted = _session(repo, "grammar", limit=2)
    assert restarted.pending_resume().current_item_id == current.id
    assert restarted.resume_pending() is True
    next_item = restarted.next_item()
    assert next_item is not None
    assert next_item.id == expected_next
    assert next_item.id != current.id
    assert restarted.study_answered == 1


def test_failed_review_keeps_current_card_checkpoint_retryable(tmp_path, monkeypatch):
    repo, _decks = _library(tmp_path)
    session = _session(repo, "grammar", limit=2)
    session.start_new_session()
    current = session.next_item()
    assert current is not None
    checkpoint = Path(repo.db_path).parent / "active_session.json"
    before = checkpoint.read_bytes()

    def fail_review(**_values):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(repo, "insert_grammar_review", fail_review)
    with pytest.raises(RuntimeError, match="database unavailable"):
        session.submit_grammar(
            item=current,
            typed_blank=current.answer,
            rating=2,
            meaning_tip_used=False,
            hint_used=False,
            grammar_tip_used=False,
            was_checked=True,
            was_skipped=False,
            response_ms=500,
        )

    assert checkpoint.read_bytes() == before
    restarted = _session(repo, "grammar", limit=2)
    assert restarted.resume_pending() is True
    assert restarted.next_item().id == current.id


def test_seed_revision_change_discards_stale_card_ids(tmp_path):
    repo, decks = _library(tmp_path)
    session = _session(repo, "vocab")
    session.start_new_session()
    session.next_item()
    checkpoint = Path(repo.db_path).parent / "active_session.json"
    assert checkpoint.exists()

    repo.upsert_deck(
        "A1",
        "vocab",
        "vocab.csv",
        "replacement-sha",
        lektion_id=repo.get_lektion_id(repo.get_book_id("continuity"), "A1", 1),
    )
    assert repo.get_deck_seed_sha1(decks["vocab"]) == "replacement-sha"

    restarted = _session(repo, "vocab")
    assert restarted.pending_resume() is not None
    assert restarted.resume_pending() is False
    assert not checkpoint.exists()


def test_profile_database_directories_keep_resume_candidates_isolated(tmp_path):
    first_repo, _decks = _library(tmp_path / "first")
    first = _session(first_repo, "vocab")
    first.start_new_session()
    first.next_item()

    second_repo, _decks = _library(tmp_path / "second")
    second = _session(second_repo, "vocab")

    assert first.pending_resume() is None
    assert second.pending_resume() is None
    assert (Path(first_repo.db_path).parent / "active_session.json").exists()
    assert not (Path(second_repo.db_path).parent / "active_session.json").exists()
