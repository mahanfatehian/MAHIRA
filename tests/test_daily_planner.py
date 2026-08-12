from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace


OBJECTIVES = ("vocab", "grammar", "sentences", "listening")


def _settings(**changes):
    values = {
        "daily_goal": 30,
        "session_limit": 30,
        "planner_due_caps": {objective: 30 for objective in OBJECTIVES},
        "planner_new_caps": {objective: 8 for objective in OBJECTIVES},
        "planner_weights": {objective: 1 for objective in OBJECTIVES},
        "planner_weighted_mix": False,
    }
    values.update(changes)
    return SimpleNamespace(**values)


class _Repo:
    def __init__(self, inventory, usage=()):
        self.inventory = list(inventory)
        self.usage = list(usage)
        self.calls = []

    def planner_inventory(self, now, cooldown_hours=12):
        self.calls.append(("inventory", int(now), cooldown_hours))
        return list(self.inventory)

    def daily_plan_usage(self, day_start, day_end):
        self.calls.append(("usage", int(day_start), int(day_end)))
        return list(self.usage)


def _item(
    objective,
    item_id,
    *,
    bucket="due",
    deck_id=None,
    level="A1",
    book_slug="menschen",
    lektion_number=1,
    due_at=100,
):
    from db.repo import PlannerInventoryItem

    return PlannerInventoryItem(
        objective=objective,
        item_id=item_id,
        deck_id=deck_id if deck_id is not None else OBJECTIVES.index(objective) + 10,
        level=level,
        book_slug=book_slug,
        lektion_number=lektion_number,
        bucket=bucket,
        due_at=due_at if bucket == "due" else None,
    )


def _usage(objective, *, completed=0, due=0, new=0):
    from db.repo import DailyPlanUsage

    return DailyPlanUsage(
        objective=objective,
        completed=completed,
        due=due,
        new=new,
    )


def _by_objective(snapshot):
    return {row.objective: row for row in snapshot.objectives}


def test_daily_plan_allocates_all_due_before_new_and_segments_by_deck():
    from core.planner import DailyPlannerService

    inventory = [
        _item("vocab", 1),
        _item("vocab", 2, due_at=101),
        _item("vocab", 3, bucket="new"),
        _item("vocab", 4, bucket="new"),
        _item("grammar", 5),
        _item("grammar", 6, bucket="new"),
        _item("sentences", 7),
        _item("listening", 8, bucket="new"),
    ]
    repo = _Repo(inventory)

    snapshot = DailyPlannerService(
        repo,
        _settings(daily_goal=6, session_limit=2),
    ).snapshot(now=1_700_000_000)

    rows = _by_objective(snapshot)
    assert (rows["vocab"].planned_due, rows["vocab"].planned_new) == (2, 0)
    assert (rows["grammar"].planned_due, rows["grammar"].planned_new) == (1, 1)
    assert (rows["sentences"].planned_due, rows["sentences"].planned_new) == (1, 0)
    assert (rows["listening"].planned_due, rows["listening"].planned_new) == (0, 1)
    assert snapshot.planned_total == 6
    assert sum(row.planned_due for row in snapshot.objectives) == 4
    assert [segment.objective for segment in snapshot.segments] == [
        "vocab", "grammar", "sentences", "listening",
    ]
    assert [segment.item_ids for segment in snapshot.segments] == [
        (1, 2),
        (5, 6),
        (7,),
        (8,),
    ]
    assert [segment.ordinal for segment in snapshot.segments] == [1, 2, 3, 4]
    assert all(segment.total_segments == 4 for segment in snapshot.segments)


def test_daily_plan_uses_deterministic_weighted_largest_remainder():
    from core.planner import DailyPlannerService

    inventory = [
        _item(objective, (index * 100) + offset)
        for index, objective in enumerate(OBJECTIVES, start=1)
        for offset in range(1, 9)
    ]
    weights = {"vocab": 4, "grammar": 2, "sentences": 1, "listening": 1}

    snapshot = DailyPlannerService(
        _Repo(inventory),
        _settings(
            daily_goal=8,
            planner_weighted_mix=True,
            planner_weights=weights,
        ),
    ).snapshot(now=1_700_000_000)

    assert [row.planned_due for row in snapshot.objectives] == [4, 2, 1, 1]
    assert [row.planned_new for row in snapshot.objectives] == [0, 0, 0, 0]


def test_daily_plan_redistributes_empty_shares_and_respects_usage_and_caps():
    from core.planner import DailyPlannerService

    inventory = [
        *[_item("vocab", item_id) for item_id in range(1, 7)],
        *[_item("vocab", item_id, bucket="new") for item_id in range(20, 26)],
        *[_item("grammar", item_id, bucket="new") for item_id in range(30, 36)],
    ]
    usage = [
        _usage("vocab", completed=3, due=1, new=1),
        _usage("grammar", completed=1, due=0, new=1),
    ]
    due_caps = {objective: 0 for objective in OBJECTIVES}
    new_caps = {objective: 0 for objective in OBJECTIVES}
    due_caps["vocab"] = 3
    new_caps.update(vocab=2, grammar=5)

    snapshot = DailyPlannerService(
        _Repo(inventory, usage),
        _settings(
            daily_goal=10,
            planner_due_caps=due_caps,
            planner_new_caps=new_caps,
        ),
    ).snapshot(now=1_700_000_000)

    rows = _by_objective(snapshot)
    assert snapshot.completed_total == 4
    assert snapshot.planned_total == 6
    assert (rows["vocab"].planned_due, rows["vocab"].planned_new) == (2, 1)
    assert (rows["grammar"].planned_due, rows["grammar"].planned_new) == (0, 3)
    assert rows["vocab"].backlog_due == 4
    assert rows["vocab"].backlog_new == 5
    assert rows["grammar"].backlog_new == 3


