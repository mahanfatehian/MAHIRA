# Phase 6 Daily Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Today into a durable, load-aware planner that enforces daily due/new caps, creates safe objective-specific sets, and reports identical calendar-day progress on Today and Progress.

**Architecture:** Add schema-v4 review classification and a pure `DailyPlannerService` that recomputes one immutable snapshot from SQLite and validated settings. The planner allocates a global goal across objective/deck-homogeneous `PlanSegment` values; MainWindow preflights one segment before the existing single-objective `SessionService` checkpoints it as an ordinary review.

**Tech Stack:** Python 3.11+, SQLite, PySide6, pytest, existing FSRS/priority and atomic settings infrastructure.

## Global Constraints

- Work on branch `daily_planner`; do not push.
- Keep the existing single-objective queue, review pages, FSRS updates, targeted drills, Lab lane isolation, undo depth, seed IDs, and profile database isolation.
- `daily_goal` is the global Today ceiling; per-objective due/new caps are hard ceilings; due is allocated before new.
- Eligibility uses `due_at <= now`, the existing 12-hour cooldown, suspension, and burial; future seen cards and Lab lanes are excluded.
- Equal weights apply when custom weighting is off; positive integer objective weights use deterministic largest-remainder allocation and redistribute empty-lane shares.
- A streak day needs one surviving checked, non-skipped primary review. Incorrect answers and primary drills count; app opens, abandoned queues, skips, and vocab Lab do not.
- Schema upgrades are version 4, verified-backup-first, transactional, integrity checked, and preserve every existing review row as `legacy`.
- Planner reads never mutate content, decks, scheduling state, or due dates.
- Validate before confirmation; cancel or stale requests must not mutate context, queues, or checkpoints.
- Use red-green TDD for every behavior. Keep implementation changes in exactly four focused commits after this plan: `fix: harden review activity`, `feat: add daily planner`, `feat: start planned sets`, and `feat: show daily plan`.

---

## File Structure

- Create `src/core/planner.py`: immutable planner models, weighted allocation, snapshot building, and segment revalidation.
- Create `src/ui/widgets/number_stepper.py`: reusable accessible integer stepper extracted from Settings.
- Create `src/ui/widgets/daily_plan_dialog.py`: persistent cap/weight editor.
- Modify `src/db/schema.sql`: add `selection_bucket` to all four primary review logs.
- Modify `src/db/init_db.py`: schema version 4, backup-first additive migration, migration description.
- Modify `src/db/repo.py`: exact review IDs/deletion, activity aggregation, planner inventory and usage queries.
- Modify `src/core/settings.py`: validated per-objective caps, weights, and custom-balance flag.
- Modify `src/core/session.py`: atomic selection classification, exact undo, planned-segment preflight/start.
- Modify `src/core/insights.py`: delegate Today/global activity counts to the canonical planner/activity boundary where applicable.
- Modify `src/ui/pages/today.py`: render and launch the daily plan.
- Modify `src/ui/pages/progress.py`: render the same snapshot and calendar-day/current-lesson labels.
- Modify `src/ui/pages/settings.py`: reuse `NumberStepper` and clarify manual-session limits.
- Modify `src/ui/main_window.py`: safe planned-segment routing and plan refresh wiring.
- Modify the four primary review pages: offer a Today return path at completion.
- Add focused tests named below; extend existing migration, activity, undo, continuity, settings, and UI suites.

---

### Task 1: Harden Primary Activity and Exact Undo

**Files:**
- Modify: `src/db/repo.py`
- Modify: `src/core/session.py`
- Modify: `tests/test_activity_lane_isolation.py`
- Modify: `tests/test_undo_reviews.py`
- Modify: `tests/test_atomic_review_transactions.py`

**Interfaces:**
- Produces: all four `Repo.insert_*_review(...) -> int` methods return the inserted row ID.
- Produces: `Repo.delete_review_event(objective: str, review_id: int, item_id: int, practice_mode: str) -> None` deletes exactly one matching event or raises.
- Produces: `Repo.daily_review_counts(since_ts: int, until_ts: int | None = None) -> dict[str, int]` counts exact primary lanes with `was_checked=1` and `was_skipped=0` in a half-open interval.
- Produces: `SessionService._undo['review_id']` identifies the exact event to reverse and `post_state_token` guards the matching scheduler state.

- [ ] **Step 1: Write failing exact-lane activity tests**

