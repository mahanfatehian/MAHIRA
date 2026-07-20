# src/mahira/config.py
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "mahira"
APP_AUTHOR = "mahira"
DB_FILENAME = "mahira.db"

# Everything generated lives below <data_root>/.mahira. Frozen Windows and
# macOS builds use standard per-user application-data roots so upgrades and
# uninstall cannot remove learner history.
STATE_DIRNAME = ".mahira"


@dataclass(frozen=True)
class Paths:
    project_root: Path   # read-only resource root (bundled data/assets/schema)
    state_dir: Path      # writable runtime dir (db, ml models, logs)
    db_path: Path
    schema_path: Path
    models_dir: Path
    settings_path: Path


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """
    Root for READ-ONLY bundled resources: data/seeds, data/pages, assets/,
    src/db/schema.sql.

    - Frozen: PyInstaller's extraction dir (sys._MEIPASS), or the executable
      directory for a onedir build.
    - From source: the repository root (<root>/src/mahira/config.py -> <root>).
    """
    if is_frozen():
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return Path(base).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_root() -> Path:
    """
    Root for WRITABLE runtime state.

    - MAHIRA_DATA_DIR env var wins (lets advanced users relocate state).
    - Frozen Windows: %LOCALAPPDATA%/MAHIRA.
    - Frozen Linux: ``$XDG_DATA_HOME/MAHIRA`` or
      ``~/.local/share/MAHIRA`` when XDG_DATA_HOME is unset.
    - Frozen macOS (.app): a macOS app bundle is read-only once installed and
      App Translocation runs it from a random read-only mount, so writable state
      must NOT live inside the bundle. Use the standard per-user Application
      Support directory instead.
    - From source: the repository root.
    """
    override = os.environ.get("MAHIRA_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        if sys.platform == "darwin" and ".app/Contents/MacOS" in str(exe_dir):
            return Path.home() / "Library" / "Application Support" / "MAHIRA"
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA")
            if local:
                return Path(local).expanduser().resolve() / "MAHIRA"
        if sys.platform.startswith("linux"):
            xdg_data = os.environ.get("XDG_DATA_HOME")
            base = (
                Path(xdg_data).expanduser()
                if xdg_data
                else Path.home() / ".local" / "share"
            )
            return base.resolve() / "MAHIRA"
        return exe_dir
    return Path(__file__).resolve().parents[2]


def get_paths(project_root: Path | None = None) -> Paths:
    """
    Build the canonical Paths object.

    `project_root` is accepted for backwards compatibility but resources always
    resolve via resource_root() and writable state via data_root(), so the
    packaged app never depends on the current working directory.
    """
    res = resource_root()
    state_dir = (data_root() / STATE_DIRNAME)
    db_path = state_dir / DB_FILENAME
    schema_path = res / "src" / "db" / "schema.sql"
    models_dir = state_dir / "ml_models"
    return Paths(
        project_root=res,
        state_dir=state_dir,
        db_path=db_path,
        schema_path=schema_path,
        models_dir=models_dir,
        settings_path=state_dir / "settings.json",
    )


def migrate_legacy_windows_state(paths: Paths) -> bool:
    """Atomically move pre-0.4 Windows state to per-user app data.

    This must run *before* ``paths.state_dir`` is created. Copying into a
    sibling temporary directory and renaming only after verification means an
    interrupted upgrade cannot leave a half-populated target that suppresses a
    later retry.
    """
    if not (is_frozen() and sys.platform == "win32"):
        return False
    legacy = Path(sys.executable).resolve().parent / STATE_DIRNAME
    target = paths.state_dir.resolve()
    if target.exists() or not legacy.is_dir() or legacy.resolve() == target:
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.migrating-{uuid.uuid4().hex}")
    try:
        shutil.copytree(legacy, temporary)

        for source in legacy.rglob("*"):
            if not source.is_file():
                continue
            copied = temporary / source.relative_to(legacy)
            if not copied.is_file() or copied.stat().st_size != source.stat().st_size:
                raise RuntimeError(f"Legacy state copy verification failed for {source.name}")

        copied_db = temporary / DB_FILENAME
        if copied_db.is_file() and copied_db.stat().st_size:
            uri = f"{copied_db.resolve().as_uri()}?mode=ro"
            check = sqlite3.connect(uri, uri=True, timeout=15.0)
            try:
                row = check.execute("PRAGMA integrity_check").fetchone()
                if not row or str(row[0]).strip().lower() != "ok":
                    raise RuntimeError("Legacy learner database failed its integrity check")
            finally:
                check.close()

        os.replace(temporary, target)
        return True
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
