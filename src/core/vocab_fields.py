from __future__ import annotations

import re
from typing import Any


_UNAVAILABLE_VALUES = {"-", "--", "—", "–"}

# Article cells hold one article ("die") or an alternation ("der/die",
# "das/der"). Both spellings occur in the shipped content.
_ARTICLE_SPLIT = re.compile(r"\s*/\s*")

# Anything outside this set is content we did not anticipate. Speaking it
# unchecked risks the voice reading punctuation aloud, so such a row falls
# back to the bare noun.
_SPEAKABLE_ARTICLES = {"der", "die", "das"}


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


def spoken_article(pos: Any, article: Any) -> str | None:
    """The article of a noun, phrased so a speech model reads it naturally.

    "der/die" becomes "der oder die", which is how a German speaker reads the
    slash. Returns None when the row has no article to speak: a non-noun, a
    blank, a legacy dash, or an unrecognised value.
    """
    raw = noun_vocab_value(pos, article)
    if raw is None:
        return None

    parts: list[str] = []
    for candidate in _ARTICLE_SPLIT.split(raw):
        word = candidate.strip()
        if not word:
            continue
        if word.casefold() not in _SPEAKABLE_ARTICLES:
            return None
        if word.casefold() not in {existing.casefold() for existing in parts}:
            parts.append(word)
    if not parts:
        return None
    return " oder ".join(parts)


def spoken_vocab_text(word: Any, pos: Any = None, article: Any = None) -> str:
    """What the voice should say for one vocabulary row.

    A German noun is only half-learned without its gender, so a noun is spoken
    with its article ("das Haus", not "Haus"). Everything else - verbs,
    adjectives, phrases - is spoken exactly as written.
    """
    text = str(word or "").strip()
    if not text:
        return ""
    prefix = spoken_article(pos, article)
    return f"{prefix} {text}" if prefix else text
