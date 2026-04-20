# src/mahira/app.py
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

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
    logging.info("sys.executable: %s", sys.executable)
    logging.info("project_root: %s", paths.project_root)
    logging.info("db_path: %s", paths.db_path)
    logging.info("schema_path: %s", paths.schema_path)
    logging.info("models_dir: %s", paths.models_dir)

    try:
        # 1) schema + migrations
        init_db(paths.db_path, paths.schema_path)

        # 2) import seeds
        repo = Repo(paths.db_path)
        load_all_seeds(repo, paths.project_root)

        # 3) ✅ run again so sentence repairs happen AFTER import too
        init_db(paths.db_path, paths.schema_path)

        # sanity logging
        try:
            with repo._conn() as conn:
                t = [r["name"] for r in conn.execute(
                    "select name from sqlite_master where type='table'"
                ).fetchall()]
                logging.info("tables: %s", t)

                if "sentences" in t:
                    c = conn.execute("select count(*) c from sentences").fetchone()["c"]
                    logging.info("sentences rows: %s", c)
                    sample = conn.execute(
                        "select target_text, words_json from sentences limit 1"
                    ).fetchone()
                    logging.info("sample sentence: %r", (sample["target_text"] if sample else None))
                    logging.info("sample words_json: %r", (sample["words_json"] if sample else None))
        except Exception:
            logging.exception("DB sanity check failed")

        app = QApplication(sys.argv)
        from PySide6.QtGui import QIcon

        try:
            icon_path = paths.project_root / "mahira" / "assets" / "logo.ico"
            if not icon_path.exists():
                icon_path = paths.project_root / "src" / "mahira" / "assets" / "logo.ico"
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