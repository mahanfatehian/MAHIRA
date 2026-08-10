from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


VOCAB_HEADER = "pos,word,article,gender,plural,meaning,ex1_de,ex1_en\n"
GRAMMAR_HEADER = "test_text,answer,test_verb,tip,meaning,grammar_tip\n"
SENTENCE_HEADER = "sentence,words,tip,translation_en\n"
LISTENING_HEADER = "text,question,answer,distractor1,translation,tip\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(
    tmp_path: Path, *, grammar: bool = False, all_objectives: bool = False
) -> Path:
    _write(
        tmp_path / "data/seeds/book/a1/1_vocab__One__Topic.csv",
        VOCAB_HEADER
        + "adj,Adjektiv,,,Adjektive,adjective word,Das ist ein Adjektiv.,That is an adjective.\n"
        + "noun,Alt,das,n,,old thing,Das ist alt.,That is old.\n",
    )
    if grammar or all_objectives:
        _write(
            tmp_path / "data/seeds/book/a1/1_grammar.csv",
            GRAMMAR_HEADER
            + "Ich null hier.,bin,sein,present tense,I am here.,sein: ich bin\n",
        )
    if all_objectives:
        _write(
            tmp_path / "data/seeds/book/a1/1_sentences.csv",
            SENTENCE_HEADER
            + "Ich bin hier.,Ich|bin|hier|.,location,I am here.\n",
        )
        _write(
            tmp_path / "data/seeds/book/a1/1_listening.csv",
            LISTENING_HEADER
            + "Ich bin hier.,Wo bin ich?,hier,dort,I am here.,listen\n",
        )
    return tmp_path


def _repo(tmp_path: Path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "mahira.db"
    init_db(db_path)
    return Repo(db_path)


class RecordingBackup:
    def __init__(self, db_path: Path):
        from db.backup import BackupService

        self.service = BackupService(db_path)
        self.calls: list[str] = []

    def create(self, reason: str):
        self.calls.append(reason)
        return self.service.create(reason, prune=False)


def _vocab_rows(repo):
    with repo._conn() as conn:
        return conn.execute(
            "SELECT id, pos, word, meaning FROM vocab ORDER BY id"
        ).fetchall()


def test_changed_seed_keeps_unambiguous_card_history_and_one_backup(tmp_path):
    from db.seed_loader import load_all_seeds

    project = _project(tmp_path)
    repo = _repo(tmp_path)
    load_all_seeds(repo, project)

    original = {str(row["word"]): row for row in _vocab_rows(repo)}
    adjective_id = int(original["Adjektiv"]["id"])
    removed_id = int(original["Alt"]["id"])
    repo.ensure_state(adjective_id)
    with repo._conn() as conn:
        conn.execute("INSERT INTO reviews(vocab_id, rating) VALUES(?, ?)", (adjective_id, 2))
        conn.execute(
            "INSERT INTO card_flags(item_type,item_id,note) VALUES('vocab',?,?)",
            (adjective_id, "keep"),
        )
        conn.execute(
            "INSERT INTO card_flags(item_type,item_id,note) VALUES('vocab',?,?)",
            (removed_id, "remove"),
        )

    _write(
        project / "data/seeds/book/a1/1_vocab__One__Topic.csv",
        VOCAB_HEADER
        + "noun,Adjektiv,das,n,Adjektive,adjective,Das ist ein Adjektiv.,That is an adjective.\n"
        + "noun,Neu,das,n,,new thing,Das ist neu.,That is new.\n",
    )
    backups = RecordingBackup(repo.db_path)
    result = load_all_seeds(repo, project, backup_service=backups)

    assert backups.calls == ["pre-seed-import"]
    assert result.backup is not None and result.backup.path.is_file()
    updated = {str(row["word"]): row for row in _vocab_rows(repo)}
    assert int(updated["Adjektiv"]["id"]) == adjective_id
    assert updated["Adjektiv"]["pos"] == "noun"
    assert updated["Adjektiv"]["meaning"] == "adjective"
    assert repo.get_state(adjective_id) is not None
    with repo._conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE vocab_id=?", (adjective_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT note FROM card_flags WHERE item_type='vocab' AND item_id=?",
            (adjective_id,),
        ).fetchone()[0] == "keep"
        assert conn.execute(
            "SELECT 1 FROM card_flags WHERE item_type='vocab' AND item_id=?",
            (removed_id,),
        ).fetchone() is None

    before = sqlite3.connect(result.backup.path)
    try:
        assert before.execute(
            "SELECT pos, meaning FROM vocab WHERE id=?", (adjective_id,)
        ).fetchone() == ("adj", "adjective word")
        assert before.execute(
            "SELECT COUNT(*) FROM reviews WHERE vocab_id=?", (adjective_id,)
        ).fetchone()[0] == 1
    finally:
        before.close()