Add real review rows for `recognition`, `production`, `builder`, and `comprehension`, plus wrong future modes in every table. Assert only checked, non-skipped whitelisted rows count and that `until_ts` excludes an event exactly at the upper boundary.

```python
def test_activity_counts_only_checked_primary_lanes(repo):
    # Fixtures insert one valid primary event per table, plus unchecked,
    # skipped, Lab, and unknown-mode rows at literal timestamps.
    assert repo.daily_review_counts(100, 200) == {"1970-01-01": 4}
```

- [ ] **Step 2: Verify the activity tests fail for the current permissive aggregation**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_activity_lane_isolation.py -q`

Expected: FAIL because grammar/sentence/listening future modes and unchecked rows are currently counted.

- [ ] **Step 3: Implement one exact `UNION ALL` activity query**

Use fixed table/mode SQL branches, half-open timestamps, and one outer local-day grouping. Do not catch arbitrary SQLite exceptions or return partial results.

```python
PRIMARY_REVIEW_LANES = (
    ("reviews", "recognition"),
    ("grammar_reviews", "production"),
    ("sentence_reviews", "builder"),
    ("listening_reviews", "comprehension"),
)
```

- [ ] **Step 4: Write failing interleaved-event undo tests**

Submit one review through Session A, then insert a later same-item review through Session B. Assert A's stale undo is refused, both event history and B's newer scheduler state remain unchanged, and A retains its undo snapshot for a safe retry/clear decision. Also assert an uncontended undo deletes A's exact event and restores A's prior state. Cover all four objectives through a table-driven fixture.

- [ ] **Step 5: Verify the undo tests fail because deletion currently targets the latest item row**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_undo_reviews.py -q`

Expected: FAIL with the later event missing, the newer scheduler state overwritten, or the wrong event retained.

- [ ] **Step 6: Return insert IDs and delete exact events atomically**

Capture `cursor.lastrowid`, store it only for non-skipped submissions, and store a token for the state written by that submission. Inside the undo `BEGIN IMMEDIATE` transaction, compare the current state token with the recorded post-state token before deleting/restoring anything. A changed state, missing/mismatched event, or failed delete raises so the transaction rolls back and the undo snapshot remains available.

```python
_REVIEW_EVENT_SPECS = {
    "vocab": ("reviews", "vocab_id", "recognition"),
    "grammar": ("grammar_reviews", "grammar_id", "production"),
    "sentence": ("sentence_reviews", "sentence_id", "builder"),
    "listening": ("listening_reviews", "listening_id", "comprehension"),
}
```

- [ ] **Step 7: Run focused and transaction regressions**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_activity_lane_isolation.py tests/test_undo_reviews.py tests/test_atomic_review_transactions.py tests/test_lane_undo_boundaries.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```powershell
git add src/db/repo.py src/core/session.py tests/test_activity_lane_isolation.py tests/test_undo_reviews.py tests/test_atomic_review_transactions.py
git commit -m "fix: harden review activity"
```

---

### Task 2: Add Durable Classification and the Daily Planner Engine

**Files:**
- Create: `src/core/planner.py`
- Modify: `src/db/schema.sql`
- Modify: `src/db/init_db.py`
- Modify: `src/db/repo.py`
- Modify: `src/core/settings.py`
- Modify: `src/core/session.py`
- Add: `tests/test_daily_planner.py`
- Add: `tests/test_review_selection_buckets.py`
- Modify: `tests/test_safety_and_settings.py`
- Modify: `tests/test_database_migration_safety.py`
- Modify: `tests/test_migration_backup_roundtrip.py`

**Interfaces:**
- Produces in `db.repo`: `PlannerInventoryItem`, `DailyPlanUsage`, `Repo.planner_inventory(now: int, cooldown_hours: float = 12)`, and `Repo.daily_plan_usage(day_start: int, day_end: int)`.
- Produces in `core.planner`: `OBJECTIVES`, `ObjectiveCaps`, `ObjectivePlan`, `PlanSegment`, `DailyPlanSnapshot`, and `DailyPlannerService.snapshot(now: int | float | None = None)`.
- Produces: `DailyPlannerService.revalidate_segment(segment: PlanSegment, now: int | float | None = None) -> PlanSegment | None`.
- Produces settings: `planner_due_caps`, `planner_new_caps`, `planner_weights`, and `planner_weighted_mix`.
- Consumes Task 1 insert IDs without changing their return contract.

- [ ] **Step 1: Write failing schema-v4 migration tests**

