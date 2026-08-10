# Core Engine and ML

## `src/core/`
Core modules should be treated as the truth for learning behavior:
- scheduling/retrievability calculation
- session updates (grades/ease/interval effects)
- deck/card utility helpers
- rule orchestration used by UI pages

## `src/core/fsrs.py`
Implements the FSRS 4.5 logic that drives long-term spacing.

Key responsibilities:
- Convert current card state + review result into next state
- Update `stability`, `difficulty`, retrievability window expectations
- Compute review interval and due timestamp
- Provide deterministic transitions from rating outcomes (e.g., easy/hard/fail)

## `src/core/srs.py`
Contains MAHIRA-facing wrappers around FSRS primitives:
- maps user-facing outcomes into scheduler inputs
- enforces app-level cooldowns and due policy
- supports due-count queries used by progress and today-listing flows
- adds app-specific guards (e.g., suspended/buried filtering, cooldown-aware due filtering)

Cross-link to repo behavior decisions:
- Due counts and cooldown policy are surfaced in practice and progress screens.
- If a card is due repeatedly, app-level business logic handles lockout/retry semantics.

## Session continuity
- `src/core/session.py` owns primary recognition queues, the displayed item identity, session position, and one-deep in-memory undo.
- `src/core/session_resume.py` persists one versioned `active_session.json` per profile using fsync + atomic replacement.
- The displayed card is not part of the remaining queue in memory, so checkpoints store `current_item_id` separately and reinsert it at the LIFO tail only after Continue.
- Resume rejects changed deck seed hashes and foreign/missing IDs. A pre-review state token detects a DB commit that outlived its JSON update and prevents a duplicate rating.
- Production/dictation Lab queues and undo snapshots are intentionally not serialized; see [[07_Development_Safety_Invariants]].

## `src/ml/sklearn_ranker.py`
Adds a second prioritization layer for candidate selection:
- transforms card/deck/user-context features into ranking scores
- learns/uses stable offline ranking to avoid brittle fixed ordering
- improves review session quality by adjusting order, not replacing FSRS math
- intended as augmentation: **FSRS decides when**, ranker nudges **which now**

## Audio engine (offline Piper TTS path)
Handled through the audio layer (often wired through core orchestration):
- Piper ONNX model loading and caching
- deterministic model selection based on configured voice profile
- queue-aware playback (play/stop/abort semantics)
- defensive temp-file handling for concurrency safety and cross-platform file access
- preview and playback modes should remain read-only for already generated assets where possible

Notes:
- audio operations should remain non-blocking to keep UI responsive
- failure paths should degrade gracefully (skip/playback error fallback)

See [[05_Folder_Driven_Seed_System]] for how textual items enter core and [[04_UI_and_Frontend]] for playback trigger points.
