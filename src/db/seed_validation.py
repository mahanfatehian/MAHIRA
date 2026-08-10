from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from db.seed_import import CEFR_LEVELS, parse_seed_filename
from db.seed_manifest import MANIFEST_FILENAME, SeedManifestError, load_book_manifest


_BOOK_SLUG_RE = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$", re.IGNORECASE)
_MAX_LEKTION_NUMBER = 9_999


@dataclass(frozen=True)
class _Field:
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class _Schema:
    allowed_headers: frozenset[str]
    required_fields: tuple[_Field, ...]
    duplicate_key: tuple[_Field, ...]
    flexible_headers: bool = False


_VOCAB_HEADERS = {
    "pos",
    "word",
    "article",
    "gender",
    "gender_tip",
    "plural",
    "meaning",
}
for _example_number in range(1, 6):
    _VOCAB_HEADERS.update(
        {f"ex{_example_number}_de", f"ex{_example_number}_en"}
    )

_SENTENCE_TARGET = _Field(
    "sentence",
    (
        "sentence",
        "target_text",
        "text",
        "prompt",
        "sentence_de",
        "sentence_en",
        "sentence_fr",
        "sentence_es",
        "de",
        "en",
        "fr",
        "es",
    ),
)
_SENTENCE_TRANSLATION = _Field(
    "translation_en", ("translation_en", "translation", "en")
)
_SENTENCE_HEADERS = set(_SENTENCE_TARGET.aliases)
_SENTENCE_HEADERS.update(_SENTENCE_TRANSLATION.aliases)
_SENTENCE_HEADERS.update({"words", "word_bank", "bank", "tip"})

_LISTENING_TEXT = _Field(
    "text", ("text", "passage", "transcript", "story", "dialogue", "audio_text")
)
_LISTENING_QUESTION = _Field("question", ("question", "q", "prompt"))
_LISTENING_ANSWER = _Field(
    "answer", ("answer", "correct", "correct_answer", "a")
)
_LISTENING_TRANSLATION = _Field(
    "translation", ("translation", "translation_en", "en")
)
_LISTENING_HEADERS = {
    *_LISTENING_TEXT.aliases,
    *_LISTENING_QUESTION.aliases,
    *_LISTENING_ANSWER.aliases,
    *_LISTENING_TRANSLATION.aliases,
    "tip",
    "hint",
    "distractors",
    "wrong",
    "options",
    "choices",
}
for _option_number in range(1, 7):
    for _option_prefix in ("distractor", "wrong", "option", "choice"):
        _LISTENING_HEADERS.add(f"{_option_prefix}{_option_number}")

_SCHEMAS = {
    "vocab": _Schema(
        frozenset(_VOCAB_HEADERS),
        (
            _Field("pos", ("pos",)),
            _Field("word", ("word",)),
            _Field("meaning", ("meaning",)),
        ),
        (
            _Field("pos", ("pos",)),
            _Field("word", ("word",)),
            _Field("meaning", ("meaning",)),
        ),
    ),
    "grammar": _Schema(
        frozenset(
            {"test_text", "answer", "test_verb", "tip", "meaning", "grammar_tip"}
        ),
        (
            _Field("test_text", ("test_text",)),
            _Field("answer", ("answer",)),
        ),
        (
            _Field("test_text", ("test_text",)),
            _Field("answer", ("answer",)),
        ),
    ),
    "sentences": _Schema(
        frozenset(_SENTENCE_HEADERS),
        (_SENTENCE_TARGET,),
        (_SENTENCE_TARGET,),
        flexible_headers=True,
    ),
    "listening": _Schema(
        frozenset(_LISTENING_HEADERS),
        (
            _LISTENING_TEXT,
            _LISTENING_QUESTION,
            _LISTENING_ANSWER,
        ),
        (_LISTENING_QUESTION, _LISTENING_TEXT),
        flexible_headers=True,
    ),
}


