from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

VOCAB = (
    "pos,word,article,gender,gender_tip,plural,meaning,ex1_de,ex1_en\n"
    "noun,Haus,das,n,neutral nouns often use das,Häuser,house,Das ist ein Haus.,"
    "That is a house.\n"
)
GRAMMAR = (
    "test_text,answer,test_verb,tip,meaning,grammar_tip\n"
    "Ich null hier.,wohne,wohnen,present tense,I live here.,ich uses -e\n"
)
SENTENCES = (
    "sentence,words,tip,translation_en\n"
    "Ich wohne hier.,Ich|wohne|hier|.,word order,I live here.\n"
)
LISTENING = (
    "text,question,answer,distractor1,distractor2,distractor3,translation,tip\n"
    "Ich wohne hier.,Wo wohnt die Person?,hier,dort,links,rechts,"
    "I live here.,Listen for hier.\n"
)


def _write(root: Path, relative: str, content: str | bytes = VOCAB) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _codes(report) -> list[str]:
    return [issue.code for issue in report.errors]


def test_valid_canonical_seed_tree_passes(tmp_path: Path):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(root, "book/a1/1_vocab__Arrival__Introductions.csv", VOCAB)
    _write(root, "book/a1/1_grammar.csv", GRAMMAR)
    _write(root, "book/a1/1_sentences.csv", SENTENCES)
    _write(root, "book/a1/1_listening.csv", LISTENING)

    report = validate_seed_tree(root)

    assert report.ok
    assert report.files_checked == 4
    assert report.rows_checked == 4
    assert report.errors == ()
    assert report.render() == "Seed validation passed: 4 files, 4 rows."


def test_bundled_seed_tree_passes_validation():
    from db.seed_validation import validate_seed_tree

    report = validate_seed_tree(REPO_ROOT / "data" / "seeds")

    assert report.ok, report.render()
    assert report.files_checked > 0
    assert report.rows_checked > 0


@pytest.mark.parametrize(
    ("relative", "expected_code"),
    [
        ("book/a7/1_vocab.csv", "layout.invalid_level"),
        ("book/a1/not_content.csv", "filename.invalid"),
        ("book/a1/nested/1_vocab.csv", "layout.unsupported_depth"),
        ("book/a1/a2_1_vocab.csv", "filename.level_conflict"),
        ("book/a1/0_vocab.csv", "filename.invalid_lektion"),
        ("book/a1/10000_vocab.csv", "filename.invalid_lektion"),
        ("book/a1/vocab.csv", "filename.missing_lektion"),
        ("1_vocab.csv", "filename.missing_level"),
        ("a1_1_vocab.csv", "filename.unscoped_lektion"),
    ],
)
def test_invalid_seed_locations_and_names_are_errors(
    tmp_path: Path, relative: str, expected_code: str
):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(root, relative)

    report = validate_seed_tree(root)

    assert not report.ok
    assert expected_code in _codes(report)


def test_invalid_headers_are_reported_together(tmp_path: Path):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(
        root,
        "book/a1/1_vocab.csv",
        "pos,word,meanng,word\nnoun,Haus,house,Haus\n",
    )

    report = validate_seed_tree(root)

    assert not report.ok
    assert {"header.duplicate", "header.unknown", "header.missing"}.issubset(
        _codes(report)
    )


@pytest.mark.parametrize(
    ("relative", "expected_code"),
    (
        ("Book/a1/1_vocab.csv", "layout.noncanonical_book_slug"),
        ("book/A1/1_vocab.csv", "layout.noncanonical_level"),
    ),
)
def test_noncanonical_folder_names_are_rejected(
    tmp_path: Path,
    relative: str,
    expected_code: str,
):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(root, relative)

    assert expected_code in _codes(validate_seed_tree(root))


def test_bom_and_values_beyond_header_are_errors(tmp_path: Path):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    malformed = b"\xef\xbb\xbfpos,word,meaning\nverb,gehen,to go,unexpected\n"
    _write(root, "book/a1/1_vocab.csv", malformed)

    report = validate_seed_tree(root)

    assert not report.ok
    assert "file.bom" in _codes(report)
    assert "row.extra_values" in _codes(report)


@pytest.mark.parametrize(
    ("filename", "content", "field"),
    [
        ("1_vocab.csv", "pos,word,meaning\nverb,gehen,   \n", "meaning"),
        (
            "1_grammar.csv",
            "test_text,answer,meaning\nIch null hier.,,I live here.\n",
            "answer",
        ),
        (
            "1_sentences.csv",
            "sentence,translation_en\n,I live here.\n",
            "sentence",
        ),
        (
            "1_listening.csv",
            "text,question,answer,translation\nHallo!,Was hörst du?,,Hello!\n",
            "answer",
        ),
    ],
)
def test_empty_required_values_are_errors(
    tmp_path: Path, filename: str, content: str, field: str
):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(root, f"book/a1/{filename}", content)

    report = validate_seed_tree(root)

    matching = [issue for issue in report.errors if issue.code == "row.empty_required"]
    assert any(f"'{field}'" in issue.message for issue in matching)


