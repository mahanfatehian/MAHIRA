"""Navigation availability is cached within one level/book/Lektion context."""

from types import SimpleNamespace


def test_objective_availability_is_not_requeried_on_page_hops():
    from ui.main_window import MainWindow

    class Repo:
        def __init__(self):
            self.calls = []

        def get_deck_id(self, level, objective, *, lektion_id):
            self.calls.append((level, objective, lektion_id))
            return 1 if objective in {"vocab", "grammar"} else None

    class Nav:
        def __init__(self):
            self.states = []

        def set_objective_states(self, enabled):
            self.states.append(set(enabled))

    repo = Repo()
    nav = Nav()
    state = SimpleNamespace(level="A1", book_slug="starten_wir", lektion_number=7)
    window = SimpleNamespace(
        session=SimpleNamespace(state=state, repo=repo),
        nav=nav,
        _last_nav_context=None,
        _current_lektion_id=lambda: 77,
    )

    MainWindow._sync_nav(window)
    assert len(repo.calls) == 4
    assert nav.states == [{"vocab", "grammar"}]

    # Table -> conjugation -> table stays in the same context, so all later
    # `_show()` calls reuse the availability result.
    MainWindow._sync_nav(window)
    MainWindow._sync_nav(window)
    assert len(repo.calls) == 4
    assert len(nav.states) == 1

    state.lektion_number = 8
    MainWindow._sync_nav(window)
    assert len(repo.calls) == 8
    assert len(nav.states) == 2
