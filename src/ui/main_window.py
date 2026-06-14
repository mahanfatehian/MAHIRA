from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QStackedWidget,
    QSizePolicy,
    QScrollArea,
)
from core.session import SessionService
from ui.navigation import NavBar
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from ui.pages.setup import SetupPage
from ui.pages.vocab_review import VocabReviewPage
from ui.pages.grammar_review import GrammarReviewPage
from ui.pages.sentence_review import SentenceReviewPage
from ui.pages.listening_review import ListeningReviewPage
from ui.pages.progress import ProgressPage
from ui.pages.learn import LearnPage

PAGE_KEYS = [
    "setup",
    "vocab_review",
    "grammar_review",
    "sentence_review",
    "listening_review",
    "progress",
    "learn",
]


class MainWindow(QMainWindow):
    def __init__(self, session: SessionService, start_page: str | None = None):
        super().__init__()
        self.session = session

        try:
            from mahira.config import resource_root
            candidates = [
                resource_root() / "assets" / "logo.ico",
                resource_root() / "assets" / "logo.png",
            ]
            for p in candidates:
                if p.exists():
                    icon = QIcon(str(p))
                    self.setWindowIcon(icon)
                    app = QApplication.instance()
                    if app is not None:
                        app.setWindowIcon(icon)
                    break
        except Exception:
            pass

        self.setWindowTitle("Mahira")

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.nav = NavBar()

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.page_scroll.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.page_scroll.setWidget(self.stack)

        def make(PageCls):
            try:
                return PageCls(session, self.nav)
            except TypeError:
                return PageCls(session)

        self.pages = {
            "setup": make(SetupPage),
            "vocab_review": make(VocabReviewPage),
            "grammar_review": make(GrammarReviewPage),
            "sentence_review": make(SentenceReviewPage),
            "listening_review": make(ListeningReviewPage),
            "progress": make(ProgressPage),
            "learn": make(LearnPage),
        }

        for key in PAGE_KEYS:
            self.stack.addWidget(self.pages[key])

        layout.addWidget(self.nav)
        layout.addWidget(self.page_scroll, 1)

        self.setCentralWidget(root)
        self.setFixedSize(1000, 900)

        self.nav.go.connect(self.go)

        if hasattr(self.pages["setup"], "start_practice"):
            self.pages["setup"].start_practice.connect(self._go_from_objective)

        # Keep the nav's objective tabs in sync as the user picks a Lektion in Setup.
        if hasattr(self.pages["setup"], "context_changed"):
            self.pages["setup"].context_changed.connect(self._sync_nav)

        if hasattr(self.pages["vocab_review"], "go_progress"):
            self.pages["vocab_review"].go_progress.connect(lambda: self.go("progress"))
        if hasattr(self.pages["grammar_review"], "go_progress"):
            self.pages["grammar_review"].go_progress.connect(lambda: self.go("progress"))
        if hasattr(self.pages["sentence_review"], "go_progress"):
            self.pages["sentence_review"].go_progress.connect(lambda: self.go("progress"))
        if hasattr(self.pages["listening_review"], "go_progress"):
            self.pages["listening_review"].go_progress.connect(lambda: self.go("progress"))

        if hasattr(self.pages["progress"], "go_learn"):
            self.pages["progress"].go_learn.connect(lambda: self.go("practice"))

        alias = {
            "practice_select": "setup",
            "level_select": "setup",
            "objective_select": "setup",
        }
        start = alias.get((start_page or ""), start_page)
        if start not in self.pages:
            start = "setup"
        self.go(start)

    def _practice_page_key(self) -> str:
        obj = (getattr(self.session.state, "objective", "") or "").lower().strip()
        if obj == "grammar":
            return "grammar_review"
        if obj == "sentences":
            return "sentence_review"
        if obj == "listening":
            return "listening_review"
        return "vocab_review"

    def _go_from_objective(self) -> None:
        self._show(self._practice_page_key())

    def _nav_key_for_page(self, page_key: str) -> str:
        return {
            "vocab_review": "vocab",
            "grammar_review": "grammar",
            "sentence_review": "sentences",
            "listening_review": "listening",
            "setup": "setup",
            "learn": "learn",
            "progress": "progress",
        }.get(page_key, "setup")

    def _current_lektion_id(self) -> int | None:
        st = self.session.state
        book = (getattr(st, "book_slug", "") or "").strip()
        level = (getattr(st, "level", "") or "").strip()
        n = int(getattr(st, "lektion_number", 0) or 0)
        if not book or not n:
            return None
        try:
            book_id = self.session.repo.get_book_id(book)
            if book_id is None:
                return None
            return self.session.repo.get_lektion_id(book_id, level, n)
        except Exception:
            return None

    def _sync_nav(self) -> None:
        """Enable the objective tabs that have a deck for the current Lektion;
        disable them all while the user is still choosing a Lektion in Setup."""
        enabled: set[str] = set()
        st = self.session.state
        level = (getattr(st, "level", "") or "").strip()
        book = (getattr(st, "book_slug", "") or "").strip()
        lek_n = int(getattr(st, "lektion_number", 0) or 0)
        if level and book and lek_n:
            lek_id = self._current_lektion_id()
            if lek_id is not None:
                for obj in ("vocab", "grammar", "sentences", "listening"):
                    try:
                        if self.session.repo.get_deck_id(level, obj, lektion_id=lek_id) is not None:
                            enabled.add(obj)
                    except Exception:
                        pass
        self.nav.set_objective_states(enabled)

    def _show(self, page_key: str) -> None:
        w = self.pages[page_key]
        self.stack.setCurrentWidget(w)
        self.page_scroll.verticalScrollBar().setValue(0)

        if hasattr(w, "on_show"):
            try:
                w.on_show()
            except Exception as e:
                print(f"[NAV] on_show error in {page_key}: {e}")

        self._sync_nav()
        self.nav.set_active(self._nav_key_for_page(page_key))

    def _current_page_key(self) -> str | None:
        cur = self.stack.currentWidget()
        for k, w in self.pages.items():
            if w is cur:
                return k
        return None

    # nav key -> review page for the four practice objectives.
    _OBJ_TO_PAGE = {
        "vocab": "vocab_review",
        "grammar": "grammar_review",
        "sentences": "sentence_review",
        "listening": "listening_review",
    }

    def go(self, page_key: str) -> None:
        # An objective tab IS its objective: set it, then show its review page.
        # Requires a chosen Lektion; otherwise fall back to Setup. (The nav also
        # disables these tabs until a Lektion exists, so this is a safety net.)
        if page_key in self._OBJ_TO_PAGE:
            if not getattr(self.session.state, "level", None) or not self._current_lektion_id():
                self._show("setup")
                return
            try:
                self.session.state.objective = page_key
            except Exception:
                pass
            self._show(self._OBJ_TO_PAGE[page_key])
            return

        if page_key == "practice":
            # Logical route (e.g. Progress' "Back to Practice"): the current objective.
            page_key = self._practice_page_key()
        elif page_key in ("practice_select", "level_select", "objective_select"):
            page_key = "setup"

        if page_key not in self.pages:
            print(f"[NAV] Unknown page key: {page_key}")
            return

        # Review pages reached via routing still need a full context.
        if page_key in ("vocab_review", "grammar_review", "sentence_review", "listening_review"):
            if not getattr(self.session.state, "level", None) or not getattr(self.session.state, "objective", None):
                self._show("setup")
                return
            self._show(self._practice_page_key())
            return

        self._show(page_key)