from __future__ import annotations

import os


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class _SessionStub:
    def __init__(
        self,
        *,
        unfinished: bool = False,
        deck_id: int = 31,
        previewed=None,
    ) -> None:
        self.unfinished = unfinished
        self.deck_id = deck_id
        self.previewed = previewed
        self.calls: list[tuple] = []

    def has_unfinished_session(self) -> bool:
        self.calls.append(('unfinished',))
        return self.unfinished

    def discard_pending_resume(self) -> None:
        self.calls.append(('discard_pending_resume',))
        self.unfinished = False

    def preview_targeted_item_ids(
        self,
        level,
        objective,
        book_slug,
        lektion_number,
        deck_id,
        item_ids,
        *,
        limit=50,
    ):
        self.calls.append(
            (
                'preview_targeted_item_ids',
                level,
                objective,
                book_slug,
                lektion_number,
                deck_id,
                tuple(item_ids),
                limit,
            )
        )
        return list(item_ids) if self.previewed is None else list(self.previewed)

    def set_context(self, level, objective, book_slug, lektion_number) -> None:
        self.calls.append(
            ('set_context', level, objective, book_slug, lektion_number)
        )

    def active_deck_id(self):
        self.calls.append(('active_deck_id',))
        return self.deck_id

    def targeted_item_ids(self, objective, item_ids, *, limit=50):
        self.calls.append(('targeted_item_ids', objective, tuple(item_ids), limit))
        return list(item_ids)

    def start_targeted_session(self, objective, item_ids, *, limit=50):
        self.calls.append(
            ('start_targeted_session', objective, tuple(item_ids), limit)
        )
        return bool(item_ids)


class _ErrorSink:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def show_drill_error(self, message: str) -> None:
        self.messages.append(message)


class _LabStub:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start_targeted_drill(self, item_ids, practice_mode) -> bool:
        self.calls.append((tuple(item_ids), practice_mode))
        return True


class _BannerStub:
    def __init__(self) -> None:
        self.hidden = 0

    def hide(self) -> None:
        self.hidden += 1


class _WindowHarness:
    _OBJ_TO_PAGE = {
        'vocab': 'vocab_review',
        'grammar': 'grammar_review',
        'sentences': 'sentence_review',
        'listening': 'listening_review',
    }

    def __init__(self, session, *, confirm_discard: bool = False) -> None:
        self.session = session
        self.errors = _ErrorSink()
        self.lab = _LabStub()
        self.pages = {'mistakes': self.errors, 'lab': self.lab}
        self.resume_banner = _BannerStub()
        self._last_nav_context = ('A1', 'old', 1)
        self.invalidations = 0
        self.shown: list[str] = []
        self.confirm_discard = confirm_discard
        self.confirmations = 0

    def _mistake_drill_error(self, message: str) -> None:
        self.errors.show_drill_error(message)

    def _invalidate_review_pages(self) -> None:
        self.invalidations += 1

    def _confirm_discard_for_mistake_drill(self) -> bool:
        self.confirmations += 1
        return self.confirm_discard

    def _show(self, destination: str) -> None:
        self.shown.append(destination)


def _request(*, mode='recognition', book_slug='starten_wir', lesson=2):
    from ui.pages.mistakes import MistakeDrillRequest

    return MistakeDrillRequest(
        objective='vocab',
        practice_mode=mode,
        deck_id=31,
        level='A1',
        book_slug=book_slug,
        lektion_number=lesson,
        item_ids=(11, 12),
    )


def test_cancel_unfinished_review_confirmation_mutates_nothing():
    from ui.main_window import MainWindow

    session = _SessionStub(unfinished=True)
    window = _WindowHarness(session)

    MainWindow._open_mistake_drill(window, _request())

    assert session.calls == [
        (
            'preview_targeted_item_ids',
            'A1',
            'vocab',
            'starten_wir',
            2,
            31,
            (11, 12),
            50,
        ),
        ('unfinished',),
    ]
    assert window.confirmations == 1
    assert window.errors.messages == []
    assert window.invalidations == 0
    assert window.shown == []


