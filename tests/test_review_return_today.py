from __future__ import annotations

import os
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _FinishedSession:
    def __init__(self):
        self.repo = SimpleNamespace()
        self.settings = SimpleNamespace(
            value=SimpleNamespace(
                audio_autoplay=False,
                audio_speed=1.0,
                reduced_motion=True,
            )
        )
        self.state = SimpleNamespace(objective="vocab")

    def study_progress(self):
        return (1, 1)

    def next_item(self):
        return None

    def next_grammar_item(self):
        return None

    def next_sentence_item(self):
        return None

    def next_listening_item(self):
        return None


@pytest.mark.parametrize(
    "module_name,class_name",
    [
        ("ui.pages.vocab_review", "VocabReviewPage"),
        ("ui.pages.grammar_review", "GrammarReviewPage"),
        ("ui.pages.sentence_review", "SentenceReviewPage"),
        ("ui.pages.listening_review", "ListeningReviewPage"),
    ],
)
def test_finished_primary_session_offers_an_accessible_return_to_today(
    module_name,
    class_name,
):
    import importlib

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    _qapp()
    page_class = getattr(importlib.import_module(module_name), class_name)
    page = page_class(_FinishedSession())
    emitted: list[bool] = []
    page.go_today.connect(lambda: emitted.append(True))
    page.show()
    try:
        page._load_next()
        QApplication.processEvents()

        completion_copy = " ".join(
            label.text() for label in page.empty_card.findChildren(QLabel)
        ).casefold()
        assert "session finished" in completion_copy

        buttons = [
            button
            for button in page.empty_card.findChildren(QPushButton)
            if "today" in button.text().casefold()
            or "today" in button.accessibleName().casefold()
        ]
        assert len(buttons) == 1
        assert buttons[0].isVisible()
        assert buttons[0].accessibleName()

        buttons[0].click()
        assert emitted == [True]
    finally:
        page.close()
        page.deleteLater()
