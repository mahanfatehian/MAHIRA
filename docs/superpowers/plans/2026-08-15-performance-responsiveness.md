# MAHIRA Responsiveness Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Today, Progress, and Setup feel faster through four measured, behavior-preserving optimizations.

**Architecture:** Keep every change inside an existing responsibility boundary: planner candidate ordering, repository read scoping, Setup lifecycle refreshes, and image transformation. Each task begins with a focused failing regression, changes no learner schema or scheduling behavior, records before/after evidence, and ends in an independent commit.

**Tech Stack:** Python 3.11+, PySide6, SQLite, pytest, scikit-learn ranker integration.

## Global Constraints

- Keep FSRS scheduling, review transactions, selection buckets, resume checkpoints, and learner data unchanged.
- Do not add a schema migration, background thread, new dependency, seed-format change, or packaging change.
- Preserve exact due-card ML ranking and deterministic curriculum order for unseen cards.
- Keep Progress refresh read-only and never hold its read transaction across an event-loop yield, dialog, or worker handoff.
- Refresh Setup after real state changes; skip only redundant work for an unchanged initial lifecycle.
- Bound the transformed-cover cache and invalidate it by path metadata, geometry, radius, and device-pixel ratio.
- Run each task red-green, benchmark it, review it, and commit it separately as `mahanfatehian`.

## File Map

- `src/core/planner.py`: chooses and orders daily-plan inventory.
- `src/ui/pages/progress.py`: scopes one synchronous Progress refresh to a coherent repository read transaction.
- `src/ui/pages/setup.py`: tracks whether the initial Setup data tree is already current.
- `src/ui/widgets/images.py`: owns bounded rounded-cover rendering and caching.
- `tests/test_daily_planner.py`: planner ordering and ranker-call regressions.
- `tests/test_progress_daily_plan.py`: Progress transaction reuse, rendered-value, and failure-state regressions.
- `tests/test_feature_pages_ui.py`: Setup lifecycle refresh-count and context-change regressions.
- `tests/test_book_covers.py`: cover-cache reuse, invalidation, geometry, DPR, fallback, and bound regressions.

---

### Task 1: Avoid ranking the unseen-card backlog

**Files:**
- Modify: `src/core/planner.py:185-286`
- Modify: `tests/test_daily_planner.py:175-205`

**Interfaces:**
- Consumes: `DailyPlannerService._rank(objective, items)` for due candidates only.
- Produces: `DailyPlanSnapshot.segments` with ML-ranked due IDs followed by repository-ordered new IDs.

- [ ] **Step 1: Add a failing new-card ordering regression**

Add this beside the existing ranking test in `tests/test_daily_planner.py`:

```python
def test_daily_plan_keeps_new_cards_in_curriculum_order_without_ranking_them():
    from core.planner import DailyPlannerService

    class _Ranker:
        def rank_vocab_ids(self, ids, *, level=None, **_):
            assert ids == [11, 12, 13]
            return [11, 12, 13]

    inventory = [
        _item("vocab", item_id, bucket="new")
        for item_id in (11, 12, 13)
    ]
    snapshot = DailyPlannerService(
        _Repo(inventory),
        _settings(daily_goal=3),
        ranker=_Ranker(),
    ).snapshot(now=1_700_000_000)

    assert snapshot.segments[0].item_ids == (11, 12, 13)
```

Keep `test_daily_plan_ranking_is_converted_to_first_served_order` as the proof that due cards still use the ranker.

- [ ] **Step 2: Run the focused RED gate**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests/test_daily_planner.py::test_daily_plan_keeps_new_cards_in_curriculum_order_without_ranking_them tests/test_daily_planner.py::test_daily_plan_ranking_is_converted_to_first_served_order -q
```

Expected: the new-card test fails because the current planner reverses the ranker output; the due-card test passes.

- [ ] **Step 3: Preserve repository order for new candidates**

Change only the new-card selection inside `DailyPlannerService.snapshot`:

```python
due_items = self._rank(objective, ready[objective]["due"])[
    : due_allocation[objective]
]
new_items = ready[objective]["new"][: new_allocation[objective]]
```

Do not alter `_rank`, allocation, caps, backlog counts, cohort segmentation, or revalidation.

- [ ] **Step 4: Run planner and planned-session regressions**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests/test_daily_planner.py tests/test_planned_sessions.py tests/test_planner_routing.py tests/test_today_planner_ui.py tests/test_progress_planner_consistency.py -q
```

Expected: all pass.

- [ ] **Step 5: Record the before/after planner benchmark**

