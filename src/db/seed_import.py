from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CEFR_LEVELS = {"a1", "a2", "b1", "b2", "c1", "c2"}
ALLOWED_OBJECTIVES = {"vocab", "grammar", "sentences", "listening"}

_TOKEN_RE = re.compile(
    r"[A-Za-zÄÖÜäöüß]+(?:[-'][A-Za-zÄÖÜäöüß]+)*|\d+|[.,!?;:()\[\]{}\"„‚''…–—-]"
)


class SeedImportError(ValueError):
    """A seed file could not be prepared safely for import."""


@dataclass(frozen=True)
class PreparedSeed:
    """One CSV snapshot shared by preflight and apply."""

    path: Path
    book_slug: str | None
    level: str
    lektion_number: int | None
    objective: str
    title: str | None
    topic: str | None
    seed_sha1: str
    rows: tuple[dict[str, object], ...]

    @property
    def deck_key(self) -> tuple[str, int | None, str, str]:
        # A book has no database identity unless there is a Lektion.
        book = self.book_slug if self.lektion_number is not None else None
        return (book or "", self.lektion_number, self.level, self.objective)


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tokenize_sentence(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text or "") if token.strip()]


def _split_words_bank(raw: str, fallback_sentence: str) -> list[str]:
    raw = (raw or "").strip()
    if raw:
        if raw.startswith("[") and raw.endswith("]"):
            try:
                value = json.loads(raw)
                if isinstance(value, list):
                    items = [str(item).strip() for item in value if str(item).strip()]
                    if items:
                        return items
            except (TypeError, ValueError):
                pass
        separator = "|" if "|" in raw else None
        items = [item.strip() for item in raw.split(separator) if item.strip()]
        if items:
            return items
    return _tokenize_sentence(fallback_sentence)


def parse_seed_filename(
    name: str,
) -> Optional[tuple[Optional[str], Optional[int], str, Optional[str], Optional[str]]]:
    """Return (level, lektion, objective, title, topic) for a seed name."""
    raw = (name or "").strip()
    if not raw.lower().endswith(".csv"):
        return None
    metadata = raw[:-4].split("__")
    core = metadata[0]
    title = metadata[1].strip() if len(metadata) >= 2 and metadata[1].strip() else None
    topic = metadata[2].strip() if len(metadata) >= 3 and metadata[2].strip() else None
    parts = [part for part in core.lower().split("_") if part]
    if not parts:
        return None
    level: str | None = None
    if parts[0] in CEFR_LEVELS:
        level = parts.pop(0).upper()
    if not parts:
        return None
    lektion_number: int | None = None
    if parts[0].isdigit():
        lektion_number = int(parts.pop(0))
    objective = "_".join(parts)
    if objective not in ALLOWED_OBJECTIVES:
        return None
    return level, lektion_number, objective, title, topic


def _norm_key(*parts: object) -> tuple[str, ...]:
    return tuple(str(part or "").strip().casefold() for part in parts)


def _slug_to_title(slug: str) -> str:
    return " ".join(word.capitalize() for word in (slug or "").replace("-", "_").split("_"))


def _row_value(row: dict[str | None, str | list[str] | None], *names: str) -> str:
    wanted = {name.strip().casefold() for name in names}
    for key, value in row.items():
        normalized = str(key or "").strip().lstrip("\ufeff").casefold()
        if normalized in wanted:
            return str(value or "").strip()
    return ""


def _require(value: str, label: str, path: Path, line_number: int) -> str:
    value = (value or "").strip()
    if not value:
        raise SeedImportError(f"{path}:{line_number}: missing {label}")
    return value


def _prepare_vocab_row(
    row: dict[str | None, str | list[str] | None], path: Path, line_number: int
) -> dict[str, object]:
    pos = _require(_row_value(row, "pos"), "pos", path, line_number).lower()
    word = _require(_row_value(row, "word"), "word", path, line_number)
    meaning = _require(_row_value(row, "meaning"), "meaning", path, line_number)

    examples: list[tuple[str, str | None]] = []
    seen_examples: set[tuple[str, str]] = set()
    for index in range(1, 6):
        german = _row_value(row, f"ex{index}_de")
        english = _row_value(row, f"ex{index}_en")
        if not german:
            continue
        key = _norm_key(german, english)
        if key in seen_examples:
            continue
        seen_examples.add(key)
        examples.append((german, english or None))

    return {
        "pos": pos,
        "word": word,
        "article": _row_value(row, "article") or None,
        "gender": _row_value(row, "gender") or None,
        "gender_tip": _row_value(row, "gender_tip") or None,
        "plural": _row_value(row, "plural") or None,
        "meaning": meaning,
        "examples": tuple(examples),
    }


def _prepare_grammar_row(
    row: dict[str | None, str | list[str] | None], path: Path, line_number: int
) -> dict[str, object]:
    return {
        "test_text": _require(_row_value(row, "test_text"), "test_text", path, line_number),
        "answer": _require(_row_value(row, "answer"), "answer", path, line_number),
        "test_verb": _row_value(row, "test_verb") or None,
        "tip": _row_value(row, "tip") or None,
        "meaning": _row_value(row, "meaning") or None,
        "grammar_tip": _row_value(row, "grammar_tip") or None,
    }


