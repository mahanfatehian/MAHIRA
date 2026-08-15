from __future__ import annotations

import os
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_progress_refresh_reuses_one_repository_connection(tmp_path, monkeypatch):
    import db.repo as repo_module
    from types import SimpleNamespace
    from db.init_db import init_db
    from db.repo import Repo
    from ui.pages.progress import ProgressPage

    db_path = tmp_path / "progress-refresh.db"
    init_db(db_path)
    repo = Repo(db_path)
    session = SimpleNamespace(
        repo=repo,
        settings=SimpleNamespace(value=SimpleNamespace(daily_goal=10)),
        state=SimpleNamespace(
            level='A1', objective='vocab', book_slug='', lektion_number=0
        ),
        active_deck_id=lambda: None,
        ml=None,
        enable_ml_ranking=False,
    )
    real_connect = repo_module.connect
    opens = 0

    def counted_connect(path):
        nonlocal opens
        opens += 1
        return real_connect(path)

    monkeypatch.setattr(repo_module, "connect", counted_connect)
    _qapp()
    page = ProgressPage(session)
    try:
        page.on_show()
        assert opens == 1
    finally:
        page.close()
        page.deleteLater()


def test_progress_shows_the_canonical_global_plan_without_an_active_lesson(
    monkeypatch,
):
    from core.planner import DailyPlanSnapshot, ObjectivePlan
    from PySide6.QtWidgets import QGroupBox, QLabel

    import ui.pages.progress as progress_module

    snapshot = DailyPlanSnapshot(
        captured_at=1_700_000_000,
        day_start=1_699_920_000,
        day_end=1_700_006_400,
        goal=10,
        completed_total=3,
        planned_total=7,
        ready_due=12,
        ready_new=3,
        backlog_due=6,
        backlog_new=2,
        objectives=(
            ObjectivePlan("vocab", 2, 1, 1, 8, 2, 4, 1, 4, 1),
            ObjectivePlan("grammar", 1, 1, 0, 4, 1, 2, 0, 2, 1),
            ObjectivePlan("sentences", 0, 0, 0, 0, 0, 0, 0, 0, 0),
            ObjectivePlan("listening", 0, 0, 0, 0, 0, 0, 0, 0, 0),
        ),
        segments=(),
    )

    class Planner:
        def snapshot(self):
            return snapshot

    monkeypatch.setattr(
        progress_module,
        "DailyPlannerService",
        lambda *_args, **_kwargs: Planner(),
        raising=False,
    )
    session = SimpleNamespace(
        repo=SimpleNamespace(daily_review_counts=lambda *_args, **_kwargs: {}),
        settings=SimpleNamespace(value=SimpleNamespace(daily_goal=10)),
        state=SimpleNamespace(
            level="A1",
            objective="vocab",
            book_slug="menschen",
            lektion_number=1,
        ),
        active_deck_id=lambda: None,
        ml=object(),
    )

    _qapp()
    page = progress_module.ProgressPage(session)
    page.show()
    try:
        page.on_show()

        copy = {
            label.text().casefold() for label in page.findChildren(QLabel)
        }
        titles = {
            group.title().casefold() for group in page.findChildren(QGroupBox)
        }
        assert {"3 completed", "7 planned", "12 due", "3 new"} <= copy
        assert "today's plan" in titles
        assert "current lesson" in titles
        assert "ready now" in titles
        assert "reviewed today" in titles
        assert "due now" not in titles
        assert "reviewed (24h)" not in titles
        assert page.today_value.text() == "3 / 10"
    finally:
        page.close()
        page.deleteLater()


