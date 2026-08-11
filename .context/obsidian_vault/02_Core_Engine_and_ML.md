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

## Recent failures and targeted drills
- `InsightsService.recent_failures()` derives failure evidence from persisted review rows whose effective `rating=0`; UI correctness flags alone are not failure history.
- Results stay in one exact `(objective, practice_mode)` lane. Lesson filtering requires the complete `(level, book_slug, lektion_number)` tuple, tags match normalized comma-delimited tokens, and all filters run before the requested result limit.
- Leech metadata means at least three persisted failures in the same lane during the inclusive trailing 30-day window. It is guidance, never an automatic state change.
- `src/core/mistake_rules.py` maps only unambiguous error tags to Learn references. Unknown or ambiguous tags have no rule link, and `CurriculumIndex` must resolve exactly one `(level, order_token)` lesson before navigation is allowed.
- `SessionService.targeted_item_ids()` revalidates requested seeded IDs against the current deck and card controls. `start_targeted_session()` reuses those rows in a temporary queue; it never copies cards or creates a drill deck.
- `preview_targeted_item_ids()` validates context, deck identity, and active IDs without mutating an unfinished session. The UI preflights first, defaults the replacement confirmation to Cancel, then revalidates after the learner explicitly discards.
- Targeted primary and Practice Lab drills are deliberately process-local and non-resumable. They do not write `active_session.json`, so restart abandons the one-off queue without changing persisted review history.

## `src/ml/sklearn_ranker.py`
Adds a second prioritization layer for candidate selection:
- transforms card/deck/user-context features into ranking scores
- learns/uses stable offline ranking to avoid brittle fixed ordering
- improves review session quality by adjusting order, not replacing FSRS math
- intended as augmentation: **FSRS decides when**, ranker nudges **which now**
- vocabulary features and review counts aggregate recognition rows only; production/dictation Lab ratings must not train or reorder the recognition lane
- vocabulary models use semantic cache version `v3`; pre-isolation `v2` weights are ignored because their aggregate features included Lab history

Targeted primary drills write their normal objective scheduler state. Vocabulary Lab drills write `vocab_practice_states` and their explicit non-recognition `practice_mode`; neither schedule nor ML aggregates may cross that boundary. See [[07_Development_Safety_Invariants]].

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
