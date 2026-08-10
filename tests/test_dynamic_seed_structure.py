"""Folder-driven CEFR structure: books appear only at the levels they have
folders for -- no hardcoded book<->level mapping anywhere."""

import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "src" / "db" / "schema.sql"

VOCAB_CSV = (
    "pos,word,article,gender,meaning\n"
    "noun,Haus,das,n,house\n"
    "verb,gehen,,,to go\n"
)


def test_parse_levelless_and_legacy_filenames():
    from db.seed_import import parse_seed_filename

    # Folder-based: no level in the filename.
    assert parse_seed_filename("1_vocab.csv") == (None, 1, "vocab", None, None)
    assert parse_seed_filename("3_sentences.csv") == (None, 3, "sentences", None, None)
    assert parse_seed_filename("1_vocab__Super!__Greetings.csv") == (
        None,
        1,
        "vocab",
        "Super!",
        "Greetings",
    )
    # Legacy flat layout with the level encoded in the filename still parses.
    assert parse_seed_filename("a1_1_grammar.csv") == ("A1", 1, "grammar", None, None)
    assert parse_seed_filename("b1_2_vocab.csv") == ("B1", 2, "vocab", None, None)
    # Junk is rejected.
    assert parse_seed_filename("notacsv.txt") is None
    assert parse_seed_filename("1_bogus.csv") is None


def _build_seeds(tmp_path):
    seeds = tmp_path / "data" / "seeds"
    layout = {
        "starten_wir/a1/1_vocab__Super!__Greetings.csv": VOCAB_CSV,
        "starten_wir/a2/1_vocab__Damals und heute__Past tense.csv": VOCAB_CSV,
        "sicher/b1/1_vocab__Auftakt__Intro.csv": VOCAB_CSV,
    }
    for rel, content in layout.items():
        p = seeds / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def _repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo
    from db.seed_loader import load_all_seeds

    db = tmp_path / "m.db"
    init_db(db, SCHEMA)
    repo = Repo(db)
    load_all_seeds(repo, tmp_path)
    return repo


def test_books_appear_only_at_their_folder_level(tmp_path):
    _build_seeds(tmp_path)
    repo = _repo(tmp_path)

    def slugs(level):
        return sorted(b.slug for b in repo.get_books_for_level(level))

    # Starten Wir has a1 + a2 folders only; Sicher has b1 only. Nothing is
    # hardcoded -- this comes entirely from the folder structure.
    assert slugs("A1") == ["starten_wir"]
    assert slugs("A2") == ["starten_wir"]
    assert slugs("B1") == ["sicher"]
    assert slugs("B2") == []  # no b2 folder anywhere -> no book at B2
    assert slugs("C1") == []


def test_levels_enabled_follow_content(tmp_path):
    _build_seeds(tmp_path)
    repo = _repo(tmp_path)

    assert repo.has_decks_for_level("A1") is True
    assert repo.has_decks_for_level("A2") is True
    assert repo.has_decks_for_level("B1") is True
    assert repo.has_decks_for_level("B2") is False
    assert repo.has_decks_for_level("C2") is False


def test_level_comes_from_folder_not_filename(tmp_path):
    _build_seeds(tmp_path)
    repo = _repo(tmp_path)

    # The A2 lektion's level is taken from the a2/ folder; its title/topic come
    # from the filename metadata.
    bid = repo.get_book_id("starten_wir")
    a2 = repo.get_lektions_for_book_level(bid, "A2")
    assert len(a2) == 1
    assert a2[0].level == "A2"
    assert a2[0].number == 1
    assert a2[0].title == "Damals und heute"
    assert a2[0].description == "Past tense"


def test_identical_deck_upsert_preserves_update_timestamp(tmp_path, monkeypatch):
    import db.repo as repo_module
    from db.init_db import init_db
    from db.repo import Repo

    db = tmp_path / "deck-upsert.db"
    init_db(db, SCHEMA)
    repo = Repo(db)
    clock = iter((100, 200, 300))
    monkeypatch.setattr(repo_module.time, "time", lambda: next(clock))

    deck_id, changed = repo.upsert_deck("A1", "vocab", "one.csv", "same-sha")
    assert changed is True

    same_id, changed = repo.upsert_deck("A1", "vocab", "one.csv", "same-sha")
    assert same_id == deck_id
    assert changed is False
    with repo._conn() as conn:
        unchanged = conn.execute(
            "SELECT seed_file, updated_at FROM decks WHERE id=?",
            (deck_id,),
        ).fetchone()
    assert unchanged["seed_file"] == "one.csv"
    assert unchanged["updated_at"] == 100

    same_id, changed = repo.upsert_deck("A1", "vocab", "renamed.csv", "same-sha")
    assert same_id == deck_id
    assert changed is False
    with repo._conn() as conn:
        renamed = conn.execute(
            "SELECT seed_file, updated_at FROM decks WHERE id=?",
            (deck_id,),
        ).fetchone()
    assert renamed["seed_file"] == "renamed.csv"
    assert renamed["updated_at"] == 300


def test_bundled_seed_rows_match_their_csv_schema():
    from db.seed_import import parse_seed_filename

    required = {
        "vocab": ("pos", "word", "meaning"),
        "grammar": ("test_text", "answer", "meaning"),
        "sentences": ("sentence", "translation_en"),
        "listening": ("text", "question", "answer", "translation"),
    }
    errors: list[str] = []

    for csv_path in sorted((REPO_ROOT / "data" / "seeds").rglob("*.csv")):
        parsed = parse_seed_filename(csv_path.name)
        if parsed is None:
            errors.append(f"{csv_path}: filename does not identify an objective")
            continue
        objective = parsed[2]

        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                errors.append(f"{csv_path}: missing header")
                continue

            missing_headers = [name for name in required[objective] if name not in reader.fieldnames]
            if missing_headers:
                errors.append(f"{csv_path}: missing headers {missing_headers}")
                continue

            for line_number, row in enumerate(reader, 2):
                if None in row:
                    errors.append(f"{csv_path}:{line_number}: values exceed the CSV header")
                missing_values = [
                    name for name in required[objective] if not (row.get(name) or "").strip()
                ]
                if missing_values:
                    errors.append(
                        f"{csv_path}:{line_number}: missing values {missing_values}"
                    )

    assert not errors, "\n".join(errors)
