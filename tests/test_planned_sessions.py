from __future__ import annotations

from dataclasses import replace
import time


def _library(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db = tmp_path / ".mahira" / "mahira.db"
    init_db(db)
    repo = Repo(db)
    book = repo.ensure_book("planner", "Planner")
    lesson = repo.ensure_lektion(book, "A1", 1, "One")
    other_lesson = repo.ensure_lektion(book, "A1", 2, "Two")
    deck, _ = repo.upsert_deck(
        "A1", "vocab", "planner.csv", "planner-sha", lektion_id=lesson
    )
    ids = [
        repo.insert_vocab(deck, "noun", word, article, gender, plural, meaning)
        for word, article, gender, plural, meaning in (
            ("Haus", "das", "n", "Häuser", "house"),
            ("Tag", "der", "m", "Tage", "day"),
            ("Buch", "das", "n", "Bücher", "book"),
            ("Stadt", "die", "f", "Städte", "city"),
        )
    ]
    foreign_deck, _ = repo.upsert_deck(
        "A1", "vocab", "other.csv", "other-sha", lektion_id=other_lesson
    )
    foreign_id = repo.insert_vocab(
        foreign_deck, "noun", "Zeit", "die", "f", "Zeiten", "time"
    )
    return repo, deck, ids, foreign_id


def _session(repo):
    from core.session import AppState, SessionService
    from core.settings import AppSettings

    session = SessionService(repo, AppState("A1", "vocab", "planner", 1))
    session.settings = type("Settings", (), {"value": AppSettings(daily_goal=30)})()
    session.set_context("A1", "vocab", "planner", 1)
    session.enable_ml_ranking = False
    return session


def _segment(deck_id, item_ids, **changes):
    from core.planner import PlanSegment

    values = {
        "objective": "vocab",
        "deck_id": deck_id,
        "level": "A1",
        "book_slug": "planner",
        "lektion_number": 1,
        "item_ids": tuple(item_ids),
        "due_count": 0,
        "new_count": len(tuple(item_ids)),
        "ordinal": 1,
        "total_segments": 1,
    }
    values.update(changes)
    return PlanSegment(**values)


def test_planned_preview_is_read_only_and_filters_controls_scope_and_duplicates(tmp_path):
    repo, deck, ids, foreign_id = _library(tmp_path)
    session = _session(repo)
    active_first, suspended, buried, active_last = ids
    repo.ensure_state(suspended)
    repo.ensure_state(buried)
    with repo._conn() as conn:
        conn.execute("UPDATE vocab_states SET suspended=1 WHERE vocab_id=?", (suspended,))
        conn.execute(
            "UPDATE vocab_states SET buried_until=? WHERE vocab_id=?",
            (int(time.time()) + 3600, buried),
        )
    requested = _segment(
        deck,
        (active_last, foreign_id, active_first, active_last, suspended, buried),
        new_count=6,
    )
    state_before = (
        session.state.level,
        session.state.objective,
        session.state.book_slug,
        session.state.lektion_number,
        list(session._queue),
        session._active_deck_id,
    )

    previewed = session.preview_planned_segment(requested, now=int(time.time()))

    assert previewed is not None
    assert previewed.item_ids == (active_last, active_first)
    assert (
        session.state.level,
        session.state.objective,
        session.state.book_slug,
        session.state.lektion_number,
        list(session._queue),
        session._active_deck_id,
    ) == state_before
    assert session.preview_planned_segment(object(), now=int(time.time())) is None
    assert session.preview_planned_segment(
        replace(requested, item_ids=7), now=int(time.time())
    ) is None
    assert session.preview_planned_segment(
        _segment(deck + 999, (active_first,)), now=int(time.time())
    ) is None


def test_planned_start_serves_first_requested_first_and_preserves_manual_plan(tmp_path):
    repo, deck, ids, _foreign_id = _library(tmp_path)
    session = _session(repo)
    requested = _segment(deck, (ids[2], ids[0], ids[3]))
    plan_before = (session.plan.limit, session.plan.mode, session.plan.new_limit)

    assert session.start_planned_segment(requested, now=int(time.time())) is True

    assert session._session_kind == "review"
    assert session._session_total == 3
    assert (session.plan.limit, session.plan.mode, session.plan.new_limit) == plan_before
    assert [session.next_vocab_item().id for _ in range(3)] == [ids[2], ids[0], ids[3]]
    assert session.next_vocab_item() is None


def test_planned_start_refuses_any_unfinished_session_without_mutation(tmp_path):
    repo, deck, ids, _foreign_id = _library(tmp_path)
    session = _session(repo)
    request = _segment(deck, ids[:2])
    assert session.start_new_session()
    queue_before = list(session._queue)

    assert session.start_planned_segment(request, now=int(time.time())) is False
    assert session._queue == queue_before
    assert session._session_kind == "review"

    session.discard_pending_resume()
    assert session.start_targeted_session("vocab", [ids[0]])
    drill_before = list(session._queue)
    assert session.start_planned_segment(request, now=int(time.time())) is False
    assert session._queue == drill_before
    assert session._session_kind == "drill"


def test_planned_segment_uses_existing_primary_resume_checkpoint(tmp_path):
    from core.session import AppState, SessionService
    from core.settings import AppSettings

    repo, deck, ids, _foreign_id = _library(tmp_path)
    original = _session(repo)
    request = _segment(deck, ids[:3])
    assert original.start_planned_segment(request, now=int(time.time()))
    visible = original.next_vocab_item()
    remaining = list(original._queue)

    restarted = SessionService(repo, AppState("A1", "vocab", "planner", 1))
    restarted.settings = type("Settings", (), {"value": AppSettings()})()
    candidate = restarted.pending_resume()
    assert candidate is not None
    assert candidate.current_item_id == visible.id
    assert list(candidate.queue) == remaining
    assert restarted.resume_pending()
    assert restarted.next_vocab_item().id == visible.id
    assert restarted._queue == remaining
