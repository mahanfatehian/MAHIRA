# src/mahira/app.py
from __future__ import annotations

import logging
import os
import sys
import traceback
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Quiet Qt Multimedia's informational FFmpeg banner (see __main__.py). Harmless
# if already set there; this covers callers that invoke run() directly.
_rules = os.environ.get("QT_LOGGING_RULES", "")
if "qt.multimedia.ffmpeg" not in _rules:
    os.environ["QT_LOGGING_RULES"] = (
        _rules + ";qt.multimedia.ffmpeg.info=false;qt.multimedia.ffmpeg.debug=false"
    ).strip(";")

from PySide6.QtWidgets import QApplication, QSplashScreen

from mahira.config import get_paths, migrate_legacy_windows_state
from db.init_db import init_db
from db.repo import Repo
from db.seed_loader import load_all_seeds
from core.session import SessionService, AppState
from ui.main_window import MainWindow
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtCore import Qt
from core.settings import SettingsService
from core.profiles import ProfileService
from ui.theme import COLORS, apply_application_theme

def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_path,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    ]
    # GUI bundles are built with console=False and can expose stdout as None.
    # Attaching a StreamHandler in that state causes logging errors precisely
    # when startup diagnostics are most important.
    if sys.stdout is not None and callable(getattr(sys.stdout, "write", None)):
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def _startup_splash() -> QSplashScreen:
    canvas = QPixmap(560, 260)
    canvas.fill(QColor(COLORS["canvas"]))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(COLORS["action_focus"]))
    painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
    painter.drawText(34, 52, "MAHIRA · DEUTSCH LERNEN")
    painter.setPen(QColor(COLORS["text_primary"]))
    painter.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
    painter.drawText(34, 112, "Your memory workspace")
    painter.setPen(QColor(COLORS["text_secondary"]))
    painter.setFont(QFont("Segoe UI", 11))
    painter.drawText(34, 150, "Preparing the offline library and review schedule…")
    painter.setPen(QColor(COLORS["outline"]))
    painter.drawLine(34, 188, 526, 188)
    painter.end()
    splash = QSplashScreen(canvas)
    splash.setAccessibleName("MAHIRA startup status")
    return splash


def run(project_root: Path, start_page: str | None = None) -> int:
    app = None
    try:
        paths = get_paths(project_root)
        migrate_legacy_windows_state(paths)
        _setup_logging(paths.state_dir / "run.log")
        logging.info("=== MAHIRA START ===")

        app = QApplication(sys.argv)
        splash = _startup_splash()
        splash.show()
        app.processEvents()
        settings = SettingsService(paths.settings_path)
        profiles = ProfileService(paths.state_dir)
        paths = replace(paths, db_path=profiles.db_path(settings.value.active_profile))

        splash.showMessage(
            "  Checking learner data…",
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            QColor(COLORS["text_secondary"]),
        )
        app.processEvents()
        init_db(paths.db_path, paths.schema_path)

        splash.showMessage(
            "  Reading the study library…",
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            QColor(COLORS["text_secondary"]),
        )
        app.processEvents()
        repo = Repo(paths.db_path)
        load_all_seeds(repo, paths.project_root)

        # 3) ✅ run again so sentence repairs happen AFTER import too
        init_db(paths.db_path, paths.schema_path)

        try:
            icon_path = paths.project_root / "assets" / "logo.ico"
            if icon_path.exists():
                app.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            logging.exception("Failed to set app icon")
        prefs = settings.value
        state = AppState(
            level=prefs.level,
            objective=prefs.objective,
            book_slug=prefs.book_slug,
            lektion_number=prefs.lektion_number,
        )
        session = SessionService(repo, state)
        session.settings = settings
        session.profiles = profiles
        session.plan.limit = prefs.session_limit
        session.plan.new_limit = prefs.new_card_limit
        apply_application_theme(app, prefs.font_scale, prefs.theme)
        win = MainWindow(session=session, start_page=start_page or prefs.last_page)
        win.show()
        splash.finish(win)
        return app.exec()

    except Exception:
        logging.error("Fatal error:\n%s", traceback.format_exc())
        try:
            # Migration/logging can fail before the normal QApplication is
            # created. A tiny fallback instance keeps frozen GUI builds from
            # failing silently when no console is attached.
            if app is None:
                app = QApplication.instance() or QApplication(["mahira-startup-error"])
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(
                None,
                "MAHIRA could not start",
                "Your learning database was not discarded. Open the data "
                "folder's run.log (or the MAHIRA-bootstrap crash log) for details.",
            )
        except Exception:
            pass
        return 1


def health_check(project_root: Path) -> int:
    """Non-interactive packaged-build check used by Windows and macOS CI."""
    try:
        paths = get_paths(project_root)
        init_db(paths.db_path, paths.schema_path)
        repo = Repo(paths.db_path)
        load_all_seeds(repo, paths.project_root)
        with repo._conn() as conn:
            if int(conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0]) <= 0:
                raise RuntimeError("No decks were imported")

        required_assets = {
            "MiniLM model": (
                paths.project_root
                / "assets/models/all-MiniLM-L12-v2/model.onnx",
                30_000_000,
            ),
            "MiniLM tokenizer": (
                paths.project_root
                / "assets/models/all-MiniLM-L12-v2/tokenizer.json",
                500_000,
            ),
            "Piper voice": (
                paths.project_root
                / "assets/models/piper/de_DE-thorsten-high.onnx",
                100_000_000,
            ),
            "Piper voice config": (
                paths.project_root
                / "assets/models/piper/de_DE-thorsten-high.onnx.json",
                1_000,
            ),
            "conjugation database": (
                paths.project_root / "assets/data/german_verbs.sqlite",
                500_000,
            ),
        }
        for label, (path, minimum_size) in required_assets.items():
            if not path.is_file() or path.stat().st_size < minimum_size:
                raise RuntimeError(f"Bundled {label} is missing or incomplete: {path}")

        # Verify the packaged native libraries can open the actual assets, not
        # merely that PyInstaller copied files with plausible sizes.
        from core.semantic_match import SemanticMatcher
        from core.audio import PiperModelManager

        if not SemanticMatcher(
            paths.project_root / "assets/models/all-MiniLM-L12-v2"
        ).available():
            raise RuntimeError("The bundled MiniLM ONNX model could not be loaded")
        PiperModelManager().get_german_voice()

        # Exercise Qt's packaged platform plugin as well as Python imports.
        health_app = QApplication.instance()
        owns_app = health_app is None
        if health_app is None:
            health_app = QApplication(["mahira-health-check"])
        probe = QPixmap(2, 2)
        if probe.isNull():
            raise RuntimeError("Qt could not create a native image surface")
        health_app.processEvents()
        if owns_app:
            health_app.quit()
        return 0
    except Exception:
        traceback.print_exc()
        return 1