# These are the article/gender representations currently understood by the
# German seed format. A paired value preserves variants such as der/die while
# still catching a typo like article=der, gender=f.
_NOUN_ARTICLE_GENDER_PAIRS = {
    ("-", "-"),
    ("der", "m"),
    ("die", "f"),
    ("das", "n"),
    ("die", "pl"),
    ("die", "f (pl)"),
    ("der/die", "m/f"),
    ("die/der", "f/m"),
    ("der/das", "m/n"),
    ("das/der", "n/m"),
    ("die/das", "f/n"),
    ("das/die", "n/f"),
}


@dataclass(frozen=True, order=True)
class SeedValidationIssue:
    path: str
    line: int
    code: str
    message: str

    def render(self) -> str:
        location = self.path
        if self.line > 0:
            location = f"{location}:{self.line}"
        return f"ERROR [{self.code}] {location}: {self.message}"


@dataclass(frozen=True)
class SeedValidationReport:
    root: Path
    files_checked: int
    rows_checked: int
    errors: tuple[SeedValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = [issue.render() for issue in self.errors]
        if self.ok:
            lines.append(
                "Seed validation passed: "
                f"{self.files_checked} files, {self.rows_checked} rows."
            )
        else:
            lines.append(
                "Seed validation failed: "
                f"{len(self.errors)} errors across "
                f"{self.files_checked} files and {self.rows_checked} rows."
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class _SeedSource:
    path: Path
    display_path: str
    book_slug: str | None
    level: str
    lektion_number: int | None
    objective: str
    title: str | None
    topic: str | None

    @property
    def deck_key(self) -> tuple[str | None, str, int | None, str]:
        return (
            self.book_slug,
            self.level,
            self.lektion_number if self.book_slug is not None else None,
            self.objective,
        )


class _Collector:
    def __init__(self, root: Path):
        self.root = root
        self.files_checked = 0
        self.rows_checked = 0
        self.errors: list[SeedValidationIssue] = []

    def error(
        self,
        path: str,
        code: str,
        message: str,
        *,
        line: int = 0,
    ) -> None:
        self.errors.append(SeedValidationIssue(path, line, code, message))

    def report(self) -> SeedValidationReport:
        return SeedValidationReport(
            root=self.root,
            files_checked=self.files_checked,
            rows_checked=self.rows_checked,
            errors=tuple(sorted(self.errors)),
        )


def _normalise_header(header: str) -> str:
    return (header or "").strip().lower().lstrip("\ufeff")


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _field_value(
    row: Mapping[object, object], field: _Field, *, flexible_headers: bool
) -> str:
    if not flexible_headers:
        return _clean(row.get(field.aliases[0]))

    normalised = {
        _normalise_header(str(key)): value
        for key, value in row.items()
        if key is not None
    }
    for alias in field.aliases:
        if alias in normalised:
            return _clean(normalised[alias])
    return ""


def _header_present(
    headers: list[str], field: _Field, *, flexible_headers: bool
) -> bool:
    if flexible_headers:
        available = {_normalise_header(header) for header in headers}
        return any(alias in available for alias in field.aliases)
    return field.aliases[0] in headers


def _source_from_path(
    root: Path,
    path: Path,
    parsed: tuple[str | None, int | None, str, str | None, str | None],
    collector: _Collector,
) -> _SeedSource | None:
    relative = path.relative_to(root)
    display = relative.as_posix()
    parts = relative.parts
    file_level, lektion_number, objective, title, topic = parsed

    book_slug: str | None = None
    folder_level: str | None = None
    if len(parts) == 1:
        pass  # Legacy book-less file: level must be in the filename.
    elif len(parts) == 2:
        raw_book_slug = parts[0]
        book_slug = raw_book_slug.lower().strip()
        if raw_book_slug != book_slug:
            collector.error(
                display,
                "layout.noncanonical_book_slug",
                "book directory names must already be lowercase with no surrounding whitespace",
            )
            return None
    elif len(parts) == 3:
        raw_book_slug = parts[0]
        book_slug = raw_book_slug.lower().strip()
        if raw_book_slug != book_slug:
            collector.error(
                display,
                "layout.noncanonical_book_slug",
                "book directory names must already be lowercase with no surrounding whitespace",
            )
            return None
        raw_folder_level = parts[1]
        folder_level = raw_folder_level.lower().strip()
        if raw_folder_level != folder_level:
            collector.error(
                display,
                "layout.noncanonical_level",
                "CEFR level directory names must already be lowercase with no surrounding whitespace",
            )
            return None
        if folder_level not in CEFR_LEVELS:
            collector.error(
                display,
                "layout.invalid_level",
                f"'{parts[1]}' is not a supported CEFR level directory",
            )
            return None
    else:
        collector.error(
            display,
            "layout.unsupported_depth",
            "CSV files must be directly under seeds/, a book, or a book/level directory",
        )
        return None

    if book_slug is not None and not _BOOK_SLUG_RE.fullmatch(book_slug):
        collector.error(
            display,
            "layout.invalid_book_slug",
            "book directories may contain lowercase letters, numbers, underscores, and hyphens",
        )
        return None

    if folder_level and file_level and folder_level.upper() != file_level:
        collector.error(
            display,
            "filename.level_conflict",
            f"filename level {file_level} conflicts with folder level {folder_level.upper()}",
        )

    effective_level = (folder_level or file_level or "").upper()
    if not effective_level:
        collector.error(
            display,
            "filename.missing_level",
            "files outside a CEFR level directory must include the level in the filename",
        )
        return None

    if (
        lektion_number is not None
        and not 1 <= lektion_number <= _MAX_LEKTION_NUMBER
    ):
        collector.error(
            display,
            "filename.invalid_lektion",
            f"Lektion numbers must be between 1 and {_MAX_LEKTION_NUMBER}",
        )
        return None

    if book_slug is not None and lektion_number is None:
        collector.error(
            display,
            "filename.missing_lektion",
            "book seeds must include a Lektion number",
        )
        return None

    if book_slug is None and lektion_number is not None:
        collector.error(
            display,
            "filename.unscoped_lektion",
            "book-less legacy seeds cannot preserve a Lektion number",
        )
        return None

    if (title or topic) and (book_slug is None or lektion_number is None):
        collector.error(
            display,
            "filename.unscoped_metadata",
            "Lektion title/topic metadata requires a book and Lektion number",
        )
        return None

    return _SeedSource(
        path=path,
        display_path=display,
        book_slug=book_slug,
        level=effective_level,
        lektion_number=lektion_number,
        objective=objective,
        title=title,
        topic=topic,
    )


def _validate_filename_metadata(path: Path, display: str, collector: _Collector) -> None:
    stem = path.name[: -len(path.suffix)]
    metadata_parts = stem.split("__")
    if len(metadata_parts) > 3:
        collector.error(
            display,
            "filename.extra_metadata",
            "only __Title and __Title__Topic metadata segments are supported",
        )
    if len(metadata_parts) >= 2 and not metadata_parts[1].strip():
        collector.error(
            display,
            "filename.empty_title",
            "Lektion metadata contains an empty title",
        )
    if len(metadata_parts) >= 3 and not metadata_parts[2].strip():
        collector.error(
            display,
            "filename.empty_topic",
            "Lektion metadata contains an empty topic",
        )


def _validate_headers(
    headers: list[str],
    schema: _Schema,
    display: str,
    collector: _Collector,
) -> dict[str, bool]:
    comparable = (
        [_normalise_header(header) for header in headers]
        if schema.flexible_headers
        else headers
    )
    for header, count in Counter(comparable).items():
        if not header:
            collector.error(display, "header.empty", "CSV contains an empty header", line=1)
        elif count > 1:
            collector.error(
                display,
                "header.duplicate",
                f"header '{header}' appears {count} times",
                line=1,
            )

    for header in sorted(set(comparable) - schema.allowed_headers):
        collector.error(
            display,
            "header.unknown",
            f"unsupported header '{header}'",
            line=1,
        )

    present: dict[str, bool] = {}
    for field in schema.required_fields:
        is_present = _header_present(
            headers, field, flexible_headers=schema.flexible_headers
        )
        present[field.name] = is_present
        if not is_present:
            collector.error(
                display,
                "header.missing",
                f"missing required header for '{field.name}'",
                line=1,
            )
    return present


def _validate_vocab_declension(
    row: Mapping[object, object], display: str, line: int, collector: _Collector
) -> None:
    pos = _clean(row.get("pos")).lower()
    article = _clean(row.get("article")).lower()
    gender = _clean(row.get("gender")).lower()

    if pos == "noun":
        if (article, gender) not in _NOUN_ARTICLE_GENDER_PAIRS:
            collector.error(
                display,
                "vocab.invalid_article_gender",
                f"noun article/gender pair '{article or '<empty>'}/{gender or '<empty>'}' is invalid",
                line=line,
            )
        return

    if article not in {"", "-"} or gender not in {"", "-"}:
        collector.error(
            display,
            "vocab.non_noun_declension",
            "only rows with pos=noun may define an article or gender",
            line=line,
        )


def _validate_csv(
    source: _SeedSource,
    collector: _Collector,
) -> None:
    path = source.path
    display = source.display_path
    schema = _SCHEMAS[source.objective]

    try:
        if path.stat().st_size == 0:
            collector.error(display, "file.empty", "CSV file is empty")
            return
    except OSError as exc:
        collector.error(display, "file.unreadable", str(exc))
        return

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            headers = list(reader.fieldnames or [])
            if not headers:
                collector.error(display, "header.missing", "CSV has no header row", line=1)
                return

            present_fields = _validate_headers(headers, schema, display, collector)
            seen: dict[tuple[str, ...], int] = {}
            row_count = 0
            for row in reader:
                row_count += 1
                collector.rows_checked += 1
                line = reader.line_num

                extra_values = row.get(None)
                if extra_values:
                    collector.error(
                        display,
                        "row.extra_values",
                        f"row has {len(extra_values)} value(s) beyond the CSV header",
                        line=line,
                    )

                if any("\x00" in _clean(value) for value in row.values()):
                    collector.error(
                        display,
                        "row.nul_character",
                        "row contains a NUL character",
                        line=line,
                    )

                values: dict[str, str] = {}
                for field in schema.required_fields:
                    value = _field_value(
                        row, field, flexible_headers=schema.flexible_headers
                    )
                    values[field.name] = value
                    if present_fields[field.name] and not value:
                        collector.error(
                            display,
                            "row.empty_required",
                            f"required field '{field.name}' is empty",
                            line=line,
                        )

                duplicate_values = tuple(
                    _field_value(row, field, flexible_headers=schema.flexible_headers)
                    for field in schema.duplicate_key
                )
                if all(duplicate_values):
                    duplicate_key = tuple(
                        value.strip().lower() for value in duplicate_values
                    )
                    first_line = seen.get(duplicate_key)
                    if first_line is not None:
                        collector.error(
                            display,
                            "row.duplicate",
                            f"row duplicates importer identity from line {first_line}",
                            line=line,
                        )
                    else:
                        seen[duplicate_key] = line

                if source.objective == "vocab":
                    _validate_vocab_declension(row, display, line, collector)

            if row_count == 0:
                collector.error(display, "file.no_rows", "CSV contains no data rows")
    except UnicodeDecodeError as exc:
        collector.error(
            display,
            "file.invalid_utf8",
            f"CSV is not valid UTF-8 ({exc.reason})",
        )
    except csv.Error as exc:
        collector.error(
            display,
            "file.invalid_csv",
            str(exc),
            line=getattr(exc, "line_num", 0) or 0,
        )
    except OSError as exc:
        collector.error(display, "file.unreadable", str(exc))


def validate_seed_tree(seed_root: str | Path) -> SeedValidationReport:
    """Validate a seed directory without opening or mutating learner state.

    Supported paths mirror :func:`db.seed_loader.load_all_seeds`: the preferred
    ``<book>/<level>/<lektion>_<objective>.csv`` form plus both legacy flat
    layouts. Every issue in the returned report is deterministic and fatal so
    the same function can gate CI and a future content-pack dry run.
    """

    root = Path(seed_root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"Seed directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Seed path is not a directory: {root}")

    collector = _Collector(root)
    book_dirs = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir() or path.is_symlink()
        ),
        key=lambda path: path.name.casefold(),
    )
    canonical_books: dict[str, Path] = {}
    for book_dir in book_dirs:
        display_book = book_dir.relative_to(root).as_posix()
        canonical = book_dir.name.strip().lower()
        previous = canonical_books.get(canonical)
        if previous is not None:
            collector.error(
                display_book,
                "layout.duplicate_book_slug",
                f"book directory collides with {previous.name!r} after normalization",
            )
        else:
            canonical_books[canonical] = book_dir
        if book_dir.is_symlink():
            collector.error(
                display_book,
                "layout.symlink",
                "seed book directories must not be symbolic links",
            )
            continue
        manifest_path = book_dir / MANIFEST_FILENAME
        if not manifest_path.exists():
            continue
        try:
            load_book_manifest(book_dir)
        except SeedManifestError as exc:
            try:
                display_path = exc.path.relative_to(root).as_posix()
            except ValueError:
                display_path = manifest_path.relative_to(root).as_posix()
            collector.error(
                display_path,
                "manifest.invalid",
                exc.message,
            )

    csv_paths = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() == ".csv"
        ),
        key=lambda path: path.relative_to(root).as_posix().lower(),
    )
    if not csv_paths:
        collector.error(".", "tree.no_csv", "seed directory contains no CSV files")
        return collector.report()

    sources: list[_SeedSource] = []
    for path in csv_paths:
        collector.files_checked += 1
        display = path.relative_to(root).as_posix()
        if path.is_symlink():
            collector.error(
                display,
                "layout.symlink",
                "seed CSV files must not be symbolic links",
            )
            continue
        if path.suffix != ".csv":
            collector.error(
                display,
                "filename.extension_case",
                "use a lowercase .csv extension for cross-platform imports",
            )

        _validate_filename_metadata(path, display, collector)
        parsed = parse_seed_filename(path.name)
        if parsed is None:
            collector.error(
                display,
                "filename.invalid",
                "filename does not identify a supported seed objective",
            )
            continue

        source = _source_from_path(root, path, parsed, collector)
        if source is None:
            # The objective is still known, so validate the CSV itself and
            # surface authoring errors in one run despite the bad location.
            file_level, lesson, objective, title, topic = parsed
            source = _SeedSource(
                path=path,
                display_path=display,
                book_slug=None,
                level=file_level or "",
                lektion_number=lesson,
                objective=objective,
                title=title,
                topic=topic,
            )
        else:
            sources.append(source)
        _validate_csv(source, collector)

    deck_sources: dict[tuple[str | None, str, int | None, str], _SeedSource] = {}
    lesson_metadata: dict[
        tuple[str, str, int], list[_SeedSource]
    ] = {}
    for source in sources:
        previous = deck_sources.get(source.deck_key)
        if previous is not None:
            collector.error(
                source.display_path,
                "deck.duplicate_source",
                f"same logical deck is already supplied by {previous.display_path}",
            )
        else:
            deck_sources[source.deck_key] = source

        if source.book_slug is not None and source.lektion_number is not None:
            lesson_key = (
                source.book_slug,
                source.level,
                source.lektion_number,
            )
            lesson_metadata.setdefault(lesson_key, []).append(source)

    for lesson_sources in lesson_metadata.values():
        titles = {source.title for source in lesson_sources if source.title}
        topics = {source.topic for source in lesson_sources if source.topic}
        if len(titles) > 1:
            for source in lesson_sources:
                if source.title:
                    collector.error(
                        source.display_path,
                        "metadata.conflicting_title",
                        "logical Lektion has conflicting titles across seed filenames",
                    )
        if len(topics) > 1:
            for source in lesson_sources:
                if source.topic:
                    collector.error(
                        source.display_path,
                        "metadata.conflicting_topic",
                        "logical Lektion has conflicting topics across seed filenames",
                    )

    return collector.report()


__all__ = [
    "SeedValidationIssue",
    "SeedValidationReport",
    "validate_seed_tree",
]