Create a schema-v3 database containing one row in every review table. Run `init_db`, then assert version 4, all original IDs/data remain, each row has `selection_bucket='legacy'`, and the verified pre-schema backup exists. Inject backup failure and assert no column/version change.

- [ ] **Step 2: Verify migration tests fail at schema version 3**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_database_migration_safety.py tests/test_migration_backup_roundtrip.py -q`

Expected: FAIL because version 4 and `selection_bucket` do not exist.

- [ ] **Step 3: Add the additive schema-v4 columns and backup-first upgrade**

Add this constrained column to all four review table declarations and through `_ensure_column` inside the existing explicit transaction:

```sql
selection_bucket TEXT NOT NULL DEFAULT 'legacy'
  CHECK(selection_bucket IN ('new', 'due', 'extra', 'legacy'))
```

Set `SCHEMA_VERSION = 4`, keep `_COPY_ORDER` unchanged, and use migration description `classified primary reviews for the daily planner`.

- [ ] **Step 4: Write failing settings normalization tests**

Exercise missing keys, partial maps, aliases/unknown keys, booleans, strings, negative/oversized caps, zero/non-finite weights, and atomic round-trip. Hand-check expected normalized maps for all four objectives.

```python
assert value.planner_due_caps == {
    "vocab": 30, "grammar": 0, "sentences": 200, "listening": 30
}
```

- [ ] **Step 5: Verify settings tests fail because planner fields are absent**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_safety_and_settings.py -q`

Expected: FAIL with missing planner settings attributes.

- [ ] **Step 6: Implement safe mapping normalization**

Use `dataclasses.field(default_factory=...)`; accept only plain finite integral values, clamp due caps to `0..200`, new caps to `0..30`, weights to `1..100`, ignore unknown objective keys, and fill missing keys from defaults. `planner_weighted_mix` uses `_normalized_bool`.

- [ ] **Step 7: Write failing atomic review-classification tests**

For each objective, submit an item with no state (`new`), a state ready outside cooldown (`due`), and a future/recent state (`extra`). Assert the stored bucket, exact primary mode, and rollback when either event insert or state update fails. Assert Lab writes remain `legacy` and do not enter primary usage.

- [ ] **Step 8: Verify bucket tests fail because insert APIs have no bucket**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_review_selection_buckets.py tests/test_atomic_review_transactions.py -q`

Expected: FAIL with absent `selection_bucket` or incorrect default `legacy`.

- [ ] **Step 9: Classify before state mutation and write the bucket atomically**

Add one pure helper used by all primary submit paths:

```python
def classify_selection_bucket(state, *, now: int, cooldown_seconds: int = 43_200) -> str:
    if state is None:
        return "new"
    if state.due_at <= now and (
        state.last_review_at is None or state.last_review_at <= now - cooldown_seconds
    ):
        return "due"
    return "extra"
```

Capture `now` once per submit, classify the pre-review state before `ensure_*_state`, pass the bucket to the Task 1 insert method, and leave vocab Lab calls at `legacy`.

- [ ] **Step 10: Write failing inventory/usage tests**

Build two books, multiple lessons, all four objectives, due/new/future/recent/buried/suspended items, and review rows on both sides of local midnight. Assert canonical candidates, context fields, deterministic order, exact lane filters, completed totals, and due/new usage.

- [ ] **Step 11: Implement repository planner read models and fixed SQL**

```python
@dataclass(frozen=True)
class PlannerInventoryItem:
    objective: str
    item_id: int
    deck_id: int
    level: str
    book_slug: str
    lektion_number: int
    bucket: str  # due | new
    due_at: int | None

@dataclass(frozen=True)
class DailyPlanUsage:
    objective: str
    completed: int
    due: int
    new: int
```

Use fixed objective/table mappings, exact primary modes, state `id IS NULL` for new, and the same due/cooldown/suspension/burial predicate for every objective. The usage query is half-open `[day_start, day_end)` and includes `legacy`/`extra` in completed only.

- [ ] **Step 12: Write failing allocation and segmentation tests**

Cover a 30-card global goal; remaining per-objective caps; equal allocation; weights `4:2:1:1`; largest-remainder ties; empty-lane redistribution; due before new; zero caps; legacy/extra global consumption; multiple decks; `session_limit`; deterministic IDs; backlog totals; and no database mutation.

```python
assert [(row.objective, row.planned_due, row.planned_new) for row in plan.objectives] == [
    ("vocab", 4, 0), ("grammar", 2, 0), ("sentences", 1, 0), ("listening", 1, 0)
]
```

- [ ] **Step 13: Verify planner tests fail because the module/API is missing**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_daily_planner.py -q`

