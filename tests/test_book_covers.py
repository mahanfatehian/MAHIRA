import os
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


def test_find_book_cover_prefers_manifest_asset_then_falls_back(tmp_path: Path):
    books = tmp_path / "books"
    books.mkdir()
    conventional = books / "menschen_a1.jpg"
    conventional.touch()
    preferred = tmp_path / "pack" / "cover.webp"
    preferred.parent.mkdir()
    preferred.touch()

    assert find_book_cover(
        "custom-book",
        "A1",
        books_dir=books,
        preferred_path=preferred,
    ) == str(preferred)

    preferred.unlink()
    assert find_book_cover(
        "menschen",
        "A1",
        books_dir=books,
        preferred_path=preferred,
    ) == str(conventional)


def test_find_book_cover_ignores_unsupported_preferred_asset(tmp_path: Path):
    conventional = tmp_path / "menschen_a1.jpg"
    conventional.touch()
    unsupported = tmp_path / "cover.txt"
    unsupported.touch()

    assert find_book_cover(
        "menschen",
        "A1",
        books_dir=tmp_path,
        preferred_path=unsupported,
    ) == str(conventional)


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


def test_rounded_cover_cache_reuses_identical_transform_and_splits_geometry(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from ui.widgets import images

    app = QApplication.instance() or QApplication([])
    assert app is not None
    source = tmp_path / "cover.png"
    pixmap = QPixmap(40, 60)
    pixmap.fill(Qt.GlobalColor.red)
    assert pixmap.save(str(source), "PNG")
    images._cached_rounded_cover_pixmap.cache_clear()

    assert images.rounded_cover_pixmap(str(source), 80, 104, 14) is not None
    assert images.rounded_cover_pixmap(str(source), 80, 104, 14) is not None
    reused = images._cached_rounded_cover_pixmap.cache_info()
    assert (reused.hits, reused.misses) == (1, 1)

    assert images.rounded_cover_pixmap(str(source), 81, 104, 14) is not None
    assert images.rounded_cover_pixmap(str(source), 80, 104, 15) is not None
    split = images._cached_rounded_cover_pixmap.cache_info()
    assert split.misses == 3
    assert split.maxsize == 128

    first = images.rounded_cover_pixmap(str(source), 80, 104, 14)
    assert first is not None
    first.fill(Qt.GlobalColor.blue)
    second = images.rounded_cover_pixmap(str(source), 80, 104, 14)
    assert second is not None
    assert second.toImage().pixelColor(40, 52) == Qt.GlobalColor.red


def test_rounded_cover_cache_splits_device_pixel_ratios(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from ui.widgets import images

    app = QApplication.instance() or QApplication([])
    assert app is not None
    source = tmp_path / "cover.png"
    pixmap = QPixmap(40, 60)
    pixmap.fill(Qt.GlobalColor.blue)
    assert pixmap.save(str(source), "PNG")
    images._cached_rounded_cover_pixmap.cache_clear()

    monkeypatch.setattr(images, "_device_pixel_ratio", lambda: 1.0)
    first = images.rounded_cover_pixmap(str(source), 80, 104, 14)
    monkeypatch.setattr(images, "_device_pixel_ratio", lambda: 2.0)
    second = images.rounded_cover_pixmap(str(source), 80, 104, 14)

    assert first is not None
    assert second is not None
    info = images._cached_rounded_cover_pixmap.cache_info()
    assert (info.hits, info.misses) == (0, 2)
    assert first.devicePixelRatio() == 1.0
    assert second.devicePixelRatio() == 2.0


def test_rounded_cover_cache_invalidates_changed_source_stat(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from ui.widgets import images

    app = QApplication.instance() or QApplication([])
    assert app is not None
    source = tmp_path / "cover.png"
    original = QPixmap(40, 60)
    original.fill(Qt.GlobalColor.red)
    assert original.save(str(source), "PNG")
    images._cached_rounded_cover_pixmap.cache_clear()

    first = images.rounded_cover_pixmap(str(source), 80, 104, 14)
    replacement = QPixmap(40, 60)
    replacement.fill(Qt.GlobalColor.blue)
    assert replacement.save(str(source), "PNG")
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    second = images.rounded_cover_pixmap(str(source), 80, 104, 14)

    assert first is not None
    assert second is not None
    assert first.toImage().pixelColor(40, 52) == Qt.GlobalColor.red
    assert second.toImage().pixelColor(40, 52) == Qt.GlobalColor.blue
    info = images._cached_rounded_cover_pixmap.cache_info()
    assert (info.hits, info.misses) == (0, 2)


def test_rounded_cover_cache_keeps_malformed_path_fallback(monkeypatch):
    from ui.widgets import images

    def raise_value_error(*_args, **_kwargs):
        raise ValueError

    monkeypatch.setattr(images.Path, "resolve", raise_value_error)
    assert images.rounded_cover_pixmap("bad\0cover.png", 80, 104, 14) is None
