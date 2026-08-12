# Architecture and Stack

MAHIRA is intentionally split into five layers:

- UI layer (`src/ui/...`)
- Core logic (`src/core/...`, `src/ml/...`, `src/audio/...`)
- Data layer (`src/db/...`, bundled assets)
- Runtime/runtime-commands (`src/...`)
- Packaging + CI (`packaging/...`, `.github/...`)

## Core stack
- **Python 3.11+**
- **PySide6** for desktop UI, signals/slots, page navigation
- **SQLite** for local persistence
- **FSRS 4.5** for review scheduling and due-date computation
- **scikit-learn** for ranker-based item reprioritization
- **Piper TTS (ONNX)** for offline pronunciation/audio playback

## Execution flow (steady state)
1. App entrypoint builds application state and dependency graph.
2. Session/user context loads profile and deck metadata from `src/db`.
3. Seed/content manifests resolve available decks from filesystem.
4. `core/planner.py` recomputes a read-only local-day snapshot for Today and
   Progress, then divides bounded work into objective/deck-homogeneous segments.
5. Today preflights one segment through `SessionService`; manual Practice and
   Mistakes retain their separate selection routes.
6. Candidate lists are ranked using deterministic FSRS priority plus ML where
   available and rendered by the objective-specific UI.
7. User interactions atomically write the review bucket and FSRS state.
8. Audio, cache, and generated artifacts remain local and reusable.

## State management
- MAHIRA keeps mutable state outside app bundle:
  - `.mahira/` (workspace root) stores databases, settings, caches, backups, and the default profile's `active_session.json`.
  - named profiles keep their checkpoint beside their database under `.mahira/profiles/<slug>/`.
- `src/core/session_resume.py` owns the versioned, atomic checkpoint format; `SessionService` owns validation and queue restoration.
- A checkpoint stores the remaining LIFO queue and displayed card separately. Continue validates the objective, deck, seed revision, item ownership, and pre-review state before restoring it.
- Planned sets reuse this ordinary primary-review checkpoint; no second itinerary
  or heterogeneous cross-objective queue is persisted.
- This enables safe upgrade behavior, repair/recovery, and deterministic migration testing.
- Backups are produced before disruptive changes to avoid silent data loss.

## Layer boundaries
- UI never performs raw scheduling math directly.
- Core computes scheduling and ranking.
- DB module enforces transactional updates for consistency.
- Audio manager owns model loading/preloading playback lifecycle.

See:
- [[02_Core_Engine_and_ML]]
- [[03_Database_and_Schema]]
- [[04_UI_and_Frontend]]
- [[05_Folder_Driven_Seed_System]]
- [[06_CI_CD_and_Packaging]]