Expected: collection or assertion FAIL for the missing planner contract.

- [ ] **Step 14: Implement immutable planner models and deterministic allocation**

`PlanSegment.item_ids` is first-served order. Rank due/new IDs per objective through the existing ranker when supplied, then use stable urgency/item-ID fallback. Allocate total objective slots by iterative largest remainder; fill each objective from due first, group selected cards by `(objective, deck_id, level, book_slug, lektion_number)`, and chunk at `session_limit`.

```python
class DailyPlannerService:
    def __init__(self, repo, settings, *, ranker=None): ...
    def snapshot(self, now=None) -> DailyPlanSnapshot: ...
    def revalidate_segment(self, segment, now=None) -> PlanSegment | None: ...
```

Revalidation builds a fresh snapshot and retains requested IDs only while they remain in the same current planned cohort; it never writes.

- [ ] **Step 15: Run the complete backend planner/migration regression set**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_daily_planner.py tests/test_review_selection_buckets.py tests/test_safety_and_settings.py tests/test_database_migration_safety.py tests/test_migration_backup_roundtrip.py tests/test_atomic_review_transactions.py tests/test_activity_lane_isolation.py tests/test_practice_lane_isolation.py -q`

Expected: PASS.

- [ ] **Step 16: Commit Task 2**

```powershell
git add src/core/planner.py src/core/settings.py src/core/session.py src/db/schema.sql src/db/init_db.py src/db/repo.py tests/test_daily_planner.py tests/test_review_selection_buckets.py tests/test_safety_and_settings.py tests/test_database_migration_safety.py tests/test_migration_backup_roundtrip.py tests/test_atomic_review_transactions.py
git commit -m "feat: add daily planner"
```

---

### Task 3: Start Planned Sets Without Weakening Resume Safety

**Files:**
- Modify: `src/core/session.py`
- Modify: `src/ui/main_window.py`
- Add: `tests/test_planned_sessions.py`
- Add: `tests/test_planner_routing.py`
- Modify: `tests/test_session_continuity.py`
- Modify: `tests/test_session_resume_store.py`
- Modify: `tests/test_session_resume_ui.py`
- Modify: `tests/test_targeted_drills.py`

**Interfaces:**
- Consumes: Task 2 `PlanSegment` and `DailyPlannerService.revalidate_segment`.
- Produces: `SessionService.preview_planned_segment(segment: PlanSegment, now=None) -> PlanSegment | None`.
- Produces: `SessionService.start_planned_segment(segment: PlanSegment, now=None) -> bool`.
- Produces: `MainWindow._open_plan_segment(segment: PlanSegment) -> None`.
- Keeps: planned queues use `session_kind='review'` and the existing `SessionSnapshot` format.

- [ ] **Step 1: Write failing SessionService planned-set tests**

Assert preview is read-only; wrong types/context/deck/objective, foreign IDs, stale cap, future, buried, suspended, and changed seed content are rejected; input duplicates are removed; first requested ID is served first; global `SessionPlan` is unchanged; and an existing review/drill/resume candidate prevents replacement.

- [ ] **Step 2: Verify the planned-session tests fail because APIs are absent**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_planned_sessions.py -q`

Expected: FAIL for missing `preview_planned_segment`/`start_planned_segment`.

- [ ] **Step 3: Implement read-only preview and guarded start**

Preview constructs `DailyPlannerService(self.repo, self.settings.value, ranker=self.ml)` and returns its fresh revalidation. Start refuses `has_unfinished_session()`, previews again, resolves/compares the exact deck, validates active IDs, then sets a normal review queue as `list(reversed(segment.item_ids))`, resets position/total, and checkpoints normally.

- [ ] **Step 4: Write failing MainWindow route-order tests**

Use a strict fake session call log. Assert this order:

```python
[
    "preview_planned_segment",
    "has_unfinished_session",
    "confirm_if_needed",
    "discard_if_confirmed",
    "set_context",
    "start_planned_segment",
    "invalidate_review_pages",
    "show_objective_page",
]
```

Stale preview and Cancel must stop before discard/context mutation. A failed second preflight/start must show an error without silently opening a normal queue. Test all four objective destinations.

