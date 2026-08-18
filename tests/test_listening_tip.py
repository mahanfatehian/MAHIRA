"""Listening items ship an authored tip that the lane never displayed.

Every one of the bundled listening rows carries a non-empty tip. It is parsed
by seed import, stored on the row and exposed on ListeningItem.tip - and
listening_review.py did not contain the word "tip" anywhere, so none of it ever
reached the learner.
"""

from __future__ import annotations

import csv
import glob
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page():
    from ui.pages.listening_review import ListeningReviewPage

    _qapp()
    widget = ListeningReviewPage(SimpleNamespace())
    yield widget
    widget.deleteLater()


def _item(**overrides):
    base = dict(
        id=1,
        deck_id=1,
        text="Guten Morgen, wie geht es Ihnen?",
        question="Wie begruesst die Person?",
        answer="Guten Morgen",
        distractors=["Gute Nacht", "Auf Wiedersehen"],
        translation="Good morning, how are you?",
        tip="Listen for the time of day in the greeting.",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------
# The content this feature exists for
# --------------------------------------------------------------------------

def test_the_bundled_content_really_does_carry_tips():
    """If content ever stops shipping tips, this feature loses its point."""
    total = with_tip = 0
    for path in glob.glob(str(REPO_ROOT / "data/seeds/*/*/*listening*.csv")):
        with io.open(path, encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                total += 1
                if (row.get("tip") or "").strip():
                    with_tip += 1
    assert total > 0
    assert with_tip == total


# --------------------------------------------------------------------------
# The widget
# --------------------------------------------------------------------------

def test_the_reveal_card_carries_a_tip_label(page):
    assert page.tip_lbl is not None
    # It has to be inside the reveal card, not merely constructed.
    assert page.tip_lbl.parentWidget() is page.reveal_card


def test_the_tip_is_hidden_until_the_card_is_answered(page):
    page.current_item = _item()
    page._options = ["Guten Morgen", "Gute Nacht", "Auf Wiedersehen"]
    page._answered = False
    page._paint_question()
    assert not page.reveal_card.isVisible()


def test_answering_reveals_the_tip(page):
    page.current_item = _item()
    page._options = ["Guten Morgen", "Gute Nacht", "Auf Wiedersehen"]
    page._chosen = "Gute Nacht"
    page._ok = False
    page._answered = True
    page._paint_answered()

    assert "time of day" in page.tip_lbl.text()
    assert not page.tip_lbl.isHidden()


def test_an_item_without_a_tip_hides_the_label(page):
    page.current_item = _item(tip=None)
    page._options = ["Guten Morgen", "Gute Nacht"]
    page._chosen = "Gute Nacht"
    page._ok = False
    page._answered = True
    page._paint_answered()

    assert page.tip_lbl.isHidden()


def test_a_blank_tip_is_treated_as_absent(page):
    page.current_item = _item(tip="   ")
    page._options = ["Guten Morgen", "Gute Nacht"]
    page._chosen = "Gute Nacht"
    page._ok = False
    page._answered = True
    page._paint_answered()

    assert page.tip_lbl.isHidden()


def test_the_transcript_and_translation_still_render(page):
    """The tip must not have displaced what the reveal card already showed."""
    page.current_item = _item()
    page._options = ["Guten Morgen", "Gute Nacht"]
    page._chosen = "Guten Morgen"
    page._ok = True
    page._answered = True
    page._paint_answered()

    assert "Guten Morgen" in page.transcript_lbl.text()
    assert "Good morning" in page.translation_lbl.text()