def _prepare_sentence_row(
    row: dict[str | None, str | list[str] | None], path: Path, line_number: int
) -> dict[str, object]:
    target = _require(
        _row_value(
            row,
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
        "sentence",
        path,
        line_number,
    )
    words = _split_words_bank(_row_value(row, "words", "word_bank", "bank"), target)
    if not words:
        raise SeedImportError(f"{path}:{line_number}: sentence has no usable word bank")
    return {
        "target_text": target,
        "translation": _row_value(row, "translation_en", "translation", "en") or None,
        "tip": _row_value(row, "tip") or None,
        "words_json": json.dumps(words, ensure_ascii=False),
    }


def _prepare_listening_row(
    row: dict[str | None, str | list[str] | None], path: Path, line_number: int
) -> dict[str, object]:
    text_value = _require(
        _row_value(row, "text", "passage", "transcript", "story", "dialogue", "audio_text"),
        "text",
        path,
        line_number,
    )
    question = _require(_row_value(row, "question", "q", "prompt"), "question", path, line_number)
    answer = _require(
        _row_value(row, "answer", "correct", "correct_answer", "a"),
        "answer",
        path,
        line_number,
    )

    candidates: list[str] = []
    combined = _row_value(row, "distractors", "wrong", "options", "choices")
    if combined:
        separator = "|" if "|" in combined else ";" if ";" in combined else None
        candidates.extend(part.strip() for part in combined.split(separator))
    for index in range(1, 7):
        value = _row_value(
            row,
            f"distractor{index}",
            f"wrong{index}",
            f"option{index}",
            f"choice{index}",
        )
        if value:
            candidates.append(value)

    seen = {_norm_key(answer)}
    distractors: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        key = _norm_key(candidate)
        if not candidate or key in seen:
            continue
        seen.add(key)
        distractors.append(candidate)

    return {
        "text": text_value,
        "question": question,
        "answer": answer,
        "distractors_json": json.dumps(distractors, ensure_ascii=False),
        "translation": _row_value(row, "translation", "translation_en", "en") or None,
        "tip": _row_value(row, "tip", "hint") or None,
    }


def _logical_key(objective: str, row: dict[str, object]) -> tuple[str, ...]:
    if objective == "vocab":
        return _norm_key(row["pos"], row["word"], row["meaning"])
    if objective == "grammar":
        return _norm_key(row["test_text"], row["answer"])
    if objective == "sentences":
        return _norm_key(row["target_text"])
    return _norm_key(row["question"], row["text"])


def prepare_seed_csv(
    csv_path: Path,
    *,
    book_slug: str | None = None,
    lektion_number: int | None = None,
    level: str | None = None,
) -> PreparedSeed | None:
    """Read and normalize one seed without touching SQLite."""
    csv_path = Path(csv_path)
    parsed = parse_seed_filename(csv_path.name)
    if parsed is None:
        return None
    file_level, file_lektion, objective, title, topic = parsed
    effective_level = (level or file_level or "").upper().strip()
    if effective_level.casefold() not in CEFR_LEVELS:
        raise SeedImportError(f"{csv_path}: missing or invalid CEFR level")
    effective_lektion = lektion_number if lektion_number is not None else file_lektion

    try:
        source = csv_path.read_bytes()
    except OSError as exc:
        raise SeedImportError(f"{csv_path}: could not read seed") from exc
    if not source:
        raise SeedImportError(f"{csv_path}: seed file is empty")
    try:
        text_value = source.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SeedImportError(f"{csv_path}: seed is not valid UTF-8") from exc

    reader = csv.DictReader(io.StringIO(text_value, newline=""))
    if not reader.fieldnames:
        raise SeedImportError(f"{csv_path}: missing CSV header")

    builders = {
        "vocab": _prepare_vocab_row,
        "grammar": _prepare_grammar_row,
        "sentences": _prepare_sentence_row,
        "listening": _prepare_listening_row,
    }
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, ...]] = set()
    for line_number, raw_row in enumerate(reader, start=2):
        if None in raw_row:
            raise SeedImportError(f"{csv_path}:{line_number}: values exceed the CSV header")
        row = builders[objective](raw_row, csv_path, line_number)
        key = _logical_key(objective, row)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    if not rows:
        raise SeedImportError(f"{csv_path}: seed contains no importable rows")

    return PreparedSeed(
        path=csv_path,
        book_slug=(book_slug or "").lower().strip() or None,
        level=effective_level,
        lektion_number=effective_lektion,
        objective=objective,
        title=title,
        topic=topic,
        seed_sha1=hashlib.sha1(source).hexdigest(),
        rows=tuple(rows),
    )


def apply_prepared_seed(repo, seed: PreparedSeed) -> int:
    """Apply a prepared seed inside the caller's database transaction."""
    lektion_id: int | None = None
    if seed.book_slug and seed.lektion_number is not None:
        book_id = repo.ensure_book(seed.book_slug, _slug_to_title(seed.book_slug))
        lektion_id = repo.ensure_lektion(
            book_id,
            seed.level,
            seed.lektion_number,
            seed.title or f"Lektion {seed.lektion_number}",
            description=seed.topic,
        )

    deck_id, _changed = repo.upsert_deck(
        seed.level,
        seed.objective,
        seed.path.name,
        seed.seed_sha1,
        lektion_id=lektion_id,
    )
    synchronizer = {
        "vocab": repo.sync_vocab_seed,
        "grammar": repo.sync_grammar_seed,
        "sentences": repo.sync_sentences_seed,
        "listening": repo.sync_listening_seed,
    }[seed.objective]
    synchronizer(deck_id, seed.rows)
    return deck_id


def import_seed_csv(
    repo,
    csv_path: Path,
    book_slug: str | None = None,
    lektion_number: int | None = None,
    level: str | None = None,
) -> None:
    """Backward-compatible atomic one-file import.

    Pack imports should use db.seed_loader.load_all_seeds so every file is
    prepared and the database is backed up before the batch is applied.
    """
    seed = prepare_seed_csv(
        csv_path,
        book_slug=book_slug,
        lektion_number=lektion_number,
        level=level,
    )
    if seed is None:
        return
    with repo.transaction():
        apply_prepared_seed(repo, seed)
