import json
from pathlib import Path

import pytest

from db.seed_manifest import (
    BookManifestCatalog,
    SeedManifestError,
    discover_book_manifests,
    load_book_manifest,
)


def _write_manifest(book_dir: Path, payload: object) -> Path:
    book_dir.mkdir(parents=True, exist_ok=True)
    manifest = book_dir / "manifest.json"
    text = payload if isinstance(payload, str) else json.dumps(payload)
    manifest.write_text(text, encoding="utf-8")
    return manifest


def test_manifest_catalog_applies_valid_title_order_and_local_cover(tmp_path: Path):
    seeds = tmp_path / "data" / "seeds"
    book = seeds / "custom_book"
    cover = book / "art" / "cover.webp"
    cover.parent.mkdir(parents=True)
    cover.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
    _write_manifest(
        book,
        {"title": "Custom Course", "order": 7, "cover": "art/cover.webp"},
    )

    manifest = load_book_manifest(book)
    assert manifest is not None
    assert manifest.book_slug == "custom_book"
    assert manifest.title == "Custom Course"
    assert manifest.order == 7
    assert manifest.cover_path == cover.resolve()

    catalog = BookManifestCatalog.from_seed_root(seeds, strict=True)
    assert catalog.title_for("custom_book", "Ignored") == "Custom Course"
    assert catalog.order_for("custom_book") == 7
    assert catalog.cover_for("custom_book") == cover.resolve()


def test_missing_manifest_preserves_slug_and_existing_title_fallbacks(tmp_path: Path):
    seeds = tmp_path / "data" / "seeds"
    (seeds / "starten_wir").mkdir(parents=True)

    assert load_book_manifest(seeds / "starten_wir") is None
    catalog = BookManifestCatalog.from_seed_root(seeds)
    assert catalog.title_for("starten_wir") == "Starten Wir"
    assert catalog.title_for("starten_wir", "Stored Title") == "Stored Title"
    assert catalog.order_for("starten_wir") is None
    assert catalog.cover_for("starten_wir") is None


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ("{", "invalid JSON"),
        (["not", "an", "object"], "JSON object"),
        ({"titel": "Typo"}, "unknown field"),
        ({"title": "   "}, "must not be empty"),
        ({"title": 42}, "must be a string"),
        ({"order": True}, "non-negative integer"),
        ({"order": -1}, "non-negative integer"),
        ({"cover": "cover.txt"}, "supported image suffix"),
        ({"cover": "missing.jpg"}, "existing file"),
        ({"cover": "../outside.jpg"}, "inside the book directory"),
        ({"cover": "nested\\cover.jpg"}, "portable relative path"),
    ),
)
def test_invalid_manifest_fields_fail_strict_validation(
    tmp_path: Path,
    payload: object,
    message: str,
):
    book = tmp_path / "data" / "seeds" / "broken"
    _write_manifest(book, payload)

    with pytest.raises(SeedManifestError, match=message):
        load_book_manifest(book)


def test_a_posix_absolute_cover_path_is_rejected(tmp_path: Path):
    """An absolute POSIX path escapes the book directory."""
    book = tmp_path / "data" / "seeds" / "broken"
    _write_manifest(book, {"cover": "/etc/outside.jpg"})

    with pytest.raises(SeedManifestError, match="stay inside the book directory"):
        load_book_manifest(book)


def test_a_windows_absolute_cover_path_is_rejected(tmp_path: Path):
    """A drive letter is not a portable relative path."""
    book = tmp_path / "data" / "seeds" / "broken"
    _write_manifest(book, {"cover": "C:/outside.jpg"})

    with pytest.raises(SeedManifestError, match="portable relative path"):
        load_book_manifest(book)


def test_a_cover_outside_the_book_directory_is_rejected(tmp_path: Path):
    """This previously used tmp_path.as_posix(), so which branch it landed in
    depended on the host: "C:/..." on Windows carries a colon and was caught as
    a non-portable path, while "/private/var/..." on macOS fell through to the
    containment check. The build only ever ran the Windows spelling, so the
    macOS release build was the first thing to see the other message."""
    book = tmp_path / "data" / "seeds" / "broken"
    _write_manifest(book, {"cover": "../escape.jpg"})

    with pytest.raises(SeedManifestError, match="stay inside the book directory"):
        load_book_manifest(book)


def test_safe_discovery_ignores_malformed_manifest_but_strict_mode_reports_it(
    tmp_path: Path,
):
    seeds = tmp_path / "data" / "seeds"
    _write_manifest(seeds / "broken_book", "{")

    assert discover_book_manifests(seeds) == {}
    catalog = BookManifestCatalog.from_seed_root(seeds)
    assert catalog.title_for("broken_book") == "Broken Book"
    assert catalog.cover_for("broken_book") is None

    with pytest.raises(SeedManifestError, match="invalid JSON"):
        discover_book_manifests(seeds, strict=True)


def test_non_utf8_manifest_is_treated_as_invalid_metadata(tmp_path: Path):
    seeds = tmp_path / "data" / "seeds"
    book = seeds / "broken_book"
    book.mkdir(parents=True)
    (book / "manifest.json").write_bytes(b'{"title": "\xff"}')

    assert discover_book_manifests(seeds) == {}
    with pytest.raises(SeedManifestError, match="not valid UTF-8"):
        discover_book_manifests(seeds, strict=True)


def test_duplicate_manifest_fields_are_rejected(tmp_path: Path):
    book = tmp_path / "data" / "seeds" / "broken_book"
    _write_manifest(book, '{"title": "First", "title": "Second"}')

    with pytest.raises(SeedManifestError, match="duplicate field 'title'"):
        load_book_manifest(book)


def test_corrupt_manifest_cover_does_not_hide_conventional_cover(tmp_path: Path):
    from ui.book_covers import find_book_cover

    seeds = tmp_path / "data" / "seeds"
    book = seeds / "menschen"
    book.mkdir(parents=True)
    (book / "cover.webp").write_bytes(b"not an image")
    _write_manifest(book, {"cover": "cover.webp"})
    conventional_dir = tmp_path / "assets" / "books"
    conventional_dir.mkdir(parents=True)
    conventional = conventional_dir / "menschen_a1.jpg"
    conventional.touch()

    catalog = BookManifestCatalog.from_seed_root(seeds)

    assert catalog.cover_for("menschen") is None
    assert find_book_cover(
        "menschen",
        "A1",
        books_dir=conventional_dir,
        preferred_path=catalog.cover_for("menschen"),
    ) == str(conventional)


def test_catalog_order_is_explicit_then_deterministic(tmp_path: Path):
    seeds = tmp_path / "data" / "seeds"
    _write_manifest(seeds / "third", {"title": "Zed", "order": 20})
    _write_manifest(seeds / "first", {"title": "Alpha", "order": 10})
    (seeds / "unmanaged").mkdir(parents=True)

    catalog = BookManifestCatalog.from_seed_root(seeds, strict=True)
    books = [
        ("unmanaged", "Beta"),
        ("third", "Stored Third"),
        ("first", "Stored First"),
    ]
    ordered = sorted(books, key=lambda book: catalog.sort_key(*book))

    assert [slug for slug, _title in ordered] == ["first", "third", "unmanaged"]
