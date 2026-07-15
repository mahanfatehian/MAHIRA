from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


@dataclass
class AppSettings:
    level: str = "A1"
    book_slug: str = ""
    lektion_number: int = 0
    objective: str = "vocab"
    daily_goal: int = 30
    session_limit: int = 30
    new_card_limit: int = 8
    audio_speed: float = 1.0
    audio_autoplay: bool = False
    theme: str = "graphite"
    font_scale: int = 100
    reduced_motion: bool = False
    strict_answers: bool = False
    last_page: str = "today"
    update_checks: bool = False
    window_width: int = 1080
    window_height: int = 820
    active_profile: str = "default"


_INT_RANGES: dict[str, tuple[int, int]] = {
    "lektion_number": (0, 999),
    "daily_goal": (5, 200),
    "session_limit": (5, 100),
    "new_card_limit": (0, 30),
    "font_scale": (90, 130),
    "window_width": (860, 7680),
    "window_height": (680, 4320),
}
_BOOL_FIELDS = {
    "audio_autoplay",
    "reduced_motion",
    "strict_answers",
    "update_checks",
}
_ENUM_FIELDS: dict[str, set[str]] = {
    "level": {"A1", "A2", "B1", "B2", "C1", "C2"},
    "objective": {"vocab", "grammar", "sentences", "listening"},
    "theme": {"graphite", "high_contrast"},
    "last_page": {
        "today",
        "setup",
        "learn",
        "practice",
        "vocab_review",
        "grammar_review",
        "sentence_review",
        "listening_review",
        "vocab_table",
        "conjugation",
        "progress",
        "mistakes",
        "settings",
        "lab",
    },
}
_PROFILE_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_OBJECTIVE_ALIASES = {
    "vocabulary": "vocab",
    "words": "vocab",
    "word": "vocab",
    "sentence": "sentences",
    "sentence_review": "sentences",
}


def _normalized_int(value: Any, default: int, lower: int, upper: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number) or not number.is_integer():
        return default
    return max(lower, min(upper, int(number)))


def _normalized_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    return default


def _normalize_settings(raw: Any, fallback: AppSettings | None = None) -> AppSettings:
    """Return a complete, safe settings value from untrusted JSON data."""
    defaults = fallback or AppSettings()
    if not isinstance(raw, dict):
        return defaults

    data = asdict(defaults)
    for name, (lower, upper) in _INT_RANGES.items():
        if name in raw:
            data[name] = _normalized_int(raw[name], data[name], lower, upper)

    for name in _BOOL_FIELDS:
        if name in raw:
            data[name] = _normalized_bool(raw[name], data[name])

    if "audio_speed" in raw:
        if isinstance(raw["audio_speed"], bool):
            speed = defaults.audio_speed
        else:
            try:
                speed = float(raw["audio_speed"])
            except (TypeError, ValueError, OverflowError):
                speed = defaults.audio_speed
        data["audio_speed"] = speed if speed in {0.75, 1.0, 1.25} else defaults.audio_speed

    for name, allowed in _ENUM_FIELDS.items():
        value = raw.get(name)
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if name == "level":
            normalized = normalized.upper()
        else:
            normalized = normalized.casefold()
        if name == "objective":
            normalized = _OBJECTIVE_ALIASES.get(normalized, normalized)
        if normalized in allowed:
            data[name] = normalized

    book_slug = raw.get("book_slug")
    if isinstance(book_slug, str):
        data["book_slug"] = book_slug.strip()[:128]

    active_profile = raw.get("active_profile")
    if isinstance(active_profile, str):
        active_profile = active_profile.strip().casefold()
        if _PROFILE_SLUG_RE.fullmatch(active_profile):
            data["active_profile"] = active_profile

    return AppSettings(**data)


class SettingsService:
    """Atomic JSON preferences; learning history remains in SQLite."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self._settings = self._load()

    @property
    def value(self) -> AppSettings:
        return self._settings

    def _load(self) -> AppSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return AppSettings()
        return _normalize_settings(raw)

    def update(self, **changes: Any) -> AppSettings:
        allowed = {f.name for f in fields(AppSettings)}
        current = asdict(self._settings)
        current.update({key: value for key, value in changes.items() if key in allowed})
        self._settings = _normalize_settings(current, fallback=self._settings)
        self.save()
        return self._settings

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(asdict(self._settings), indent=2), encoding="utf-8")
        temp.replace(self.path)
