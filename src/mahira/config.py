# src/mahira/config.py
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "mahira"
APP_AUTHOR = "mahira"
DB_FILENAME = "mahira.db"

# Folder (next to the executable / repo root) that holds ALL writable runtime
# state. Everything MAHIRA generates lives under <data_root>/.mahira so the app
# is fully self-contained — nothing is written to %APPDATA%, ~/Library, or any
# other per-user/OS location.
STATE_DIRNAME = ".mahira"


@dataclass(frozen=True)
class Paths:
    project_root: Path   # read-only resource root (bundled data/assets/schema)
    state_dir: Path      # writable runtime dir (db, ml models, logs)
    db_path: Path
    schema_path: Path
    models_dir: Path


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
    Root for WRITABLE runtime state. Resolved so the app is portable and keeps
    everything inside the installation folder:

    - MAHIRA_DATA_DIR env var wins (lets advanced users relocate state).
    - Frozen: the directory that contains the executable (the install folder).
    - From source: the repository root.
    """
    override = os.environ.get("MAHIRA_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
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
    )
