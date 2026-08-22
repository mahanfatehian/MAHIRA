"""German nouns must be pronounced with their article.

A noun without its gender is only half-learned, so the table's speaker reads
the article column of the same row: "das Haus", not "Haus". Rows carrying two
articles ("der/die") are spoken as "der oder die", which is how a German
speaker reads the slash.
"""

from __future__ import annotations

import os

import pytest

from core.vocab_fields import spoken_article, spoken_vocab_text

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# --------------------------------------------------------------------------
# The phrase builder
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "article,word,expected",
    [
        ("das", "Haus", "das Haus"),
        ("der", "Tisch", "der Tisch"),
        ("die", "Tuer", "die Tuer"),
    ],
)
def test_a_noun_is_spoken_with_its_article(article, word, expected):
    assert spoken_vocab_text(word, "noun", article) == expected


@pytest.mark.parametrize(
    "article,expected",
    [
        ("der/die", "der oder die"),
        ("das/der", "das oder der"),
        ("die/das", "die oder das"),
        ("die/der", "die oder der"),
        ("der/das", "der oder das"),
        ("der / die", "der oder die"),
    ],
)
def test_two_articles_are_spoken_as_an_alternation(article, expected):
    """All of these spellings occur in the shipped content."""
    assert spoken_vocab_text("Arme", "noun", article) == f"{expected} Arme"


def test_a_repeated_article_is_not_said_twice():
    assert spoken_vocab_text("Wort", "noun", "die/die") == "die Wort"


@pytest.mark.parametrize("article", ["-", "--", "", None, "   "])
def test_a_noun_without_a_real_article_is_spoken_alone(article):
    """Numbers like 'null' and 'eins' are tagged noun with a dash article."""
    assert spoken_vocab_text("null", "noun", article) == "null"


@pytest.mark.parametrize("pos", ["verb", "adj", "adverb", "phrase", "pronoun", None, ""])
def test_non_nouns_never_gain_an_article(pos):
    assert spoken_vocab_text("gehen", pos, "der") == "gehen"


def test_an_unrecognised_article_falls_back_to_the_bare_word():
    """Better a bare noun than the voice reading punctuation aloud."""
    assert spoken_vocab_text("Ding", "noun", "(das)") == "Ding"
    assert spoken_vocab_text("Ding", "noun", "das!") == "Ding"
    assert spoken_article("noun", "el") is None


def test_an_empty_word_produces_nothing():
    assert spoken_vocab_text("", "noun", "das") == ""
    assert spoken_vocab_text(None, "noun", "das") == ""


def test_surrounding_whitespace_is_handled():
    assert spoken_vocab_text("  Haus  ", "noun", "  das  ") == "das Haus"


# --------------------------------------------------------------------------
# The table model, including the self-quiz mask
# --------------------------------------------------------------------------

def _model(masked=None):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from ui.pages.vocab_table import _VocabTableModel

    QApplication.instance() or QApplication([])
    model = _VocabTableModel(dict(masked or {}))
    model.set_rows(
        [
            {"word": "Haus", "article": "das", "pos": "noun", "meaning": "house", "plural": "Haeuser"},
            {"word": "Arme", "article": "der/die", "pos": "noun", "meaning": "poor person", "plural": ""},
            {"word": "gehen", "article": "-", "pos": "verb", "meaning": "to go", "plural": ""},
        ]
    )
    return model


def test_the_model_speaks_a_noun_with_its_article():
    assert _model().audio_text(0) == "das Haus"


def test_the_model_speaks_an_alternation():
    assert _model().audio_text(1) == "der oder die Arme"


def test_the_model_leaves_a_verb_alone():
    assert _model().audio_text(2) == "gehen"


def test_a_masked_article_is_not_read_aloud():
    """Speaking it would announce the answer the learner is recalling."""
    model = _model({"article": True})
    assert model.audio_text(0) == "Haus"
    assert model.audio_text(1) == "Arme"


def test_revealing_the_article_restores_it():
    model = _model({"article": True})
    assert model.audio_text(0) == "Haus"
    model.toggle_reveal(0, "article")
    assert model.audio_text(0) == "das Haus"


def test_masking_another_column_does_not_suppress_the_article():
    model = _model({"meaning": True})
    assert model.audio_text(0) == "das Haus"


def test_an_out_of_range_row_is_safe():
    assert _model().audio_text(99) == ""
