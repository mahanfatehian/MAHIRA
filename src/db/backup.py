from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created_at: int
    size_bytes: int
    reason: str


class BackupService:
    """Consistent SQLite backups plus small, human-readable metadata sidecars."""

    def __init__(self, db_path: str | Path, backup_dir: str | Path | None = None):
        self.db_path = Path(db_path).expanduser().resolve()
        self.backup_dir = (
            Path(backup_dir).expanduser().resolve()
            if backup_dir is not None
            else self.db_path.parent / "backups"
        )

    def create(
        self,
        reason: str = "manual",
        *,
        prune: bool = True,
    ) -> BackupInfo | None:
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        safe_reason = "".join(c if c.isalnum() or c in "-_" else "-" for c in reason).strip("-")
        stem = f"mahira-{stamp}-{safe_reason or 'backup'}"
        target = self.backup_dir / f"{stem}.db"
        sequence = 2
        while target.exists():
            target = self.backup_dir / f"{stem}-{sequence}.db"
            sequence += 1
        partial = target.with_name(target.name + ".partial")

        source = destination = None
        try:
            source = sqlite3.connect(str(self.db_path), timeout=15.0)
            destination = sqlite3.connect(str(partial), timeout=15.0)
            try:
                source.execute("PRAGMA busy_timeout=15000")
                destination.execute("PRAGMA busy_timeout=15000")
                with destination:
                    source.backup(destination, pages=256, sleep=0.05)
                row = destination.execute("PRAGMA integrity_check").fetchone()
                if not row or str(row[0]).lower() != "ok":
                    raise RuntimeError(f"Backup integrity check failed: {row!r}")
                violations = destination.execute("PRAGMA foreign_key_check").fetchmany(10)
                if violations:
                    raise RuntimeError(
                        f"Backup contains foreign-key violations: {violations!r}"
                    )
            finally:
                if destination is not None:
                    destination.close()
                if source is not None:
                    source.close()
        except Exception:
            partial.unlink(missing_ok=True)
            raise

        try:
            os.replace(partial, target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

        meta = {"created_at": now, "reason": reason, "source": str(self.db_path)}
        sidecar = target.with_suffix(".json")
        sidecar_temp = sidecar.with_suffix(".json.tmp")
        try:
            sidecar_temp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            os.replace(sidecar_temp, sidecar)
        except Exception:
            sidecar_temp.unlink(missing_ok=True)
            raise
        if prune:
            self.prune()
        return BackupInfo(target, now, target.stat().st_size, reason)

    def list(self) -> list[BackupInfo]:
        if not self.backup_dir.exists():
            return []
        result: list[BackupInfo] = []
        for path in self.backup_dir.glob("mahira-*.db"):
            reason = "backup"
            created_at = int(path.stat().st_mtime)
            sidecar = path.with_suffix(".json")
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    reason = str(data.get("reason") or reason)
                    created_at = int(data.get("created_at") or created_at)
            except (OSError, ValueError, TypeError):
                pass
            result.append(BackupInfo(path, created_at, path.stat().st_size, reason))
        return sorted(result, key=lambda item: item.created_at, reverse=True)

    def restore(self, backup_path: str | Path) -> None:
        source_path = Path(backup_path).expanduser().resolve()
        if source_path.parent != self.backup_dir or not source_path.is_file():
            raise ValueError("Backup must be one of MAHIRA's managed backup files")
        check = sqlite3.connect(str(source_path), timeout=15.0)
        try:
            row = check.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                raise RuntimeError("The selected backup is damaged")
            if check.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeError("The selected backup has broken relationships")
        finally:
            check.close()
        # Keep the selected source available while taking the safety snapshot.
        # If retention is already full and this is the oldest backup, pruning
        # here would delete it before sqlite3.connect() opens it.
        self.create("before-restore", prune=False)
        source = sqlite3.connect(str(source_path), timeout=15.0)
        destination = sqlite3.connect(str(self.db_path), timeout=15.0)
        try:
            source.execute("PRAGMA busy_timeout=15000")
            destination.execute("PRAGMA busy_timeout=15000")
            with destination:
                source.backup(destination, pages=256, sleep=0.05)
            row = destination.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                raise RuntimeError("The restored database failed its integrity check")
            if destination.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeError("The restored database has broken relationships")
        finally:
            destination.close()
            source.close()
        self.prune()

    def prune(self, keep: int = 12) -> None:
        for item in self.list()[max(1, int(keep)) :]:
            item.path.unlink(missing_ok=True)
            item.path.with_suffix(".json").unlink(missing_ok=True)
