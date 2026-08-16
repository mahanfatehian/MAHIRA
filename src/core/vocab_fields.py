from __future__ import annotations

from typing import Any


_UNAVAILABLE_VALUES = {"-", "--", "—", "–"}


def usable_vocab_value(value: Any) -> str | None:
    """Return a trimmed vocab value, or None for blanks and legacy dashes."""
    text = str(value or "").strip()
    return text if text and text not in _UNAVAILABLE_VALUES else None


def noun_vocab_value(pos: Any, value: Any) -> str | None:
    """Return a usable value only when it belongs to a noun."""
    if str(pos or "").strip().casefold() != "noun":
        return None
    return usable_vocab_value(value)


def noun_declension_values(
    pos: Any,
    article: Any = None,
    gender: Any = None,
    plural: Any = None,
) -> tuple[str | None, str | None, str | None]:
    """Article, gender, and plural are meaningful only for nouns."""
    return (
        noun_vocab_value(pos, article),
        noun_vocab_value(pos, gender),
        noun_vocab_value(pos, plural),
    )
