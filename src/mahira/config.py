# src/mahira/config.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

try:
    # Optional fallback if project folder is read-only (packaged apps etc.)
    from platformdirs import user_data_dir
except Exception:  # pragma: no cover
    user_data_dir = None


APP_NAME = "mahira"
APP_AUTHOR = "mahira"
DB_FILENAME = "mahira.db"


@dataclass(frozen=True)
class Paths:
    project_root: Path
    state_dir: Path
    db_path: Path
    schema_path: Path
    models_dir: Path


def _detect_project_root() -> Path:
    """
    Assumes repo structure:
      <root>/src/mahira/config.py
    """
    here = Path(__file__).resolve()
    # config.py -> mahira -> src -> <root>
    return here.parents[2]


def get_paths(project_root: Path) -> Paths:
    project_root = Path(project_root).expanduser().resolve()
    state_dir = project_root / ".mahira"
    db_path = state_dir / "mahira.db"
    schema_path = project_root / "src" / "db" / "schema.sql"
    models_dir = state_dir / "ml_models"
    return Paths(
        project_root=project_root,
        state_dir=state_dir,
        db_path=db_path,
        schema_path=schema_path,
        models_dir=models_dir,
    )
