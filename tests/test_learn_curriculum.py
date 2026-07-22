"""Learn-tab curriculum: lesson pages are folder-driven by CEFR level."""

from pathlib import Path

import pytest


def test_parse_folder_based_filename():
    from ui.pages.learn import _parse_md_filename

    # Level comes from the folder (level_hint); filename omits it.
    r = _parse_md_filename(
        Path("data/pages/a1/1.1_nouns_articles_(der, die, das).md"), level_hint="a1"
    )
    assert r is not None
    level, obj, lesson, obj_no, lesson_no, token = r
    assert level == "A1"
    assert obj == "nouns"
    assert obj_no == 1 and lesson_no == 1 and token == "1.1"

    # Objective with spaces/ampersand still parses.
    r2 = _parse_md_filename(
        Path("3.1_pronouns & Determiners_personal_pronouns_(ich, du, er...).md"),
        level_hint="a1",
    )
    assert r2 is not None
    assert r2[0] == "A1" and r2[3] == 3 and r2[4] == 1


def test_parse_legacy_filename_still_works():
    from ui.pages.learn import _parse_md_filename

    r = _parse_md_filename(Path("a1_2.3_verbs_present_tense_(Stem-Changing).md"))
    assert r is not None
    assert r[0] == "A1" and r[1] == "verbs" and r[3] == 2 and r[4] == 3


def test_levelless_filename_without_folder_is_rejected():
    from ui.pages.learn import _parse_md_filename

    assert _parse_md_filename(Path("1.1_nouns_articles.md")) is None


def test_answer_markers_extract_only_the_hidden_section():
    from ui.pages.learn import (
        ANSWERS_END,
        ANSWERS_START,
        _split_answers_markers_only,
    )

    markdown = f"Lesson body\n{ANSWERS_START}\nAnswer key\n{ANSWERS_END}\nFooter"

    assert _split_answers_markers_only(markdown) == (
        "Lesson body\n\nFooter",
        "Answer key",
    )


@pytest.mark.parametrize(
    "markdown",
    (
        "Lesson body\n<!-- ANSWERS_START -->\nunfinished answer",
        "Lesson body\n<!-- ANSWERS_END -->",
        "<!-- ANSWERS_END -->\nLesson body\n<!-- ANSWERS_START -->\nAnswer key",
    ),
)
def test_malformed_answer_markers_remain_regular_lesson_content(markdown):
    from ui.pages.learn import _split_answers_markers_only

    assert _split_answers_markers_only(markdown) == (markdown, None)


def test_curriculum_index_loads_a1_from_folders():
    """The shipped data/pages/a1/*.md lessons load via the folder structure."""
    from ui.pages.learn import CurriculumIndex

    idx = CurriculumIndex()
    idx.reload()

    assert "A1" in idx.levels()
    objectives = idx.objectives_for("A1")
    assert objectives, "no A1 objectives found"
    assert "nouns" in objectives
    # Lessons within an objective carry their numeric ordering token.
    nouns = objectives["nouns"]
    assert any(ref.order_token == "1.1" for ref in nouns)
