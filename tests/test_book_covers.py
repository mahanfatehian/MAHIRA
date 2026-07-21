from pathlib import Path

from ui.book_covers import (
    cover_stem_for_slug,
    find_book_cover,
    level_cover_paths,
)


def test_cover_stem_uses_existing_camel_case_convention():
    assert cover_stem_for_slug("starten_wir") == "startenWir"
    assert cover_stem_for_slug("menschen") == "menschen"
    assert cover_stem_for_slug("../outside") == ""


def test_find_book_cover_prefers_real_jpeg_over_legacy_ico(tmp_path: Path):
    legacy = tmp_path / "startenWir_a1.ico"
    preferred = tmp_path / "startenWir_a1.jpg"
    legacy.touch()
    preferred.touch()

    assert find_book_cover("starten_wir", "A1", books_dir=tmp_path) == str(preferred)


def test_find_book_cover_keeps_legacy_fallback(tmp_path: Path):
    legacy = tmp_path / "menschen_a1.ico"
    legacy.touch()

    assert find_book_cover("menschen", "a1", books_dir=tmp_path) == str(legacy)
    assert find_book_cover("menschen", "D1", books_dir=tmp_path) is None


def test_level_cover_paths_filters_and_sorts_supported_images(tmp_path: Path):
    for name in (
        "startenWir_a1.webp",
        "menschen_a1.jpg",
        "ignored_a1.txt",
        "menschen_a2.jpg",
    ):
        (tmp_path / name).touch()

    assert level_cover_paths("A1", books_dir=tmp_path) == (
        str(tmp_path / "menschen_a1.jpg"),
        str(tmp_path / "startenWir_a1.webp"),
    )
    assert level_cover_paths("", books_dir=tmp_path) == ()
