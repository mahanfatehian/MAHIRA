"""New material must be introduced in lesson order, not filename order.

decks are numbered in seed-import order, and seed import walks a glob, so the
filenames sort lexicographically: 10, 11, 12, 1, 2, 3... Lektion 10 therefore
gets deck_id 1. Every 'new' row in planner_inventory has a NULL due_at and ties
at COALESCE(due_at, 0) = 0, so deck_id was the effective sort key and a brand
new learner's first plan opened on Lektion 10.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "src" / "db" / "schema.sql"


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo
    from db.seed_loader import load_all_seeds

    db_path = tmp_path / "planner-order.db"
    init_db(db_path, SCHEMA)
    r = Repo(db_path)
    load_all_seeds(r, REPO_ROOT)
    return r


def test_the_glob_order_this_guards_against_is_real():
    """If seeds ever stop loading out of order, this test loses its point."""
    names = [
        f.name.split("_")[0]
        for f in sorted((REPO_ROOT / "data/seeds/starten_wir/a1").glob("*vocab*.csv"))
    ]
    assert names[0] != "1", "seed glob no longer starts at Lektion 10"


def _new_items(repo, objective: str):
    inventory = repo.planner_inventory(int(time.time()), cooldown_hours=12)
    return [
        item
        for item in inventory
        if item.objective == objective and item.bucket == "new"
    ]


def test_new_vocabulary_starts_at_the_first_lektion(repo):
    items = _new_items(repo, "vocab")
    assert items, "no new vocabulary in the inventory"
    assert items[0].lektion_number == 1


@pytest.mark.parametrize("objective", ["vocab", "grammar", "sentences", "listening"])
def test_every_lane_introduces_new_material_in_lesson_order(repo, objective):
    items = _new_items(repo, objective)
    if not items:
        pytest.skip(f"no new {objective} content is shipped")
    numbers = [item.lektion_number for item in items]
    assert numbers == sorted(numbers)


def test_deck_id_order_would_have_failed_this(repo):
    """Documents the actual defect: deck_id order is not lesson order."""
    items = _new_items(repo, "vocab")
    by_deck = sorted(items, key=lambda i: (i.deck_id, i.item_id))
    assert by_deck[0].lektion_number != 1


def test_ordering_is_stable_across_calls(repo):
    first = [(i.objective, i.item_id) for i in repo.planner_inventory(1_800_000_000)]
    second = [(i.objective, i.item_id) for i in repo.planner_inventory(1_800_000_000)]
    assert first == second


def test_due_items_still_come_before_new_ones(repo):
    now = int(time.time())
    vocab = [i for i in repo.planner_inventory(now) if i.objective == "vocab"]
    buckets = [i.bucket for i in vocab]
    assert buckets == sorted(buckets, key=lambda b: 0 if b == "due" else 1)
