from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, time as day_time, timedelta
from typing import Mapping

from db.repo import DailyPlanUsage, PlannerInventoryItem


OBJECTIVES = ("vocab", "grammar", "sentences", "listening")


@dataclass(frozen=True)
class ObjectiveCaps:
    due_cap: int
    new_cap: int
    weight: int = 1


@dataclass(frozen=True)
class ObjectivePlan:
    objective: str
    completed: int
    completed_due: int
    completed_new: int
    ready_due: int
    ready_new: int
    planned_due: int
    planned_new: int
    backlog_due: int
    backlog_new: int

    @property
    def planned(self) -> int:
        return self.planned_due + self.planned_new


@dataclass(frozen=True)
class PlanSegment:
    objective: str
    deck_id: int
    level: str
    book_slug: str
    lektion_number: int
    item_ids: tuple[int, ...]
    due_count: int
    new_count: int
    ordinal: int
    total_segments: int


@dataclass(frozen=True)
class DailyPlanSnapshot:
    captured_at: int
    day_start: int
    day_end: int
    goal: int
    completed_total: int
    planned_total: int
    ready_due: int
    ready_new: int
    backlog_due: int
    backlog_new: int
    objectives: tuple[ObjectivePlan, ...]
    segments: tuple[PlanSegment, ...]

    @property
    def remaining_goal(self) -> int:
        return max(0, self.goal - self.completed_total)


def _local_day_bounds(timestamp: int) -> tuple[int, int]:
    current_day = datetime.fromtimestamp(timestamp).date()
    next_day = current_day + timedelta(days=1)
    return (
        int(datetime.combine(current_day, day_time.min).timestamp()),
        int(datetime.combine(next_day, day_time.min).timestamp()),
    )


def _bounded_int(value, default: int, lower: int, upper: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lower, min(upper, number))


def _objective_map(value, default: int, lower: int, upper: int) -> dict[str, int]:
    source = value if isinstance(value, Mapping) else {}
    return {
        objective: _bounded_int(source.get(objective, default), default, lower, upper)
        for objective in OBJECTIVES
    }


def _allocate_slots(
    demand: Mapping[str, int],
    weights: Mapping[str, int],
    total: int,
) -> dict[str, int]:
    """Allocate at most ``total`` using iterative largest remainder.

    Capped/empty objectives leave the round and their unused share is
    redistributed. Objective order is the deterministic tie-break.
    """
    allocation = {objective: 0 for objective in OBJECTIVES}
    remaining = max(0, int(total))
    while remaining:
        active = [
            objective
            for objective in OBJECTIVES
            if allocation[objective] < max(0, int(demand.get(objective, 0)))
        ]
        if not active:
            break
        weight_total = sum(max(1, int(weights.get(objective, 1))) for objective in active)
        quotas = {
            objective: remaining
            * max(1, int(weights.get(objective, 1)))
            / weight_total
            for objective in active
        }

        granted = 0
        for objective in active:
            available = max(0, int(demand.get(objective, 0))) - allocation[objective]
            share = min(available, int(quotas[objective]))
            if share:
                allocation[objective] += share
                granted += share
        remaining -= granted
        if not remaining:
            break

        remainder_order = sorted(
            active,
            key=lambda objective: (
                -(quotas[objective] - int(quotas[objective])),
                OBJECTIVES.index(objective),
            ),
        )
        awarded_remainder = False
        for objective in remainder_order:
            if not remaining:
                break
            if allocation[objective] >= max(0, int(demand.get(objective, 0))):
                continue
            allocation[objective] += 1
            remaining -= 1
            awarded_remainder = True
        if not granted and not awarded_remainder:
            break
    return allocation