def test_stale_request_fails_before_dialog_or_review_mutation():
    from ui.main_window import MainWindow

    session = _SessionStub(unfinished=True, previewed=[])
    window = _WindowHarness(session, confirm_discard=True)

    MainWindow._open_mistake_drill(window, _request())

    assert session.calls == [
        (
            'preview_targeted_item_ids',
            'A1',
            'vocab',
            'starten_wir',
            2,
            31,
            (11, 12),
            50,
        )
    ]
    assert window.confirmations == 0
    assert not any(call[0] == 'discard_pending_resume' for call in session.calls)
    assert window.invalidations == 0
    assert window.shown == []
    assert 'Refresh Mistakes' in window.errors.messages[0]


def test_confirm_unfinished_review_discards_before_context_change():
    from ui.main_window import MainWindow

    session = _SessionStub(unfinished=True)
    window = _WindowHarness(session, confirm_discard=True)

    MainWindow._open_mistake_drill(window, _request())

    assert session.calls[:4] == [
        (
            'preview_targeted_item_ids',
            'A1',
            'vocab',
            'starten_wir',
            2,
            31,
            (11, 12),
            50,
        ),
        ('unfinished',),
        ('discard_pending_resume',),
        ('set_context', 'A1', 'vocab', 'starten_wir', 2),
    ]
    assert window.confirmations == 1
    assert window.shown == ['vocab_review']


def test_primary_targeted_route_revalidates_then_starts_exact_queue():
    from ui.main_window import MainWindow

    session = _SessionStub()
    window = _WindowHarness(session)

    MainWindow._open_mistake_drill(window, _request())

    assert session.calls == [
        (
            'preview_targeted_item_ids',
            'A1',
            'vocab',
            'starten_wir',
            2,
            31,
            (11, 12),
            50,
        ),
        ('unfinished',),
        ('set_context', 'A1', 'vocab', 'starten_wir', 2),
        ('active_deck_id',),
        ('targeted_item_ids', 'vocab', (11, 12), 50),
        ('start_targeted_session', 'vocab', (11, 12), 50),
    ]
    assert window.invalidations == 1
    assert window.resume_banner.hidden == 1
    assert window._last_nav_context is None
    assert window.shown == ['vocab_review']


def test_lab_targeted_route_stages_revalidated_ids_without_primary_queue():
    from ui.main_window import MainWindow

    session = _SessionStub()
    window = _WindowHarness(session)

    MainWindow._open_mistake_drill(window, _request(mode='dictation'))

    assert ('targeted_item_ids', 'vocab', (11, 12), 50) in session.calls
    assert not any(call[0] == 'start_targeted_session' for call in session.calls)
    assert window.lab.calls == [((11, 12), 'dictation')]
    assert window.invalidations == 1
    assert window.shown == ['lab']


def test_level_only_legacy_deck_uses_the_same_validated_target_route():
    from ui.main_window import MainWindow

    session = _SessionStub()
    window = _WindowHarness(session)

    MainWindow._open_mistake_drill(
        window,
        _request(book_slug='', lesson=0),
    )

    assert ('set_context', 'A1', 'vocab', '', 0) in session.calls
    assert ('start_targeted_session', 'vocab', (11, 12), 50) in session.calls
    assert window.shown == ['vocab_review']


def test_learn_reference_route_only_navigates_after_public_resolver_succeeds():
    from ui.main_window import MainWindow

    class LearnStub:
        def __init__(self) -> None:
            self.calls = []

        def open_reference(self, level, order_token):
            self.calls.append((level, order_token))
            return order_token == '1.4'

    window = _WindowHarness(_SessionStub())
    learn = LearnStub()
    window.pages['learn'] = learn

    MainWindow._open_learn_reference(window, 'A1', '1.4')
    MainWindow._open_learn_reference(window, 'A1', 'missing')

    assert learn.calls == [('A1', '1.4'), ('A1', 'missing')]
    assert window.shown == ['learn']
    assert window.errors.messages == ['That learning reference is not available.']