def test_progress_snapshot_failure_clears_stale_data_and_stops_dependent_reads():
    from core.planner import DailyPlanSnapshot, ObjectivePlan

    import ui.pages.progress as progress_module

    snapshot = DailyPlanSnapshot(
        captured_at=1_700_000_000,
        day_start=1_699_920_000,
        day_end=1_700_006_400,
        goal=10,
        completed_total=3,
        planned_total=7,
        ready_due=12,
        ready_new=3,
        backlog_due=6,
        backlog_new=2,
        objectives=tuple(
            ObjectivePlan(objective, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            for objective in ("vocab", "grammar", "sentences", "listening")
        ),
        segments=(),
    )

    class Planner:
        calls = 0

        def snapshot(self):
            self.calls += 1
            if self.calls == 1:
                return snapshot
            raise RuntimeError("database unavailable")

    class Repo:
        activity_reads = 0

        def daily_review_counts(self, _since):
            self.activity_reads += 1
            return {}

    repo = Repo()
    active_deck_reads = 0

    def active_deck_id():
        nonlocal active_deck_reads
        active_deck_reads += 1
        return None

    session = SimpleNamespace(
        repo=repo,
        settings=SimpleNamespace(value=SimpleNamespace(daily_goal=10)),
        state=SimpleNamespace(
            level="A1",
            objective="vocab",
            book_slug="menschen",
            lektion_number=1,
        ),
        active_deck_id=active_deck_id,
        ml=None,
    )

    _qapp()
    page = progress_module.ProgressPage(session)
    page.planner = Planner()
    page.show()
    try:
        page.on_show()
        assert page.plan_completed_label.text() == "3 completed"
        assert page.today_value.text() == "3 / 10"
        assert page.due_card.value_label.text() == "0"

        page.on_show()

        assert page._snapshot is None
        assert page.plan_completed_label.text() == "Plan unavailable"
        assert "3 completed" not in " ".join(
            label.text() for label in (
                page.plan_completed_label,
                page.plan_planned_label,
                page.plan_due_label,
                page.plan_new_label,
            )
        )
        assert page.streak_value.text() == "--"
        assert page.longest_value.text() == "--"
        assert page.today_value.text() == "-- / --"
        assert "unavailable" in page.activity_caption.text().casefold()
        assert page.due_card.value_label.text() == "--"
        assert page.reviewed_today_card.value_label.text() == "--"
        assert "unavailable" in page.performance_label.text().casefold()
        assert repo.activity_reads == 1
        assert active_deck_reads == 1
    finally:
        page.close()
        page.deleteLater()


@pytest.mark.parametrize("objective", ("vocab", "grammar", "sentences", "listening"))
@pytest.mark.parametrize("boundary", ("due", "cooldown"))
def test_progress_ready_now_uses_snapshot_clock_across_eligibility_boundaries(
    tmp_path,
    monkeypatch,
    objective,
    boundary,
):
    """A refresh must not mix the planner clock with a later wall clock."""
    from core.planner import DailyPlanSnapshot, ObjectivePlan
    from db.init_db import init_db
    from db.repo import Repo

    import db.repo as repo_module
    import ui.pages.progress as progress_module

    captured_at = 1_700_000_000
    later_clock = captured_at + (2 * 3600)
    db_path = tmp_path / f"progress-{objective}-{boundary}.db"
    init_db(db_path)
    repo = Repo(db_path)
    deck_id, _changed = repo.upsert_deck(
        "A1",
        objective,
        f"{objective}.csv",
        "snapshot-clock",
    )

    if objective == "vocab":
        item_id = repo.insert_vocab(
            deck_id, "noun", "Termin", "der", "m", "Termine", "appointment"
        )
        repo.ensure_state(item_id)
        state_table, foreign_key = "vocab_states", "vocab_id"
        counter = repo.due_count
    elif objective == "grammar":
        item_id = repo.insert_grammar(
            deck_id, "Ich ___ Deutsch.", "lerne", "lernen", None, None, None
        )
        repo.ensure_grammar_state(item_id)
        state_table, foreign_key = "grammar_states", "grammar_id"
        counter = repo.grammar_due_count
    elif objective == "sentences":
        item_id = repo.insert_sentence(
            deck_id,
            "Ich lerne Deutsch.",
            "I learn German.",
            None,
            '["Ich", "lerne", "Deutsch", "."]',
        )
        repo.ensure_sentence_state(item_id)
        state_table, foreign_key = "sentence_states", "sentence_id"
        counter = repo.sentence_due_count
    else:
        item_id = repo.insert_listening(
            deck_id,
            "Ich habe morgen einen Termin.",
            "Wann ist der Termin?",
            "Morgen",
            '["Heute", "Gestern"]',
            None,
            None,
        )
        repo.ensure_listening_state(item_id)
        state_table, foreign_key = "listening_states", "listening_id"
        counter = repo.listening_due_count

    due_at = captured_at + 1 if boundary == "due" else captured_at - 1
    last_review_at = (
        captured_at - (11 * 3600) if boundary == "cooldown" else None
    )
    with repo._conn() as conn:
        conn.execute(
            f"UPDATE {state_table} "
            "SET due_at=?, last_review_at=?, suspended=0, buried_until=NULL "
            f"WHERE {foreign_key}=?",
            (due_at, last_review_at, item_id),
        )

    monkeypatch.setattr(
        repo_module,
        "time",
        SimpleNamespace(time=lambda: later_clock),
    )
    assert counter(deck_id, cooldown_hours=12) == 1

    snapshot = DailyPlanSnapshot(
        captured_at=captured_at,
        day_start=captured_at - 3600,
        day_end=captured_at + (23 * 3600),
        goal=10,
        completed_total=0,
        planned_total=0,
        ready_due=0,
        ready_new=0,
        backlog_due=0,
        backlog_new=0,
        objectives=tuple(
            ObjectivePlan(name, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            for name in ("vocab", "grammar", "sentences", "listening")
        ),
        segments=(),
    )
    planner = SimpleNamespace(snapshot=lambda: snapshot)
    session = SimpleNamespace(
        repo=repo,
        settings=SimpleNamespace(value=SimpleNamespace(daily_goal=10)),
        state=SimpleNamespace(
            level="A1",
            objective=objective,
            book_slug="menschen",
            lektion_number=1,
        ),
        active_deck_id=lambda: deck_id,
        ml=None,
    )

    _qapp()
    page = progress_module.ProgressPage(session)
    page.planner = planner
    page.show()
    try:
        page.on_show()

        assert page.due_card.value_label.text() == "0"
    finally:
        page.close()
        page.deleteLater()
