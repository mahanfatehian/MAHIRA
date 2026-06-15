"""Semantic meaning matching (offline all-mpnet-base-v2 embedding model).

Guards the regression that motivated this: the old fuzzy matcher accepted
"eight" for "eighty". The embedding model must reject number near-misses and
clear wrong answers while still accepting strong synonyms.

The pairs asserted here are chosen to sit well clear of the 0.70 threshold on
mpnet (margins > 0.10), so the contract is stable across onnxruntime builds.
Borderline pairs that mpnet packs near the cut (e.g. father/mother ~0.69,
automobile/car ~0.72) are deliberately NOT hard-asserted. Skipped automatically
if the model / onnxruntime / tokenizers aren't available.
"""
import pytest

from core.semantic_match import get_matcher

_matcher = get_matcher()
pytestmark = pytest.mark.skipif(
    not _matcher.available(),
    reason="meaning-match model / onnxruntime / tokenizers not available",
)


def test_number_confusion_is_rejected():
    # The exact bug: eighty != eight (and other number near-misses) — mpnet
    # rates these ~0.40-0.43, far below threshold.
    assert _matcher.matches("eight", ["eighty"]) is False
    assert _matcher.matches("eighteen", ["eighty"]) is False
    assert _matcher.matches("ninety", ["nine"]) is False


def test_exact_match_is_accepted():
    # Exact (normalized) glosses short-circuit before the model runs.
    assert _matcher.matches("eighty", ["eighty"]) is True
    assert _matcher.matches("job", ["profession", "job"]) is True


def test_real_synonyms_accepted():
    # Strong synonyms clear 0.70 comfortably (~0.79-0.80).
    assert _matcher.matches("to purchase", ["to buy"]) is True
    assert _matcher.matches("to begin", ["to start"]) is True
    assert _matcher.matches("kid", ["child"]) is True


def test_unrelated_meanings_rejected():
    assert _matcher.matches("cat", ["dog"]) is False
    assert _matcher.matches("hot", ["cold"]) is False
    assert _matcher.matches("", ["dog"]) is False
