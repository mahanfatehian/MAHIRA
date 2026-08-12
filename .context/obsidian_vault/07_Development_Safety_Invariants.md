# Development Safety Invariants

Phase 0 freezes the contracts that later phases depend on. A change is safe to merge only when these invariants still hold and the regression gates below pass.

## Five non-negotiable invariants

### 1. Practice lanes stay isolated

- Recognition scheduling uses the objective state tables: `vocab_states`, `grammar_states`, `sentence_states`, and `listening_states`.
- Vocabulary Lab production/dictation schedules use `vocab_practice_states`; their event rows carry a non-recognition `practice_mode`.
- Lab activity must not move recognition due dates, mastery, review counts, or undo state.
- Add or update `tests/test_practice_lane_isolation.py` whenever a query, review write, or new practice mode touches lane data.

See [[02_Core_Engine_and_ML]] and [[03_Database_and_Schema]].

### 2. Undo is one-deep, scoped, and atomic

- `SessionService` holds only the latest main-review snapshot.
- Undo restores the pre-review scheduler state, deletes only the matching review event, restores the session milestone counters, and requeues the card.
- Vocabulary review deletion defaults to `practice_mode='recognition'`; it must never delete production or dictation history.
- A failed undo keeps both database state and the snapshot unchanged so the learner can retry.
- A Lab submission clears stale recognition undo rather than crossing lanes.

Primary coverage: `tests/test_undo_reviews.py` and `tests/test_atomic_review_transactions.py`.

### 3. Due counts keep their stated meaning

- A raw due item has scheduler state with `due_at <= now` and is neither suspended nor actively buried.
- Unseen items are reported separately; they are not silently counted as due reviews.
- Today and Progress use `DailyPlannerService`, whose Ready now policy also
  excludes cards reviewed within the 12-hour cooldown.
- Current lesson counts are explicitly subsets and never presented as global
  planner totals.
- Vocabulary review totals, mastery, and 24-hour counts describe recognition unless a UI explicitly labels another lane.

Primary coverage: `tests/test_bury_actions.py` and `tests/test_practice_lane_isolation.py`. See [[04_UI_and_Frontend]].

## Phase 6 daily-planner guardrails

- Schema v4 stores `selection_bucket` (`new`, `due`, `extra`, or `legacy`)
  in the same transaction as each genuine primary review and scheduler update.
- Only exact checked/non-skipped primary modes consume the local-day global goal
  and per-objective caps. Incorrect answers count; skips and Lab lanes do not.
- Planner snapshots are read-only and recomputed from current DB/settings state.
  They never bury cards, change due dates, or persist a second itinerary.
- Every segment contains one objective and one seeded deck and is capped by
  `session_limit`; heterogeneous queues are forbidden.
- Segment preflight happens before unfinished-session replacement. Stale work
  fails closed, Cancel mutates nothing, and accepted work uses the ordinary
  crash-safe review checkpoint.
- Today and Progress must display the same snapshot semantics and local calendar
  day. Current lesson Reviewed today uses half-open day bounds and exact lanes.

Primary coverage: `tests/test_daily_planner.py`,
`tests/test_review_selection_buckets.py`, `tests/test_planned_sessions.py`,
`tests/test_today_planner_ui.py`, and
`tests/test_progress_planner_consistency.py`.

### 4. The review cooldown does not rewrite memory

- Repository `pick_session_*` selectors and Progress use a 12-hour cooldown to suppress just-reviewed cards from due-only work.
- `SessionService.start_new_session()` is a separate recall-priority mixed-deck path: it ranks every eligible card and dampens recent reviews instead of applying a hard cooldown.
- Cooldown filters on `last_review_at`; it does not alter FSRS `due_at`, erase events, or create a second schedule.
- After the window expires, an otherwise due card becomes selectable again.
- Callers needing raw scheduler truth may pass a zero cooldown explicitly; UI labels must not present that value as session-ready.
- Do not switch a path between hard cooldown and priority damping without updating `tests/test_selection.py` and `tests/test_bury_actions.py`.

See [[02_Core_Engine_and_ML]].

### 5. Mutable state lives outside the app bundle

- Bundled code, seeds, pages, models, and schema are read-only resources resolved from `resource_root()`.
- Databases, settings, profiles, logs, backups, and learned ML artifacts live below the writable `.mahira/` state directory returned by `get_paths()`.
- Source runs place `.mahira/` under the repository data root; frozen builds use the platform's per-user application-data root.
- Upgrades and uninstall operations must not depend on or delete writable learner state inside a PyInstaller bundle.
- Core study, review, backup, and audio playback paths remain usable without a network connection.

