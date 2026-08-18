"""Listening must obey the same always-on recall priority as the other lanes.

Before rank_listening_ids existed, session assembly looked it up with getattr,
found nothing, and fell through to `self.rng.shuffle(...)`. That silently broke
the never-drop invariant for a quarter of the app: the most-at-risk listening
items could be shuffled out of a capped session.
"""

from __future__ import annotations

import json
import time

import pytest

from db.init_db import init_db
from db.repo import Repo


@pytest.fixture()
def repo(tmp_path):
    db_path = tmp_path / "listening-ranking.db"
    init_db(db_path)
    return Repo(db_path)


@pytest.fixture()
def ranker(repo, tmp_path):
    from core.ml.sklearn_ranker import SklearnRanker

    return SklearnRanker(repo, model_dir=tmp_path / "ml_models")


def _deck(repo):
    deck_id, _ = repo.upsert_deck("A1", "listening", "listening.csv", "sha-listening")
    return deck_id


def _add(repo, deck_id, n: int) -> list[int]:
    return [
        repo.insert_listening(
            deck_id,
            f"Das ist Satz {i}.",
            f"Frage {i}?",
            f"Antwort {i}",
            json.dumps([f"Falsch {i}a", f"Falsch {i}b"]),
            None,
            None,
        )
        for i in range(n)
    ]


def _set_state(repo, listening_id: int, **cols):
    assignments = ", ".join(f"{k}=?" for k in cols)
    with repo._conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO listening_states(listening_id) VALUES (?)",
            (listening_id,),
        )
        conn.execute(
            f"UPDATE listening_states SET {assignments} WHERE listening_id=?",
            (*cols.values(), listening_id),
        )


def test_the_ranker_exposes_a_listening_method(ranker):
    """session.py looks this up by name with getattr; a rename silently
    reintroduces the random shuffle."""
    assert callable(getattr(ranker, "rank_listening_ids", None))


def test_ranking_an_empty_deck_is_safe(ranker):
    assert ranker.rank_listening_ids([]) == []


def test_every_id_survives_ranking(repo, ranker):
    ids = _add(repo, _deck(repo), 12)
    ranked = ranker.rank_listening_ids(list(ids))
    assert sorted(ranked) == sorted(ids)


def test_ranking_is_deterministic(repo, ranker):
    ids = _add(repo, _deck(repo), 15)
    assert ranker.rank_listening_ids(list(ids)) == ranker.rank_listening_ids(list(ids))


def test_an_overdue_item_outranks_a_freshly_reviewed_one(repo, ranker):
    """rank_* returns LOW priority first and HIGH last; the queue is popped
    from the end, so the at-risk item must sort last."""
    ids = _add(repo, _deck(repo), 2)
    now = int(time.time())
    safe, overdue = ids

    _set_state(
        repo,
        safe,
        reps=5,
        lapses=0,
        due_at=now + 30 * 86400,
        last_review_at=now - 86400,
        stability=60.0,
        difficulty=2.0,
        interval_days=60.0,
    )
    _set_state(
        repo,
        overdue,
        reps=5,
        lapses=4,
        due_at=now - 60 * 86400,
        last_review_at=now - 90 * 86400,
        stability=3.0,
        difficulty=9.0,
        interval_days=3.0,
    )

    ranked = ranker.rank_listening_ids([safe, overdue])
    assert ranked[-1] == overdue


def test_an_at_risk_item_is_never_dropped_from_a_capped_session(repo, ranker):
    """The invariant the shuffle was breaking."""
    deck_id = _deck(repo)
    ids = _add(repo, deck_id, 40)
    now = int(time.time())
    for item_id in ids:
        _set_state(
            repo,
            item_id,
            reps=4,
            lapses=0,
            due_at=now + 45 * 86400,
            last_review_at=now - 86400,
            stability=90.0,
            difficulty=2.0,
            interval_days=90.0,
        )

    at_risk = ids[7]
    _set_state(
        repo,
        at_risk,
        reps=9,
        lapses=7,
        due_at=now - 120 * 86400,
        last_review_at=now - 150 * 86400,
        stability=1.5,
        difficulty=10.0,
        interval_days=1.5,
    )

    ranked = ranker.rank_listening_ids(list(ids))
    top_ten = ranked[-10:]
    assert at_risk in top_ten


def test_unseen_items_are_ranked_without_a_state_row(repo, ranker):
    ids = _add(repo, _deck(repo), 6)
    ranked = ranker.rank_listening_ids(list(ids))
    assert sorted(ranked) == sorted(ids)


def test_a_fresh_deck_is_introduced_in_natural_order(repo, ranker):
    """Tie-break is (priority, -original_index), so an all-unseen deck keeps
    its id order once the queue is reversed."""
    ids = _add(repo, _deck(repo), 8)
    ranked = ranker.rank_listening_ids(list(ids))
    assert list(reversed(ranked)) == sorted(ids)


def test_replayed_items_outrank_items_answered_first_time(repo, ranker):
    """Replaying audio repeatedly is this lane's struggle signal."""
    ids = _add(repo, _deck(repo), 2)
    now = int(time.time())
    fluent, replayed = ids

    for item_id in ids:
        _set_state(
            repo,
            item_id,
            reps=4,
            lapses=0,
            due_at=now - 86400,
            last_review_at=now - 5 * 86400,
            stability=10.0,
            difficulty=5.0,
            interval_days=10.0,
        )

    with repo._conn() as conn:
        for _ in range(4):
            conn.execute(
                "INSERT INTO listening_reviews(listening_id, correct, rating, "
                "replay_count, response_ms) VALUES (?,1,2,0,3000)",
                (fluent,),
            )
            conn.execute(
                "INSERT INTO listening_reviews(listening_id, correct, rating, "
                "replay_count, response_ms) VALUES (?,1,2,6,3000)",
                (replayed,),
            )

    assert ranker.rank_listening_ids([fluent, replayed])[-1] == replayed
