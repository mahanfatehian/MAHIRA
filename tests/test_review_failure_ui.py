from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _FailingSession:
    def __init__(self) -> None:
        self.record_calls = 0

    def record_item_answered(self) -> bool:
        self.record_calls += 1
        return True

    @staticmethod
    def _fail(*_args, **_kwargs):
        raise RuntimeError("injected database failure")

    submit_vocab = _fail
    submit_grammar = _fail
    submit_sentence = _fail
    submit_listening = _fail


@pytest.mark.parametrize(
    "objective", ("vocab", "grammar", "sentences", "listening")
)
def test_failed_review_stays_on_card_without_progress(objective):
    from ui.pages.grammar_review import GrammarReviewPage
    from ui.pages.listening_review import ListeningReviewPage
    from ui.pages.sentence_review import SentenceReviewPage
    from ui.pages.vocab_review import VocabReviewPage

    app = _qapp()
    page_class = {
        "vocab": VocabReviewPage,
        "grammar": GrammarReviewPage,
        "sentences": SentenceReviewPage,
        "listening": ListeningReviewPage,
    }[objective]
    page = page_class(SimpleNamespace())
    session = _FailingSession()
    page.session = session
    item = SimpleNamespace(id=1, deck_id=7)
    page.current_item = item
    page.card_started_at = time.time() - 1
    loads: list[bool] = []
    page._load_next = lambda: loads.append(True)

    if objective == "vocab":
        page.typed_meaning = "house"
        page.typed_gender = "n"
        page.typed_plural = "Häuser"
        page.was_checked = True
    elif objective == "grammar":
        page.typed_blank = "lerne"
        page.was_checked = True
    elif objective == "sentences":
        page.was_checked = True
    else:
        page._answered = True
        page._chosen = "Deutsch"
        page._response_ms = 1_000

    try:
        page._on_rated(2)
        app.processEvents()

        assert page.current_item is item
        assert loads == []
        assert session.record_calls == 0
        assert page.milestone_bar.isHidden()
        assert not page.save_error.isHidden()
        assert page.save_error.accessibleName() == "Review save failed"
        assert "not recorded" in page.save_error.text()
    finally:
        page.close()
        page.deleteLater()


def test_review_save_error_clears_for_the_next_card():
    from ui.widgets.review_save_error import ReviewSaveError

    _qapp()
    status = ReviewSaveError()
    try:
        status.show_failure()
        assert not status.isHidden()

        status.clear_failure()
        assert status.isHidden()
        assert status.text() == ""
    finally:
        status.close()
        status.deleteLater()
