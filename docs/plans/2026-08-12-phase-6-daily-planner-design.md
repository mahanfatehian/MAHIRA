# Phase 6 Daily Planner Design

**Date:** 2026-08-12

**Status:** Approved for implementation

**Theme:** Make Today a truthful, load-aware planner without replacing MAHIRA's existing review engines.

## Goal

Phase 6 gives learners one home screen that turns ready work into a bounded daily plan. The plan must enforce daily due/new limits, optionally balance work across objectives, explain overload, and agree with Progress. It must preserve the existing objective-specific review pages, FSRS updates, undo, targeted drills, and crash-safe session resume.

The definition of done is:

- Today selects only work that fits the remaining daily plan.
- Per-objective due and new caps are enforced across repeated app sessions.
- Today and Progress use the same eligibility and calendar-day rules.
- A streak advances only after genuine primary review work.
- Existing manual review, Lab, drill, resume, profile, and seed invariants remain intact.

## Chosen Approach

Use a dynamic daily planner backed by durable review classification.

Rejected alternatives:

1. Deriving due/new usage from existing state after a review is unreliable because FSRS has already changed that state.
2. Persisting a complete cross-objective itinerary duplicates queue state and introduces another recovery protocol.
3. Interleaving heterogeneous item IDs in one queue breaks the current single-objective page, undo, and resume contracts.

The planner therefore recomputes its itinerary from current database state whenever Today or Progress refreshes. It emits homogeneous segments for one objective and one deck at a time. An existing review-session checkpoint remains the only durable unfinished queue.

## Workload Semantics

### Global target and hard caps

- `daily_goal` is the maximum number of primary reviews recommended by Today's plan for the local calendar day.
- Every objective has an independent daily due cap and daily new cap.
- Default due cap: 30 per objective.
- Default new cap: the existing `new_card_limit` value, initially 8 per objective.
- Existing `session_limit` remains the maximum size of one focused segment.
- Caps limit Today's recommended selection; they never mutate due dates, bury cards, create decks, or delete work.
- Explicit manual practice remains available. Genuine manual due/new answers consume the same daily usage, so Today and Progress immediately adjust rather than recommending duplicate load.

### Eligible buckets

The planner has one canonical eligibility policy shared with Progress:

- **Due:** an existing primary state with `due_at <= now`, whose last review is outside the existing 12-hour cooldown.
- **New:** an active item with no scheduler state.
- **Extra:** a seen item that is not currently due. Extra work is never selected by Today.
- Suspended or currently buried items are excluded from every bucket.
- Lab production/dictation lanes are excluded.
- Future timestamps and stale item/deck references are rejected during segment preflight.

### Allocation

1. Capture one `now` and local-day interval for the entire snapshot.
2. Subtract today's committed due/new usage and all genuine primary reviews from the relevant caps and global goal.
3. Clamp each objective by its remaining hard caps and current eligible demand.
4. Allocate the remaining global target across objectives with deterministic largest-remainder rounding.
5. With custom balance disabled, use equal objective weights.
6. With custom balance enabled, use the learner's positive integer weights.
7. Redistribute unused shares to objectives that still have eligible demand, without crossing hard caps.
8. Within an objective, select due before new.
9. Rank cards with the existing deterministic priority/ML path where available; listening receives a deterministic fallback.
10. Divide the result into objective-and-deck-homogeneous segments no larger than `session_limit`.

Tie-breaking is stable by objective order, urgency, context, and item ID so identical database state produces the same plan.

### Overload

Today distinguishes:

- **Backlog overload:** ready due work exceeds today's remaining caps or global goal. Excess cards remain due and are shown as later work.
- **Segment overload:** the planned workload needs more than one focused set because of `session_limit`, objective, or deck boundaries.

Example copy: `47 due - today's plan covers 30 in 3 focused sets. The rest stays ready for later.`

No split operation changes seed content, deck ownership, scheduler state, or due dates.

## Durable Accounting and Migration

Phase 6 introduces schema version 4. Before upgrading an existing profile database, MAHIRA must create and verify the normal pre-migration backup, then apply the migration transactionally and run integrity and foreign-key checks.

Each primary review table gains a `selection_bucket` value:

- `new`
- `due`
- `extra`
- `legacy`

Existing rows use `legacy`; Phase 6 does not guess historical due/new state. Legacy primary reviews still count toward daily activity and the global goal, but not toward a fabricated due/new breakdown.

The bucket is classified immediately before the scheduler update and written atomically with the review event and state change. All primary paths use this rule, including targeted drills and manual practice. Lab rows remain outside planner accounting.

Daily cap usage counts committed, checked, non-skipped primary review events in the `due` and `new` buckets. Incorrect answers count because they are genuine work. Skips do not create review events and do not count. Undo deletes the exact review event, so both activity and cap usage reverse naturally.

Review insertion returns its exact row ID. The undo record stores that ID and deletes only that event, preventing another process's later review of the same card from being removed accidentally.

Existing `created_at` indexes are sufficient for the expected local history size; Phase 6 does not add speculative indexes.

## Genuine Session and Streak Rules

An active study day is a local calendar day containing at least one surviving, committed, checked, non-skipped primary review event.

- Correct and incorrect answers count.
- Targeted primary mistake drills count.
- Opening MAHIRA, creating a queue, displaying a card, abandoning a session, or skipping does not count.
- Vocab Lab production and dictation do not count.
- Undoing the only qualifying event removes that active day.
- The daily goal is not required to preserve a streak; goal completion is displayed separately.

Activity aggregation uses one repository-owned `UNION ALL` query with an exact practice-mode whitelist for all four objectives. A query failure must not silently return a plausible partial streak.

