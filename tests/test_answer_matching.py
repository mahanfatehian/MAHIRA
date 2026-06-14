"""Answer matching: multi-separator alternatives, infinitive/article normalization,
typo tolerance, and the precision guards."""

from types import SimpleNamespace

from core.session import (
    _answer_matches,
    _fuzzy_equal,
    _grammar_correct,
    _norm,
    _split_answers,
)


def test_norm_strips_infinitive_and_articles():
    assert _norm("to work") == "work"
    assert _norm("a house") == "house"
    assert _norm("an apple") == "apple"
    assert _norm("the cat") == "cat"
    # Bare "to" is not a prefix and must survive.
    assert _norm("to") == "to"


def test_norm_drops_parentheticals():
    assert _norm("leaf (botany)") == "leaf"


def test_split_answers_multi_separator():
    # Alternatives are split out AND the whole phrase is kept as a fallback.
    assert _split_answers("leaf / paper") == ["leaf", "paper", "leaf paper"]
    assert _split_answers("bist; seid") == ["bist", "seid", "bist seid"]
    assert _split_answers("to get up, to rise") == ["get up", "rise", "get up to rise"]


def test_blatt_partial_gloss_matches():
    accepted = _split_answers("leaf / paper")
    assert _answer_matches("leaf", accepted, fuzzy=True) is True
    assert _answer_matches("paper", accepted, fuzzy=True) is True
    assert _answer_matches("leaf / paper", accepted, fuzzy=True) is True


def test_arbeiten_infinitive_marker_matches():
    accepted = _split_answers("to work")
    assert _answer_matches("work", accepted, fuzzy=True) is True
    assert _answer_matches("to work", accepted, fuzzy=True) is True


def test_fuzzy_forgives_typos_but_not_short_collisions():
    assert _fuzzy_equal("arbeiten", "arbieten") is True   # transposition
    assert _fuzzy_equal("ist", "isst") is False           # too short -> must be exact
    assert _fuzzy_equal("work", "word") is False          # len 4 -> exact only


def test_unrelated_answer_rejected():
    accepted = _split_answers("leaf / paper")
    assert _answer_matches("tree", accepted, fuzzy=True) is False


def test_grammar_uses_exact_any_match_no_fuzzy():
    item = SimpleNamespace(answer="bist; seid")
    assert _grammar_correct(item, "bist") is True
    assert _grammar_correct(item, "seid") is True
    assert _grammar_correct(item, "bin") is False
    # No fuzzy for grammar: a near-miss form is NOT accepted.
    item2 = SimpleNamespace(answer="ist")
    assert _grammar_correct(item2, "isst") is False


def test_check_vocab_fields_examples():
    from core.session import SessionService
    from db.repo import VocabItem

    svc = object.__new__(SessionService)  # no DB needed for pure checking

    arbeiten = VocabItem(
        id=1, deck_id=1, pos="verb", word="arbeiten", meaning="to work",
        article=None, gender=None, gender_tip=None, plural=None,
    )
    res = svc.check_vocab_fields(arbeiten, "work", "", "")
    assert res["meaning_ok"] is True

    blatt = VocabItem(
        id=2, deck_id=1, pos="noun", word="Blatt", meaning="leaf / paper",
        article="das", gender="n", gender_tip=None, plural="Blätter",
    )
    res2 = svc.check_vocab_fields(blatt, "leaf", "n", "Blätter")
    assert res2["meaning_ok"] is True
    assert res2["gender_ok"] is True
    assert res2["plural_ok"] is True
