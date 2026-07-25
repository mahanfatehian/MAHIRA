from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Optional

CEFR_LEVELS = {"a1", "a2", "b1", "b2", "c1", "c2"}
ALLOWED_OBJECTIVES = {"vocab", "grammar", "sentences", "listening"}

_TOKEN_RE = re.compile(
    r"[A-Za-zÄÖÜäöüß]+(?:[-'][A-Za-zÄÖÜäöüß]+)*|\d+|[.,!?;:()\[\]{}\"""„‚''…–—-]"
)


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tokenize_sentence(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text or "") if t and not t.isspace()]


def _split_words_bank(raw: str, fallback_sentence: str) -> list[str]:
    raw = (raw or "").strip()
    if raw:
        if raw.startswith("[") and raw.endswith("]"):
            try:
                arr = json.loads(raw)
                if isinstance(arr, list):
                    out = [str(x).strip() for x in arr if str(x).strip()]
                    if out:
                        return out
            except Exception:
                pass

        if "|" in raw:
            toks = [t.strip() for t in raw.split("|") if t.strip()]
        else:
            toks = [t.strip() for t in raw.split() if t.strip()]
        if toks:
            return toks

    return _tokenize_sentence(fallback_sentence)


def parse_seed_filename(
    name: str,
) -> Optional[tuple[Optional[str], Optional[int], str, Optional[str], Optional[str]]]:
    """
    Parse a seed CSV filename and return
        (level, lektion_number, objective, title, topic).

    The CEFR level is OPTIONAL in the filename. In the folder-based layout the
    level comes from the directory (data/seeds/<book>/<level>/...), so the
    filename only needs "<lektion_number>_<objective>":

        "1_vocab.csv", "1_grammar.csv", "3_sentences.csv"

    The legacy flat layout, where the level is encoded in the filename, is also
    still accepted for backward compatibility:

        "a1_1_vocab.csv", "a1_vocab.csv"

    Optional Lektion metadata may be appended after a double-underscore so the
    Lektion's display name and topic live IN THE FILENAME (not in CSV content):

        "<n>_<objective>__<Title>__<Topic>.csv"
        e.g. "1_vocab__Super!__Greetings, names, numbers 0-20, alphabet.csv"

    Only ONE file per Lektion needs the metadata (the vocab file is the
    convention). title/topic keep their original casing; the core part is
    matched case-insensitively. `level` is returned upper-cased or None when the
    filename carries no level (the caller then supplies it from the folder).

    Returns None if the filename doesn't match a valid pattern.
    """
    raw = (name or "").strip()
    if not raw.lower().endswith(".csv"):
        return None

    base = raw[:-4]  # keep original case for title/topic

    # Split optional "__Title__Topic" metadata off the core part.
    meta = base.split("__")
    core = meta[0]
    title = meta[1].strip() if len(meta) >= 2 and meta[1].strip() else None
    topic = meta[2].strip() if len(meta) >= 3 and meta[2].strip() else None

    parts = [p for p in core.lower().split("_") if p != ""]
    if not parts:
        return None

    # Optional leading CEFR level (legacy flat layout).
    level: Optional[str] = None
    if parts[0] in CEFR_LEVELS:
        level = parts[0].upper()
        parts = parts[1:]

    if not parts:
        return None

    # Optional leading Lektion number.
    lektion_number: Optional[int] = None
    if parts[0].isdigit():
        lektion_number = int(parts[0])
        objective = "_".join(parts[1:])
    else:
        objective = "_".join(parts)

    if objective not in ALLOWED_OBJECTIVES:
        return None

    return level, lektion_number, objective, title, topic


def _norm_key(*parts: str) -> tuple[str, ...]:
    return tuple((p or "").strip().lower() for p in parts)


