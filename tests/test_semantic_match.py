"""Semantic meaning matching (offline all-MiniLM-L12-v2 embedding model).

Guards the regression that motivated this: the old fuzzy matcher accepted
"eight" for "eighty". The embedding model must reject number near-misses and
clear wrong answers while still accepting strong synonyms.

The pairs asserted here sit well clear of the 0.72 threshold on MiniLM-L12
(margins > 0.07), so the contract is stable across onnxruntime builds. Pairs the
model packs near the cut (e.g. kid/child ~0.72, father/mother ~0.68, and the
antonym buy/sell ~0.79 which no threshold separates) are deliberately not
hard-asserted — that grey zone is what the "Accept my answer" override is for.
Skipped automatically if the model / onnxruntime / tokenizers aren't available.
"""
import pytest

from core.semantic_match import get_matcher

_matcher = get_matcher()
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not _matcher.available(),
        reason="meaning-match model / onnxruntime / tokenizers not available",
    ),
]


def test_number_confusion_is_rejected():
    # The exact bug: eighty != eight (and other number near-misses) — MiniLM-L12
    # rates these ~0.59-0.65, below threshold.
    assert _matcher.matches("eight", ["eighty"]) is False
    assert _matcher.matches("eighteen", ["eighty"]) is False
    assert _matcher.matches("ninety", ["nine"]) is False


def test_exact_match_is_accepted():
    # Exact (normalized) glosses short-circuit before the model runs.
    assert _matcher.matches("eighty", ["eighty"]) is True
    assert _matcher.matches("job", ["profession", "job"]) is True


def test_real_synonyms_accepted():
    # Strong synonyms clear 0.72 comfortably (~0.82-0.93).
    assert _matcher.matches("to purchase", ["to buy"]) is True
    assert _matcher.matches("to begin", ["to start"]) is True
    assert _matcher.matches("automobile", ["car"]) is True
    assert _matcher.matches("big", ["large"]) is True


def test_unrelated_meanings_rejected():
    assert _matcher.matches("cat", ["dog"]) is False
    assert _matcher.matches("hot", ["cold"]) is False
    assert _matcher.matches("", ["dog"]) is False
