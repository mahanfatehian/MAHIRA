# UI and Frontend

## `src/ui/pages/`
Page modules represent major user workflows:
- Today / review queue
- Mistake notebook
- Practice Lab
- Verb Conjugation
- Progress/dashboard
- Seed/deck browsing and onboarding/configuration pages

The UI layer should treat pages as state consumers, not owners of storage policy.

## View flow
1. A valid cold-start checkpoint opens Today with a global Continue/Discard banner; no review page may auto-create a queue before that choice.
2. Continue validates/restores context and routes to the saved objective; Discard removes only the unfinished queue, not completed reviews.
3. Today and Progress each render the same immutable
   `DailyPlannerService.snapshot()` contract: completed/planned totals, ready
   due/new work, backlog, and homogeneous focused segments.
4. A Today action emits the original `PlanSegment`; MainWindow revalidates it
   before replacement confirmation, context mutation, or review-page routing.
5. Practice transitions to review widgets (prompt, options, feedback).
6. On answer submission:
   - session updates scheduled state in DB
   - immediate ranking or next-card selection refreshes
7. A finished planned set offers an explicit Return to Today action; it never
   auto-switches objectives.
8. Mistake notebook reads persisted failure history, applies lane-safe filters, and routes selected seeded IDs into a one-off targeted drill.
9. Verb Conjugation view reads expanded paradigms from DB and enforces locale-safe input and hints.
10. Progress separates global Today's plan metrics from Current lesson stats.

## `src/ui/widgets/`
Custom widgets are reused across pages to keep behavior consistent:
- special-character keyboard (`ß`, `ä`, `ö`, `ü`, `ẞ`, punctuation variants)
- flow layout containers for adaptive token chips/challenge rows
- sentence builders with segment controls and input validation
- reusable status chips, feedback badges, and deck selectors
- `NumberStepper` and `DailyPlanDialog` for bounded, accessible planner defaults

## Mistake Notebook workflow
- `Recent failures` and `Recurring & flagged` are explicit views; state-only trouble rows are never mixed into a Show-N failure result.
- Filters cover Show N items, one exact error tag, one complete `(level, book_slug, lektion_number)` identity, and one exact lane. Recent-failure filtering occurs in core before limiting results.
- **Practice this** drills one eligible row. **Practice these** is enabled only when the visible active rows share one deck and exact `(objective, practice_mode)` lane, preventing accidental cross-schedule queues.
- Primary-lane requests route through `SessionService.start_targeted_session()`. Vocabulary production/dictation requests route through `PracticeLabPage.start_targeted_drill()` after the same seeded-ID revalidation.
- Drill queues reuse existing cards, end after the selected IDs, and are intentionally process-local/non-resumable. They create neither cloned cards nor permanent decks.
- Starting a drill from an unfinished session first performs a read-only stale-request check, then asks for explicit replacement with Cancel as the default. Completed ratings are never discarded.
- Bury, suspend, resume, and per-row drill controls remain explicit learner actions. A suspended failure stays useful as history but cannot enter a drill until resumed.
- A leech badge appears at three failures in the same lane within 30 days and only suggests burying/suspending or reviewing a rule; it never changes state automatically.
- Rule navigation is explicit and fail-closed: `gender -> A1 1.4`, `plural -> A1 1.2`, `article_missing -> A1 1.1`, and `word_order -> A1 4.1`. Ambiguous `article`, unknown tags, and missing/duplicate curriculum references expose no Learn link.

## Interaction contracts
- Pages request operations through services/repository APIs
- Pages expose only UI state and user-intent events
- Core persistence and ranking remain backend-owned (testable without full UI)
- Primary drill ratings update the objective's normal lane (vocab recognition, grammar production, sentence builder, or listening comprehension). Practice Lab ratings update only production/dictation and never recognition ML features.
- Same-process review reentry may retain a draft only while `SessionService.is_current_item()` confirms that page still owns the card.
- Deck/context/profile changes invalidate the checkpoint and hidden page card ownership.

For architecture coupling, see [[01_Architecture_and_Stack]] and [[02_Core_Engine_and_ML]].
