from __future__ import annotations

from dataclasses import replace
import time

import pytest


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


def _runtime_state(session):
    return (
        session.state.level,
        session.state.objective,
        session.state.book_slug,
        session.state.lektion_number,
        tuple(session._queue),
        session._current_item_id,
        session._current_objective,
        session._current_state_token,
        session._undo,
        session._active_deck_id,
        session._session_position,
        session._session_total,
        session._session_kind,
        session.study_answered,
        session.study_next_milestone,
        session._pending_resume,
    )


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


def test_planned_preview_ignores_ranker_when_ml_ranking_is_disabled(tmp_path):
    from core.settings import AppSettings

    repo, deck, ids, _foreign_id = _library(tmp_path)
    session = _session(repo)
    session.settings.value = AppSettings(daily_goal=2)

    class ReorderingRanker:
        def __init__(self):
            self.calls = 0

        def rank_vocab_ids(self, item_ids, *, level=None):
            self.calls += 1
            # Ranker output is queue order, so returning the repository order
            # would reverse which two cards fit in this small daily plan.
            return list(item_ids)

    ranker = ReorderingRanker()
    session.ml = ranker
    session.enable_ml_ranking = False
    requested = _segment(deck, ids[:2])

    previewed = session.preview_planned_segment(requested, now=int(time.time()))

    assert previewed is not None
    assert previewed.item_ids == tuple(ids[:2])
    assert ranker.calls == 0


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


@pytest.mark.parametrize(
    ("make_stale", "replace_unfinished"),
    ((False, False), (True, True)),
)
def test_atomic_planned_start_preserves_unfinished_context_and_checkpoint_on_failure(
    tmp_path, make_stale, replace_unfinished
):
    repo, _deck, ids, foreign_id = _library(tmp_path)
    session = _session(repo)
    session.plan.limit = 3
    session.plan.new_limit = 3
    assert session.start_new_session()
    assert session.next_vocab_item() is not None

    foreign_deck = repo.get_vocab_by_id(foreign_id).deck_id
    requested = _segment(
        foreign_deck,
        (foreign_id,),
        lektion_number=2,
    )
    previewed = session.preview_planned_segment(requested, now=int(time.time()))
    assert previewed is not None

    checkpoint = repo.db_path.parent / "active_session.json"
    state_before = _runtime_state(session)
    checkpoint_before = checkpoint.read_bytes()
    if make_stale:
        repo.ensure_state(foreign_id)
        with repo._conn() as conn:
            conn.execute(
                "UPDATE vocab_states SET suspended=1 WHERE vocab_id=?",
                (foreign_id,),
            )

    assert session.start_planned_segment_for_context(
        previewed,
        replace_unfinished=replace_unfinished,
        now=int(time.time()),
    ) is False

    assert _runtime_state(session) == state_before
    assert checkpoint.read_bytes() == checkpoint_before
    assert session.state.lektion_number == 1
    assert session._active_deck_id != foreign_deck
    assert tuple(session._queue) == state_before[4]


def _unfinished_replacement_case(tmp_path):
    repo, _deck, _ids, foreign_id = _library(tmp_path)
    session = _session(repo)
    session.plan.limit = 3
    session.plan.new_limit = 3
    assert session.start_new_session()
    assert session.next_vocab_item() is not None
    session._undo = {"preserve": object()}

    foreign_deck = repo.get_vocab_by_id(foreign_id).deck_id
    requested = _segment(
        foreign_deck,
        (foreign_id,),
        lektion_number=2,
    )
    checkpoint = repo.db_path.parent / "active_session.json"
    return (
        repo,
        session,
        requested,
        _runtime_state(session),
        checkpoint,
        checkpoint.read_bytes(),
    )


def test_atomic_planned_replacement_rolls_back_runtime_when_transaction_exit_fails(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager

    (
        repo,
        session,
        requested,
        state_before,
        checkpoint,
        checkpoint_before,
    ) = _unfinished_replacement_case(tmp_path)
    original_transaction = repo.transaction

    @contextmanager
    def fail_after_yield():
        with original_transaction() as conn:
            yield conn
            raise RuntimeError("injected transaction exit failure")

    monkeypatch.setattr(repo, "transaction", fail_after_yield)

    assert session.start_planned_segment_for_context(
        requested,
        replace_unfinished=True,
        now=int(time.time()),
    ) is False

    assert _runtime_state(session) == state_before
    assert checkpoint.read_bytes() == checkpoint_before


def test_atomic_planned_replacement_rolls_back_runtime_when_checkpoint_save_fails(
    tmp_path, monkeypatch
):
    (
        _repo,
        session,
        requested,
        state_before,
        checkpoint,
        checkpoint_before,
    ) = _unfinished_replacement_case(tmp_path)

    def fail_save(_snapshot):
        raise OSError("injected checkpoint save failure")

    monkeypatch.setattr(session._resume_store, "save", fail_save)

    assert session.start_planned_segment_for_context(
        requested,
        replace_unfinished=True,
        now=int(time.time()),
    ) is False

    assert _runtime_state(session) == state_before
    assert checkpoint.read_bytes() == checkpoint_before


def test_atomic_planned_start_locks_revalidation_before_switching_context(
    tmp_path, monkeypatch
):
    repo, _deck, _ids, foreign_id = _library(tmp_path)
    session = _session(repo)
    foreign_deck = repo.get_vocab_by_id(foreign_id).deck_id
    requested = _segment(
        foreign_deck,
        (foreign_id,),
        lektion_number=2,
    )
    observed: list[tuple[str, bool]] = []
    original_preview = session.preview_planned_segment
    original_get_deck_id = repo.get_deck_id

    def guarded_preview(segment, now=None):
        connection = repo._active_conn
        observed.append(
            ("preview", bool(connection is not None and connection.in_transaction))
        )
        return original_preview(segment, now=now)

    def guarded_get_deck_id(*args, **kwargs):
        connection = repo._active_conn
        observed.append(
            ("deck", bool(connection is not None and connection.in_transaction))
        )
        return original_get_deck_id(*args, **kwargs)

    monkeypatch.setattr(session, "preview_planned_segment", guarded_preview)
    monkeypatch.setattr(repo, "get_deck_id", guarded_get_deck_id)

    assert session.start_planned_segment_for_context(
        requested,
        now=int(time.time()),
    ) is True

    assert observed
    assert ("preview", True) in observed
    assert ("deck", True) in observed
    assert session.state.level == "A1"
    assert session.state.objective == "vocab"
    assert session.state.book_slug == "planner"
    assert session.state.lektion_number == 2
    assert session._active_deck_id == foreign_deck
    assert session.next_vocab_item().id == foreign_id


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