Run the existing local snapshot benchmark against the active profile database for at least 20 warmed calls with `enable_ml_ranking=True`. Record median and p95 in the task handoff. Acceptance target: median at or below 70 ms on the same machine where the baseline was about 228 ms; selected totals and due ordering must be unchanged.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- src/core/planner.py tests/test_daily_planner.py
git commit -m "perf: streamline daily plans"
```

---

### Task 2: Reuse one SQLite snapshot for Progress

**Files:**
- Modify: `src/ui/pages/progress.py:895-1030`
- Modify: `tests/test_progress_daily_plan.py`

**Interfaces:**
- Consumes: `Repo.read_transaction()` and existing nested `Repo._conn()` reuse.
- Produces: `ProgressPage.on_show()` with the same rendered values and a private `_refresh_from_repository()` body.

- [ ] **Step 1: Add a failing connection-reuse regression**

Build a real temporary repository using the existing Progress fixtures, patch `db.repo.connect` only after database initialization, and assert that one refresh opens one physical connection:

```python
def test_progress_refresh_reuses_one_repository_connection(tmp_path, monkeypatch):
    import db.repo as repo_module
    from types import SimpleNamespace
    from db.init_db import init_db
    from db.repo import Repo
    from ui.pages.progress import ProgressPage

    db_path = tmp_path / "progress-refresh.db"
    init_db(db_path)
    repo = Repo(db_path)
    session = SimpleNamespace(
        repo=repo,
        settings=SimpleNamespace(value=SimpleNamespace(daily_goal=10)),
        state=SimpleNamespace(
            level='A1', objective='vocab', book_slug='', lektion_number=0
        ),
        active_deck_id=lambda: None,
        ml=None,
        enable_ml_ranking=False,
    )
    real_connect = repo_module.connect
    opens = 0

    def counted_connect(path):
        nonlocal opens
        opens += 1
        return real_connect(path)

    monkeypatch.setattr(repo_module, "connect", counted_connect)
    _qapp()
    page = ProgressPage(session)
    try:
        page.on_show()
        assert opens == 1
    finally:
        page.close()
        page.deleteLater()
```

The active lesson is deliberately empty: the assertion covers the canonical plan and activity reads while keeping the fixture independent of seed content.

- [ ] **Step 2: Run the focused RED gate**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests/test_progress_daily_plan.py::test_progress_refresh_reuses_one_repository_connection -q
```

Expected: failure with more than one physical connection open.

- [ ] **Step 3: Scope the refresh to one read transaction**

Rename the existing `on_show` body to `_refresh_from_repository`, and add this wrapper:

```python
def on_show(self):
    read_transaction = getattr(self.session.repo, "read_transaction", None)
    read_scope = (
        read_transaction() if callable(read_transaction) else nullcontext()
    )
    try:
        with read_scope:
            self._refresh_from_repository()
    except Exception:
        self._show_refresh_unavailable()

def _refresh_from_repository(self):
    try:
        plan_snapshot = self._refresh_daily_plan()
    except Exception:
        self._show_refresh_unavailable()
        return
    # Existing synchronous refresh body remains unchanged below.
```

Import `nullcontext` from `contextlib`. Do not call `processEvents`, open dialogs, emit work to another thread, or wait while inside this scope.

- [ ] **Step 4: Run Progress truthfulness and transaction regressions**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests/test_progress_daily_plan.py tests/test_progress_planner_consistency.py tests/test_activity_lane_isolation.py tests/test_bury_actions.py tests/test_feature_pages_ui.py -q
```

Expected: all pass, including success-to-failure clearing and canonical clock assertions.

- [ ] **Step 5: Record the before/after Progress benchmark**

Measure at least 20 warmed `ProgressPage.on_show()` calls using the same seeded database, counting `db.repo.connect` calls. Acceptance target: one physical open per refresh and median no worse than baseline; expected median is about 42 ms versus 61 ms.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- src/ui/pages/progress.py tests/test_progress_daily_plan.py
git commit -m "perf: reuse progress reads"
```

---

### Task 3: Skip redundant Setup lifecycle rebuilds

**Files:**
- Modify: `src/ui/pages/setup.py:565-700`
- Modify: `tests/test_feature_pages_ui.py`

**Interfaces:**
- Consumes: canonical `session.state` fields and existing `_refresh_*` methods.
- Produces: `_state_signature() -> tuple[str, str, int, str]`, `_refresh_structure()`, and an unchanged-initial-show guard.

