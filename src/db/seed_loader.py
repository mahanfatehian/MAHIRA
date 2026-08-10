from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from db.backup import BackupInfo, BackupService
from db.seed_import import (
    CEFR_LEVELS,
    PreparedSeed,
    SeedImportError,
    apply_prepared_seed,
    prepare_seed_csv,
)


ValidationHook = Callable[[Path], object]


@dataclass(frozen=True)
class SeedDeckPlan:
    seed: PreparedSeed
    action: str
    reason: str
    deck_id: int | None = None

    @property
    def changed(self) -> bool:
        return self.action != "unchanged"


@dataclass(frozen=True)
class SeedImportPlan:
    entries: tuple[SeedDeckPlan, ...]
    backup: BackupInfo | None = None

    @property
    def changes(self) -> tuple[SeedDeckPlan, ...]:
        return tuple(entry for entry in self.entries if entry.changed)

    @property
    def unchanged(self) -> tuple[SeedDeckPlan, ...]:
        return tuple(entry for entry in self.entries if not entry.changed)

    @property
    def has_changes(self) -> bool:
        return any(entry.changed for entry in self.entries)


def _seed_specs(project_root: Path):
    """Yield CSV path plus folder-derived book and level metadata."""
    seeds_root = Path(project_root) / "data" / "seeds"
    if not seeds_root.exists():
        return

    # Legacy book-less files carry their level in the filename.
    for csv_path in sorted(seeds_root.glob("*.csv")):
        yield csv_path, None, None

    for book_dir in sorted(seeds_root.iterdir()):
        if not book_dir.is_dir():
            continue
        book_slug = book_dir.name.lower().strip()
        for level_dir in sorted(book_dir.iterdir()):
            if not level_dir.is_dir():
                continue
            level = level_dir.name.lower().strip()
            if level not in CEFR_LEVELS:
                continue
            for csv_path in sorted(level_dir.glob("*.csv")):
                yield csv_path, book_slug, level

        # Backward-compatible book-folder files carry level in the filename.
        for csv_path in sorted(book_dir.glob("*.csv")):
            yield csv_path, book_slug, None


def _prepare_pack(project_root: Path) -> tuple[PreparedSeed, ...]:
    prepared: list[PreparedSeed] = []
    targets: dict[tuple[str, int | None, str, str], Path] = {}
    for path, book_slug, level in _seed_specs(project_root):
        seed = prepare_seed_csv(path, book_slug=book_slug, level=level)
        if seed is None:
            continue
        previous = targets.get(seed.deck_key)
        if previous is not None:
            raise SeedImportError(
                f"{path}: targets the same deck as {previous}; one seed file is allowed per deck"
            )
        targets[seed.deck_key] = path
        prepared.append(seed)
    return tuple(prepared)