def test_daily_plan_ranking_is_converted_to_first_served_order():
    from core.planner import DailyPlannerService

    class _Ranker:
        def rank_vocab_ids(self, ids, *, level=None, **_):
            assert ids == [1, 2, 3]
            assert level == "A1"
            return [1, 3, 2]  # SessionService-style pop order: 2 is highest.

    snapshot = DailyPlannerService(
        _Repo([_item("vocab", item_id) for item_id in (1, 2, 3)]),
        _settings(daily_goal=3),
        ranker=_Ranker(),
    ).snapshot(now=1_700_000_000)

    assert snapshot.segments[0].item_ids == (2, 3, 1)


def test_revalidate_segment_is_read_only_and_keeps_only_current_same_cohort_ids():
    from core.planner import DailyPlannerService

    repo = _Repo([_item("vocab", item_id) for item_id in (1, 2, 3)])
    service = DailyPlannerService(repo, _settings(daily_goal=3))
    original = service.snapshot(now=1_700_000_000).segments[0]
    repo.inventory = [
        _item("vocab", 1),
        _item("vocab", 3),
        _item("vocab", 4, deck_id=99),
    ]

    refreshed = service.revalidate_segment(original, now=1_700_000_001)

    assert refreshed is not None
    assert refreshed.item_ids == (1, 3)
    assert refreshed.deck_id == original.deck_id
    assert refreshed.due_count == 2
    assert refreshed.new_count == 0
    assert repo.inventory == [
        _item("vocab", 1),
        _item("vocab", 3),
        _item("vocab", 4, deck_id=99),
    ]
    assert service.revalidate_segment(replace(original, deck_id=99), now=1_700_000_001) is None


def test_completed_global_goal_stops_selection_but_keeps_ready_and_backlog_truthful():
    from core.planner import DailyPlannerService

    snapshot = DailyPlannerService(
        _Repo(
            [_item("vocab", 1), _item("grammar", 2, bucket="new")],
            [_usage("vocab", completed=5, due=0, new=0)],
        ),
        _settings(daily_goal=5),
    ).snapshot(now=1_700_000_000)

    assert snapshot.completed_total == 5
    assert snapshot.planned_total == 0
    assert snapshot.ready_due == 1
    assert snapshot.ready_new == 1
    assert snapshot.backlog_due == 1
    assert snapshot.backlog_new == 1
    assert snapshot.segments == ()


def test_revalidation_honors_a_reduced_current_session_limit():
    from core.planner import DailyPlannerService

    settings = _settings(daily_goal=10, session_limit=10)
    service = DailyPlannerService(
        _Repo([_item("vocab", item_id) for item_id in range(1, 11)]),
        settings,
    )
    stale = service.snapshot(now=1_700_000_000).segments[0]
    settings.session_limit = 3

    current = service.revalidate_segment(stale, now=1_700_000_001)

    assert current is not None
    assert current.item_ids == (1, 2, 3)
    assert current.ordinal == 1
    assert current.total_segments == 4
    assert len(current.item_ids) <= settings.session_limit


def test_daily_plan_reads_inventory_and_usage_in_one_repository_snapshot():
    from core.planner import DailyPlannerService

    class _SnapshotRepo(_Repo):
        def __init__(self):
            super().__init__([_item("vocab", 1)])
            self.inside_snapshot = False

        @contextmanager
        def read_transaction(self):
            self.inside_snapshot = True
            try:
                yield
            finally:
                self.inside_snapshot = False

        def planner_inventory(self, now, cooldown_hours=12):
            assert self.inside_snapshot
            return super().planner_inventory(now, cooldown_hours)

        def daily_plan_usage(self, day_start, day_end):
            assert self.inside_snapshot
            return super().daily_plan_usage(day_start, day_end)

    snapshot = DailyPlannerService(
        _SnapshotRepo(), _settings(daily_goal=1)
    ).snapshot(now=1_700_000_000)

    assert snapshot.planned_total == 1


def test_equal_weight_largest_remainder_ties_follow_objective_order():
    from core.planner import DailyPlannerService

    inventory = [
        _item(objective, index * 100 + offset)
        for index, objective in enumerate(OBJECTIVES, start=1)
        for offset in range(3)
    ]

    snapshot = DailyPlannerService(
        _Repo(inventory), _settings(daily_goal=2)
    ).snapshot(now=1_700_000_000)

    assert [row.planned_due for row in snapshot.objectives] == [1, 1, 0, 0]


def test_same_objective_multiple_decks_produce_homogeneous_segments():
    from core.planner import DailyPlannerService

    snapshot = DailyPlannerService(
        _Repo(
            [
                _item("vocab", 1, deck_id=10),
                _item("vocab", 2, deck_id=11, lektion_number=2),
                _item("vocab", 3, deck_id=10),
            ]
        ),
        _settings(daily_goal=3, session_limit=3),
    ).snapshot(now=1_700_000_000)

    assert [(segment.deck_id, segment.item_ids) for segment in snapshot.segments] == [
        (10, (1, 3)),
        (11, (2,)),
    ]


def test_local_day_bounds_are_adjacent_local_midnights():
    from core.planner import _local_day_bounds

    captured = int(datetime(2026, 8, 12, 13, 45).timestamp())
    start, end = _local_day_bounds(captured)
    local_start = datetime.fromtimestamp(start)
    local_end = datetime.fromtimestamp(end)

    assert local_start.time().isoformat() == "00:00:00"
    assert local_end.time().isoformat() == "00:00:00"
    assert local_end.date() == local_start.date() + timedelta(days=1)
