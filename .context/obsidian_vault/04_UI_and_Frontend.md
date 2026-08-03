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
1. Today view selects due items via core/db.
2. Practice transitions to review widgets (prompt, options, feedback).
3. On answer submission:
   - session updates scheduled state in DB
   - immediate ranking or next-card selection refreshes
4. Mistake notebook reads persisted error history and routes to targeted re-practice.
5. Verb Conjugation view reads expanded paradigms from DB and enforces locale-safe input and hints.
6. Progress page renders aggregate metrics using repository queries.

## `src/ui/widgets/`
Custom widgets are reused across pages to keep behavior consistent:
- special-character keyboard (`ß`, `ä`, `ö`, `ü`, `ẞ`, punctuation variants)
- flow layout containers for adaptive token chips/challenge rows
- sentence builders with segment controls and input validation
- reusable status chips, feedback badges, and deck selectors

## Interaction contracts
- Pages request operations through services/repository APIs
- Pages expose only UI state and user-intent events
- Core persistence and ranking remain backend-owned (testable without full UI)

For architecture coupling, see [[01_Architecture_and_Stack]] and [[02_Core_Engine_and_ML]].
