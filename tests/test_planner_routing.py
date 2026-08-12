from __future__ import annotations

from dataclasses import replace
import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


_RETURN_REQUEST = object()


class _SessionFake:
    def __init__(
        self,
        events: list[tuple],
        *,
        preview_result=_RETURN_REQUEST,
        unfinished: bool = False,
        start_result: bool = True,
    ) -> None:
        self.events = events
        self.preview_result = preview_result
        self.unfinished = unfinished
        self.start_result = start_result

    def preview_planned_segment(self, segment, now=None):
        self.events.append(("preview_planned_segment", segment))
        if self.preview_result is _RETURN_REQUEST:
            return segment
        return self.preview_result

    def has_unfinished_session(self) -> bool:
        self.events.append(("has_unfinished_session",))
        return self.unfinished

    def start_planned_segment_for_context(
        self,
        segment,
        *,
        replace_unfinished=False,
        now=None,
    ) -> bool:
        self.events.append(
            (
                "start_planned_segment_for_context",
                segment,
                replace_unfinished,
            )
        )
        return self.start_result

    def start(self, *args, **kwargs):
        self.events.append(("legacy_start", args, kwargs))
        return True


class _TodayFake:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def show_plan_error(self, message: str) -> None:
        self.messages.append(message)


class _BannerFake:
    def __init__(self) -> None:
        self.hidden = 0

    def hide(self) -> None:
        self.hidden += 1


class _WindowHarness:
    _OBJ_TO_PAGE = {
        "vocab": "vocab_review",
        "grammar": "grammar_review",
        "sentences": "sentence_review",
        "listening": "listening_review",
    }

    def __init__(
        self,
        session: _SessionFake,
        events: list[tuple],
        *,
        confirm_discard: bool = False,
    ) -> None:
        self.session = session
        self.events = events
        self.today = _TodayFake()
        self.pages = {"today": self.today}
        self.confirm_discard = confirm_discard
        self.resume_banner = _BannerFake()
        self._last_nav_context = ("A1", "old", 1)

    def _plan_segment_error(self, message: str) -> None:
        self.today.show_plan_error(message)

    # Keep the harness focused on the observable confirmation behavior while
    # allowing a descriptive private helper name in MainWindow.
    _daily_plan_error = _plan_segment_error
    _planner_error = _plan_segment_error

    def _confirm_discard_for_plan_segment(self) -> bool:
        self.events.append(("confirm_if_needed",))
        return self.confirm_discard

    _confirm_discard_for_daily_plan = _confirm_discard_for_plan_segment
    _confirm_discard_for_planned_set = _confirm_discard_for_plan_segment

    def _invalidate_review_pages(self) -> None:
        self.events.append(("invalidate_review_pages",))

    def _show(self, destination: str) -> None:
        self.events.append(("show_objective_page", destination))

    def _open_context_practice(self, *args) -> None:
        self.events.append(("legacy_open_context_practice", *args))

    def _sync_resume_banner(self) -> None:
        self.events.append(("legacy_sync_resume_banner",))


def _segment(objective: str = "vocab"):
    from core.planner import PlanSegment

    return PlanSegment(
        objective=objective,
        deck_id=41,
        level="A2",
        book_slug="menschen",
        lektion_number=7,
        item_ids=(101, 102),
        due_count=1,
        new_count=1,
        ordinal=2,
        total_segments=5,
    )


@pytest.mark.parametrize(
    ("objective", "destination"),
    [
        ("vocab", "vocab_review"),
        ("grammar", "grammar_review"),
        ("sentences", "sentence_review"),
        ("listening", "listening_review"),
    ],
)
def test_planned_set_routes_each_objective_after_atomic_final_preflight(
    objective,
    destination,
):
    from ui.main_window import MainWindow

    requested = _segment(objective)
    previewed = replace(
        requested,
        item_ids=(102,),
        due_count=0,
        new_count=1,
        ordinal=1,
    )
    events: list[tuple] = []
    session = _SessionFake(events, preview_result=previewed, unfinished=True)
    window = _WindowHarness(session, events, confirm_discard=True)

    MainWindow._open_plan_segment(window, requested)

    assert events == [
        ("preview_planned_segment", requested),
        ("has_unfinished_session",),
        ("confirm_if_needed",),
        ("start_planned_segment_for_context", previewed, True),
        ("invalidate_review_pages",),
        ("show_objective_page", destination),
    ]
    assert window.today.messages == []
    assert window.resume_banner.hidden == 1
    assert window._last_nav_context is None


def test_stale_plan_preview_stops_before_unfinished_guard_or_mutation():
    from ui.main_window import MainWindow

    requested = _segment()
    events: list[tuple] = []
    session = _SessionFake(events, preview_result=None, unfinished=True)
    window = _WindowHarness(session, events, confirm_discard=True)

    MainWindow._open_plan_segment(window, requested)

    assert events == [("preview_planned_segment", requested)]
    assert window.today.messages
    assert window.resume_banner.hidden == 0


def test_cancelled_unfinished_plan_stops_before_discard_or_context_mutation():
    from ui.main_window import MainWindow

    requested = _segment("grammar")
    events: list[tuple] = []
    session = _SessionFake(events, unfinished=True)
    window = _WindowHarness(session, events, confirm_discard=False)

    MainWindow._open_plan_segment(window, requested)

    assert events == [
        ("preview_planned_segment", requested),
        ("has_unfinished_session",),
        ("confirm_if_needed",),
    ]
    assert window.today.messages == []
    assert window.resume_banner.hidden == 0


def test_ready_plan_skips_confirmation_and_starts_directly():
    from ui.main_window import MainWindow

    requested = _segment("sentences")
    events: list[tuple] = []
    session = _SessionFake(events)
    window = _WindowHarness(session, events, confirm_discard=False)

    MainWindow._open_plan_segment(window, requested)

    assert events == [
        ("preview_planned_segment", requested),
        ("has_unfinished_session",),
        ("start_planned_segment_for_context", requested, False),
        ("invalidate_review_pages",),
        ("show_objective_page", "sentence_review"),
    ]
    assert window.today.messages == []


def test_failed_second_start_reports_error_without_opening_a_normal_queue():
    from ui.main_window import MainWindow

    requested = _segment("listening")
    events: list[tuple] = []
    session = _SessionFake(events, start_result=False)
    window = _WindowHarness(session, events)

    MainWindow._open_plan_segment(window, requested)

    assert events == [
        ("preview_planned_segment", requested),
        ("has_unfinished_session",),
        ("start_planned_segment_for_context", requested, False),
    ]
    assert window.today.messages
    assert window.resume_banner.hidden == 0
