"""The daily plan must rank listening like the other three lanes.

DailyPlannerService._rank maps each objective to a ranker method by name. The
map had no 'listening' entry, so _rank returned the inventory untouched and the
plan picked listening cards by raw inventory order - the same blind spot that
made whole listening sessions a random shuffle.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "src" / "db" / "schema.sql"


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "planner-listening.db"
    init_db(db_path, SCHEMA)
    return Repo(db_path)


@pytest.fixture()
def planner(repo, tmp_path):
    from core.ml.sklearn_ranker import SklearnRanker
    from core.planner import DailyPlannerService
    from core.settings import AppSettings

    ranker = SklearnRanker(repo, model_dir=tmp_path / "ml_models")
    return DailyPlannerService(repo, AppSettings(), ranker=ranker)


def _items(repo, n: int):
    deck_id, _ = repo.upsert_deck("A1", "listening", "l.csv", "sha-l")
    return [
        repo.insert_listening(
            deck_id,
            f"Passage {i}",
            f"Frage {i}?",
            f"Antwort {i}",
            json.dumps([f"X{i}", f"Y{i}"]),
            None,
            None,
        )
        for i in range(n)
    ]


def test_listening_is_mapped_to_a_ranker_method(planner):
    from core.ml.sklearn_ranker import SklearnRanker

    assert hasattr(SklearnRanker, "rank_listening_ids")


def test_the_planner_reorders_listening(repo, planner):
    ids = _items(repo, 12)
    now = int(time.time())

    # Every item shares a due_at, so planner_inventory hands them back in
    # item_id order and only the ranker can change that. Without an identical
    # due_at the inventory sort alone could produce the expected order and the
    # test would pass with the ranker unwired.
    at_risk = ids[9]
    due_at = now - 86400
    with repo._conn() as conn:
        for item_id in ids:
            conn.execute(
                "INSERT INTO listening_states(listening_id, reps, lapses, due_at, "
                "last_review_at, stability, difficulty, interval_days) "
                "VALUES (?,4,0,?,?,60.0,2.0,60.0)",
                (item_id, due_at, now - 5 * 86400),
            )
        conn.execute(
            "UPDATE listening_states SET lapses=8, stability=1.2, difficulty=10.0, "
            "interval_days=1.2, last_review_at=? WHERE listening_id=?",
            (now - 120 * 86400, at_risk),
        )

    inventory = [
        item
        for item in repo.planner_inventory(now, cooldown_hours=12)
        if item.objective == "listening"
    ]
    assert len(inventory) == len(ids)
    assert [i.item_id for i in inventory] == sorted(ids), (
        "inventory is not in plain item order; the test cannot isolate ranking"
    )

    ranked = planner._rank("listening", inventory)
    assert [i.item_id for i in ranked] != [i.item_id for i in inventory], (
        "listening came back in inventory order - the ranker was not applied"
    )
    # _rank returns first-served order, so the weakest item leads.
    assert ranked[0].item_id == at_risk


def test_ranking_preserves_every_item(repo, planner):
    ids = _items(repo, 10)
    now = int(time.time())
    inventory = [
        item
        for item in repo.planner_inventory(now, cooldown_hours=12)
        if item.objective == "listening"
    ]
    ranked = planner._rank("listening", inventory)
    assert sorted(i.item_id for i in ranked) == sorted(ids)


def test_a_missing_ranker_is_still_safe(repo):
    from core.planner import DailyPlannerService
    from core.settings import AppSettings

    ids = _items(repo, 5)
    now = int(time.time())
    inventory = [
        item
        for item in repo.planner_inventory(now, cooldown_hours=12)
        if item.objective == "listening"
    ]
    plain = DailyPlannerService(repo, AppSettings(), ranker=None)
    assert [i.item_id for i in plain._rank("listening", inventory)] == list(ids)