class DailyPlannerService:
    """Pure planner over repository read models and validated preferences."""

    def __init__(self, repo, settings, *, ranker=None):
        self.repo = repo
        self.settings = settings
        self.ranker = ranker

    def _caps(self) -> dict[str, ObjectiveCaps]:
        due = _objective_map(
            getattr(self.settings, "planner_due_caps", None), 30, 0, 200
        )
        new = _objective_map(
            getattr(self.settings, "planner_new_caps", None), 8, 0, 30
        )
        weights = _objective_map(
            getattr(self.settings, "planner_weights", None), 1, 1, 100
        )
        if not bool(getattr(self.settings, "planner_weighted_mix", False)):
            weights = {objective: 1 for objective in OBJECTIVES}
        return {
            objective: ObjectiveCaps(due[objective], new[objective], weights[objective])
            for objective in OBJECTIVES
        }

    def _rank(
        self,
        objective: str,
        items: list[PlannerInventoryItem],
    ) -> list[PlannerInventoryItem]:
        if len(items) < 2 or self.ranker is None:
            return items
        method_name = {
            "vocab": "rank_vocab_ids",
            "grammar": "rank_grammar_ids",
            "sentences": "rank_sentence_ids",
        }.get(objective)
        method = getattr(self.ranker, method_name, None) if method_name else None
        if method is None:
            return items
        ids = [item.item_id for item in items]
        levels = {item.level for item in items}
        level = next(iter(levels)) if len(levels) == 1 else None
        try:
            ranked = [int(item_id) for item_id in method(ids, level=level)]
        except Exception:
            return items
        if len(ranked) != len(ids) or set(ranked) != set(ids):
            return items
        by_id = {item.item_id: item for item in items}
        # Ranker output is queue order for SessionService.pop(); planner models
        # expose the more natural first-served order.
        return [by_id[item_id] for item_id in reversed(ranked)]

    def snapshot(self, now: int | float | None = None) -> DailyPlanSnapshot:
        captured_at = int(datetime.now().timestamp() if now is None else now)
        day_start, day_end = _local_day_bounds(captured_at)
        read_transaction = getattr(self.repo, "read_transaction", None)
        read_scope = read_transaction() if callable(read_transaction) else nullcontext()
        with read_scope:
            inventory = list(
                self.repo.planner_inventory(captured_at, cooldown_hours=12)
            )
            usage_rows = list(self.repo.daily_plan_usage(day_start, day_end))
        usage = {
            objective: DailyPlanUsage(objective, 0, 0, 0)
            for objective in OBJECTIVES
        }
        for row in usage_rows:
            if row.objective in usage:
                usage[row.objective] = row

        ready = {
            objective: {"due": [], "new": []}
            for objective in OBJECTIVES
        }
        for item in inventory:
            if item.objective in ready and item.bucket in {"due", "new"}:
                ready[item.objective][item.bucket].append(item)

        caps = self._caps()
        completed_total = sum(row.completed for row in usage.values())
        goal = _bounded_int(getattr(self.settings, "daily_goal", 30), 30, 0, 200)
        remaining_goal = max(0, goal - completed_total)
        due_demand = {
            objective: min(
                len(ready[objective]["due"]),
                max(0, caps[objective].due_cap - usage[objective].due),
            )
            for objective in OBJECTIVES
        }
        new_demand = {
            objective: min(
                len(ready[objective]["new"]),
                max(0, caps[objective].new_cap - usage[objective].new),
            )
            for objective in OBJECTIVES
        }
        weights = {objective: caps[objective].weight for objective in OBJECTIVES}
        objective_allocation = _allocate_slots(
            {
                objective: due_demand[objective] + new_demand[objective]
                for objective in OBJECTIVES
            },
            weights,
            remaining_goal,
        )
        due_allocation = {
            objective: min(due_demand[objective], objective_allocation[objective])
            for objective in OBJECTIVES
        }
        new_allocation = {
            objective: min(
                new_demand[objective],
                objective_allocation[objective] - due_allocation[objective],
            )
            for objective in OBJECTIVES
        }

        selected: dict[str, list[PlannerInventoryItem]] = {}
        objective_rows: list[ObjectivePlan] = []
        for objective in OBJECTIVES:
            due_items = self._rank(objective, ready[objective]["due"])[
                : due_allocation[objective]
            ]
            new_items = self._rank(objective, ready[objective]["new"])[
                : new_allocation[objective]
            ]
            selected[objective] = [*due_items, *new_items]
            objective_rows.append(
                ObjectivePlan(
                    objective=objective,
                    completed=usage[objective].completed,
                    completed_due=usage[objective].due,
                    completed_new=usage[objective].new,
                    ready_due=len(ready[objective]["due"]),
                    ready_new=len(ready[objective]["new"]),
                    planned_due=len(due_items),
                    planned_new=len(new_items),
                    backlog_due=len(ready[objective]["due"]) - len(due_items),
                    backlog_new=len(ready[objective]["new"]) - len(new_items),
                )
            )

        session_limit = _bounded_int(
            getattr(self.settings, "session_limit", 30), 30, 1, 100
        )
        pending_segments: list[
            tuple[str, int, str, str, int, tuple[int, ...], int, int]
        ] = []
        for objective in OBJECTIVES:
            cohorts: dict[tuple[int, str, str, int], list[PlannerInventoryItem]] = {}
            for item in selected[objective]:
                key = (
                    item.deck_id,
                    item.level,
                    item.book_slug,
                    item.lektion_number,
                )
                cohorts.setdefault(key, []).append(item)
            for (deck_id, level, book_slug, lektion_number), items in cohorts.items():
                for offset in range(0, len(items), session_limit):
                    chunk = items[offset : offset + session_limit]
                    pending_segments.append(
                        (
                            objective,
                            deck_id,
                            level,
                            book_slug,
                            lektion_number,
                            tuple(item.item_id for item in chunk),
                            sum(item.bucket == "due" for item in chunk),
                            sum(item.bucket == "new" for item in chunk),
                        )
                    )
        total_segments = len(pending_segments)
        segments = tuple(
            PlanSegment(
                objective=values[0],
                deck_id=values[1],
                level=values[2],
                book_slug=values[3],
                lektion_number=values[4],
                item_ids=values[5],
                due_count=values[6],
                new_count=values[7],
                ordinal=index,
                total_segments=total_segments,
            )
            for index, values in enumerate(pending_segments, start=1)
        )
        return DailyPlanSnapshot(
            captured_at=captured_at,
            day_start=day_start,
            day_end=day_end,
            goal=goal,
            completed_total=completed_total,
            planned_total=sum(row.planned for row in objective_rows),
            ready_due=sum(row.ready_due for row in objective_rows),
            ready_new=sum(row.ready_new for row in objective_rows),
            backlog_due=sum(row.backlog_due for row in objective_rows),
            backlog_new=sum(row.backlog_new for row in objective_rows),
            objectives=tuple(objective_rows),
            segments=segments,
        )

    def revalidate_segment(
        self,
        segment: PlanSegment,
        now: int | float | None = None,
    ) -> PlanSegment | None:
        if not isinstance(segment, PlanSegment):
            return None
        snapshot = self.snapshot(now=now)
        cohort = (
            segment.objective,
            segment.deck_id,
            segment.level,
            segment.book_slug,
            segment.lektion_number,
        )
        requested = tuple(dict.fromkeys(segment.item_ids))
        matching = []
        for current in snapshot.segments:
            current_cohort = (
                current.objective,
                current.deck_id,
                current.level,
                current.book_slug,
                current.lektion_number,
            )
            if current_cohort == cohort:
                matching.append(current)
        chosen = next(
            (
                current
                for item_id in requested
                for current in matching
                if item_id in current.item_ids
            ),
            None,
        )
        if chosen is None:
            return None
        available = {
            item_id: "due" if index < chosen.due_count else "new"
            for index, item_id in enumerate(chosen.item_ids)
        }
        kept = tuple(item_id for item_id in requested if item_id in available)
        if not kept:
            return None
        return PlanSegment(
            objective=segment.objective,
            deck_id=segment.deck_id,
            level=segment.level,
            book_slug=segment.book_slug,
            lektion_number=segment.lektion_number,
            item_ids=kept,
            due_count=sum(available[item_id] == "due" for item_id in kept),
            new_count=sum(available[item_id] == "new" for item_id in kept),
            ordinal=chosen.ordinal,
            total_segments=chosen.total_segments,
        )
