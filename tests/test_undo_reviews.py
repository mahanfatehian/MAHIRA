from __future__ import annotations

from dataclasses import replace

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
            "state_table": "vocab_states",
            "state_fk": "vocab_id",
            "review_table": "reviews",
            "practice_mode": "recognition",
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
            "state_table": "grammar_states",
            "state_fk": "grammar_id",
            "review_table": "grammar_reviews",
            "practice_mode": "production",
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
            "state_table": "sentence_states",
            "state_fk": "sentence_id",
            "review_table": "sentence_reviews",
            "practice_mode": "builder",
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
            "state_table": "listening_states",
            "state_fk": "listening_id",
            "review_table": "listening_reviews",
            "practice_mode": "comprehension",
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


def _review_ids(repo, table: str) -> list[int]:
    with repo._conn() as conn:
        return [
            int(row[0])
            for row in conn.execute(
                f"SELECT id FROM {table} ORDER BY id"
            ).fetchall()
        ]


def _raw_state_control(repo, case) -> tuple[int, int, int | None] | None:
    with repo._conn() as conn:
        row = conn.execute(
            f"SELECT id, suspended, buried_until FROM {case['state_table']} "
            f"WHERE {case['state_fk']}=?",
            (case["item"].id,),
        ).fetchone()
    if row is None:
        return None
    return (
        int(row["id"]),
        int(row["suspended"]),
        None if row["buried_until"] is None else int(row["buried_until"]),
    )


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
    assert isinstance(session._undo["review_id"], int)
    assert session._undo["post_state_token"]
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
def test_stale_undo_preserves_a_later_same_item_review(repo, objective):
    case = _case(repo, objective)
    first = _session_shell(repo)
    second = _session_shell(repo)

    case["submit"](first, False)
    first.record_item_answered()
    case["submit"](second, False)
    state_after_second = case["get_state"]()

    assert first.undo_last() is None
    assert first.can_undo() is True
    assert case["get_state"]() == state_after_second
    assert _review_count(repo, case["review_table"]) == 2


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentence", "listening")
)
@pytest.mark.parametrize(
    ("field", "delta"), (("ease", 0.25), ("interval_days", 1.0))
)
def test_stale_undo_rejects_each_persisted_scheduler_change(
    repo, objective, field, delta
):
    case = _case(repo, objective)
    session = _session_shell(repo)

    case["submit"](session, False)
    state_after_review = case["get_state"]()
    review_ids = _review_ids(repo, case["review_table"])
    changed_state = replace(
        state_after_review,
        **{field: getattr(state_after_review, field) + delta},
    )
    getattr(repo, case["update_state"])(changed_state)

    assert session.undo_last() is None
    assert session.can_undo() is True
    assert case["get_state"]() == changed_state
    assert _review_ids(repo, case["review_table"]) == review_ids


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentence", "listening")
)
def test_scheduler_state_read_exposes_identity_and_controls(repo, objective):
    case = _case(repo, objective)
    session = _session_shell(repo)
    case["submit"](session, False)

    state = case["get_state"]()
    raw = _raw_state_control(repo, case)

    assert raw is not None
    assert state.id == raw[0]
    assert state.suspended is False
    assert state.buried_until is None


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentence", "listening")
)
@pytest.mark.parametrize("control", ("suspended", "buried_until"))
def test_first_review_control_change_blocks_undo(repo, objective, control):
    from core.insights import InsightsService

    case = _case(repo, objective)
    session = _session_shell(repo)
    case["submit"](session, False)
    review_ids = _review_ids(repo, case["review_table"])

    other_repo = type(repo)(repo.db_path)
    insights = InsightsService(other_repo)
    control_objective = "sentences" if objective == "sentence" else objective
    if control == "suspended":
        insights.set_suspended(control_objective, case["item"].id, True)
    else:
        insights.bury(control_objective, case["item"].id, now=1_700_000_000)
    controlled_state = _raw_state_control(repo, case)

    assert controlled_state is not None
    assert controlled_state[1] == (1 if control == "suspended" else 0)
    assert (controlled_state[2] is not None) == (control == "buried_until")
    assert session.undo_last() is None
    assert session.can_undo() is True
    assert _raw_state_control(repo, case) == controlled_state
    assert _review_ids(repo, case["review_table"]) == review_ids


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentence", "listening")
)
@pytest.mark.parametrize(
    "mismatch",
    (
        "missing_review_id",
        "wrong_review_id",
        "missing_item_id",
        "wrong_item_id",
    ),
)
def test_undo_event_identity_mismatch_preserves_state_and_history(
    repo, objective, mismatch
):
    case = _case(repo, objective)
    session = _session_shell(repo)
    case["submit"](session, False)
    state_after_review = case["get_state"]()
    review_ids = _review_ids(repo, case["review_table"])

    if mismatch == "missing_review_id":
        session._undo["review_id"] = None
    elif mismatch == "wrong_review_id":
        session._undo["review_id"] += 1_000_000
    elif mismatch == "missing_item_id":
        session._undo["item_id"] = None
    else:
        session._undo["item_id"] += 1_000_000
        session._undo["post_state_token"] = "missing"

    assert session.undo_last() is None
    assert session.can_undo() is True
    assert case["get_state"]() == state_after_review
    assert _review_ids(repo, case["review_table"]) == review_ids


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentence", "listening")
)
def test_delete_review_event_rejects_wrong_primary_mode(repo, objective):
    case = _case(repo, objective)
    session = _session_shell(repo)
    case["submit"](session, False)
    review_id = session._undo["review_id"]
    review_ids = _review_ids(repo, case["review_table"])

    with pytest.raises(ValueError, match="practice mode"):
        repo.delete_review_event(
            objective,
            review_id,
            case["item"].id,
            "wrong-mode",
        )

    assert _review_ids(repo, case["review_table"]) == review_ids


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentence", "listening")
)
def test_delete_review_event_targets_requested_older_event(repo, objective):
    case = _case(repo, objective)
    first = _session_shell(repo)
    second = _session_shell(repo)

    case["submit"](first, False)
    older_review_id = first._undo["review_id"]
    case["submit"](second, False)
    newer_review_id = second._undo["review_id"]
    assert _review_ids(repo, case["review_table"]) == [
        older_review_id,
        newer_review_id,
    ]

    repo.delete_review_event(
        objective,
        older_review_id,
        case["item"].id,
        case["practice_mode"],
    )

    assert _review_ids(repo, case["review_table"]) == [newer_review_id]


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


