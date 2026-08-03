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
4. Today/Practice/Mistake flows request candidate items.
5. Candidate list is ranked using FSRS + ML and rendered by UI.
6. User interactions write back performance metrics to local DB.
7. Audio, cache, and generated artifacts remain local and reusable.

## State management
- MAHIRA keeps mutable state outside app bundle:
  - `.mahira/` (workspace root) stores db, settings, cache, queue state, backups.
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
