"""New material must keep flowing when the learner has a due backlog.

The planner used to allocate one pooled budget across objectives and let due
work take its share first. Any backlog at or above the daily goal therefore
drove new cards to exactly zero: the course stopped advancing until the learner
cleared the backlog, and nothing in the UI said why.
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import pytest

from core.planner import NEW_RESERVE_FRACTION, DailyPlannerService
from core.settings import AppSettings
from db.init_db import init_db
from db.repo import Repo

OBJECTIVES = ("vocab", "grammar", "sentences", "listening")
SCHEMA = Path(__file__).resolve().parents[1] / "src" / "db" / "schema.sql"
STATE = {
    "vocab": ("vocab_states", "vocab_id"),
    "grammar": ("grammar_states", "grammar_id"),
    "sentences": ("sentence_states", "sentence_id"),
    "listening": ("listening_states", "listening_id"),
}
NOW = 1_800_000_000


def _insert(repo, deck_id, objective, i):
    if objective == "vocab":
        return repo.insert_vocab(deck_id, "noun", f"W{i}", "das", "n", None, f"m{i}")
    if objective == "grammar":
        return repo.insert_grammar(deck_id, f"G{i} ___.", "x", None, None, None, None)
    if objective == "sentences":
        return repo.insert_sentence(deck_id, f"S{i} satz.", f"t{i}", None, None)
    return repo.insert_listening(
        deck_id, f"P{i}", f"Q{i}", f"A{i}", json.dumps(["a", "b"]), None, None
    )


def _repo(due_per_lane: int, new_per_lane: int) -> Repo:
    path = Path(tempfile.mkdtemp()) / "plan.db"
    init_db(path, SCHEMA)
    repo = Repo(path)
    for objective in OBJECTIVES:
        deck_id, _ = repo.upsert_deck("A1", objective, f"{objective}.csv", f"s{objective}")
        for i in range(due_per_lane + new_per_lane):
            item_id = _insert(repo, deck_id, objective, i)
            if i < due_per_lane:
                table, column = STATE[objective]
                with repo._conn() as conn:
                    conn.execute(
                        f"INSERT INTO {table}({column},reps,lapses,due_at,"
                        f"last_review_at,stability,difficulty,interval_days) "
                        f"VALUES (?,3,0,?,?,5.0,5.0,5.0)",
                        (item_id, NOW - 86400, NOW - 6 * 86400),
                    )
    return repo


def _plan(repo, **overrides):
    settings = replace(AppSettings(), **overrides)
    snap = DailyPlannerService(repo, settings).snapshot(NOW)
    return (
        sum(o.planned_due for o in snap.objectives),
        sum(o.planned_new for o in snap.objectives),
        snap.planned_total,
    )


@pytest.fixture(scope="module")
def backlog():
    return _repo(due_per_lane=40, new_per_lane=40)


@pytest.fixture(scope="module")
def fresh():
    return _repo(due_per_lane=0, new_per_lane=40)


# --------------------------------------------------------------------------
# The defect
# --------------------------------------------------------------------------

def test_a_backlog_no_longer_starves_new_material(backlog):
    due, new, total = _plan(backlog)
    assert new > 0, "a due backlog drove new cards to zero again"
    assert total == 30


@pytest.mark.parametrize("goal", [10, 30, 60, 150])
def test_new_material_survives_at_every_goal(backlog, goal):
    due, new, total = _plan(backlog, daily_goal=goal)
    assert new > 0
    assert due > 0


def test_the_reserve_is_roughly_the_documented_fraction(backlog):
    _due, new, _total = _plan(backlog, daily_goal=100)
    assert new == pytest.approx(100 * NEW_RESERVE_FRACTION, abs=2)


def test_due_work_still_takes_the_majority(backlog):
    due, new, _total = _plan(backlog)
    assert due > new, "rescuing forgotten cards must still dominate the plan"


# --------------------------------------------------------------------------
# The reserve must never cost the learner a full plan
# --------------------------------------------------------------------------

# Default per-lane caps allow 4 x (30 due + 8 new).
CAP_CAPACITY = 4 * (30 + 8)


@pytest.mark.parametrize("goal", [5, 30, 60, 150, 200])
def test_the_plan_always_fills_whichever_limit_binds(backlog, goal):
    """Reserving slots for new work must never shrink the plan.

    Above the per-skill capacity the caps bind instead of the goal, which is
    the case the Adjust plan dialog calls out explicitly.
    """
    _due, _new, total = _plan(backlog, daily_goal=goal)
    assert total == min(goal, CAP_CAPACITY)


def test_a_fresh_learner_still_gets_a_full_plan_of_new_cards(fresh):
    due, new, total = _plan(fresh)
    assert due == 0
    assert new == 30
    assert total == 30


def test_unused_new_capacity_flows_back_to_due(backlog):
    """New switched off must not shrink the plan."""
    due, new, total = _plan(
        backlog, planner_new_caps={o: 0 for o in OBJECTIVES}
    )
    assert new == 0
    assert due == 30
    assert total == 30


def test_unused_due_capacity_flows_to_new(backlog):
    due, new, total = _plan(
        backlog, planner_due_caps={o: 0 for o in OBJECTIVES}
    )
    assert due == 0
    assert new == 30
    assert total == 30


def test_turning_new_material_off_is_still_honoured(backlog):
    _due, new, _total = _plan(backlog, planner_new_caps={o: 0 for o in OBJECTIVES})
    assert new == 0


def test_per_lane_new_caps_still_bound_the_reserve(backlog):
    _due, new, _total = _plan(
        backlog,
        daily_goal=200,
        planner_new_caps={o: 2 for o in OBJECTIVES},
    )
    assert new <= 8


def test_nothing_is_ever_over_allocated(backlog):
    for goal in (5, 17, 30, 99, 200):
        due, new, total = _plan(backlog, daily_goal=goal)
        assert due + new == total
        assert total <= goal
