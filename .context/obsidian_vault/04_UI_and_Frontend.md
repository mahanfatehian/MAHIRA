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
3. Today view selects due items via core/db.
4. Practice transitions to review widgets (prompt, options, feedback).
5. On answer submission:
   - session updates scheduled state in DB
   - immediate ranking or next-card selection refreshes
6. Mistake notebook reads persisted error history and routes to targeted re-practice.
7. Verb Conjugation view reads expanded paradigms from DB and enforces locale-safe input and hints.
8. Progress page renders aggregate metrics using repository queries.

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
- Same-process review reentry may retain a draft only while `SessionService.is_current_item()` confirms that page still owns the card.
- Deck/context/profile changes invalidate the checkpoint and hidden page card ownership.

For architecture coupling, see [[01_Architecture_and_Stack]] and [[02_Core_Engine_and_ML]].
