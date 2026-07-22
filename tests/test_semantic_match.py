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

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def matcher():
    from core.semantic_match import get_matcher

    instance = get_matcher()
    if not instance.available():
        pytest.skip("meaning-match model / onnxruntime / tokenizers not available")
    return instance


def test_number_confusion_is_rejected(matcher):
    # The exact bug: eighty != eight (and other number near-misses) — MiniLM-L12
    # rates these ~0.59-0.65, below threshold.
    assert matcher.matches("eight", ["eighty"]) is False
    assert matcher.matches("eighteen", ["eighty"]) is False
    assert matcher.matches("ninety", ["nine"]) is False


def test_exact_match_is_accepted(matcher):
    # Exact (normalized) glosses short-circuit before the model runs.
    assert matcher.matches("eighty", ["eighty"]) is True
    assert matcher.matches("job", ["profession", "job"]) is True


def test_real_synonyms_accepted(matcher):
    # Strong synonyms clear 0.72 comfortably (~0.82-0.93).
    assert matcher.matches("to purchase", ["to buy"]) is True
    assert matcher.matches("to begin", ["to start"]) is True
    assert matcher.matches("automobile", ["car"]) is True
    assert matcher.matches("big", ["large"]) is True


def test_unrelated_meanings_rejected(matcher):
    assert matcher.matches("cat", ["dog"]) is False
    assert matcher.matches("hot", ["cold"]) is False
    assert matcher.matches("", ["dog"]) is False
