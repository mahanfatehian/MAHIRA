"""Build connectable circle-pairs from a Lektion's vocab, and shuffle them into
ambiguity-free waves.

A *pair* is two circles the player connects: an article and its noun, a noun and
its plural, or a word and its meaning. A *wave* is a small set of pairs shown at
once. The one hard rule when composing a wave: **no circle text may repeat
inside a wave** — otherwise two identical "der" circles would make the correct
connection a coin-flip instead of a recall test.
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass

ARTICLE = "article"
PLURAL = "plural"
MEANING = "meaning"

# The three German definite articles, used both to emit article pairs and to
# derive an article from a bare grammatical gender (m/f/n).
_ARTICLES = frozenset({"der", "die", "das"})
# Seed CSVs use a bare dash as the "not applicable" sentinel (every verb/adjective
# plural, invariant nouns, etc.) — never a real caption to connect to. Kept to the
# unambiguous dash variants so a real word (e.g. the interjection "na") survives.
_SENTINELS = frozenset({"-", "--", "---", "–", "—"})
_GENDER_TO_ARTICLE = {
    "m": "der", "masc": "der", "masculine": "der",
    "f": "die", "fem": "die", "feminine": "die",
    "n": "das", "neut": "das", "neuter": "das",
}


@dataclass(frozen=True)
class Pair:
    """One connectable pair. `a`/`b` are the two circle captions; `kind` is what
    relationship the player is practising; `word` is the German headword (used
    for optional text-to-speech reinforcement on a correct connect)."""

    a: str
    b: str
    kind: str
    vocab_id: int
    word: str


def _get(item, name: str):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _clean(value) -> str:
    text = ("" if value is None else str(value)).strip()
    # Treat sentinel placeholders as absent so we never ask the player to connect
    # a word to a "-" circle.
    return "" if text.lower() in _SENTINELS else text


def _first_sense(meaning) -> str:
    """Vocab meanings can stack senses ("train; railway"). For a snappy circle we
    take only the first, keeping multi-word senses ("to get up") intact."""
    text = _clean(meaning)
    if not text:
        return ""
    for sep in (";", "/", "|"):
        if sep in text:
            return text.split(sep)[0].strip()
    # A trailing-comma list ("car, automobile") -> first sense; but never split a
    # single sense that merely contains a comma clause.
    if "," in text and len(text) > 24:
        return text.split(",")[0].strip()
    return text


def _article_for(item) -> str:
    article = _clean(_get(item, "article")).lower()
    if article in _ARTICLES:
        return article
    gender = _clean(_get(item, "gender")).lower()
    return _GENDER_TO_ARTICLE.get(gender, "")


def build_pairs(items) -> list[Pair]:
    """Derive every candidate pair from `items` (vocab rows: objects or dicts
    with word / pos / article / gender / plural / meaning)."""
    pairs: list[Pair] = []
    for item in items:
        word = _clean(_get(item, "word"))
        if not word:
            continue

        try:
            vid = int(_get(item, "id"))
        except (TypeError, ValueError):
            vid = 0

        article = _article_for(item)
        if article:
            pairs.append(Pair(article, word, ARTICLE, vid, word))

        plural = _clean(_get(item, "plural"))
        if plural and plural.lower() != word.lower():
            pairs.append(Pair(word, plural, PLURAL, vid, word))

        meaning = _first_sense(_get(item, "meaning"))
        if meaning and meaning.lower() != word.lower():
            pairs.append(Pair(word, meaning, MEANING, vid, word))

    return pairs


def make_waves(pairs, wave_size: int = 3, rng=None) -> list[list[Pair]]:
    """Shuffle `pairs` into waves of up to `wave_size`, guaranteeing that the
    circle captions within any single wave are all distinct (so a connection is
    never ambiguous). Pairs that can't fit the current wave roll forward."""
    rng = rng or _random
    pool = list(pairs)
    rng.shuffle(pool)

    waves: list[list[Pair]] = []
    while pool:
        wave: list[Pair] = []
        used: set[str] = set()
        leftover: list[Pair] = []
        for pair in pool:
            if len(wave) >= wave_size or pair.a in used or pair.b in used:
                leftover.append(pair)
                continue
            wave.append(pair)
            used.add(pair.a)
            used.add(pair.b)
        if not wave:
            # Pathological: every remaining pair collides with itself somehow.
            break
        waves.append(wave)
        pool = leftover
    return waves
