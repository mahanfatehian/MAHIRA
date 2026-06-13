# src/mahira/app.py
from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

# Quiet Qt Multimedia's informational FFmpeg banner (see __main__.py). Harmless
# if already set there; this covers callers that invoke run() directly.
_rules = os.environ.get("QT_LOGGING_RULES", "")
if "qt.multimedia.ffmpeg" not in _rules:
    os.environ["QT_LOGGING_RULES"] = (
        _rules + ";qt.multimedia.ffmpeg.info=false;qt.multimedia.ffmpeg.debug=false"
    ).strip(";")

from PySide6.QtWidgets import QApplication

from mahira.config import get_paths
from db.init_db import init_db
from db.repo import Repo
from db.seed_loader import load_all_seeds
from core.session import SessionService, AppState
from ui.main_window import MainWindow
from PySide6.QtGui import QIcon

def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run(project_root: Path, start_page: str | None = None) -> int:
    paths = get_paths(project_root)
    _setup_logging(paths.state_dir / "run.log")

    logging.info("=== MAHIRA START ===")


    try:
        # 1) schema + migrations
        init_db(paths.db_path, paths.schema_path)

        # 2) import seeds
        repo = Repo(paths.db_path)
        load_all_seeds(repo, paths.project_root)

        # 3) ✅ run again so sentence repairs happen AFTER import too
        init_db(paths.db_path, paths.schema_path)


        app = QApplication(sys.argv)
        from PySide6.QtGui import QIcon

        try:
            icon_path = paths.project_root / "assets" / "logo.ico"
            if icon_path.exists():
                app.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            logging.exception("Failed to set app icon")
        state = AppState()
        session = SessionService(repo, state)
        win = MainWindow(session=session, start_page=start_page)
        win.show()
        return app.exec()

    except Exception:
        logging.error("Fatal error:\n%s", traceback.format_exc())
        return 1