- [ ] **Step 1: Add failing refresh-count regressions**

Use a real `SetupPage`, replace the four structural refresh methods with counters after construction, process the queued timer, then call `on_show`:

```python
def test_setup_deferred_and_first_show_do_not_rebuild_unchanged_structure(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from db.init_db import init_db
    from db.repo import Repo
    from ui.pages.setup import SetupPage

    db_path = tmp_path / 'setup-refresh.db'
    init_db(db_path)
    session = SimpleNamespace(
        repo=Repo(db_path),
        state=SimpleNamespace(
            level='A1', book_slug='', lektion_number=0, objective=''
        ),
    )
    _qapp()
    page = SetupPage(session)
    calls = {name: 0 for name in ("levels", "books", "lektions", "objectives")}
    monkeypatch.setattr(page, "_refresh_levels_enabled", lambda: calls.__setitem__("levels", calls["levels"] + 1))
    monkeypatch.setattr(page, "_refresh_books", lambda: calls.__setitem__("books", calls["books"] + 1))
    monkeypatch.setattr(page, "_refresh_lektions", lambda: calls.__setitem__("lektions", calls["lektions"] + 1))
    monkeypatch.setattr(page, "_refresh_objectives", lambda: calls.__setitem__("objectives", calls["objectives"] + 1))

    QApplication.processEvents()
    page.on_show()

    assert calls == {"levels": 0, "books": 0, "lektions": 0, "objectives": 0}
```

Add a second test with the same explicit temporary `Repo`/`SimpleNamespace` fixture. After processing the timer, mutate `session.state.level` from `'A1'` to `'A2'`, call `on_show`, and assert every structural counter becomes one. Ensure both tests close/delete the page.

- [ ] **Step 2: Run the focused RED gate**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests/test_feature_pages_ui.py -k "setup_deferred or setup_context_change" -q
```

Expected: the unchanged case records two structural rebuilds (timer and `on_show`) instead of zero.

- [ ] **Step 3: Centralize structural refresh and guard the first show**

Add these private helpers and state:

```python
def _state_signature(self) -> tuple[str, str, int, str]:
    state = self.session.state
    return (
        _norm_level(getattr(state, "level", None) or ""),
        (getattr(state, "book_slug", None) or "").strip().lower(),
        int(getattr(state, "lektion_number", None) or 0),
        _norm_objective(getattr(state, "objective", None) or ""),
    )

def _refresh_structure(self) -> None:
    self._refresh_levels_enabled()
    self._refresh_books()
    self._refresh_lektions()
    self._refresh_objectives()
```

After the constructor's one structural population, store:

```python
self._last_structure_signature = self._state_signature()
self._skip_unchanged_initial_show = True
```

Make `_post_init_refresh` lightweight by removing `_refresh_structure`; retain state sync, step coercion, breadcrumb, and due strip. In `on_show`, reload the catalog and sync state, then run `_refresh_structure()` only when the signature changed or the one-time unchanged guard has already been consumed. Update `_last_structure_signature` after a rebuild, consume `_skip_unchanged_initial_show` on the first show, and always retain coercion/breadcrumb/due-strip work.

- [ ] **Step 4: Run Setup and navigation regressions**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests/test_feature_pages_ui.py tests/test_dynamic_seed_structure.py tests/test_main_window_construction.py tests/test_context_consistency.py tests/test_book_covers.py -q
```

Expected: all pass; actual state changes still rebuild and render correct controls.

- [ ] **Step 5: Record the before/after Setup benchmark**