See [[01_Architecture_and_Stack]], [[03_Database_and_Schema]], and [[06_CI_CD_and_Packaging]].

## Persistence guardrails

- A review event and its scheduler update commit in one repository transaction.
- Seed packs validate fully before database access. Planning is read-only;
  changed batches require one verified backup and one all-or-nothing
  transaction.
- Seed refreshes preserve IDs/history only for exact or unambiguous one-to-one
  matches. Ambiguous replacements fail safe as remove/add, and unchanged deck
  hashes never rewrite rows.
- Optional book manifests are read-only resource metadata. Missing or invalid
  manifests must retain folder titles/order and conventional-cover fallbacks.
- Primary review continuity is recognition-only, versioned, and profile-scoped. Default and named profiles must never share `active_session.json`.
- The displayed card is persisted separately from the remaining LIFO queue; otherwise restart silently skips it.
- Continue validates deck identity, seed SHA, item ownership, and the displayed card's pre-review state token. Invalid/stale checkpoints fail closed and never block startup.
- A failed review write leaves the same checkpoint retryable. If SQLite committed before JSON advanced, state-token reconciliation skips the already-rated card.
- Deck/context/profile changes, explicit Discard, and session completion remove the checkpoint. Undo and Practice Lab queues remain non-persistent by design.
- Schema upgrades are transactional, reject future schema versions, and create an integrity-checked backup before changing an existing older database.
- Legacy rebuilds checkpoint WAL, migrate through a temporary database, verify copied rows and foreign keys, then replace the original.
- `tests/test_migration_backup_roundtrip.py` proves the pre-migration backup can restore the old database and that the restored file can be upgraded again without losing learner data.
- `tests/test_session_resume_store.py`, `tests/test_session_continuity.py`, and `tests/test_session_resume_ui.py` lock the checkpoint, cold-restart, reconciliation, and Continue/Discard contracts.

## Phase 5 mistake-remediation guardrails

- Recent failures come from persisted effective `rating=0` review events. Queries preserve the exact `(objective, practice_mode)` lane, require all three lesson fields `(level, book_slug, lektion_number)` together, use exact normalized tag tokens, and apply these filters before `limit`.
- A leech is three or more failures in that same lane within the inclusive trailing 30-day window. It may suggest bury/suspend and an exact Learn rule, but must never mutate card controls automatically.
- Learn links are allow-listed only for unambiguous tags and open only when the curriculum index finds one unique `(level, order_token)` match. Unknown/ambiguous tags and zero or multiple lesson matches fail closed.
- Targeted drills contain only revalidated IDs from the existing seeded deck. Do not clone content, create a permanent drill deck, or allow suspended/future-buried/foreign IDs into the queue.
- Preflight a targeted request without changing state before offering to replace any unfinished session. Cancel is the default; a stale request must never show the replacement dialog or clear its checkpoint.
- Targeted primary and Practice Lab queues are intentionally process-local and non-resumable; `active_session.json` remains reserved for normal primary review continuity.
- Primary drills update their objective's normal lane. Vocabulary production/dictation drills update `vocab_practice_states` and explicit Lab event modes; recognition due state, totals, undo, and `sklearn_ranker` features remain isolated.

Primary coverage: `tests/test_recent_failures.py`, `tests/test_targeted_drills.py`, `tests/test_mistakes_ui.py`, `tests/test_mistake_drill_routing.py`, `tests/test_learn_reference_resolution.py`, and `tests/test_ml_lane_isolation.py`. See [[02_Core_Engine_and_ML]] and [[04_UI_and_Frontend]].

## Phase 0 regression gates

Run from the repository root with the project virtual environment:

```powershell
.\venv\Scripts\python.exe -m compileall -q src
.\venv\Scripts\python.exe -m pytest -m "not slow" --timeout=60 -q
.\venv\Scripts\python.exe -m pytest --timeout=120 -q
```

The fast command mirrors `.github/workflows/tests.yml`; the full command also loads the locally available semantic model tests.

The UI smoke gate is `tests/test_review_smoke_path.py`. It constructs the real `MainWindow` and a temporary SQLite learner profile, then follows this path:

`Today -> Vocabulary review -> check and rate one card -> Progress`

It must prove that one review is persisted and visible on Progress. This is a wiring test, not a replacement for focused unit tests.

## Safe handoff rule

Before starting the next roadmap phase:

1. Keep all five invariants true or deliberately revise their documentation and tests in the same change.
2. Run the complete suite with a clean result.
3. Leave no half-wired UI route, migration format, or feature flag behind.
4. Keep each independent behavior change in its own commit.

Return to [[00_MAHIRA_Index]].
