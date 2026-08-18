"""Space must not fire Skip by accident.

In the listening and sentence lanes there is no text field holding focus, so
the first focusable control is often Skip. A single Space then silently
lapses the card. Skip stays clickable and Tab-reachable; it just refuses to
take click-focus or act as a dialog default button.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _assert_hardened(button) -> None:
    from PySide6.QtCore import Qt

    assert button.autoDefault() is False
    assert button.isDefault() is False
    assert button.focusPolicy() == Qt.FocusPolicy.TabFocus


def test_vocab_skip_is_hardened():
    from ui.widgets.card_widget import CardWidget

    _qapp()
    card = CardWidget()
    _assert_hardened(card.skip_btn)
    card.deleteLater()


def test_grammar_skip_is_hardened():
    from ui.widgets.grammar_card_widget import GrammarCardWidget

    _qapp()
    card = GrammarCardWidget()
    _assert_hardened(card.btn_skip)
    card.deleteLater()


def test_sentence_skip_is_hardened():
    from ui.widgets.sentence_builder_widget import SentenceBuilderWidget

    _qapp()
    card = SentenceBuilderWidget()
    _assert_hardened(card.btn_skip)
    card.deleteLater()


def test_listening_skip_is_hardened():
    from ui.pages.listening_review import ListeningReviewPage

    _qapp()

    class _Session:
        def __getattr__(self, name):
            return lambda *a, **k: None

    page = ListeningReviewPage(_Session())
    _assert_hardened(page.skip_btn)
    page.deleteLater()
