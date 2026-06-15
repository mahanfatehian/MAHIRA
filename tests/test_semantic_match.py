"""Semantic meaning matching (offline MiniLM embedding model).

Guards the specific regression that motivated it: the old fuzzy matcher accepted
"eight" for "eighty" (edit distance 1). The embedding model must reject that while
still accepting trivial variations and real glosses.

Skipped automatically if the model/onnxruntime/tokenizers aren't available, so the
suite still runs in a minimal environment.
"""
import pytest

from core.semantic_match import get_matcher

_matcher = get_matcher()
pytestmark = pytest.mark.skipif(
    not _matcher.available(),
    reason="MiniLM model / onnxruntime / tokenizers not available",
)


def test_number_confusion_is_rejected():
    # The exact bug: eighty != eight (and other number near-misses).
    assert _matcher.matches("eight", ["eighty"]) is False
    assert _matcher.matches("eighteen", ["eighty"]) is False
    assert _matcher.matches("ninety", ["nine"]) is False


def test_exact_and_trivial_variations_accepted():
    assert _matcher.matches("eighty", ["eighty"]) is True
    assert _matcher.matches("work", ["to work"]) is True
    assert _matcher.matches("the family", ["family"]) is True
    assert _matcher.matches("job", ["profession", "job"]) is True


def test_real_synonyms_accepted():
    assert _matcher.matches("to purchase", ["to buy"]) is True
    assert _matcher.matches("automobile", ["car"]) is True


def test_unrelated_meanings_rejected():
    assert _matcher.matches("cat", ["dog"]) is False
    assert _matcher.matches("mother", ["father"]) is False
    assert _matcher.matches("", ["dog"]) is False
