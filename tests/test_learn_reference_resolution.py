from pathlib import Path
from types import SimpleNamespace


def _lesson(
    level: str,
    token: str,
    objective: str = 'nouns',
    lesson: str = 'articles',
) -> object:
    from ui.pages.learn import LessonRef

    major, minor = (int(part) for part in token.split('.', 1))
    return LessonRef(
        level=level,
        objective_key=objective,
        lesson_key=lesson,
        path=Path('unused.md'),
        obj_no=major,
        lesson_no=minor,
        order_token=token,
    )


def test_resolve_reference_normalizes_input_and_requires_exact_token():
    from ui.pages.learn import CurriculumIndex

    a1 = _lesson('A1', '1.1')
    a2 = _lesson('A2', '1.1')
    index = CurriculumIndex()
    index._by_level = {
        'A1': {'nouns': [a1]},
        'A2': {'nouns': [a2]},
    }

    assert index.resolve_reference('  a1  ', ' 1.1 ') is a1
    assert index.resolve_reference('A2', '1.1') is a2
    assert index.resolve_reference('A1', '01.1') is None
    assert index.resolve_reference('A1', '') is None
    assert index.resolve_reference('not-a-level', '1.1') is None


def test_resolve_reference_fails_closed_for_missing_or_duplicate_matches():
    from ui.pages.learn import CurriculumIndex

    first = _lesson('A1', '4.1', 'syntax', 'word_order')
    duplicate = _lesson('A1', '4.1', 'sentences', 'main_clause')
    index = CurriculumIndex()
    index._by_level = {
        'A1': {
            'syntax': [first],
            'sentences': [duplicate],
        }
    }

    assert index.resolve_reference('A1', '9.9') is None
    assert index.resolve_reference('A1', '4.1') is None


class _IndexStub:
    def __init__(self, result):
        self.result = result
        self.reload_calls = 0
        self.resolve_calls = []

    def reload(self):
        self.reload_calls += 1

    def resolve_reference(self, level, order_token):
        self.resolve_calls.append((level, order_token))
        return self.result


def test_open_reference_reloads_and_does_not_mutate_page_on_failure():
    from ui.pages.learn import LearnPage

    previous = _lesson('B1', '2.1', 'verbs', 'past')
    index = _IndexStub(None)
    opened = []
    page = SimpleNamespace(
        index=index,
        level='B1',
        current_objective='verbs',
        current_lesson=previous,
        _open_lesson=opened.append,
    )

    assert LearnPage.open_reference(page, 'A1', '1.1') is False
    assert index.reload_calls == 1
    assert index.resolve_calls == [('A1', '1.1')]
    assert page.level == 'B1'
    assert page.current_objective == 'verbs'
    assert page.current_lesson is previous
    assert opened == []


def test_open_reference_sets_resolved_level_and_opens_unique_lesson():
    from ui.pages.learn import LearnPage

    resolved = _lesson('A1', '1.1')
    index = _IndexStub(resolved)
    opened = []
    page = SimpleNamespace(index=index, level='B2', _open_lesson=opened.append)

    assert LearnPage.open_reference(page, ' a1 ', '1.1') is True
    assert index.reload_calls == 1
    assert index.resolve_calls == [(' a1 ', '1.1')]
    assert page.level == 'A1'
    assert opened == [resolved]