Measure constructor, zero-delay callback, and first `on_show` separately over at least five warm runs, counting repository connections. Acceptance target: the timer plus unchanged first show perform zero structural refresh calls and eliminate the measured extra 56 connection opens; total initial path should improve by at least 100 ms on the same machine.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- src/ui/pages/setup.py tests/test_feature_pages_ui.py
git commit -m "perf: trim setup refreshes"
```

---

### Task 4: Cache transformed cover pixmaps safely

**Files:**
- Modify: `src/ui/widgets/images.py`
- Modify: `tests/test_book_covers.py`

**Interfaces:**
- Consumes: image path, source stat metadata, width, height, radius, and `_device_pixel_ratio()`.
- Produces: `_cached_rounded_cover_pixmap(...)->Optional[QPixmap]` with an LRU maximum of 128 entries; public `rounded_cover_pixmap` behavior remains unchanged.

- [ ] **Step 1: Add failing cache reuse and invalidation regressions**

Extend `tests/test_book_covers.py` with a real temporary PNG and cache-info assertions:

```python
def test_rounded_cover_cache_reuses_identical_transform_and_splits_geometry(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from ui.widgets import images

    app = QApplication.instance() or QApplication([])
    assert app is not None
    source = tmp_path / "cover.png"
    pixmap = QPixmap(40, 60)
    pixmap.fill(Qt.GlobalColor.red)
    assert pixmap.save(str(source), "PNG")
    images._cached_rounded_cover_pixmap.cache_clear()

    assert images.rounded_cover_pixmap(str(source), 80, 104, 14) is not None
    assert images.rounded_cover_pixmap(str(source), 80, 104, 14) is not None
    reused = images._cached_rounded_cover_pixmap.cache_info()
    assert (reused.hits, reused.misses) == (1, 1)

    assert images.rounded_cover_pixmap(str(source), 81, 104, 14) is not None
    assert images.rounded_cover_pixmap(str(source), 80, 104, 15) is not None
    split = images._cached_rounded_cover_pixmap.cache_info()
    assert split.misses == 3
    assert split.maxsize == 128
```

Add two more tests: patch `_device_pixel_ratio` from `1.0` to `2.0` and assert a cache miss; overwrite/save the PNG and advance its mtime with `os.utime`, then assert a miss and changed pixel color. Retain existing missing/corrupt preferred-cover fallbacks.

- [ ] **Step 2: Run the focused RED gate**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests/test_book_covers.py -k "rounded_cover_cache" -q
```

Expected: failure because `_cached_rounded_cover_pixmap` does not exist and every call rerenders.

- [ ] **Step 3: Add the bounded stat-aware LRU renderer**

In `src/ui/widgets/images.py`, import `lru_cache` and `Path`. Move the current transform body into:

```python
@lru_cache(maxsize=128)
def _cached_rounded_cover_pixmap(
    resolved_path: str,
    mtime_ns: int,
    file_size: int,
    width: int,
    height: int,
    radius: int,
    dpr: float,
) -> Optional[QPixmap]:
    del mtime_ns, file_size
    src = QPixmap(resolved_path)
    if src.isNull():
        return None
    # Existing scale, crop, rounded-clip, paint, and DPR logic follows.
```

Make the public wrapper validate and key the source before calling it:

```python
try:
    resolved = Path(path).resolve(strict=True)
    stat = resolved.stat()
except (OSError, RuntimeError):
    return None
dpr = round(_device_pixel_ratio(), 4)
cached = _cached_rounded_cover_pixmap(
    str(resolved), stat.st_mtime_ns, stat.st_size,
    max(1, int(width)), max(1, int(height)), max(0, int(radius)), dpr,
)
return QPixmap(cached) if cached is not None else None
```

The returned shallow `QPixmap` copy prevents callers from mutating the cached object. Missing paths are never cached; corrupt existing sources may cache `None` only for their exact stat key.

- [ ] **Step 4: Run cover and Setup regressions**

Run:

```powershell
venv\Scripts\python.exe -m pytest tests/test_book_covers.py tests/test_seed_manifest.py tests/test_feature_pages_ui.py tests/test_main_window_construction.py -q
```

Expected: all pass, including preferred-cover fallback and HiDPI assertions.

- [ ] **Step 5: Record the before/after cover benchmark**

Render the nine bundled covers 50 times at 80x104/radius 14 after clearing the cache once. Record cold pass and warm-pass medians plus cache hits/misses. Acceptance target: warm passes perform zero source transforms and remain below 10 ms for all nine covers on the same machine.

- [ ] **Step 6: Commit Task 4**

```powershell
git add -- src/ui/widgets/images.py tests/test_book_covers.py
git commit -m "perf: cache book covers"
```

---

## Final Verification and Review

- [ ] Run the complete suite:

```powershell
venv\Scripts\python.exe -m pytest -q
```

- [ ] Validate bundled seed content:

```powershell
$env:PYTHONPATH = "src"
venv\Scripts\python.exe -m mahira validate-seeds
```

- [ ] Run the packaged application health contract and compilation checks supported by the repository:

```powershell
$env:PYTHONPATH = "src"
venv\Scripts\python.exe -m mahira --health-check
venv\Scripts\python.exe -m compileall -q src tests
git diff --check
git status --short
```

- [ ] Request an independent review of all four commits. Fix any Critical or Important finding in the owning commit boundary, rerun its focused tests, then rerun the complete suite.

- [ ] Confirm the final four performance commits use `mahanfatehian <mahanfatehian@gmail.com>` and do not push them.
