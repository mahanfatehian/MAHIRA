from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROFILE_NAME_MAX_LENGTH = 80
PROFILE_SLUG_MAX_LENGTH = 48
_PROFILE_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class LearnerProfile:
    slug: str
    name: str
    created_at: int


class ProfileService:
    """Learner isolation by database file; default keeps the historic path."""

    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.index_path = self.state_dir / "profiles.json"
        self._profiles = self._load()

    def _load(self) -> list[LearnerProfile]:
        default = LearnerProfile("default", "My learning", 0)
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raw = []

        profiles = [default]
        used = {default.slug}
        if not isinstance(raw, list):
            return profiles

        # Treat each record as untrusted independently: one malformed entry
        # must not discard every valid learner that follows it in the index.
        for record in raw:
            profile = self._profile_from_record(record)
            if profile is None or profile.slug in used:
                continue
            used.add(profile.slug)
            profiles.append(profile)
        return profiles

    @staticmethod
    def _profile_from_record(record: Any) -> LearnerProfile | None:
        if not isinstance(record, dict):
            return None

        slug = record.get("slug")
        if (
            not isinstance(slug, str)
            or len(slug) > PROFILE_SLUG_MAX_LENGTH
            or _PROFILE_SLUG_RE.fullmatch(slug) is None
            or slug == "default"
            or slug in _WINDOWS_RESERVED_NAMES
        ):
            return None

        name = ProfileService._clean_name(record.get("name"))
        if not name:
            return None

        created_at = record.get("created_at")
        if isinstance(created_at, bool):
            return None
        try:
            created_at = int(created_at)
        except (TypeError, ValueError, OverflowError):
            return None
        if created_at < 0:
            return None

        return LearnerProfile(slug, name, created_at)

    @staticmethod
    def _clean_name(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        normalized = " ".join(_CONTROL_CHAR_RE.sub(" ", value).split())
        return normalized[:PROFILE_NAME_MAX_LENGTH].rstrip()

    @staticmethod
    def _slug_base(name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
        base = base[:PROFILE_SLUG_MAX_LENGTH].rstrip("-")
        if not base:
            return "learner"
        if base in _WINDOWS_RESERVED_NAMES:
            return f"learner-{base}"
        return base

    def list(self) -> list[LearnerProfile]:
        return list(self._profiles)

    def create(self, name: str) -> LearnerProfile:
        clean_name = self._clean_name(name)
        if not clean_name:
            raise ValueError("Profile name cannot be empty")
        base = self._slug_base(clean_name)
        slug = base
        used = {p.slug for p in self._profiles}
        index = 2
        while slug in used:
            suffix = f"-{index}"
            prefix = base[: PROFILE_SLUG_MAX_LENGTH - len(suffix)].rstrip("-")
            slug = f"{prefix or 'learner'}{suffix}"
            index += 1
        profile = LearnerProfile(slug, clean_name, int(time.time()))
        self._profiles.append(profile)
        self.save()
        return profile

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temp = self.index_path.with_suffix(".tmp")
        temp.write_text(json.dumps([p.__dict__ for p in self._profiles], indent=2), encoding="utf-8")
        temp.replace(self.index_path)

    def db_path(self, slug: str) -> Path:
        if slug == "default" or not any(p.slug == slug for p in self._profiles):
            return self.state_dir / "mahira.db"
        return self.state_dir / "profiles" / slug / "mahira.db"