def test_other_objectives_preserve_ids_states_and_reviews_on_updates(tmp_path):
    from db.seed_loader import load_all_seeds

    project = _project(tmp_path, all_objectives=True)
    repo = _repo(tmp_path)
    load_all_seeds(repo, project)
    with repo._conn() as conn:
        grammar_id = int(conn.execute("SELECT id FROM grammar").fetchone()[0])
        sentence_id = int(conn.execute("SELECT id FROM sentences").fetchone()[0])
        listening_id = int(conn.execute("SELECT id FROM listening").fetchone()[0])
    repo.ensure_grammar_state(grammar_id)
    repo.ensure_sentence_state(sentence_id)
    repo.ensure_listening_state(listening_id)
    with repo._conn() as conn:
        conn.execute("INSERT INTO grammar_reviews(grammar_id) VALUES(?)", (grammar_id,))
        conn.execute("INSERT INTO sentence_reviews(sentence_id) VALUES(?)", (sentence_id,))
        conn.execute("INSERT INTO listening_reviews(listening_id) VALUES(?)", (listening_id,))

    _write(
        project / "data/seeds/book/a1/1_grammar.csv",
        GRAMMAR_HEADER
        + "Ich null hier.,stehe,stehen,new tip,I stand here.,stehen: ich stehe\n",
    )
    _write(
        project / "data/seeds/book/a1/1_sentences.csv",
        SENTENCE_HEADER
        + "Ich bin hier.,Ich|bin|hier|.,new location tip,I am right here.\n",
    )
    _write(
        project / "data/seeds/book/a1/1_listening.csv",
        LISTENING_HEADER
        + "Ich bin hier.,Wo bin ich?,dort,hier,I am right here.,new listen tip\n",
    )
    backups = RecordingBackup(repo.db_path)
    load_all_seeds(repo, project, backup_service=backups)

    assert backups.calls == ["pre-seed-import"]
    grammar = repo.get_grammar_by_id(grammar_id)
    sentence = repo.get_sentence_by_id(sentence_id)
    listening = repo.get_listening_by_id(listening_id)
    assert grammar is not None and grammar.answer == "stehe" and grammar.tip == "new tip"
    assert sentence is not None and sentence.translation == "I am right here."
    assert listening is not None and listening.answer == "dort"
    assert repo.get_grammar_state(grammar_id) is not None
    assert repo.get_sentence_state(sentence_id) is not None
    assert repo.get_listening_state(listening_id) is not None
    with repo._conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM grammar_reviews WHERE grammar_id=?", (grammar_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM sentence_reviews WHERE sentence_id=?", (sentence_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM listening_reviews WHERE listening_id=?", (listening_id,)
        ).fetchone()[0] == 1


def test_unchanged_second_load_does_not_create_a_backup(tmp_path):
    from db.seed_loader import load_all_seeds

    project = _project(tmp_path)
    repo = _repo(tmp_path)
    load_all_seeds(repo, project)
    backups = RecordingBackup(repo.db_path)

    plan = load_all_seeds(repo, project, backup_service=backups)

    assert not plan.has_changes
    assert backups.calls == []


def test_dry_run_reports_change_without_database_or_backup_writes(tmp_path):
    from db.seed_loader import load_all_seeds

    project = _project(tmp_path)
    repo = _repo(tmp_path)
    load_all_seeds(repo, project)
    before = [(int(row["id"]), str(row["meaning"])) for row in _vocab_rows(repo)]

    _write(
        project / "data/seeds/book/a1/1_vocab__One__Topic.csv",
        VOCAB_HEADER + "noun,Adjektiv,das,n,Adjektive,changed meaning,,\n",
    )
    backups = RecordingBackup(repo.db_path)
    plan = load_all_seeds(repo, project, dry_run=True, backup_service=backups)

    assert [entry.action for entry in plan.changes] == ["update"]
    assert backups.calls == []
    assert [(int(row["id"]), str(row["meaning"])) for row in _vocab_rows(repo)] == before


