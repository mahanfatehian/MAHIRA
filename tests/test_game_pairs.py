"""Blitz pair/wave construction: derive the right pairs from vocab and never let
two identical circle captions land in the same wave."""

import random

from core.game.pairs import (
    ARTICLE,
    MEANING,
    PLURAL,
    build_pairs,
    make_waves,
)


def _vocab(id, word, *, pos="noun", article="", gender="", plural="", meaning=""):
    return {
        "id": id,
        "word": word,
        "pos": pos,
        "article": article,
        "gender": gender,
        "plural": plural,
        "meaning": meaning,
    }


def test_noun_yields_article_plural_and_meaning_pairs():
    items = [_vocab(1, "Zug", article="der", plural="Züge", meaning="train")]
    pairs = build_pairs(items)
    kinds = {p.kind for p in pairs}
    assert kinds == {ARTICLE, PLURAL, MEANING}

    by_kind = {p.kind: p for p in pairs}
    assert by_kind[ARTICLE].a == "der" and by_kind[ARTICLE].b == "Zug"
    assert by_kind[PLURAL].a == "Zug" and by_kind[PLURAL].b == "Züge"
    assert by_kind[MEANING].a == "Zug" and by_kind[MEANING].b == "train"
    assert all(p.vocab_id == 1 and p.word == "Zug" for p in pairs)


def test_article_is_derived_from_gender_when_missing():
    items = [_vocab(2, "Haus", article="", gender="n", plural="Häuser", meaning="house")]
    art = [p for p in build_pairs(items) if p.kind == ARTICLE]
    assert len(art) == 1 and art[0].a == "das"


def test_non_noun_with_only_meaning_yields_one_pair():
    items = [_vocab(3, "gehen", pos="verb", meaning="to go")]
    pairs = build_pairs(items)
    assert len(pairs) == 1
    assert pairs[0].kind == MEANING and pairs[0].b == "to go"


def test_meaning_takes_first_sense_only():
    items = [_vocab(4, "Bank", article="die", meaning="bench; bank")]
    meaning = [p for p in build_pairs(items) if p.kind == MEANING][0]
    assert meaning.b == "bench"


def test_degenerate_fields_are_skipped():
    # No word -> nothing; plural == word -> no plural pair; empty meaning -> none.
    assert build_pairs([_vocab(5, "")]) == []
    pairs = build_pairs([_vocab(6, "Auto", article="das", plural="Auto", meaning="")])
    assert {p.kind for p in pairs} == {ARTICLE}


def test_dash_sentinel_never_becomes_a_pair():
    # Seeds use "-" for "no plural" (verbs/adjectives, invariant nouns). It must
    # never produce a (word, "-") circle to connect.
    items = [
        _vocab(7, "laufen", pos="verb", plural="-", meaning="to run"),
        _vocab(8, "Musik", article="die", plural="-", meaning="music"),
        _vocab(9, "schön", pos="adj", plural="–", meaning="-"),  # en-dash + dash meaning
    ]
    pairs = build_pairs(items)
    captions = [c for p in pairs for c in (p.a, p.b)]
    assert not any(cap in {"-", "--", "–", "—"} for cap in captions), captions
    # laufen/Musik still yield their meaning (and Musik its article); schön yields nothing.
    kinds = {(p.word, p.kind) for p in pairs}
    assert ("laufen", MEANING) in kinds
    assert ("Musik", MEANING) in kinds and ("Musik", ARTICLE) in kinds
    assert all(w != "schön" for (w, _k) in kinds)


def test_waves_have_unique_captions_and_cover_all_pairs():
    rng = random.Random(1234)
    # Several nouns that all share the article "der" — the collision stress test.
    items = [
        _vocab(i, w, article="der", plural=w + "e", meaning=f"m{i}")
        for i, w in enumerate(["Zug", "Tisch", "Stuhl", "Hund", "Ball", "Baum"], start=1)
    ]
    pairs = build_pairs(items)
    waves = make_waves(pairs, wave_size=3, rng=rng)

    # Every pair placed exactly once.
    placed = [p for wave in waves for p in wave]
    assert len(placed) == len(pairs)
    assert {id(p) for p in placed} == {id(p) for p in pairs}

    for wave in waves:
        assert len(wave) <= 3
        captions = [c for p in wave for c in (p.a, p.b)]
        assert len(captions) == len(set(captions)), f"ambiguous wave: {captions}"