def _sentences_deck_needs_reimport(repo, deck_id: int) -> bool:
    try:
        with repo._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM sentences
                WHERE deck_id=?
                  AND (
                    target_text IS NULL OR TRIM(target_text)=''
                    OR words_json IS NULL OR TRIM(words_json)=''
                    OR TRIM(words_json)='[]'
                  )
                """,
                (deck_id,),
            ).fetchone()
            return bool(row) and int(row["c"]) > 0
    except Exception:
        return False


def _slug_to_title(slug: str) -> str:
    """Convert a directory slug like 'starten_wir' to 'Starten Wir'."""
    return " ".join(word.capitalize() for word in (slug or "").replace("-", "_").split("_"))


def import_seed_csv(
    repo,
    csv_path: Path,
    book_slug: str | None = None,
    lektion_number: int | None = None,
    level: str | None = None,
) -> None:
    parsed = parse_seed_filename(csv_path.name)
    if not parsed:
        return

    file_level, file_lektion_number, objective, file_title, file_topic = parsed

    # Level from the caller (i.e. the folder data/seeds/<book>/<level>/) takes
    # priority over any level encoded in the filename. This is what makes the
    # CEFR structure fully folder-driven and dynamic.
    effective_level = (level or file_level)
    if not effective_level:
        return
    effective_level = effective_level.upper().strip()

    # lektion_number from caller takes priority (e.g. if parsed from dir structure),
    # otherwise use the one embedded in the filename.
    effective_lektion = lektion_number if lektion_number is not None else file_lektion_number

    try:
        if csv_path.stat().st_size == 0:
            return
    except Exception:
        pass

    seed_sha1 = sha1_file(csv_path)

    # Resolve lektion_id from book/lektion if provided. The Lektion's display
    # name (title) and topic (description) come from the filename metadata — see
    # parse_seed_filename. ensure_lektion only overwrites them when a real name
    # is supplied, so the metadata can live on a single file per Lektion.
    lektion_id: int | None = None
    if book_slug and effective_lektion is not None:
        book_id = repo.ensure_book(
            book_slug,
            _slug_to_title(book_slug),
        )
        lektion_title = file_title or f"Lektion {effective_lektion}"
        lektion_id = repo.ensure_lektion(
            book_id, effective_level, effective_lektion, lektion_title, description=file_topic
        )

    deck_id, changed = repo.upsert_deck(
        effective_level, objective, csv_path.name, seed_sha1, lektion_id=lektion_id
    )

    # ---------- VOCAB ----------
    if objective == "vocab":
        if not changed and repo.deck_vocab_count(deck_id) > 0:
            return
        repo.clear_vocab_deck(deck_id)

        seen: set[tuple[str, str, str]] = set()

        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return

            for row in reader:
                pos = (row.get("pos") or "").strip()
                word = (row.get("word") or "").strip()
                meaning = (row.get("meaning") or "").strip()
                if not pos or not word or not meaning:
                    continue

                key = _norm_key(pos, word, meaning)
                if key in seen:
                    continue
                seen.add(key)

                gender_tip = (row.get("gender_tip") or "").strip()

                vocab_id = repo.insert_vocab(
                    deck_id=deck_id,
                    pos=pos,
                    word=word,
                    article=(row.get("article") or "").strip(),
                    gender=(row.get("gender") or "").strip(),
                    plural=(row.get("plural") or "").strip(),
                    meaning=meaning,
                    gender_tip=gender_tip or None,
                )

                seen_ex: set[tuple[str, str]] = set()
                for i in range(1, 6):
                    de = (row.get(f"ex{i}_de") or "").strip()
                    en = (row.get(f"ex{i}_en") or "").strip()
                    if not de:
                        continue
                    ex_key = _norm_key(de, en)
                    if ex_key in seen_ex:
                        continue
                    seen_ex.add(ex_key)
                    repo.insert_example(vocab_id, de, en or None)
        return

    # ---------- GRAMMAR ----------
    if objective == "grammar":
        if not changed and repo.deck_grammar_count(deck_id) > 0:
            return
        repo.clear_grammar_deck(deck_id)

        seen: set[tuple[str, str]] = set()

        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return

            for row in reader:
                test_text = (row.get("test_text") or "").strip()
                answer = (row.get("answer") or "").strip()
                if not test_text or not answer:
                    continue

                key = _norm_key(test_text, answer)
                if key in seen:
                    continue
                seen.add(key)

                repo.insert_grammar(
                    deck_id=deck_id,
                    test_text=test_text,
                    answer=answer,
                    test_verb=(row.get("test_verb") or "").strip() or None,
                    tip=(row.get("tip") or "").strip() or None,
                    meaning=(row.get("meaning") or "").strip() or None,
                    grammar_tip=(row.get("grammar_tip") or "").strip() or None,
                )
        return

    # ---------- SENTENCES ----------
    if objective == "sentences":
        if not changed and repo.deck_sentences_count(deck_id) > 0 and not _sentences_deck_needs_reimport(repo, deck_id):
            return

        repo.clear_sentences_deck(deck_id)

        def _get(row: dict, *names: str) -> str:
            for n in names:
                n = (n or "").strip().lower()
                for k in row.keys():
                    kk = (k or "").strip().lower().lstrip("﻿")
                    if kk == n:
                        return (row.get(k) or "").strip()
            return ""

        seen: set[tuple[str]] = set()

        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return

            for row in reader:
                target = _get(
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
                )
                if not target:
                    continue

                key = _norm_key(target)
                if key in seen:
                    continue
                seen.add(key)

                words_raw = _get(row, "words", "word_bank", "bank")
                words = _split_words_bank(words_raw, target)
                if not words:
                    words = _tokenize_sentence(target)

                tip = _get(row, "tip") or None
                translation = _get(row, "translation_en", "translation", "en") or None

                repo.insert_sentence(
                    deck_id=deck_id,
                    target_text=target,
                    translation=translation,
                    tip=tip,
                    words_json=json.dumps(words, ensure_ascii=False),
                )
        return

    # ---------- LISTENING ----------
    if objective == "listening":
        if not changed and repo.deck_listening_count(deck_id) > 0:
            return
        repo.clear_listening_deck(deck_id)

        def _get(row: dict, *names: str) -> str:
            for n in names:
                n = (n or "").strip().lower()
                for k in row.keys():
                    kk = (k or "").strip().lower().lstrip("﻿")
                    if kk == n:
                        return (row.get(k) or "").strip()
            return ""

        def _distractors(row: dict, answer: str) -> list[str]:
            """Collect wrong options from either numbered columns
            (distractor1, distractor2, ... / wrong1, option_b ...) or a single
            pipe/semicolon-separated 'distractors' column. The correct answer is
            never included as its own distractor."""
            out: list[str] = []
            seen = {(_norm_key(answer))}

            combined = _get(row, "distractors", "wrong", "options", "choices")
            parts: list[str] = []
            if combined:
                if "|" in combined:
                    parts = [p.strip() for p in combined.split("|")]
                elif ";" in combined:
                    parts = [p.strip() for p in combined.split(";")]
                else:
                    parts = [combined.strip()]

            for i in range(1, 7):
                v = _get(row, f"distractor{i}", f"wrong{i}", f"option{i}", f"choice{i}")
                if v:
                    parts.append(v)

            for p in parts:
                p = (p or "").strip()
                if not p:
                    continue
                k = _norm_key(p)
                if k in seen:
                    continue
                seen.add(k)
                out.append(p)
            return out

        seen: set[tuple[str, ...]] = set()

        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return

            for row in reader:
                text = _get(row, "text", "passage", "transcript", "story", "dialogue", "audio_text")
                question = _get(row, "question", "q", "prompt")
                answer = _get(row, "answer", "correct", "correct_answer", "a")
                if not text or not question or not answer:
                    continue

                key = _norm_key(question, text)
                if key in seen:
                    continue
                seen.add(key)

                distractors = _distractors(row, answer)
                translation = _get(row, "translation", "translation_en", "en") or None
                tip = _get(row, "tip", "hint") or None

                repo.insert_listening(
                    deck_id=deck_id,
                    text=text,
                    question=question,
                    answer=answer,
                    distractors_json=json.dumps(distractors, ensure_ascii=False),
                    translation=translation,
                    tip=tip,
                )
        return
