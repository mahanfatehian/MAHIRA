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

from mahira.config import (
    STATE_DIRNAME,
    get_paths,
    migrate_legacy_windows_state,
    resource_root,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", default=None)
    parser.add_argument("--health-check", action="store_true")
    commands = parser.add_subparsers(dest="command")
    validate_parser = commands.add_parser(
        "validate-seeds",
        help="validate seed CSVs without changing learner data",
    )
    validate_parser.add_argument(
        "seed_root",
        nargs="?",
        type=Path,
        help="seed directory (defaults to the bundled data/seeds directory)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-seeds":
        # Keep authoring tools independent from Qt and learner state. In
        # particular, this branch must run before importing mahira.app or
        # resolving/creating the writable .mahira directory.
        from db.seed_validation import validate_seed_tree

        seed_root = args.seed_root or (resource_root() / "data" / "seeds")
        try:
            report = validate_seed_tree(seed_root)
        except (OSError, ValueError) as exc:
            print(f"validate-seeds: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        print(report.render())
        raise SystemExit(0 if report.ok else 1)

    # Resources are read from the bundle; writable learner state lives in the
    # platform's per-user application-data directory. The Windows legacy move
    # must happen before creating the target directory or it can never run.
    project_root = resource_root()
    paths = get_paths(project_root)
    bootstrap_error = ""
    try:
        migrate_legacy_windows_state(paths)
        state_dir = paths.state_dir
    except Exception:
        # Do not create the intended target after a failed migration: doing so
        # would make the next launch look migrated. Use temp for the crash log
        # only; run() retries and reports the migration failure safely.
        import tempfile

        bootstrap_error = traceback.format_exc()
        state_dir = Path(tempfile.gettempdir()) / "MAHIRA-bootstrap" / STATE_DIRNAME
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
    if bootstrap_error:
        _log.write("\n\n=== STATE MIGRATION ERROR ===\n")
        _log.write(bootstrap_error)
        _log.flush()
    faulthandler.enable(file=_log, all_threads=True)

    def _excepthook(t, v, tb):
        _log.write("\n\n=== UNCAUGHT EXCEPTION ===\n")
        traceback.print_exception(t, v, tb, file=_log)
        _log.flush()
        sys.__excepthook__(t, v, tb)

    sys.excepthook = _excepthook

    # Import the Qt application only for GUI and packaged health-check paths;
    # validate-seeds intentionally remains a lightweight standard-library CLI.
    from mahira.app import health_check, run

    if args.health_check:
        raise SystemExit(health_check(project_root))

    raise SystemExit(run(project_root=project_root, start_page=args.page))


if __name__ == "__main__":
    main()
