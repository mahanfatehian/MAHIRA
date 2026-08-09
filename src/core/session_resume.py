from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SESSION_RESUME_VERSION = 1
_MAX_QUEUE_ITEMS = 500
_OBJECTIVES = {"vocab", "grammar", "sentences", "listening"}
_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}


def _plain_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class SessionSnapshot:
    level: str
    objective: str
    book_slug: str
    lektion_number: int
    deck_id: int
    deck_seed_sha1: str
    queue: tuple[int, ...]
    current_item_id: int | None
    current_state_token: str | None
    position: int
    total: int
    study_answered: int
    study_next_milestone: int
    saved_at: int
    session_kind: str = "review"
    practice_mode: str = "recognition"
    version: int = SESSION_RESUME_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "level": self.level,
            "objective": self.objective,
            "book_slug": self.book_slug,
            "lektion_number": self.lektion_number,
            "deck_id": self.deck_id,
            "deck_seed_sha1": self.deck_seed_sha1,
            "queue": list(self.queue),
            "current_item_id": self.current_item_id,
            "current_state_token": self.current_state_token,
            "position": self.position,
            "total": self.total,
            "study_answered": self.study_answered,
            "study_next_milestone": self.study_next_milestone,
            "saved_at": self.saved_at,
            "session_kind": self.session_kind,
            "practice_mode": self.practice_mode,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> SessionSnapshot | None:
        if not isinstance(raw, dict):
            return None

        version = _plain_int(raw.get("version"))
        if version != SESSION_RESUME_VERSION:
            return None

        level_raw = raw.get("level")
        objective_raw = raw.get("objective")
        book_raw = raw.get("book_slug")
        if not isinstance(level_raw, str) or not isinstance(objective_raw, str):
            return None
        if not isinstance(book_raw, str):
            return None

        level = level_raw.strip().upper()
        objective = objective_raw.strip().lower()
        book_slug = book_raw.strip()
        if level not in _LEVELS or objective not in _OBJECTIVES:
            return None
        if len(book_slug) > 128 or any(ord(char) < 32 for char in book_slug):
            return None
        deck_seed_sha1 = raw.get("deck_seed_sha1")
        if not isinstance(deck_seed_sha1, str) or len(deck_seed_sha1) > 128:
            return None
        session_kind = raw.get("session_kind")
        practice_mode = raw.get("practice_mode")
        if session_kind != "review" or practice_mode != "recognition":
            return None

        lektion_number = _plain_int(raw.get("lektion_number"))
        deck_id = _plain_int(raw.get("deck_id"))
        position = _plain_int(raw.get("position"))
        total = _plain_int(raw.get("total"))
        study_answered = _plain_int(raw.get("study_answered"))
        study_next_milestone = _plain_int(raw.get("study_next_milestone"))
        saved_at = _plain_int(raw.get("saved_at"))
        if (
            lektion_number is None
            or not 0 <= lektion_number <= 999
            or deck_id is None
            or deck_id <= 0
            or position is None
            or position < 0
            or total is None
            or not 1 <= total <= _MAX_QUEUE_ITEMS
            or position > total
            or study_answered is None
            or not 0 <= study_answered <= 1_000_000
            or study_next_milestone is None
            or not 30 <= study_next_milestone <= 1_000_020
            or saved_at is None
            or saved_at < 0
        ):
            return None

        queue_raw = raw.get("queue")
        if not isinstance(queue_raw, list) or len(queue_raw) > _MAX_QUEUE_ITEMS:
            return None
        queue: list[int] = []
        seen: set[int] = set()
        for value in queue_raw:
            item_id = _plain_int(value)
            if item_id is None or item_id <= 0 or item_id in seen:
                return None
            seen.add(item_id)
            queue.append(item_id)

        current_raw = raw.get("current_item_id")
        current_item_id = None if current_raw is None else _plain_int(current_raw)
        if current_raw is not None and (
            current_item_id is None
            or current_item_id <= 0
            or current_item_id in seen
        ):
            return None
        if current_item_id is None and not queue:
            return None
        current_state_token = raw.get("current_state_token")
        if current_item_id is None:
            if current_state_token is not None:
                return None
        elif not isinstance(current_state_token, str) or not current_state_token:
            return None
        if isinstance(current_state_token, str) and len(current_state_token) > 256:
            return None
        if position + len(queue) + int(current_item_id is not None) > total:
            return None

        return cls(
            level=level,
            objective=objective,
            book_slug=book_slug,
            lektion_number=lektion_number,
            deck_id=deck_id,
            deck_seed_sha1=deck_seed_sha1,
            queue=tuple(queue),
            current_item_id=current_item_id,
            current_state_token=current_state_token,
            position=position,
            total=total,
            study_answered=study_answered,
            study_next_milestone=study_next_milestone,
            saved_at=saved_at,
        )


class SessionResumeStore:
    """Versioned, atomic JSON storage for one profile's open review session."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()

    def load(self) -> SessionSnapshot | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        snapshot = SessionSnapshot.from_dict(raw)
        if snapshot is None:
            logging.warning("Ignoring invalid session checkpoint: %s", self.path)
        return snapshot

    def save(self, snapshot: SessionSnapshot) -> None:
        validated = SessionSnapshot.from_dict(snapshot.to_dict())
        if validated is None:
            raise ValueError("Refusing to persist an invalid session checkpoint")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(validated.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(self.path.suffix + ".tmp").unlink(missing_ok=True)
