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
from ui.pages.progress import ProgressPage
from ui.pages.learn import LearnPage

PAGE_KEYS = [
    "setup",
    "vocab_review",
    "grammar_review",
    "sentence_review",
    "progress",
    "learn",
]


class MainWindow(QMainWindow):
    def __init__(self, session: SessionService, start_page: str | None = None):
        super().__init__()
        self.session = session

        try:
            project_root = self.session.repo.db_path.parent.parent
            candidates = [
                project_root / "assets" / "logo.ico",
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

        if hasattr(self.pages["vocab_review"], "go_progress"):
            self.pages["vocab_review"].go_progress.connect(lambda: self.go("progress"))
        if hasattr(self.pages["grammar_review"], "go_progress"):
            self.pages["grammar_review"].go_progress.connect(lambda: self.go("progress"))
        if hasattr(self.pages["sentence_review"], "go_progress"):
            self.pages["sentence_review"].go_progress.connect(lambda: self.go("progress"))

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
        return "vocab_review"

    def _go_from_objective(self) -> None:
        self._show(self._practice_page_key())

    def _nav_key_for_page(self, page_key: str) -> str:
        if page_key in ("vocab_review", "grammar_review", "sentence_review"):
            return "practice"
        if page_key == "setup":
            return "setup"
        if page_key == "learn":
            return "learn"
        if page_key == "progress":
            return "progress"
        return "setup"

    def _show(self, page_key: str) -> None:
        w = self.pages[page_key]
        self.stack.setCurrentWidget(w)
        self.nav.set_active(self._nav_key_for_page(page_key))
        self.page_scroll.verticalScrollBar().setValue(0)

        if hasattr(w, "on_show"):
            try:
                w.on_show()
            except Exception as e:
                print(f"[NAV] on_show error in {page_key}: {e}")

    def _current_page_key(self) -> str | None:
        cur = self.stack.currentWidget()
        for k, w in self.pages.items():
            if w is cur:
                return k
        return None

    def go(self, page_key: str) -> None:
        if page_key == "practice":
            page_key = self._practice_page_key()
        elif page_key == "setup":
            page_key = "setup"
        elif page_key == "learn":
            page_key = "learn"
        elif page_key == "progress":
            page_key = "progress"

        if page_key in ("practice_select", "level_select", "objective_select"):
            page_key = "setup"

        if page_key not in self.pages:
            print(f"[NAV] Unknown page key: {page_key}")
            return

        if self._current_page_key() == page_key:
            self._show(page_key)
            return

        if page_key in ("vocab_review", "grammar_review", "sentence_review"):
            if not getattr(self.session.state, "level", None):
                self._show("setup")
                return
            if not getattr(self.session.state, "objective", None):
                self._show("setup")
                return
            self._show(self._practice_page_key())
            return

        self._show(page_key)