- [ ] **Step 5: Verify route tests fail before MainWindow wiring exists**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_planner_routing.py -q`

Expected: FAIL for missing route or mutation ordering.

- [ ] **Step 6: Implement MainWindow confirmation and routing**

Add a planner-specific error surface on Today and reuse the mistake-drill safety pattern with copy `Discard unfinished session and start today's set? Completed ratings stay saved.` Never call the legacy `_open_context_practice` path for planned work.

- [ ] **Step 7: Prove ordinary resume compatibility**

Start a planned segment, pop the visible item, persist the current item plus remaining LIFO queue, cold-load and Continue, and assert the exact same item/order. Assert completed review classification survives restart and a next Today snapshot does not select consumed work.

- [ ] **Step 8: Run planned routing, resume, and drill regressions**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_planned_sessions.py tests/test_planner_routing.py tests/test_session_continuity.py tests/test_session_resume_store.py tests/test_session_resume_ui.py tests/test_targeted_drills.py tests/test_mistake_drill_routing.py -q`

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```powershell
git add src/core/session.py src/ui/main_window.py tests/test_planned_sessions.py tests/test_planner_routing.py tests/test_session_continuity.py tests/test_session_resume_store.py tests/test_session_resume_ui.py tests/test_targeted_drills.py
git commit -m "feat: start planned sets"
```

---

### Task 4: Show One Truthful Plan on Today and Progress

**Files:**
- Create: `src/ui/widgets/number_stepper.py`
- Create: `src/ui/widgets/daily_plan_dialog.py`
- Modify: `src/ui/pages/settings.py`
- Modify: `src/ui/pages/today.py`
- Modify: `src/ui/pages/progress.py`
- Modify: `src/ui/main_window.py`
- Modify: `src/ui/pages/vocab_review.py`
- Modify: `src/ui/pages/grammar_review.py`
- Modify: `src/ui/pages/sentence_review.py`
- Modify: `src/ui/pages/listening_review.py`
- Modify: `src/core/insights.py`
- Add: `tests/test_today_planner_ui.py`
- Add: `tests/test_progress_planner_consistency.py`
- Add: `tests/test_daily_plan_dialog.py`
- Modify: `tests/test_feature_pages_ui.py`
- Modify: `tests/test_review_smoke_path.py`
- Modify: `tests/test_main_window_construction.py`
- Modify: `README.md`
- Modify: `.context/obsidian_vault/01_Architecture_and_Stack.md`
- Modify: `.context/obsidian_vault/04_UI_and_Frontend.md`
- Modify: `.context/obsidian_vault/07_Development_Safety_Invariants.md`

**Interfaces:**
- Produces: `NumberStepper(minimum, maximum, step, accessible_name)` with the existing `value`, `setValue`, `valueChanged`, `minus`, and `plus` contract.
- Produces: `DailyPlanDialog(settings_service, parent=None)` whose accepted save calls one atomic `SettingsService.update(...)`.
- Produces: `TodayPage.plan_segment_requested = Signal(object)` and `TodayPage.show_plan_error(message)`.
- Produces: `go_today = Signal()` on all four primary review pages.
- Consumes: identical Task 2 snapshot models on Today and Progress.

- [ ] **Step 1: Write failing reusable-stepper and dialog tests**

Assert bounds, keyboard/button changes, accessible names, initial values from settings, custom-weight visibility, invalid values impossible through controls, Cancel leaves disk unchanged, and Save writes all four complete maps atomically.

- [ ] **Step 2: Verify widget tests fail because the modules are absent**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_daily_plan_dialog.py -q`

Expected: collection FAIL for missing widgets.

- [ ] **Step 3: Extract `NumberStepper` and implement the planner dialog**

Move, do not copy, Settings' `_Stepper`; keep a private alias only if a compatibility test/import requires it. Use a scroll-safe two-column objective grid, a `Balance across skills` checkbox, and Due/New/Weight controls with the Task 2 ranges. Save persistent defaults through one `settings.update(...)` call.

- [ ] **Step 4: Write failing Today states and action tests**

With literal immutable snapshots, cover empty, normal, zero-cap, backlog overload, and multi-segment plans. Assert completed/planned, due/new rows, `N more due`, split copy, button enabled state, next-segment choice, objective action choice, plan dialog refresh, and emitted `PlanSegment` identity.