def _existing_seed_status(conn, seed: PreparedSeed):
    if seed.book_slug and seed.lektion_number is not None:
        row = conn.execute(
            """
            SELECT d.id AS deck_id, d.seed_file, d.seed_sha1,
                   l.title AS lektion_title, l.description AS lektion_topic
            FROM books b
            JOIN lektions l
              ON l.book_id=b.id AND l.level=? AND l.number=?
            LEFT JOIN decks d
              ON d.lektion_id=l.id AND d.level=? AND d.objective=?
            WHERE b.slug=?
            """,
            (
                seed.level,
                seed.lektion_number,
                seed.level,
                seed.objective,
                seed.book_slug,
            ),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT d.id AS deck_id, d.seed_file, d.seed_sha1,
                   NULL AS lektion_title, NULL AS lektion_topic
            FROM decks d
            WHERE d.level=? AND d.lektion_id IS NULL AND d.objective=?
            """,
            (seed.level, seed.objective),
        ).fetchone()
    if row is None or row["deck_id"] is None:
        return None

    table = {
        "vocab": "vocab",
        "grammar": "grammar",
        "sentences": "sentences",
        "listening": "listening",
    }[seed.objective]
    item_count = int(
        conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE deck_id=?",
            (int(row["deck_id"]),),
        ).fetchone()[0]
    )
    incomplete_sentences = False
    if seed.objective == "sentences" and item_count:
        incomplete_sentences = bool(
            conn.execute(
                """
                SELECT 1 FROM sentences
                WHERE deck_id=? AND (
                    target_text IS NULL OR TRIM(target_text)='' OR
                    words_json IS NULL OR TRIM(words_json)='' OR TRIM(words_json)='[]'
                )
                LIMIT 1
                """,
                (int(row["deck_id"]),),
            ).fetchone()
        )
    return row, item_count, incomplete_sentences


def _plan_entry(conn, seed: PreparedSeed) -> SeedDeckPlan:
    status = _existing_seed_status(conn, seed)
    if status is None:
        return SeedDeckPlan(seed, "add", "deck is not imported")
    row, item_count, incomplete_sentences = status
    deck_id = int(row["deck_id"])
    if str(row["seed_sha1"] or "") != seed.seed_sha1:
        return SeedDeckPlan(seed, "update", "seed content changed", deck_id)
    if item_count <= 0 or incomplete_sentences:
        return SeedDeckPlan(seed, "repair", "deck content is incomplete", deck_id)
    if str(row["seed_file"] or "") != seed.path.name:
        return SeedDeckPlan(seed, "metadata", "seed filename changed", deck_id)
    if seed.title and str(row["lektion_title"] or "") != seed.title:
        return SeedDeckPlan(seed, "metadata", "Lektion title changed", deck_id)
    if seed.topic is not None and str(row["lektion_topic"] or "") != seed.topic:
        return SeedDeckPlan(seed, "metadata", "Lektion topic changed", deck_id)
    return SeedDeckPlan(seed, "unchanged", "seed hash and deck are current", deck_id)


def plan_seed_import(
    repo,
    project_root: Path,
    *,
    validation_hook: ValidationHook | None = None,
) -> SeedImportPlan:
    """Build an import plan without creating or mutating a learner database.

    A validation hook may raise before parsing. It intentionally receives only
    the seed root, keeping the loader independent of any CLI/reporting API.
    """
    seeds_root = Path(project_root) / "data" / "seeds"
    if validation_hook is None:
        from db.seed_validation import validate_seed_tree

        validation_hook = validate_seed_tree
    validation_result = validation_hook(seeds_root)
    if getattr(validation_result, "ok", True) is False:
        render = getattr(validation_result, "render", None)
        detail = render() if callable(render) else "seed validation failed"
        raise SeedImportError(detail)
    prepared = _prepare_pack(project_root)

    db_path = Path(repo.db_path)
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return SeedImportPlan(
            tuple(SeedDeckPlan(seed, "add", "database is not initialized") for seed in prepared)
        )

    # URI mode=ro prevents planning/dry-run from changing the learner database.
    # Path.as_uri() also quotes percent signs and other legal Windows path text.
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        entries = tuple(_plan_entry(conn, seed) for seed in prepared)
    finally:
        conn.close()
    return SeedImportPlan(entries)


def load_all_seeds(
    repo,
    project_root: Path,
    *,
    dry_run: bool = False,
    backup_service: BackupService | None = None,
    validation_hook: ValidationHook | None = None,
) -> SeedImportPlan:
    """Preflight, back up once, then atomically apply every changed seed."""
    if repo._active_conn is not None:
        raise RuntimeError("load_all_seeds must own the seed import transaction")

    plan = plan_seed_import(repo, project_root, validation_hook=validation_hook)
    if dry_run or not plan.has_changes:
        return plan

    db_path = Path(repo.db_path)
    if not db_path.is_file() or db_path.stat().st_size == 0:
        raise RuntimeError("initialize the learner database before applying seeds")

    service = backup_service or BackupService(db_path)
    backup = service.create("pre-seed-import")
    if backup is None:
        raise RuntimeError("seed import stopped because its safety backup failed")

    with repo.transaction():
        for entry in plan.changes:
            apply_prepared_seed(repo, entry.seed)
    return replace(plan, backup=backup)