def test_dry_run_does_not_create_a_missing_database(tmp_path):
    from db.repo import Repo
    from db.seed_loader import load_all_seeds

    project = _project(tmp_path)
    db_path = tmp_path / "not-created.db"
    repo = Repo(db_path)

    plan = load_all_seeds(repo, project, dry_run=True)

    assert plan.has_changes
    assert {entry.action for entry in plan.entries} == {"add"}
    assert not db_path.exists()


def test_backup_failure_prevents_seed_writes(tmp_path):
    from db.seed_loader import load_all_seeds

    project = _project(tmp_path)
    repo = _repo(tmp_path)
    load_all_seeds(repo, project)
    before = [(int(row["id"]), str(row["meaning"])) for row in _vocab_rows(repo)]

    _write(
        project / "data/seeds/book/a1/1_vocab__One__Topic.csv",
        VOCAB_HEADER + "noun,Adjektiv,das,n,Adjektive,changed meaning,,\n",
    )

    class FailingBackup:
        def create(self, _reason: str):
            raise RuntimeError("injected backup failure")

    with pytest.raises(RuntimeError, match="injected backup failure"):
        load_all_seeds(repo, project, backup_service=FailingBackup())

    assert [(int(row["id"]), str(row["meaning"])) for row in _vocab_rows(repo)] == before


def test_invalid_pack_fails_before_backup_or_database_writes(tmp_path):
    from db.seed_import import SeedImportError
    from db.seed_loader import load_all_seeds

    project = _project(tmp_path)
    repo = _repo(tmp_path)
    load_all_seeds(repo, project)
    before = [(int(row["id"]), str(row["meaning"])) for row in _vocab_rows(repo)]
    _write(
        project / "data/seeds/book/a1/1_vocab__One__Topic.csv",
        VOCAB_HEADER + "noun,Adjektiv,das,n,Adjektive,,,\n",
    )
    backups = RecordingBackup(repo.db_path)

    with pytest.raises(SeedImportError, match="required field 'meaning' is empty"):
        load_all_seeds(repo, project, backup_service=backups)

    assert backups.calls == []
    assert [(int(row["id"]), str(row["meaning"])) for row in _vocab_rows(repo)] == before


def test_changed_pack_rolls_back_as_one_transaction(tmp_path, monkeypatch):
    import db.seed_loader as loader

    project = _project(tmp_path, grammar=True)
    repo = _repo(tmp_path)
    loader.load_all_seeds(repo, project)
    with repo._conn() as conn:
        old_hashes = dict(
            conn.execute("SELECT objective, seed_sha1 FROM decks").fetchall()
        )
        old_meaning = conn.execute(
            "SELECT meaning FROM vocab WHERE word='Adjektiv'"
        ).fetchone()[0]

    _write(
        project / "data/seeds/book/a1/1_vocab__One__Topic.csv",
        VOCAB_HEADER + "noun,Adjektiv,das,n,Adjektive,changed meaning,,\n",
    )
    _write(
        project / "data/seeds/book/a1/1_grammar.csv",
        GRAMMAR_HEADER
        + "Ich null hier.,stehe,stehen,present tense,I stand here.,stehen: ich stehe\n",
    )

    real_apply = loader.apply_prepared_seed

    applied: list[str] = []

    def fail_after_first(repo_arg, seed):
        if not applied:
            applied.append(seed.objective)
            return real_apply(repo_arg, seed)
        raise RuntimeError("injected apply failure")

    monkeypatch.setattr(loader, "apply_prepared_seed", fail_after_first)
    backups = RecordingBackup(repo.db_path)
    with pytest.raises(RuntimeError, match="injected apply failure"):
        loader.load_all_seeds(repo, project, backup_service=backups)

    assert backups.calls == ["pre-seed-import"]
    assert applied
    with repo._conn() as conn:
        assert dict(conn.execute("SELECT objective, seed_sha1 FROM decks").fetchall()) == old_hashes
        assert conn.execute(
            "SELECT meaning FROM vocab WHERE word='Adjektiv'"
        ).fetchone()[0] == old_meaning