Calendar grouping follows the device's current local timezone, matching existing MAHIRA behavior. Freezing historical days to a travel-time timezone is outside this phase.

## Core Boundaries

Add a small planner module with immutable read models:

- `ObjectiveCaps`
- `ObjectivePlan`
- `PlanSegment`
- `DailyPlanSnapshot`
- `DailyPlannerService`

Repository queries provide canonical inventory, eligible IDs, and local-day usage. Today and Progress consume the same `DailyPlanSnapshot` contract.

MainWindow owns user-facing routing and confirmation. It performs a non-mutating
segment preflight before it offers to replace unfinished work. If the learner
cancels, MainWindow changes neither context nor session state.

After that guard, `SessionService.start_planned_segment(...)` accepts one
precomputed homogeneous segment and:

1. revalidates the context, deck, item ownership, caps, and bucket eligibility;
2. rejects an unexpected unfinished session rather than replacing it implicitly;
3. applies the already-approved context;
4. replaces the queue with the surviving ordered IDs;
5. checkpoints it through the normal primary review resume path.

If every ID became stale, the request fails without changing context, queue, or checkpoint. A planned segment never uses the temporary mistake-drill session kind.

No new itinerary file or planner-session table is introduced. Crossing a process restart relies on the existing primary review snapshot. After every committed answer, reopening Today recomputes the remaining plan from durable events.

## Settings

The existing atomic settings JSON gains validated mappings for:

- due caps by objective;
- new caps by objective;
- objective weights;
- custom balance enabled/disabled.

Unknown objectives are ignored, missing objectives receive defaults, booleans are not accepted as integers, caps are clamped to documented ranges, and weights must be finite positive integers. Corrupt settings continue to fall back safely through the existing atomic-load contract.

Planner preferences follow the existing global study-settings scope in Phase 6. Refactoring all study preferences to per-profile storage belongs to the later profiles/goals phase.

## Today UX

Today gains a compact `Today's plan` card ahead of recommendations and mistakes:

- completed versus planned total;
- ready workload;
- one row per objective with completed/planned and due/new composition;
- explicit backlog text;
- segment count when work must be split;
- `Start next set` as the primary action;
- `Adjust plan...` for caps and optional custom weights.

The adjustment UI is a dialog rather than eight inline controls, preserving compact layouts and 130% text scaling. Saving it updates the persistent planner defaults in the existing settings file; Phase 6 does not add a separate date-scoped override. Controls have keyboard access and accessible names. The existing stepper pattern should become a reusable widget rather than being copied.

Direct objective actions request that objective's next valid planned segment. They do not open a normal full-deck queue behind global counts.

When a planned segment finishes, the completion state offers a return to Today. Automatic cross-page switching is deliberately excluded.

## Progress UX

Progress displays the same global Today-plan summary from the same planner snapshot. Existing deck-specific statistics are labeled `Current lesson`.

- `Reviewed (24h)` becomes `Reviewed today` where it is compared with Today's goal.
- `Due now` becomes `Ready now` and uses the same cooldown, burial, suspension, and local-time policy as the planner.
- Global plan totals and current-lesson subsets are visually and textually distinct.

Refreshing Today and Progress with the same database state and `now` must produce identical global totals.

## Failure and Recovery Rules

- Planner reads never mutate scheduling or seed content.
- Backup failure aborts schema migration before writes.
- Invalid settings fall back to bounded defaults.
- Stale segment requests fail before unfinished work is discarded.
- Canceling an unfinished-session confirmation performs no mutation.
- Failed review submission retains the current item and does not consume a cap.
- Successful submission atomically advances FSRS, records the review bucket, and updates derived planner usage.
- Undo restores scheduler state and removes the exact review event.
- Profile databases, backups, activity, and resume checkpoints remain isolated.

## Test Strategy

Implementation is test-first. Required coverage includes:

### Planner and selection

- all four objectives and multiple deck contexts;
- due/new separation and due-before-new ordering;
- no future, buried, suspended, or foreign items;
- remaining daily caps across repeated sessions and restart;
- global goal ceiling;
- equal and custom weights;
- deterministic rounding and empty-lane redistribution;
- segment size/context/objective invariants;
- overload and zero-work states;
- stale-request preflight without mutation.

### Accounting and migration

- schema 3 to 4 verified backup and round trip;
- existing review/history preservation;
- atomic bucket/event/state writes;
- primary manual and targeted paths count;
- Lab lanes do not count;
- wrong answers count and skips do not;
- exact-event undo, including interleaved same-item reviews;
- local-midnight reset and legacy-row behavior.

### Today, Progress, and routing

- identical snapshots and labels;
- normal, empty, backlog, and multi-segment states;
- settings validation and persistence;
- keyboard/accessibility behavior and enlarged text;
- unfinished-session cancel/confirm ordering;
- crash-safe planned segment resume;
- end-to-end `Today -> review -> Progress` agreement.

The full suite, source compilation, seed validation, migration safety tests, and independent adversarial review must pass before completion.

## Commit Boundaries

After this design commit, implementation should remain within four focused commits:

1. `fix: harden review activity` - exact lane aggregation and exact-event undo.
2. `feat: add daily planner` - schema v4 classification, planner settings, inventory, allocation, and tests.
3. `feat: start planned sets` - segment preflight, queue integration, resume/routing safety, and tests.
4. `feat: show daily plan` - Today, Progress, adjustment UI, accessibility, documentation, and end-to-end tests.

## Out of Scope

- a heterogeneous cross-objective queue;
- automatic page switching between objectives;
- persistent full-day itineraries;
- profile-scoped planner preferences;
- historical due/new backfill;
- Lab streak credit;
- frozen write-time timezone identity;
- FSRS presets, gates, or the later profiles/goals phase.