def test_optional_explanations_and_translations_may_be_empty(tmp_path: Path):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(
        root,
        "book/a1/1_grammar.csv",
        "test_text,answer,meaning\nIch null hier.,wohne,\n",
    )
    _write(
        root,
        "book/a1/1_sentences.csv",
        "sentence,translation_en\nIch wohne hier.,\n",
    )
    _write(
        root,
        "book/a1/1_listening.csv",
        "text,question,answer,translation\nHallo!,Was hörst du?,Hallo!,\n",
    )

    report = validate_seed_tree(root)

    assert report.ok, report.render()


def test_manifest_errors_are_reported_by_validation_and_cli(tmp_path: Path):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(root, "book/a1/1_vocab.csv", VOCAB)
    (root / "book/manifest.json").write_bytes(b'{"title": "\xff"}')

    report = validate_seed_tree(root)

    assert "manifest.invalid" in _codes(report)
    environment, _runtime = _cli_environment(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "mahira", "validate-seeds", str(root)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "manifest.invalid" in result.stdout


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        (
            "1_vocab.csv",
            "pos,word,article,gender,meaning\n"
            "noun,Haus,das,n,house\n"
            "NOUN, haus ,das,n,HOUSE\n",
        ),
        (
            "1_grammar.csv",
            "test_text,answer,meaning\n"
            "Ich null hier.,wohne,I live here.\n"
            " ich null hier. ,WOHNE,Here I live.\n",
        ),
        (
            "1_sentences.csv",
            "sentence,translation_en\n"
            "Ich wohne hier.,I live here.\n"
            " ich wohne hier. ,Here I live.\n",
        ),
        (
            "1_listening.csv",
            "text,question,answer,translation\n"
            "Hallo!,Was hörst du?,Hallo!,Hello!\n"
            " hallo! , WAS HÖRST DU? ,Etwas anderes,Something else\n",
        ),
    ],
)
def test_duplicate_rows_match_importer_identity(
    tmp_path: Path, filename: str, content: str
):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(root, f"book/a1/{filename}", content)

    report = validate_seed_tree(root)

    duplicates = [issue for issue in report.errors if issue.code == "row.duplicate"]
    assert len(duplicates) == 1
    assert "line 2" in duplicates[0].message


def test_invalid_noun_metadata_and_non_noun_declension_are_errors(tmp_path: Path):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(
        root,
        "book/a1/1_vocab.csv",
        "pos,word,article,gender,meaning\n"
        "noun,Tisch,der,f,table\n"
        "adj,Adjektiv,das,n,adjective\n",
    )

    report = validate_seed_tree(root)

    assert "vocab.invalid_article_gender" in _codes(report)
    assert "vocab.non_noun_declension" in _codes(report)


def test_legacy_flat_layouts_remain_valid(tmp_path: Path):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(root, "a1_vocab.csv", "pos,word,meaning\nverb,gehen,to go\n")
    _write(root, "legacy_book/a1_1_vocab.csv", VOCAB)

    report = validate_seed_tree(root)

    assert report.ok, report.render()


def test_duplicate_decks_and_conflicting_metadata_are_errors(tmp_path: Path):
    from db.seed_validation import validate_seed_tree

    root = tmp_path / "seeds"
    _write(root, "book/a1/1_vocab__Arrival__Basics.csv", VOCAB)
    _write(root, "book/a1/1_vocab.csv", VOCAB)
    _write(root, "book/a1/1_grammar__Welcome__Other.csv", GRAMMAR)

    report = validate_seed_tree(root)

    assert "deck.duplicate_source" in _codes(report)
    assert "metadata.conflicting_title" in _codes(report)
    assert "metadata.conflicting_topic" in _codes(report)


def _cli_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    # A raising PySide6 stub proves that validate-seeds never imports the GUI.
    blocker = tmp_path / "import-blocker"
    package = blocker / "PySide6"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "raise RuntimeError('validate-seeds imported PySide6')\n", encoding="utf-8"
    )
    runtime = tmp_path / "runtime"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(blocker), str(REPO_ROOT / "src"))
    )
    environment["PYTHONUTF8"] = "1"
    environment["MAHIRA_DATA_DIR"] = str(runtime)
    return environment, runtime


def test_validate_seeds_cli_is_gui_free_and_does_not_create_state(tmp_path: Path):
    root = tmp_path / "seeds"
    _write(root, "book/a1/1_vocab.csv", VOCAB)
    environment, runtime = _cli_environment(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "mahira", "validate-seeds", str(root)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Seed validation passed" in result.stdout
    assert not runtime.exists()


def test_validate_seeds_cli_uses_distinct_failure_exit_codes(tmp_path: Path):
    root = tmp_path / "seeds"
    _write(root, "book/a1/1_vocab.csv", "pos,word,meaning\nverb,gehen,\n")
    environment, _runtime = _cli_environment(tmp_path)

    invalid = subprocess.run(
        [sys.executable, "-m", "mahira", "validate-seeds", str(root)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    missing = subprocess.run(
        [
            sys.executable,
            "-m",
            "mahira",
            "validate-seeds",
            str(tmp_path / "missing"),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert invalid.returncode == 1
    assert "Seed validation failed" in invalid.stdout
    assert missing.returncode == 2
    assert "Seed directory does not exist" in missing.stderr
