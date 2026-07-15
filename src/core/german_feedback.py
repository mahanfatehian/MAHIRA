from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


_ARTICLES = {"der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer"}


@dataclass(frozen=True)
class AnswerFeedback:
    correct: bool
    tags: tuple[str, ...]
    message: str


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÄÖÜäöüß]+", text or "")


def classify_german_answer(typed: str, expected: str) -> AnswerFeedback:
    typed = " ".join((typed or "").strip().split())
    expected = " ".join((expected or "").strip().split())
    if typed == expected:
        return AnswerFeedback(True, (), "Exact answer.")
    tags: list[str] = []
    if typed.casefold() == expected.casefold():
        tags.append("capitalization")
    typed_words = _words(typed)
    expected_words = _words(expected)
    if expected_words and expected_words[0].casefold() in _ARTICLES:
        if not typed_words or typed_words[0].casefold() not in _ARTICLES:
            tags.append("article_missing")
        elif typed_words[0].casefold() != expected_words[0].casefold():
            tags.append("article")
    if len(typed_words) > 1 and sorted(w.casefold() for w in typed_words) == sorted(w.casefold() for w in expected_words):
        if [w.casefold() for w in typed_words] != [w.casefold() for w in expected_words]:
            tags.append("word_order")
    stripped_typed = re.sub(r"[^\wÄÖÜäöüß]", "", typed, flags=re.UNICODE).casefold()
    stripped_expected = re.sub(r"[^\wÄÖÜäöüß]", "", expected, flags=re.UNICODE).casefold()
    if stripped_typed == stripped_expected and typed.casefold() != expected.casefold():
        tags.append("punctuation")
    ratio = SequenceMatcher(None, typed.casefold(), expected.casefold()).ratio()
    if not tags and ratio >= 0.72:
        tags.append("spelling")
    if not tags:
        tags.append("different_answer")
    labels = {
        "capitalization": "Check German capitalization",
        "article_missing": "Include the article with the noun",
        "article": "Check the noun's article or case",
        "word_order": "The words are present, but their order changes the sentence",
        "punctuation": "The wording matches; check punctuation",
        "spelling": "Very close—check the spelling",
        "different_answer": "Compare your answer with the model answer",
    }
    return AnswerFeedback(False, tuple(tags), labels[tags[0]] + ".")
