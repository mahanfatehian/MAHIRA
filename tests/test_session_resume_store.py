from __future__ import annotations

import json


def _snapshot(**changes):
    from core.session_resume import SessionSnapshot

    values = {
        "level": "A1",
        "objective": "vocab",
        "book_slug": "starten_wir",
        "lektion_number": 7,
        "deck_id": 42,
        "deck_seed_sha1": "seed-sha",
        "queue": (10, 11, 12),
        "current_item_id": 13,
        "current_state_token": "2:0:100:200",
        "position": 2,
        "total": 10,
        "study_answered": 32,
        "study_next_milestone": 60,
        "saved_at": 123456,
    }
    values.update(changes)
    return SessionSnapshot(**values)


def test_session_resume_store_round_trips_versioned_state(tmp_path):
    from core.session_resume import SESSION_RESUME_VERSION, SessionResumeStore

    path = tmp_path / ".mahira" / "active_session.json"
    store = SessionResumeStore(path)
    expected = _snapshot(book_slug="menschen")

    store.save(expected)

    assert store.load() == expected
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == SESSION_RESUME_VERSION
    assert payload["queue"] == [10, 11, 12]
    assert not path.with_suffix(".json.tmp").exists()


def test_session_resume_store_ignores_corrupt_or_untrusted_payloads(tmp_path):
    from core.session_resume import SessionResumeStore

    path = tmp_path / "active_session.json"
    store = SessionResumeStore(path)
    invalid = [
        "not json",
        json.dumps([]),
        json.dumps({**_snapshot().to_dict(), "version": 999}),
        json.dumps({**_snapshot().to_dict(), "queue": [10, 10]}),
        json.dumps({**_snapshot().to_dict(), "deck_id": True}),
        json.dumps({**_snapshot().to_dict(), "position": 2.5}),
        json.dumps({**_snapshot().to_dict(), "current_item_id": 10}),
        json.dumps({**_snapshot().to_dict(), "queue": [], "current_item_id": None}),
    ]

    for payload in invalid:
        path.write_text(payload, encoding="utf-8")
        assert store.load() is None


def test_failed_atomic_replace_preserves_previous_checkpoint(tmp_path, monkeypatch):
    import core.session_resume as resume_module
    from core.session_resume import SessionResumeStore

    path = tmp_path / "active_session.json"
    store = SessionResumeStore(path)
    original = _snapshot()
    store.save(original)

    def fail_replace(_source, _target):
        raise OSError("disk unavailable")

    monkeypatch.setattr(resume_module.os, "replace", fail_replace)
    try:
        store.save(_snapshot(position=3, current_item_id=14))
    except OSError:
        pass
    else:
        raise AssertionError("save should surface an atomic replacement failure")

    assert json.loads(path.read_text(encoding="utf-8")) == original.to_dict()
    assert not path.with_suffix(".json.tmp").exists()


def test_session_resume_store_clear_removes_checkpoint_and_temporary_file(tmp_path):
    from core.session_resume import SessionResumeStore

    path = tmp_path / "active_session.json"
    temporary = path.with_suffix(".json.tmp")
    path.write_text("{}", encoding="utf-8")
    temporary.write_text("partial", encoding="utf-8")

    SessionResumeStore(path).clear()

    assert not path.exists()
    assert not temporary.exists()
