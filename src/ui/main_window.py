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
from PySide6.QtGui import QIcon, QShortcut, QKeySequence
from PySide6.QtWidgets import QApplication
from ui.pages.setup import SetupPage
from ui.pages.vocab_review import VocabReviewPage
from ui.pages.grammar_review import GrammarReviewPage
from ui.pages.sentence_review import SentenceReviewPage
from ui.pages.listening_review import ListeningReviewPage
from ui.pages.progress import ProgressPage
from ui.pages.learn import LearnPage
from ui.pages.vocab_table import VocabTablePage
from ui.pages.conjugation import ConjugationPage

PAGE_KEYS = [
    "setup",
    "vocab_review",
    "grammar_review",
    "sentence_review",
    "listening_review",
    "progress",
    "learn",
    "vocab_table",
    "conjugation",
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
            "vocab_table": make(VocabTablePage),
            "conjugation": make(ConjugationPage),
        }

        for key in PAGE_KEYS:
            self.stack.addWidget(self.pages[key])

        layout.addWidget(self.nav)
        layout.addWidget(self.page_scroll, 1)

        self.setCentralWidget(root)
        self.setFixedSize(1000, 900)

        self.nav.go.connect(self.go)

        # Focus / Zen mode: F11 toggles a distraction-free view (hides the side
        # nav and, where supported, the page's own chrome); Esc leaves it.
        self._focus_mode = False
        self._sc_f11 = QShortcut(QKeySequence("F11"), self)
        self._sc_f11.activated.connect(self.toggle_focus_mode)
        self._sc_esc = QShortcut(QKeySequence("Escape"), self)
        self._sc_esc.activated.connect(self._exit_focus_mode)

        # Keyboard help: ? or F1 opens a one-glance shortcut sheet.
        self._help_dialog = None
        self._sc_help = QShortcut(QKeySequence("?"), self)
        self._sc_help.activated.connect(self._on_help_key)
        self._sc_f1 = QShortcut(QKeySequence("F1"), self)
        self._sc_f1.activated.connect(self._show_shortcuts_help)

        if hasattr(self.pages["setup"], "start_practice"):
            self.pages["setup"].start_practice.connect(self._go_from_objective)

        # Keep the nav's objective tabs in sync as the user picks a Lektion in Setup.
        if hasattr(self.pages["setup"], "context_changed"):
            self.pages["setup"].context_changed.connect(self._sync_nav)

        # "Table" on the Vocabulary card opens the read-only study grid; its own
        # Back button returns to the objective-selection screen.
        if hasattr(self.pages["setup"], "open_vocab_table"):
            self.pages["setup"].open_vocab_table.connect(lambda: self.go("vocab_table"))
        if hasattr(self.pages["vocab_table"], "go_back"):
            self.pages["vocab_table"].go_back.connect(lambda: self.go("setup"))

        # Tapping a verb's tag in the Vocab Table opens its full conjugation;
        # the conjugation tab's Back button returns to the table.
        if hasattr(self.pages["vocab_table"], "conjugate_verb"):
            self.pages["vocab_table"].conjugate_verb.connect(self._open_conjugation)
        if hasattr(self.pages["conjugation"], "go_back"):
            self.pages["conjugation"].go_back.connect(lambda: self.go("vocab_table"))

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

    def set_focus_mode(self, on: bool) -> None:
        self._focus_mode = bool(on)
        self.nav.setVisible(not self._focus_mode)
        cur = self.stack.currentWidget()
        if hasattr(cur, "set_focus_mode"):
            try:
                cur.set_focus_mode(self._focus_mode)
            except Exception:
                pass

    def toggle_focus_mode(self) -> None:
        self.set_focus_mode(not getattr(self, "_focus_mode", False))

    def _exit_focus_mode(self) -> None:
        if getattr(self, "_focus_mode", False):
            self.set_focus_mode(False)

    # ----------------------------------------------------------------- help
    def _on_help_key(self) -> None:
        # If the learner is typing, "?" is a literal character, not a help key.
        from PySide6.QtWidgets import QLineEdit

        app = QApplication.instance()
        fw = app.focusWidget() if app is not None else None
        if isinstance(fw, QLineEdit) and fw.isEnabled() and not fw.isReadOnly():
            fw.insert("?")
            return
        self._show_shortcuts_help()

    def _show_shortcuts_help(self) -> None:
        dlg = self._help_dialog
        if dlg is None:
            dlg = self._build_shortcuts_dialog()
            self._help_dialog = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _build_shortcuts_dialog(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel

        rows = [
            ("1 / 2 / 3 / 4", "Rate Again / Hard / Good / Easy (after checking)"),
            ("Enter", "Check your answer · then move to the next card"),
            ("Ctrl + Z", "Undo the last answer and redo that card"),
            ("F11", "Focus mode — hide the chrome and just study"),
            ("Esc", "Leave Focus mode"),
            ("? / F1", "Show this shortcut sheet"),
        ]

        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard shortcuts")
        dlg.setMinimumWidth(420)
        dlg.setStyleSheet("QDialog { background-color: #141414; }")

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(10)

        title = QLabel("Keyboard shortcuts")
        title.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:18px; font-weight:950; border:none; background:transparent; }"
        )
        lay.addWidget(title)

        for keys, desc in rows:
            row = QLabel(
                f"<span style='color:#7AE582; font-weight:900;'>{keys}</span>"
                f"&nbsp;&nbsp;<span style='color:#C8C8C8;'>{desc}</span>"
            )
            row.setStyleSheet("QLabel { font-size:13px; border:none; background:transparent; }")
            lay.addWidget(row)

        return dlg

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

    def _open_conjugation(self, word: str, meaning: str = "") -> None:
        page = self.pages.get("conjugation")
        if page is not None and hasattr(page, "set_verb"):
            try:
                page.set_verb(word, meaning)
            except Exception:
                pass
        self.go("conjugation")

    def _nav_key_for_page(self, page_key: str) -> str:
        return {
            "vocab_review": "vocab",
            "grammar_review": "grammar",
            "sentence_review": "sentences",
            "listening_review": "listening",
            "setup": "setup",
            "learn": "learn",
            "progress": "progress",
            "vocab_table": "setup",
            "conjugation": "setup",
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

        # Keep every page's chrome in sync with the current focus state — both
        # ways, so a page shown after Focus mode is turned off gets its bar back.
        if hasattr(w, "set_focus_mode"):
            try:
                w.set_focus_mode(getattr(self, "_focus_mode", False))
            except Exception:
                pass

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

        if page_key == "vocab_table":
            # Read-only study grid: needs a vocab deck for the current Lektion;
            # otherwise fall back to Setup. It doesn't touch the objective.
            try:
                has_vocab = self.session.vocab_deck_id() is not None
            except Exception:
                has_vocab = False
            if not getattr(self.session.state, "level", None) or not has_vocab:
                self._show("setup")
                return
            self._show("vocab_table")
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