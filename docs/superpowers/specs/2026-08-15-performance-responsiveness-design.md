# MAHIRA Responsiveness Performance Design

Date: 2026-08-15  
Branch: `daily_planner`

## Goal

Improve the responsiveness users feel while opening Today, Progress, and Setup without changing learner data, review scheduling, session durability, or visible learning behavior. Each optimization must be independently testable, benchmarked, and committed with a short message under the repository's configured `mahanfatehian` identity.

## Measured Baseline

Measurements use the current local MAHIRA database and warm-cache medians unless noted otherwise.

- Daily-plan snapshot with ML ranking: about 228 ms. The planner ranks 12,439 eligible cards even though the displayed plan selects only 30.
- Progress refresh: about 61 ms and 11 SQLite connection opens.
- Initial Setup construction, deferred refresh, and first `on_show`: about 266-294 ms and 84 SQLite connection opens. Two refreshes rebuild unchanged controls.
- Rebuilding nine transformed book covers: about 69 ms after the source files are available.

## Approved Scope

### 1. Streamline daily-plan ranking

The planner will keep ML ranking for due cards, where learner history provides meaningful signals. New/unseen cards will retain the repository's deterministic curriculum order and will not be sent through the ML ranker.

This avoids ranking the entire unseen backlog and reduces the measured snapshot median from about 228 ms to about 51 ms. Due-card ordering remains adaptive; new-card ordering becomes explicitly stable and curriculum-driven.

Tests must prove:

- due candidates are still passed to and ordered by the configured ranker;
- unseen candidates retain natural repository order even when a ranker would reorder them;
- allocation, caps, segment composition, and deterministic tie behavior remain unchanged.

### 2. Reuse one Progress read transaction

`ProgressPage.on_show` will collect its synchronous database-backed snapshot and lesson statistics within one repository read transaction. Existing repository helpers will continue to own their SQL; the UI will only scope their reads to one coherent connection/snapshot.

No dialog, signal wait, worker handoff, or other user interaction may occur while this read transaction is active. Rendering remains outside the transaction when practical.

Expected effect: roughly 61 ms and 11 connection opens become 42 ms and one connection open.

Tests must prove:

- Progress renders the same totals and labels;
- a refresh uses one physical connection for the scoped reads;
- failures still render the explicit unavailable state rather than plausible zeros;
- the refresh remains read-only.

### 3. Remove duplicate Setup refreshes

Setup will retain its initial synchronous population. The zero-delay post-construction callback will only perform lightweight coercion, breadcrumb, and due-strip work instead of rebuilding all level, book, lesson, and objective controls. The immediate first `on_show` will skip a full rebuild when the context/content signature is unchanged; later real context or seed changes will still trigger a complete refresh.

Expected effect: remove about 170 ms and 56 unnecessary database connection opens from the initial Setup path.

Tests must prove:

- initial controls and due information are populated correctly;
- constructor plus deferred initialization does not duplicate the full refresh;
- an unchanged first `on_show` is a no-op for structural rebuilding;
- actual context or content changes rebuild the appropriate controls;
- navigation and accessibility behavior remain unchanged.

### 4. Cache transformed book covers

The cover resolver will cache the final rounded/scaled pixmap using a key that includes the resolved path, file modification metadata, target dimensions, corner radius, and device-pixel ratio. A changed source file, display scale, or requested geometry must miss the cache. Missing or invalid images must continue through the existing fallback path.

The cache will be bounded so long-running sessions cannot accumulate arbitrary entries.

Expected effect: repeated nine-cover rendering avoids roughly 69 ms of image transformation work after the first render.

Tests must prove:

- repeated identical requests reuse the transformed result;
- file changes invalidate the cached result;
- size, radius, and device-pixel ratio form distinct cache entries;
- corrupt or missing preferred covers retain the conventional-cover and initials fallbacks;
- the cache remains bounded.

## Explicit Non-Goals

- No database schema migration or learner-state rewrite.
- No changes to FSRS scheduling, review transactions, selection buckets, or resume checkpoints.
- No background ML training, threaded repository access, or shutdown-flush lifecycle changes in this pass.
- No broad lazy page construction or navigation rewrite.
- No seed-format or packaging changes.

The deferred alternatives have larger potential wins but materially higher lifecycle and compatibility risk: background/lazy ML initialization, lazy Piper imports, parse-once seed-import architecture, and new history indexes.

## Safety and Verification

Each slice follows red-green TDD: add a focused regression or behavior test, observe the intended failure, implement the smallest production change, and rerun the focused suite. Before each commit, record benchmark evidence and run related regression suites. Before completion, run the full test suite, seed validation, application health check, compilation, and `git diff --check`, followed by an independent code review.

The intended commit sequence is:

1. `perf: streamline daily plans`
2. `perf: reuse progress reads`
3. `perf: trim setup refreshes`
4. `perf: cache book covers`

The commits are intentionally independent so any regression can be isolated or reverted without affecting the other improvements.
