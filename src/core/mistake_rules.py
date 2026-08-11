from __future__ import annotations

from dataclasses import dataclass


TAG_LABELS = {
    'meaning': 'meaning',
    'gender': 'noun gender',
    'plural': 'plural form',
    "capitalization": "capitalization",
    "article_missing": "missing article",
    "article": "article or case",
    "word_order": "word order",
    "punctuation": "punctuation",
    "spelling": "spelling",
    "different_answer": "answer mismatch",
}


@dataclass(frozen=True)
class LearnReference:
    level: str
    order_token: str
    label: str


# Only unambiguous links belong here.  In particular, ``article`` may indicate
# gender or any one of several cases, so routing it to one lesson would guess.
LEARN_REFERENCE_BY_ERROR_TAG = {
    'gender': LearnReference('A1', '1.4', 'Review noun gender'),
    'plural': LearnReference('A1', '1.2', 'Review plural forms'),
    "article_missing": LearnReference("A1", "1.1", "Review articles"),
    "word_order": LearnReference("A1", "4.1", "Review word order"),
}


def error_tags(value: str | None) -> tuple[str, ...]:
    """Return normalized, de-duplicated persisted error tags."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in str(value or "").split(","):
        tag = raw.strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return tuple(result)


def tag_label(tag: str) -> str:
    normalized = str(tag or "").strip().lower()
    return TAG_LABELS.get(normalized, normalized.replace("_", " "))


def learn_reference_for_tags(value: str | None) -> LearnReference | None:
    """Resolve the first exact rule link; unknown/ambiguous tags fail closed."""
    for tag in error_tags(value):
        reference = LEARN_REFERENCE_BY_ERROR_TAG.get(tag)
        if reference is not None:
            return reference
    return None
