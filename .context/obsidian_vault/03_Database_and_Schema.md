# Database and Schema

MAHIRA persistence is centered in `src/db/`, with SQLite as the single source of learner truth.

## `src/db/` structure intent
- connection lifecycle (open/close/PRAGMA setup)
- repository functions for cards, decks, sessions, profiles, mistakes
- migration orchestration
- migration rollback safety via backups
- profile and settings persistence

## SQLite model
- Local file database inside `.mahira/`
- normalized tables for vocab/items, sessions, scheduling state, deck metadata, and user settings
- explicit indexes where query paths are frequent (e.g., due queue lookups, deck selectors)

## Schema v4 planner accounting
- Each primary review table stores `selection_bucket`: `new`, `due`, `extra`,
  or `legacy`.
- `new` and `due` are classified from the persisted pre-review scheduler state;
  ineligible, cooldown, or off-plan attempts are `extra`. Older/Lab events remain
  `legacy` and never consume planner caps.
- The review event, bucket, and FSRS state update commit in one immediate
  transaction. Undo deletes that exact event and restores only an unchanged
  post-review state.
- `daily_plan_usage()` counts checked, non-skipped, exact primary lanes inside
  one half-open local calendar day. See [[02_Core_Engine_and_ML]] and
  [[07_Development_Safety_Invariants]].

## Backup-first migration pattern
Before applying schema changes:
1. copy DB to backup location (timestamped in `.mahira/`)
2. run migration transaction
3. verify success
4. keep rollback artifact if anything fails

This pattern prevents destructive upgrade behavior and supports support recovery without cloud dependency.

## Learner profiles
- Profiles partition learning contexts
- scheduling and progress views are profile-scoped
- profile settings can alter review behavior, daily caps, and deck visibility

## German verb paradigm expansion (`german_verbs.sqlite`)
- An internal asset (`german_verbs.sqlite`) is expanded at import-time into six-person forms
- This enrichment layer avoids runtime API dependence and stabilizes conjugation exercises
- Expansion writes derived forms to local structures so all conjugation pages operate deterministically

Relevant code paths are consumed by:
- [[02_Core_Engine_and_ML]]
- [[04_UI_and_Frontend]]
- [[05_Folder_Driven_Seed_System]]
- [[07_Development_Safety_Invariants]]

See also: migration discipline and backup workflow details in [[06_CI_CD_and_Packaging]].
