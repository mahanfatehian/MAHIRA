"""A failed card must come back before the session ends.

FSRS schedules a lapse ten minutes out instead of a day out so the learner
meets it again in the same sitting. The state was persisted correctly, but the
queue is built once at session start and only ever shrinks, so the card was
never actually re-shown - the relearning step existed only in the database.
"""

from __future__ import annotations

import time

import pytest

from core.session import _is_relearning_step
from db.repo import VocabState


class _Recorder:
    """Minimal stand-in exercising the queue mechanics directly."""

    from core.session import SessionService as _S

    RELEARN_QUEUE_GAP = _S.RELEARN_QUEUE_GAP
    MAX_RELEARN_REQUEUES = _S.MAX_RELEARN_REQUEUES
    _requeue_for_relearning = _S._requeue_for_relearning

    def __init__(self, queue):
        self._queue = list(queue)
        self._relearn_counts = {}
        self._session_position = 0
        self._session_total = len(queue)


def _state(interval_days: float) -> VocabState:
    return VocabState(
        vocab_id=1,
        ease=2.5,
        interval_days=interval_days,
        reps=1,
        lapses=1,
        due_at=int(time.time()),
        last_review_at=int(time.time()),
        stability=1.0,
        difficulty=8.0,
    )


# --------------------------------------------------------------------------
# When does a review count as a lapse?
# --------------------------------------------------------------------------

def test_a_lapse_is_a_relearning_step():
    assert _is_relearning_step(_state(0.0), was_skipped=False) is True


@pytest.mark.parametrize("interval", [1.0, 3.0, 30.0])
def test_a_successful_review_is_not(interval):
    assert _is_relearning_step(_state(interval), was_skipped=False) is False


def test_a_skip_is_not_a_relearning_step():
    """A skip means 'not now'; re-showing it three cards later ignores that."""
    assert _is_relearning_step(_state(0.0), was_skipped=True) is False


def test_a_missing_or_broken_interval_is_handled():
    class Bare:
        pass

    class Broken:
        interval_days = "?"

    assert _is_relearning_step(Bare(), was_skipped=False) is False
    assert _is_relearning_step(Broken(), was_skipped=False) is False


# --------------------------------------------------------------------------
# Queue mechanics
# --------------------------------------------------------------------------

def test_a_failed_card_is_put_back_into_the_queue():
    session = _Recorder([10, 20, 30, 40, 50])
    session._requeue_for_relearning("vocab", 99)
    assert 99 in session._queue


def test_it_returns_after_the_configured_gap():
    """The queue pops from the END, so the gap is counted from there."""
    session = _Recorder([10, 20, 30, 40, 50])
    session._requeue_for_relearning("vocab", 99)
    served = list(reversed(session._queue))
    assert served.index(99) == _Recorder.RELEARN_QUEUE_GAP


def test_it_still_returns_when_the_queue_is_nearly_empty():
    session = _Recorder([10])
    session._requeue_for_relearning("vocab", 99)
    assert list(reversed(session._queue)) == [10, 99]


def test_it_returns_even_on_the_very_last_card():
    session = _Recorder([])
    session._requeue_for_relearning("vocab", 99)
    assert session._queue == [99]


def test_the_session_total_grows_so_progress_stays_honest():
    session = _Recorder([10, 20, 30])
    before = session._session_total
    session._requeue_for_relearning("vocab", 99)
    assert session._session_total == before + 1


def test_repeated_failures_are_bounded():
    """A card the learner keeps failing must not make the session endless."""
    session = _Recorder([10, 20, 30])
    for _ in range(20):
        session._requeue_for_relearning("vocab", 99)
    assert session._queue.count(99) == _Recorder.MAX_RELEARN_REQUEUES


def test_the_cap_is_per_item():
    session = _Recorder([10, 20, 30])
    for _ in range(20):
        session._requeue_for_relearning("vocab", 98)
        session._requeue_for_relearning("vocab", 99)
    assert session._queue.count(98) == _Recorder.MAX_RELEARN_REQUEUES
    assert session._queue.count(99) == _Recorder.MAX_RELEARN_REQUEUES


def test_the_cap_is_per_objective():
    session = _Recorder([10, 20, 30])
    session._requeue_for_relearning("vocab", 7)
    session._requeue_for_relearning("grammar", 7)
    assert session._relearn_counts[("vocab", 7)] == 1
    assert session._relearn_counts[("grammar", 7)] == 1


def test_the_gap_is_long_enough_to_be_a_real_recall_attempt():
    assert _Recorder.RELEARN_QUEUE_GAP >= 2


# --------------------------------------------------------------------------
# End to end: a real session, a real failed card
# --------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "src" / "db" / "schema.sql"


@pytest.fixture()
def repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo
    from db.seed_loader import load_all_seeds

    db_path = tmp_path / "relearn.db"
    init_db(db_path, SCHEMA)
    r = Repo(db_path)
    load_all_seeds(r, REPO_ROOT)
    return r


@pytest.fixture()
def session(repo):
    from core.session import AppState, SessionService

    s = SessionService(repo, AppState())
    s.set_context("A1", "vocab", book_slug="starten_wir", lektion_number=1)
    assert s.start_new_session() is True
    return s


def _fail(session, item):
    return session.submit_vocab(
        item=item,
        typed_meaning="definitely wrong",
        typed_gender="",
        typed_plural="",
        rating=0,
        tip_used=False,
        gender_tip_used=False,
        was_checked=True,
        was_skipped=False,
        response_ms=1500,
    )


def _pass(session, item):
    return session.submit_vocab(
        item=item,
        typed_meaning=item.meaning,
        typed_gender=item.article or "",
        typed_plural=item.plural or "",
        rating=2,
        tip_used=False,
        gender_tip_used=False,
        was_checked=True,
        was_skipped=False,
        response_ms=1500,
    )


def test_a_failed_card_is_served_again_in_the_same_session(session):
    first = session.next_vocab_item()
    _fail(session, first)

    seen = []
    item = session.next_vocab_item()
    while item is not None:
        seen.append(item.id)
        item = session.next_vocab_item()

    assert first.id in seen, "the failed card never came back"


def test_the_failed_card_is_scheduled_minutes_away_not_days(session, repo):
    from core import fsrs

    first = session.next_vocab_item()
    before = int(time.time())
    _fail(session, first)
    state = repo.get_state(first.id)
    assert state.interval_days == 0.0
    assert before <= state.due_at <= before + fsrs.RELEARN_STEP_SECONDS + 5


def test_a_passed_card_is_not_served_again(session):
    first = session.next_vocab_item()
    _pass(session, first)

    seen = []
    item = session.next_vocab_item()
    while item is not None:
        seen.append(item.id)
        item = session.next_vocab_item()

    assert first.id not in seen


def test_the_session_still_terminates_when_everything_is_failed(session):
    served = 0
    item = session.next_vocab_item()
    while item is not None and served < 2000:
        _fail(session, item)
        served += 1
        item = session.next_vocab_item()

    assert item is None, "session did not terminate"
    assert served < 2000
