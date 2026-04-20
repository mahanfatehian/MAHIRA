# src/mahira/__main__.py
from __future__ import annotations

import argparse
import sys
import traceback
import faulthandler
from pathlib import Path

from mahira.app import run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", default=None)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    state_dir = project_root / ".mahira"
    state_dir.mkdir(parents=True, exist_ok=True)

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