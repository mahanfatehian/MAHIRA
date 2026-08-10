"""Optional, read-only metadata for folder-driven seed books."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


MANIFEST_FILENAME = "manifest.json"
SUPPORTED_COVER_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".ico"}
)
_ALLOWED_KEYS = frozenset({"title", "order", "cover"})
_MAX_MANIFEST_BYTES = 64 * 1024
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class SeedManifestError(ValueError):
    """A present book manifest is malformed or references an unsafe asset."""

    def __init__(self, path: Path, message: str):
        self.path = Path(path)
        self.message = str(message)
        super().__init__(f"{self.path}: {self.message}")


@dataclass(frozen=True)
class BookManifest:
    """Validated metadata from one ``data/seeds/<book>/manifest.json`` file."""

    book_slug: str
    title: str | None = None
    order: int | None = None
    cover_path: Path | None = None


def _read_manifest_object(manifest_path: Path) -> dict[str, object]:
    try:
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise SeedManifestError(
                manifest_path,
                f"manifest exceeds {_MAX_MANIFEST_BYTES // 1024} KiB",
            )
        raw = manifest_path.read_text(encoding="utf-8-sig")
    except SeedManifestError:
        raise
    except UnicodeDecodeError as exc:
        raise SeedManifestError(manifest_path, "manifest is not valid UTF-8") from exc
    except OSError as exc:
        raise SeedManifestError(manifest_path, f"cannot read manifest: {exc}") from exc

    def _unique_object(pairs):
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise SeedManifestError(
                    manifest_path,
                    f"duplicate field '{key}'",
                )
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except SeedManifestError:
        raise
    except json.JSONDecodeError as exc:
        raise SeedManifestError(
            manifest_path,
            f"invalid JSON at line {exc.lineno}, column {exc.colno}",
        ) from exc
    if not isinstance(value, dict):
        raise SeedManifestError(manifest_path, "manifest root must be a JSON object")

    unknown = sorted(str(key) for key in value if key not in _ALLOWED_KEYS)
    if unknown:
        raise SeedManifestError(
            manifest_path,
            f"unknown field(s): {', '.join(unknown)}",
        )
    return value


def _parse_title(manifest_path: Path, value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SeedManifestError(manifest_path, "title must be a string")
    title = value.strip()
    if not title:
        raise SeedManifestError(manifest_path, "title must not be empty")
    if len(title) > 120:
        raise SeedManifestError(manifest_path, "title must be at most 120 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in title):
        raise SeedManifestError(manifest_path, "title must not contain control characters")
    return title


def _parse_order(manifest_path: Path, value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise SeedManifestError(manifest_path, "order must be a non-negative integer")
    return value


def _parse_cover(manifest_path: Path, book_dir: Path, value: object) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SeedManifestError(manifest_path, "cover must be a relative path string")

    cover = value.strip()
    if not cover:
        raise SeedManifestError(manifest_path, "cover must not be empty")
    if "\\" in cover or ":" in cover or _WINDOWS_DRIVE_RE.match(cover):
        raise SeedManifestError(
            manifest_path,
            "cover must use a portable relative path with forward slashes",
        )

    relative = PurePosixPath(cover)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise SeedManifestError(manifest_path, "cover must stay inside the book directory")
    if relative.suffix.lower() not in SUPPORTED_COVER_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_COVER_SUFFIXES))
        raise SeedManifestError(
            manifest_path,
            f"cover must use a supported image suffix ({supported})",
        )

    unresolved = book_dir.joinpath(*relative.parts)
    cursor = book_dir
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise SeedManifestError(
                manifest_path,
                "cover must not use symbolic links",
            )

    try:
        book_root = book_dir.resolve(strict=True)
        candidate = unresolved.resolve(strict=True)
        candidate.relative_to(book_root)
    except (OSError, ValueError) as exc:
        raise SeedManifestError(
            manifest_path,
            "cover must name an existing file inside the book directory",
        ) from exc
    if not candidate.is_file():
        raise SeedManifestError(manifest_path, "cover must name a regular file")

    try:
        with candidate.open("rb") as handle:
            signature = handle.read(16)
    except OSError as exc:
        raise SeedManifestError(manifest_path, "cover file cannot be read") from exc
    suffix = candidate.suffix.lower()
    signature_ok = {
        ".jpg": signature.startswith(b"\xff\xd8\xff"),
        ".jpeg": signature.startswith(b"\xff\xd8\xff"),
        ".png": signature.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": (
            len(signature) >= 12
            and signature.startswith(b"RIFF")
            and signature[8:12] == b"WEBP"
        ),
        ".ico": signature.startswith(b"\x00\x00\x01\x00"),
    }[suffix]
    if not signature_ok:
        raise SeedManifestError(
            manifest_path,
            f"cover content does not match its {suffix} image suffix",
        )
    return candidate


def load_book_manifest(book_dir: Path) -> BookManifest | None:
    """Load and strictly validate a book manifest; return ``None`` if absent."""

    book_dir = Path(book_dir)
    manifest_path = book_dir / MANIFEST_FILENAME
    if manifest_path.is_symlink():
        raise SeedManifestError(manifest_path, "manifest must not be a symbolic link")
    if not manifest_path.exists():
        return None
    if not manifest_path.is_file():
        raise SeedManifestError(manifest_path, "manifest must be a regular file")

    value = _read_manifest_object(manifest_path)
    return BookManifest(
        book_slug=book_dir.name.lower().strip(),
        title=_parse_title(manifest_path, value.get("title")),
        order=_parse_order(manifest_path, value.get("order")),
        cover_path=_parse_cover(manifest_path, book_dir, value.get("cover")),
    )


def discover_book_manifests(
    seeds_root: Path,
    *,
    strict: bool = False,
) -> dict[str, BookManifest]:
    """Discover manifests, skipping invalid metadata unless ``strict`` is set."""

    seeds_root = Path(seeds_root)
    try:
        book_dirs = sorted(
            (path for path in seeds_root.iterdir() if path.is_dir()),
            key=lambda path: path.name.casefold(),
        )
    except OSError as exc:
        if strict:
            raise SeedManifestError(seeds_root, f"cannot scan seed books: {exc}") from exc
        return {}

    found: dict[str, BookManifest] = {}
    for book_dir in book_dirs:
        try:
            manifest = load_book_manifest(book_dir)
        except SeedManifestError:
            if strict:
                raise
            continue
        if manifest is not None:
            found[manifest.book_slug] = manifest
    return found


def _fallback_title(slug: str) -> str:
    words = [word for word in re.split(r"[-_]+", (slug or "").strip()) if word]
    return " ".join(word.capitalize() for word in words)


class BookManifestCatalog:
    """Safe display lookup over validated manifests for one seed library."""

    def __init__(self, manifests: dict[str, BookManifest] | None = None):
        self._manifests = dict(manifests or {})

    @classmethod
    def from_seed_root(
        cls,
        seeds_root: Path,
        *,
        strict: bool = False,
    ) -> "BookManifestCatalog":
        return cls(discover_book_manifests(seeds_root, strict=strict))

    def get(self, slug: str) -> BookManifest | None:
        return self._manifests.get((slug or "").lower().strip())

    def title_for(self, slug: str, fallback: str | None = None) -> str:
        manifest = self.get(slug)
        if manifest is not None and manifest.title:
            return manifest.title
        return (fallback or "").strip() or _fallback_title(slug)

    def order_for(self, slug: str) -> int | None:
        manifest = self.get(slug)
        return manifest.order if manifest is not None else None

    def cover_for(self, slug: str) -> Path | None:
        manifest = self.get(slug)
        return manifest.cover_path if manifest is not None else None

    def sort_key(
        self,
        slug: str,
        fallback_title: str | None = None,
    ) -> tuple[bool, int, str, str]:
        order = self.order_for(slug)
        return (
            order is None,
            order if order is not None else 0,
            self.title_for(slug, fallback_title).casefold(),
            (slug or "").casefold(),
        )


__all__ = [
    "BookManifest",
    "BookManifestCatalog",
    "MANIFEST_FILENAME",
    "SUPPORTED_COVER_SUFFIXES",
    "SeedManifestError",
    "discover_book_manifests",
    "load_book_manifest",
]