def test_undo_does_not_delete_lab_review_row(repo):
    """Recognition undo must only drop recognition rows, never Lab lanes."""
    case = _case(repo, "vocab")
    session = _session_shell(repo)
    item = case["item"]

    case["submit"](session, False)
    session.record_item_answered()
    assert session.can_undo() is True

    session.submit_vocab_production(
        item, "das Haus", practice_mode="production", response_ms=400
    )
    assert session.can_undo() is False

    # Manually re-arm a recognition undo after Lab (simulates stale snap edge)
    # and ensure delete still targets recognition only.
    session._undo = {
        "objective": "vocab",
        "item_id": item.id,
        "prev_state": None,
        "logged": True,
        "state_was_missing": False,
        "study_progress": (0, 30),
    }
    # Seed a real prev state so undo can restore without deleting state.
    prev = repo.get_state(item.id)
    session._undo["prev_state"] = prev
    session._undo["state_was_missing"] = prev is None

    with repo._conn() as conn:
        modes_before = [
            r[0]
            for r in conn.execute(
                "SELECT practice_mode FROM reviews WHERE vocab_id=? ORDER BY rowid",
                (item.id,),
            ).fetchall()
        ]
    assert modes_before == ["recognition", "production"]

    # Force a recognition-scoped delete via repo API
    repo.delete_last_review(item.id, practice_mode="recognition")

    with repo._conn() as conn:
        modes_after = [
            r[0]
            for r in conn.execute(
                "SELECT practice_mode FROM reviews WHERE vocab_id=? ORDER BY rowid",
                (item.id,),
            ).fetchall()
        ]
    assert modes_after == ["production"]
