from pathlib import Path

import pytest
from PySide6.QtGui import QImageReader

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


@pytest.mark.parametrize(
    ("name", "width"),
    (
        ("menschen_a1.jpg", 768),
        ("menschen_a2.jpg", 768),
        ("menschen_b1.jpg", 768),
        ("startenWir_a1.jpg", 724),
        ("startenWir_a2.jpg", 724),
        ("startenWir_b1.jpg", 724),
        ("sicher_b1.jpg", 768),
        ("sicher_b2.jpg", 768),
        ("sicher_c1.jpg", 768),
    ),
)
def test_bundled_book_covers_are_valid_publisher_jpegs(name: str, width: int):
    cover = Path(__file__).resolve().parents[1] / "assets" / "books" / name
    reader = QImageReader(str(cover))

    assert bytes(reader.format()).lower() == b"jpeg"
    assert reader.size().width() == width
    assert reader.size().height() == 1024
    assert not reader.read().isNull()


@pytest.mark.parametrize(
    ("slug", "level", "name"),
    (
        ("menschen", "A2", "menschen_a2.jpg"),
        ("starten_wir", "B1", "startenWir_b1.jpg"),
        ("sicher", "C1", "sicher_c1.jpg"),
    ),
)
def test_bundled_cover_lookup_uses_real_jpegs(slug: str, level: str, name: str):
    cover = find_book_cover(slug, level)

    assert cover is not None
    assert Path(cover).name == name
