from __future__ import annotations

import logging
import time

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QStackedWidget,
    QSizePolicy,
    QScrollArea,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
)
from core.session import SessionService
from ui.navigation import NavBar
from PySide6.QtGui import QIcon, QShortcut, QKeySequence
from PySide6.QtWidgets import QApplication
from core.planner import PlanSegment
from ui.pages.setup import SetupPage
from ui.pages.vocab_review import VocabReviewPage
from ui.pages.grammar_review import GrammarReviewPage
from ui.pages.sentence_review import SentenceReviewPage
from ui.pages.listening_review import ListeningReviewPage
from ui.pages.progress import ProgressPage
from ui.pages.learn import LearnPage
from ui.pages.vocab_table import VocabTablePage
from ui.pages.conjugation import ConjugationPage
from ui.pages.today import TodayPage
from ui.pages.mistakes import MistakeDrillRequest, MistakesPage
from ui.pages.settings import SettingsPage
from ui.pages.practice_lab import PracticeLabPage
from ui.theme import apply_application_theme, apply_typography_scale

PAGE_KEYS = [
    "today",
    "setup",
    "vocab_review",
    "grammar_review",
    "sentence_review",
    "listening_review",
    "progress",
    "learn",
    "vocab_table",
    "conjugation",
    "mistakes",
    "settings",
    "lab",
]


class CurrentPageStack(QStackedWidget):
    """Advertise only the visible page's height to the outer scroll area.

    Settings is intentionally taller than a review page. A stock stacked
    widget reports the largest hidden child's size, which would put a needless
    scrollbar and empty tail on every legacy tab. Horizontal policy remains
    Expanding, so this does not reintroduce the earlier clipping regression.

    Overriding the two size hints is not enough on its own. QScrollArea sizes
    a resizable widget from heightForWidth() whenever the widget's layout
    advertises it, in preference to either hint, and QStackedLayout answers
    with the tallest page rather than the visible one. Settings needs 1656 px
    at a 1080x820 window, so every other page was stretched to 1656 px inside
    a 744 px viewport and earned a 910 px outer scrollbar it had no content
    for - a second scrollbar over the top of the page's own, which dragged the
    header out of view and lost the reader's place. Vocab Table asks for
    416 px. Delegating the height query to the current page too gives every
    page an outer scrollbar if and only if it really is taller than the
    viewport, which measures as Settings and Progress alone.
    """

    def sizeHint(self) -> QSize:
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        current = self.currentWidget()
        if current is None:
            return super().minimumSizeHint()
        return QSize(0, current.minimumSizeHint().height())

    def heightForWidth(self, width: int) -> int:
        current = self.currentWidget()
        if current is None:
            return super().heightForWidth(width)
        return current.heightForWidth(width)

    def hasHeightForWidth(self) -> bool:
        # Not what fixes the scrollbar: QScrollArea puts this question to the
        # layout rather than to us, and a stacked layout answers for every page
        # at once, so removing this changes no measured geometry today. It is
        # here to keep the pair consistent - a widget that answers the height
        # query for one page should say whether that page has one - for any
        # future parent that does ask the widget.
        current = self.currentWidget()
        if current is None:
            return super().hasHeightForWidth()
        return current.hasHeightForWidth()

    def setCurrentWidget(self, widget: QWidget) -> None:
        super().setCurrentWidget(widget)
        self.updateGeometry()


