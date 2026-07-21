"""Resolve bundled book-cover artwork without depending on one file format."""

from __future__ import annotations

from pathlib import Path


# Keep the universally supported JPEG format first. The remaining suffixes make
# upgrades backwards-compatible with older bundles and future artwork formats.
BOOK_COVER_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".ico")
_CEFR_LEVELS = frozenset({"a1", "a2", "b1", "b2", "c1", "c2"})


def cover_stem_for_slug(slug: str) -> str:
    """Convert starten_wir to the asset stem startenWir."""
    parts = [part for part in (slug or "").split("_") if part]
    if not parts or any(not part.isalnum() for part in parts):
        return ""
    return parts[0].lower() + "".join(
        part[:1].upper() + part[1:].lower() for part in parts[1:]
    )


def _normalise_level(level: str) -> str:
    value = (level or "").strip().lower()
    return value if value in _CEFR_LEVELS else ""


def _default_books_dir() -> Path:
    from mahira.config import resource_root

    return resource_root() / "assets" / "books"


def find_book_cover(
    slug: str,
    level: str,
    *,
    books_dir: Path | None = None,
) -> str | None:
    """Return the preferred bundled cover for one book and CEFR level."""
    stem = cover_stem_for_slug(slug)
    normalised_level = _normalise_level(level)
    if not stem or not normalised_level:
        return None

    try:
        directory = books_dir if books_dir is not None else _default_books_dir()
        base = directory / f"{stem}_{normalised_level}"
        for suffix in BOOK_COVER_SUFFIXES:
            candidate = base.with_suffix(suffix)
            if candidate.is_file():
                return str(candidate)
    except (ImportError, OSError):
        return None
    return None


def level_cover_paths(
    level: str,
    *,
    books_dir: Path | None = None,
) -> tuple[str, ...]:
    """Return all supported bundled covers for a CEFR level, stably sorted."""
    normalised_level = _normalise_level(level)
    if not normalised_level:
        return ()

    try:
        directory = books_dir if books_dir is not None else _default_books_dir()
        if not directory.is_dir():
            return ()
        supported = set(BOOK_COVER_SUFFIXES)
        suffix = f"_{normalised_level}"
        matches = (
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.lower() in supported
            and path.stem.lower().endswith(suffix)
        )
        ordered = sorted(matches, key=lambda path: path.name.lower())
        return tuple(str(path) for path in ordered)
    except (ImportError, OSError):
        return ()