- [ ] **Step 5: Verify Today tests fail against the old global lane UI**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_today_planner_ui.py -q`

Expected: FAIL because Today still emits raw contexts and cannot show capped plan data.

- [ ] **Step 6: Replace misleading lane routing with the planner card**

Build one snapshot per `on_show`, render four objective rows from it, emit the first overall or objective segment, retain Mistakes/recommended-lesson secondary cards, and route adjustments through `DailyPlanDialog`. Do not mutate the planner, database, or global `SessionPlan` while rendering.

- [ ] **Step 7: Write failing Today/Progress agreement tests**

Freeze `now`, use one real repo/settings fixture, show both pages, and assert global reviewed/planned/ready totals match exactly. Assert Progress labels `Today's plan`, `Current lesson`, `Ready now`, and `Reviewed today`; the current-lesson subset must not be presented as global.

- [ ] **Step 8: Verify consistency tests fail on rolling-24-hour/raw-due labels**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_progress_planner_consistency.py -q`

Expected: FAIL on mismatched totals or labels.

- [ ] **Step 9: Render the canonical snapshot in Progress**

Use `DailyPlannerService` for the global plan summary and the same local-day boundary for current-lesson reviewed counts. Replace raw/rolling labels without deleting total review or mastery information. Update `InsightsService.lanes()` or callers so no Today/Progress path keeps a conflicting due definition.

- [ ] **Step 10: Add completion return and end-to-end smoke coverage**

Expose a Today button/signal on all four primary pages. On empty queue, keep `Session finished` and make Today the clear next action. Exercise `Today -> planned set -> checked answer -> Progress` with a real repo and assert the completed/bucket totals and streak activity agree.

- [ ] **Step 11: Run enlarged-text and construction regressions**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_today_planner_ui.py tests/test_progress_planner_consistency.py tests/test_daily_plan_dialog.py tests/test_feature_pages_ui.py tests/test_review_smoke_path.py tests/test_main_window_construction.py tests/test_navigation_cache.py -q`

Expected: PASS with no Qt warnings. Tests set font scale to 130%, construct compact pages, inspect accessible names, and exercise buttons via Qt signals rather than source text.

- [ ] **Step 12: Document the planner and invariants concisely**

README describes capped sequential sets and schema-v4 backup safety. The vault links Today/Progress to `core/planner.py`, documents review bucket semantics, exact primary lanes, and explicitly forbids heterogeneous queues or Lab streak credit.

- [ ] **Step 13: Run focused Phase 6 regression set**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_daily_planner.py tests/test_review_selection_buckets.py tests/test_planned_sessions.py tests/test_planner_routing.py tests/test_today_planner_ui.py tests/test_progress_planner_consistency.py tests/test_daily_plan_dialog.py tests/test_activity_lane_isolation.py tests/test_undo_reviews.py tests/test_session_resume_store.py tests/test_session_resume_ui.py tests/test_review_smoke_path.py -q`

Expected: PASS.

- [ ] **Step 14: Commit Task 4**

```powershell
git add src/ui/widgets/number_stepper.py src/ui/widgets/daily_plan_dialog.py src/ui/pages/settings.py src/ui/pages/today.py src/ui/pages/progress.py src/ui/main_window.py src/ui/pages/vocab_review.py src/ui/pages/grammar_review.py src/ui/pages/sentence_review.py src/ui/pages/listening_review.py src/core/insights.py tests/test_today_planner_ui.py tests/test_progress_planner_consistency.py tests/test_daily_plan_dialog.py tests/test_feature_pages_ui.py tests/test_review_smoke_path.py tests/test_main_window_construction.py README.md .context/obsidian_vault/01_Architecture_and_Stack.md .context/obsidian_vault/04_UI_and_Frontend.md .context/obsidian_vault/07_Development_Safety_Invariants.md
git commit -m "feat: show daily plan"
```

---

## Final Verification and Review

- [ ] Run the full suite: `venv\\Scripts\\python.exe -m pytest -q`.
- [ ] Compile source: `venv\\Scripts\\python.exe -m compileall -q src`.
- [ ] Validate content: `$env:PYTHONPATH='src'; venv\\Scripts\\python.exe -m mahira validate-seeds`.
- [ ] Run `git diff --check` and confirm `git status --short` is clean.
- [ ] Re-read `docs/plans/2026-08-12-phase-6-daily-planner-design.md` and map every requirement to code/tests.
- [ ] Request an ultra whole-branch review from the merge base through HEAD; fix all Critical/Important findings in one reviewed fix wave.
- [ ] Use `superpowers:finishing-a-development-branch` and leave `daily_planner` ready for the user to push or merge.
