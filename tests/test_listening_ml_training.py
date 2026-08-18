"""Listening reviews must train the ranker like the other three lanes.

session.submit_listening already called ml.update_listening behind a hasattr
guard, but SklearnRanker never defined the method, so listening contributed
zero training data and its model stayed unfitted forever.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "src" / "db" / "schema.sql"


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db_path = tmp_path / "listening-ml.db"
    init_db(db_path, SCHEMA)
    return Repo(db_path)


@pytest.fixture()
def ranker(repo, tmp_path):
    from core.ml.sklearn_ranker import SklearnRanker

    return SklearnRanker(repo, model_dir=tmp_path / "ml_models")


def _item(repo):
    deck_id, _ = repo.upsert_deck("A1", "listening", "l.csv", "sha-l")
    item_id = repo.insert_listening(
        deck_id,
        "Guten Morgen.",
        "Wie begruesst die Person?",
        "Guten Morgen",
        json.dumps(["Gute Nacht", "Auf Wiedersehen"]),
        None,
        None,
    )
    return repo.get_listening_by_id(item_id)


def test_update_listening_exists(ranker):
    assert callable(getattr(ranker, "update_listening", None))


def test_update_listening_fits_the_lane_model(repo, ranker):
    item = _item(repo)
    state = repo.ensure_listening_state(item.id)

    for _ in range(25):
        ranker.update_listening(
            item=item,
            state_before=state,
            review_result={"ok": False},
            effective_rating=0,
            was_checked=True,
            was_skipped=False,
            response_ms=4000,
            level="A1",
        )

    model = ranker._load_model("listening", "A1")
    assert model.samples_seen >= 25


def test_submit_listening_trains_through_the_session(repo, tmp_path):
    from core.ml.sklearn_ranker import SklearnRanker
    from core.session import AppState, SessionService

    item = _item(repo)
    session = SessionService(repo, AppState())
    session.ml = SklearnRanker(repo, model_dir=tmp_path / "ml_models")
    session.set_context("A1", "listening", book_slug="", lektion_number=0)

    # Force the item into the live queue so submit path runs fully.
    session._queue = []
    session._current_item_id = item.id
    session._current_objective = "listening"
    session._session_total = 1
    session._session_position = 0

    session.submit_listening(
        item=item,
        chosen="Gute Nacht",
        was_checked=True,
        was_skipped=False,
        response_ms=2500,
        replay_count=2,
        rating=0,
    )

    model = session.ml._load_model("listening", "A1")
    assert model.samples_seen >= 1