class MainWindow(QMainWindow):
    def __init__(self, session: SessionService, start_page: str | None = None):
        super().__init__()
        self.session = session
        self._shutdown_started = False
        self._close_pending = False
        self._shutdown_started_at = 0.0
        self._shutdown_delay_logged = False

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
        root.setObjectName("MainWindowRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.nav = NavBar()

        self.stack = CurrentPageStack()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("PageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.page_scroll.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.page_scroll.setWidget(self.stack)

        self.resume_banner = self._build_resume_banner()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        content_layout.addWidget(self.resume_banner)
        content_layout.addWidget(self.page_scroll, 1)

        def make(PageCls):
            return PageCls(session, self.nav)

        self.pages = {
            "today": make(TodayPage),
            "setup": make(SetupPage),
            "vocab_review": make(VocabReviewPage),
            "grammar_review": make(GrammarReviewPage),
            "sentence_review": make(SentenceReviewPage),
            "listening_review": make(ListeningReviewPage),
            "progress": make(ProgressPage),
            "learn": make(LearnPage),
            "vocab_table": make(VocabTablePage),
            "conjugation": make(ConjugationPage),
            "mistakes": make(MistakesPage),
            "settings": make(SettingsPage),
            "lab": make(PracticeLabPage),
        }

        for key in PAGE_KEYS:
            self.stack.addWidget(self.pages[key])

        layout.addWidget(self.nav)
        layout.addWidget(content, 1)

        self.setCentralWidget(root)
        self.setMinimumSize(860, 680)
        prefs = getattr(getattr(session, "settings", None), "value", None)
        self.resize(
            max(860, int(getattr(prefs, "window_width", 1080))),
            max(680, int(getattr(prefs, "window_height", 820))),
        )

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
            self.pages["setup"].context_changed.connect(self._on_context_changed)

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
        for key in (
            "vocab_review",
            "grammar_review",
            "sentence_review",
            "listening_review",
        ):
            go_today = getattr(self.pages[key], "go_today", None)
            if go_today is not None:
                go_today.connect(lambda: self.go("today"))

        if hasattr(self.pages["progress"], "go_learn"):
            self.pages["progress"].go_learn.connect(lambda: self.go("practice"))

        self.pages["today"].practice_requested.connect(self._open_context_practice)
        self.pages["today"].plan_segment_requested.connect(self._open_plan_segment)
        self.pages["today"].open_mistakes.connect(lambda: self.go("mistakes"))
        self.pages["mistakes"].drill_requested.connect(self._open_mistake_drill)
        self.pages["mistakes"].learn_requested.connect(self._open_learn_reference)
        self.pages["settings"].settings_changed.connect(self._apply_settings)
        # app.py already applied the theme before this window was built.
        self._applied_appearance = self._appearance_signature()

        # Objective availability depends only on level/book/Lektion.  Page
        # navigation inside that context (especially Table <-> Conjugation)
        # must not reopen SQLite six times on every hop.
        self._last_nav_context: tuple[str, str, int] | None = None

        has_resume = self._sync_resume_banner()

        alias = {
            "practice_select": "setup",
            "level_select": "setup",
            "objective_select": "setup",
        }
        start = alias.get((start_page or ""), start_page)
        if has_resume:
            # Review pages auto-create a queue in on_show(). Keep the saved
            # candidate untouched until the learner chooses Continue/Discard.
            start = "today"
        if start not in self.pages:
            start = "setup"
        self.go(start)

    def _build_resume_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("SessionResumeBanner")
        banner.setAccessibleName("Unfinished review session")
        banner.setStyleSheet(
            "QFrame#SessionResumeBanner { background:#102016; border:1px solid #2F7D4A; "
            "border-radius:12px; }"
        )
        row = QHBoxLayout(banner)
        row.setContentsMargins(16, 11, 12, 11)
        row.setSpacing(10)

        self.resume_label = QLabel()
        self.resume_label.setObjectName("SessionResumeLabel")
        self.resume_label.setWordWrap(True)
        self.resume_label.setStyleSheet(
            "QLabel { color:#EAF8EE; font-size:12px; font-weight:750; "
            "background:transparent; border:none; }"
        )
        row.addWidget(self.resume_label, 1)

        self.resume_discard_btn = QPushButton("Discard")
        self.resume_discard_btn.setObjectName("SessionResumeDiscardButton")
        self.resume_discard_btn.setAccessibleName("Discard unfinished session")
        self.resume_discard_btn.setStyleSheet(
            "QPushButton { color:#D5DDD7; background:#172019; border:1px solid #496052; "
            "border-radius:8px; padding:7px 12px; font-weight:800; }"
            "QPushButton:hover { background:#202A22; }"
        )
        self.resume_discard_btn.clicked.connect(self._discard_resume)
        row.addWidget(self.resume_discard_btn)

        self.resume_continue_btn = QPushButton("Continue")
        self.resume_continue_btn.setObjectName("SessionResumeContinueButton")
        self.resume_continue_btn.setAccessibleName("Continue unfinished session")
        self.resume_continue_btn.setStyleSheet(
            "QPushButton { color:#07120A; background:#7AE582; border:1px solid #7AE582; "
            "border-radius:8px; padding:7px 14px; font-weight:900; }"
            "QPushButton:hover { background:#91EE98; }"
        )
        self.resume_continue_btn.clicked.connect(self._continue_resume)
        row.addWidget(self.resume_continue_btn)
        banner.hide()
        return banner

    def _sync_resume_banner(self) -> bool:
        getter = getattr(self.session, "pending_resume", None)
        candidate = getter() if callable(getter) else None
        if candidate is None:
            self.resume_banner.hide()
            return False

        objective = {
            "vocab": "Vocabulary",
            "grammar": "Grammar",
            "sentences": "Sentence",
            "listening": "Listening",
        }.get(str(candidate.objective), str(candidate.objective).title())
        context = [str(candidate.level)]
        if candidate.book_slug:
            context.append(
                " ".join(
                    word.capitalize()
                    for word in candidate.book_slug.replace("-", "_").split("_")
                )
            )
        if candidate.lektion_number:
            context.append(f"Lektion {candidate.lektion_number}")
        next_position = min(candidate.total, candidate.position + 1)
        self.resume_label.setText(
            f"Unfinished {objective} session  ·  {' · '.join(context)}  ·  "
            f"card {next_position} of {candidate.total}"
        )
        self.resume_banner.show()
        return True

    def _invalidate_review_pages(self) -> None:
        for key in (
            "vocab_review",
            "grammar_review",
            "sentence_review",
            "listening_review",
        ):
            page = self.pages.get(key)
            if page is not None and hasattr(page, "current_item"):
                page.current_item = None

    def _continue_resume(self) -> None:
        resume = getattr(self.session, "resume_pending", None)
        if not callable(resume) or not resume():
            self._sync_resume_banner()
            return
        self._invalidate_review_pages()
        self.resume_banner.hide()
        self._last_nav_context = None
        self._show(self._practice_page_key())

    def _discard_resume(self) -> None:
        discard = getattr(self.session, "discard_pending_resume", None)
        if callable(discard):
            discard()
        self._invalidate_review_pages()
        self.resume_banner.hide()

    def _on_context_changed(self) -> None:
        discard = getattr(self.session, "discard_pending_resume", None)
        if callable(discard):
            discard()
        self._invalidate_review_pages()
        self.resume_banner.hide()
        self._last_nav_context = None
        self._sync_nav(force=True)

    def closeEvent(self, event) -> None:
        # A QThread.quit() call cannot interrupt Piper/ONNX while its worker
        # slot is inside a blocking synthesis call. Destroying the window after
        # an arbitrary two-second wait can therefore abort Qt. Invalidate every
        # page once, request orderly thread shutdown, and keep the event loop
        # alive until the workers actually finish.
        if not self._shutdown_started:
            self._shutdown_started = True
            self._begin_shutdown()

        running = self._running_worker_threads()
        if running:
            for thread in running:
                try:
                    thread.requestInterruption()
                    thread.quit()
                except RuntimeError:
                    pass
            event.ignore()
            if not self._close_pending:
                self._close_pending = True
                self._shutdown_started_at = time.monotonic()
                self.setEnabled(False)
                self.setWindowTitle("Mahira · Finishing background audio…")
                QTimer.singleShot(50, self._finish_deferred_close)
            return

        settings = getattr(self.session, "settings", None)
        if settings is not None:
            state = self.session.state
            try:
                settings.update(
                    level=state.level, objective=state.objective,
                    book_slug=state.book_slug, lektion_number=state.lektion_number,
                    last_page=self._current_page_key() or "today",
                    window_width=self.width(), window_height=self.height(),
                )
            except Exception:
                # Preference persistence must never keep the process alive after
                # all learning transactions have already completed safely.
                logging.exception("Could not persist window settings during shutdown")
        self._close_pending = False
        super().closeEvent(event)

    def _begin_shutdown(self) -> None:
        for page in self.pages.values():
            cleanup = getattr(page, "_cleanup_audio", None)
            if callable(cleanup):
                try:
                    cleanup(delete=True)
                except Exception:
                    pass
            clear = getattr(page, "_clear_current_audio_cache", None)
            if callable(clear):
                try:
                    clear()
                except Exception:
                    pass
            stop = getattr(page, "_stop_audio", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
            stop_background = getattr(page, "_stop_background", None)
            if callable(stop_background):
                try:
                    stop_background()
                except Exception:
                    pass
            for service_name in ("playback_service", "_playback", "_play_svc"):
                service = getattr(page, service_name, None)
                if service is not None:
                    try:
                        service.stop()
                    except Exception:
                        pass

    def _running_worker_threads(self) -> list:
        running = []
        seen: set[int] = set()
        for page in self.pages.values():
            for name in ("_audio_thread", "_update_thread"):
                thread = getattr(page, name, None)
                if thread is None or id(thread) in seen:
                    continue
                seen.add(id(thread))
                try:
                    if thread.isRunning():
                        running.append(thread)
                except RuntimeError:
                    continue
        return running

    def _finish_deferred_close(self) -> None:
        if self._running_worker_threads():
            elapsed = time.monotonic() - self._shutdown_started_at
            if elapsed >= 5.0:
                self.setWindowTitle("Mahira · Waiting for audio to finish safely…")
            if elapsed >= 15.0 and not self._shutdown_delay_logged:
                self._shutdown_delay_logged = True
                logging.warning(
                    "Shutdown is waiting for a blocking native worker; the window "
                    "will close as soon as that operation returns"
                )
            QTimer.singleShot(50, self._finish_deferred_close)
            return
        self._close_pending = False
        self.close()

    # Set during __init__ once the page wiring is in place; the class-level
    # default keeps _apply_settings safe if it ever fires earlier.
    _applied_appearance = None

    def _appearance_signature(self):
        settings = getattr(self.session, "settings", None)
        value = getattr(settings, "value", None)
        if value is None:
            return None
        return (int(getattr(value, "font_scale", 100)), str(getattr(value, "theme", "")))

    def _apply_settings(self) -> None:
        settings = getattr(self.session, "settings", None)
        app = QApplication.instance()
        if settings is None or app is None:
            return

        # Re-theming rebuilds the application stylesheet and walks every widget
        # to rescale typography - measured at 627 ms over 1375 widgets. Saving
        # a daily goal or a review preference does not change how anything
        # looks, so only do it when the appearance settings actually moved.
        appearance = self._appearance_signature()
        if appearance is not None and appearance == self._applied_appearance:
            return
        self._applied_appearance = appearance

        apply_application_theme(app, settings.value.font_scale, settings.value.theme)
        apply_typography_scale(self, settings.value.font_scale)

    def _plan_segment_error(self, message: str) -> None:
        page = self.pages.get("today")
        show_error = getattr(page, "show_plan_error", None)
        if callable(show_error):
            show_error(message)

    def _confirm_discard_for_plan_segment(self) -> bool:
        choice = QMessageBox.question(
            self,
            "Unfinished session",
            "Discard unfinished session and start today's set?\n\n"
            "Completed ratings stay saved.",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return choice == QMessageBox.StandardButton.Discard

    def _open_plan_segment(self, segment: PlanSegment) -> None:
        if not isinstance(segment, PlanSegment):
            self._plan_segment_error("This planned set is no longer valid.")
            return

        try:
            previewed = self.session.preview_planned_segment(segment)
        except Exception:
            logging.exception("Could not preflight the planned review set")
            previewed = None
        if previewed is None:
            self._plan_segment_error(
                "Today's plan changed. Refresh it before starting this set."
            )
            return

        try:
            has_unfinished = self.session.has_unfinished_session()
        except Exception:
            logging.exception("Could not inspect the current review session")
            self._plan_segment_error("The current session could not be checked safely.")
            return
        if has_unfinished:
            if not self._confirm_discard_for_plan_segment():
                return

        try:
            started = self.session.start_planned_segment_for_context(
                previewed,
                replace_unfinished=has_unfinished,
            )
        except Exception:
            logging.exception("Could not start the planned review set")
            started = False
        if not started:
            self._plan_segment_error(
                "Today's plan changed before it could start. Refresh and try again."
            )
            return

        self._invalidate_review_pages()
        self.resume_banner.hide()
        self._last_nav_context = None
        self._show(self._OBJ_TO_PAGE[previewed.objective])

    def _mistake_drill_error(self, message: str) -> None:
        page = self.pages.get('mistakes')
        show_error = getattr(page, 'show_drill_error', None)
        if callable(show_error):
            show_error(message)

    def _confirm_discard_for_mistake_drill(self) -> bool:
        choice = QMessageBox.question(
            self,
            'Unfinished session',
            'Discard unfinished session and start drill?\n\n'
            'Completed ratings stay saved.',
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return choice == QMessageBox.StandardButton.Discard

    def _open_mistake_drill(self, request: MistakeDrillRequest) -> None:
        if not isinstance(request, MistakeDrillRequest):
            self._mistake_drill_error('This mistake drill request is no longer valid.')
            return

        primary_modes = {
            'vocab': 'recognition',
            'grammar': 'production',
            'sentences': 'builder',
            'listening': 'comprehension',
        }
        is_lab = (
            request.objective == 'vocab'
            and request.practice_mode in {'production', 'dictation'}
        )
        if not is_lab and primary_modes.get(request.objective) != request.practice_mode:
            self._mistake_drill_error('This practice lane is not supported here.')
            return

        preview = getattr(self.session, 'preview_targeted_item_ids', None)
        try:
            previewed = (
                list(
                    preview(
                        request.level,
                        request.objective,
                        request.book_slug,
                        request.lektion_number,
                        request.deck_id,
                        request.item_ids,
                        limit=50,
                    )
                )
                if callable(preview)
                else []
            )
        except Exception:
            logging.exception("Could not preflight the requested mistake drill")
            previewed = []
        if not previewed:
            self._mistake_drill_error(
                'These cards were hidden, suspended, removed, or moved to another deck. '
                'Refresh Mistakes and try again.'
            )
            return

        has_unfinished = getattr(self.session, 'has_unfinished_session', None)
        if not callable(has_unfinished):
            has_unfinished = getattr(self.session, 'has_unfinished_review', None)
        if callable(has_unfinished) and has_unfinished():
            if not self._confirm_discard_for_mistake_drill():
                return
            discard = getattr(self.session, 'discard_pending_resume', None)
            if not callable(discard):
                self._mistake_drill_error('The unfinished session could not be discarded.')
                return
            try:
                discard()
            except Exception:
                logging.exception("Could not discard the unfinished session")
                self._mistake_drill_error('The unfinished session could not be discarded.')
                return

        try:
            self.session.set_context(
                request.level,
                request.objective,
                request.book_slug,
                request.lektion_number,
            )
            active_deck = self.session.active_deck_id()
        except Exception:
            logging.exception("Could not activate the requested mistake drill context")
            self._mistake_drill_error('That lesson is no longer available for practice.')
            return
        if active_deck is None or int(active_deck) != int(request.deck_id):
            self._mistake_drill_error('That mistake now belongs to a different deck.')
            return

        selected = self.session.targeted_item_ids(
            request.objective,
            previewed,
            limit=50,
        )
        if not selected:
            self._mistake_drill_error(
                'These cards were hidden, suspended, or removed. Refresh Mistakes and try again.'
            )
            return

        if is_lab:
            page = self.pages.get('lab')
            start_drill = getattr(page, 'start_targeted_drill', None)
            if not callable(start_drill) or not start_drill(
                selected,
                request.practice_mode,
            ):
                self._mistake_drill_error('These cards are no longer available in Practice Lab.')
                return
            destination = 'lab'
        else:
            if not self.session.start_targeted_session(
                request.objective,
                selected,
                limit=50,
            ):
                self._mistake_drill_error('No active cards remain in this mistake drill.')
                return
            destination = self._OBJ_TO_PAGE[request.objective]

        self._invalidate_review_pages()
        self.resume_banner.hide()
        self._last_nav_context = None
        self._show(destination)

    def _open_learn_reference(self, level: str, order_token: str) -> None:
        page = self.pages.get('learn')
        open_reference = getattr(page, 'open_reference', None)
        if callable(open_reference) and open_reference(level, order_token):
            self._show('learn')
            return
        self._mistake_drill_error('That learning reference is not available.')

    def _open_context_practice(self, objective: str, level: str, book: str, lesson: int) -> None:
        try:
            self.session.set_context(level, objective, book, lesson)
        except RuntimeError:
            self.go("setup")
            return
        self._last_nav_context = None
        self._sync_resume_banner()
        self._show(self._OBJ_TO_PAGE.get(objective, "vocab_review"))

    def _open_context_lab(
        self,
        level: str,
        book: str,
        lesson: int,
        practice_mode: str,
    ) -> None:
        try:
            self.session.set_context(level, "vocab", book, lesson)
        except RuntimeError:
            self.go("setup")
            return
        page = self.pages["lab"]
        select_mode = getattr(page, "select_mode", None)
        if callable(select_mode):
            select_mode(practice_mode, reload=False)
        self._last_nav_context = None
        self._sync_resume_banner()
        self.go("lab")

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
            "today": "today",
            "vocab_review": "vocab",
            "grammar_review": "grammar",
            "sentence_review": "sentences",
            "listening_review": "listening",
            "setup": "setup",
            "learn": "learn",
            "progress": "progress",
            "vocab_table": "setup",
            "conjugation": "setup",
            "mistakes": "mistakes",
            "settings": "settings",
            "lab": "lab",
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

    def _sync_nav(self, force: bool = False) -> None:
        """Enable the objective tabs that have a deck for the current Lektion;
        disable them all while the user is still choosing a Lektion in Setup."""
        enabled: set[str] = set()
        st = self.session.state
        level = (getattr(st, "level", "") or "").strip()
        book = (getattr(st, "book_slug", "") or "").strip()
        lek_n = int(getattr(st, "lektion_number", 0) or 0)
        signature = (level.upper(), book, lek_n)
        if not force and signature == self._last_nav_context:
            return
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
        self._last_nav_context = signature

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

        prefs = getattr(getattr(self.session, "settings", None), "value", None)
        scale = int(getattr(prefs, "font_scale", 100) or 100)
        self._sync_nav()
        self.nav.set_active(self._nav_key_for_page(page_key))
        apply_typography_scale(self.nav, scale)
        apply_typography_scale(w, scale)

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
            try:
                self.session.active_deck_id()
            except Exception:
                pass
            self._sync_resume_banner()
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
