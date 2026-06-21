# src/mahira/__main__.py
from __future__ import annotations

import argparse
import os
import sys
import traceback
import faulthandler
from pathlib import Path

# Silence Qt Multimedia's informational FFmpeg banner on startup
# ("qt.multimedia.ffmpeg: Using Qt multimedia with FFmpeg version ..."). It is
# not an error. Must be set BEFORE any Qt module is imported. Real warnings and
# errors from the multimedia backend are preserved.
_rules = os.environ.get("QT_LOGGING_RULES", "")
if "qt.multimedia.ffmpeg" not in _rules:
    os.environ["QT_LOGGING_RULES"] = (
        _rules + ";qt.multimedia.ffmpeg.info=false;qt.multimedia.ffmpeg.debug=false"
    ).strip(";")

from mahira.app import run
from mahira.config import data_root, resource_root, STATE_DIRNAME


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", default=None)
    args = parser.parse_args()

    # Resources are read from the bundle; all writable state stays inside the
    # installation folder (data_root) so nothing lands in user/OS locations.
    project_root = resource_root()
    state_dir = data_root() / STATE_DIRNAME
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # The resolved state dir isn't writable (e.g. a read-only or translocated
        # install). Fall back to a temp dir so the app can still launch and write
        # a crash log, instead of dying silently before the excepthook below is
        # even installed. Point the rest of the app at the same dir.
        import tempfile

        fallback = Path(tempfile.gettempdir()) / "MAHIRA"
        state_dir = fallback / STATE_DIRNAME
        state_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MAHIRA_DATA_DIR"] = str(fallback)

    log_path = state_dir / "crash.log"
    _log = open(log_path, "a", encoding="utf-8")
    faulthandler.enable(file=_log, all_threads=True)

    def _excepthook(t, v, tb):
        _log.write("\n\n=== UNCAUGHT EXCEPTION ===\n")
        traceback.print_exception(t, v, tb, file=_log)
        _log.flush()
        sys.__excepthook__(t, v, tb)

    sys.excepthook = _excepthook

    raise SystemExit(run(project_root=project_root, start_page=args.page))


if __name__ == "__main__":
    main()