from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.audio import PiperModelManager, PlaybackService, PronunciationService
from core.session import SessionService


# ---------------------------------------------------------------------------
# Option button styles
# ---------------------------------------------------------------------------
_OPT_IDLE = """
    QPushButton {
        background-color: #161616; color: #F0F0F0;
        border: 1px solid #2E2E2E; border-radius: 12px;
        padding: 14px 16px; font-size: 14px; font-weight: 700; text-align: left;
    }
    QPushButton:hover { background-color: #1E1E1E; border: 1px solid #4A4A4A; }
    QPushButton:disabled { color: #8A8A8A; }
"""

_OPT_CORRECT = """
    QPushButton {
        background-color: #16351F; color: #C8F7D4;
        border: 1px solid #4CAF50; border-radius: 12px;
        padding: 14px 16px; font-size: 14px; font-weight: 800; text-align: left;
    }
    QPushButton:disabled { color: #C8F7D4; }
"""

_OPT_WRONG = """
    QPushButton {
        background-color: #3A1A1A; color: #F7C8C8;
        border: 1px solid #E0524F; border-radius: 12px;
        padding: 14px 16px; font-size: 14px; font-weight: 800; text-align: left;
    }
    QPushButton:disabled { color: #F7C8C8; }
"""

_OPT_DIM = """
    QPushButton {
        background-color: #141414; color: #6F6F6F;
        border: 1px solid #242424; border-radius: 12px;
        padding: 14px 16px; font-size: 14px; font-weight: 700; text-align: left;
    }
    QPushButton:disabled { color: #6F6F6F; }
"""


class PronunciationWorker(QObject):
    """Synthesizes a passage to a cached WAV off the UI thread."""

    finished = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, service: PronunciationService, text: str) -> None:
        super().__init__()
        self.service = service
        self.text = text

    @Slot()
    def run(self) -> None:
        try:
            wav_path = self.service.generate_wav(self.text)
            self.finished.emit(self.text, str(wav_path))
        except Exception as e:  # noqa: BLE001 - surfaced to the UI as a status
            self.failed.emit(self.text, str(e))


class ListeningReviewPage(QWidget):
    """
    Listening comprehension panel.

    A passage is read aloud by the offline TTS but never shown; the learner
    answers a 4-option multiple-choice question about it. After answering, the
    correct option is highlighted (and the right answer named when wrong), the
    full transcript is revealed, and the audio can be replayed.

    Audio handling guarantees the user asked for:
    - the passage is synthesized once and cached; Repeat reuses that exact WAV
      (no re-generation), and spamming Repeat just restarts the same clip;
    - pressing Next or leaving the tab stops playback immediately;
    - a synthesis that finishes after the user has left does not start playing.

    Resume: an item that has NOT been answered is kept, so leaving and returning
    to the tab shows the same question (not a fresh one). Once answered, moving
    on advances normally.
    """

    go_progress = Signal()

    def __init__(self, session: SessionService, nav=None) -> None:
        super().__init__()
        self.session = session
        self.nav = nav

        self.current_item: Any = None
        self._options: list[str] = []
        self._answered = False
        self._was_skipped = False
        self.card_started_at = 0.0

        # Audio state
        self.model_manager = PiperModelManager()
        self.pronunciation_service = PronunciationService(self.model_manager)

        self.playback_service = PlaybackService(self)
        self.playback_service.started.connect(self._on_playback_started)
        self.playback_service.finished.connect(self._on_playback_finished)
        self.playback_service.failed.connect(self._on_playback_failed)

        self._audio_thread: QThread | None = None
        self._audio_worker: PronunciationWorker | None = None
        self._audio_text: str = ""
        self._audio_path: str = ""
        self._replay_count: int = 0

        self.setObjectName("ListeningReviewPage")
        self.setStyleSheet("ListeningReviewPage { background-color: #0E0E0E; }")

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)

        # Top bar
        top_bar = QFrame()
        top_bar.setObjectName("TopBarCard")
        top_bar.setStyleSheet(
            "QFrame#TopBarCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 14px; }"
        )
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 12, 16, 12)
        top_bar_layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.page_title = QLabel("Listening")
        self.page_title.setStyleSheet("color:#FFFFFF; font-size:20px; font-weight:950; border:none;")
        self.page_subtitle = QLabel("Hear a passage, then answer")
        self.page_subtitle.setStyleSheet("color:#9A9A9A; font-size:11px; font-weight:700; border:none;")
        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)

        top_bar_layout.addLayout(title_col)
        top_bar_layout.addStretch(1)

        self.counter_lbl = QLabel("0 / 0")
        self.counter_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.counter_lbl.setMinimumWidth(60)
        self.counter_lbl.setStyleSheet(
            "color:#FFFFFF; font-size:12px; font-weight:800; background:#1A1A1A; border:1px solid #2E2E2E; border-radius:8px; padding:6px 10px;"
        )

        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedWidth(60)
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #244B36; color: #F4FFF7; border: 1px solid #4CAF50; border-radius: 10px; padding: 8px; font-weight: 900; font-size: 12px; }"
            "QPushButton:hover { background-color: #2B5B41; border: 1px solid #7AE582; }"
        )
        self.stats_btn = QPushButton("Stats")
        self.stats_btn.setFixedWidth(60)
        self.stats_btn.setStyleSheet(
            "QPushButton { background-color: #163A5C; color: #FFFFFF; border: 1px solid #24537D; border-radius: 10px; padding: 8px; font-weight: 900; font-size: 12px; }"
            "QPushButton:hover { background-color: #1B4B78; border: 1px solid #FFFFFF; }"
        )
        self.start_btn.clicked.connect(self._start_session)
        self.stats_btn.clicked.connect(self.go_progress.emit)

        top_bar_layout.addWidget(self.counter_lbl)
        top_bar_layout.addWidget(self.start_btn)
        top_bar_layout.addWidget(self.stats_btn)
        outer.addWidget(top_bar)

        # Milestone banner
        self.milestone_bar = QFrame()
        self.milestone_bar.setObjectName("MilestoneBar")
        self.milestone_bar.setFixedHeight(48)
        self.milestone_bar.setStyleSheet(
            "QFrame#MilestoneBar { background: #1A3A20; border: 1px solid #4CAF50; border-radius: 12px; }"
        )
        ms_layout = QHBoxLayout(self.milestone_bar)
        ms_layout.setContentsMargins(16, 6, 12, 6)
        ms_layout.setSpacing(8)
        self.milestone_lbl = QLabel("Milestone reached!")
        self.milestone_lbl.setStyleSheet("QLabel { color: #7AE582; font-size: 13px; font-weight: 900; border: none; }")
        ms_dismiss = QPushButton("×")
        ms_dismiss.setFixedSize(26, 26)
        ms_dismiss.setStyleSheet(
            "QPushButton { background: #2A2A2A; color: #888; border: 1px solid #3A3A3A; border-radius: 6px; font-size: 14px; font-weight: 700; }"
            "QPushButton:hover { color: #FFF; border-color: #666; }"
        )
        ms_dismiss.clicked.connect(self._dismiss_milestone_banner)
        ms_layout.addWidget(self.milestone_lbl, 1)
        ms_layout.addWidget(ms_dismiss)
        self.milestone_bar.hide()
        outer.addWidget(self.milestone_bar)

        # Main card
        self.main_shell = QFrame()
        self.main_shell.setObjectName("MainShell")
        self.main_shell.setStyleSheet(
            "QFrame#MainShell { background-color: #121212; border: 1px solid #262626; border-radius: 16px; }"
        )
        self.main_shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        shell = QVBoxLayout(self.main_shell)
        shell.setContentsMargins(20, 18, 20, 18)
        shell.setSpacing(14)

        # Audio control row
        audio_row = QHBoxLayout()
        audio_row.setSpacing(10)
        self.audio_btn = QPushButton("▶  Play audio")
        self.audio_btn.setMinimumHeight(46)
        self.audio_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.audio_btn.clicked.connect(self._play_passage)
        self.audio_status = QLabel("")
        self.audio_status.setStyleSheet("color:#8A8A8A; font-size:11px; font-weight:700; border:none;")
        audio_row.addWidget(self.audio_btn, 0)
        audio_row.addWidget(self.audio_status, 1)
        shell.addLayout(audio_row)

        # Question
        self.question_lbl = QLabel("")
        self.question_lbl.setWordWrap(True)
        self.question_lbl.setStyleSheet(
            "color:#FFFFFF; font-size:17px; font-weight:900; border:none; background:transparent;"
        )
        shell.addWidget(self.question_lbl)

        # Options
        self.options_box = QVBoxLayout()
        self.options_box.setSpacing(8)
        self.option_btns: list[QPushButton] = []
        for i in range(4):
            b = QPushButton("")
            b.setStyleSheet(_OPT_IDLE)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(48)
            b.clicked.connect(lambda _=False, idx=i: self._on_option_clicked(idx))
            self.option_btns.append(b)
            self.options_box.addWidget(b)
        shell.addLayout(self.options_box)

        # Result line
        self.result_lbl = QLabel("")
        self.result_lbl.setWordWrap(True)
        self.result_lbl.setStyleSheet("font-size:13px; font-weight:900; border:none; background:transparent;")
        self.result_lbl.hide()
        shell.addWidget(self.result_lbl)

        # Transcript reveal
        self.reveal_frame = QFrame()
        self.reveal_frame.setObjectName("RevealFrame")
        self.reveal_frame.setStyleSheet(
            "QFrame#RevealFrame { background-color: #161616; border: 1px solid #2E2E2E; border-radius: 12px; }"
        )
        reveal_lay = QVBoxLayout(self.reveal_frame)
        reveal_lay.setContentsMargins(14, 12, 14, 12)
        reveal_lay.setSpacing(6)
        reveal_header = QLabel("Transcript")
        reveal_header.setStyleSheet("color:#8FB8FF; font-size:11px; font-weight:900; border:none; letter-spacing:1px;")
        self.transcript_lbl = QLabel("")
        self.transcript_lbl.setWordWrap(True)
        self.transcript_lbl.setStyleSheet("color:#E8E8E8; font-size:14px; font-weight:600; border:none;")
        self.translation_lbl = QLabel("")
        self.translation_lbl.setWordWrap(True)
        self.translation_lbl.setStyleSheet("color:#9A9A9A; font-size:12px; font-weight:600; border:none; font-style:italic;")
        reveal_lay.addWidget(reveal_header)
        reveal_lay.addWidget(self.transcript_lbl)
        reveal_lay.addWidget(self.translation_lbl)
        self.reveal_frame.hide()
        shell.addWidget(self.reveal_frame)

        shell.addStretch(1)

        # Next
        next_row = QHBoxLayout()
        next_row.addStretch(1)
        self.next_btn = QPushButton("Next  →")
        self.next_btn.setMinimumHeight(44)
        self.next_btn.setMinimumWidth(120)
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setStyleSheet(
            "QPushButton { background-color: #244B36; color: #F4FFF7; border: 1px solid #4CAF50; border-radius: 12px; padding: 8px 18px; font-weight: 900; font-size: 13px; }"
            "QPushButton:hover { background-color: #2B5B41; border: 1px solid #7AE582; }"
        )
        self.next_btn.clicked.connect(self._on_next)
        self.next_btn.hide()
        next_row.addWidget(self.next_btn)
        shell.addLayout(next_row)

        outer.addWidget(self.main_shell, 1)

        # Empty / finished state
        self.empty_card = QFrame()
        self.empty_card.setObjectName("EmptyCard")
        self.empty_card.setStyleSheet(
            "QFrame#EmptyCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 14px; }"
        )
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)
        self.empty_title = QLabel("No listening items available.")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet("color:#FFFFFF; font-size:18px; font-weight:950; border:none;")
        self.empty_desc = QLabel("Choose a level, book, and lektion first.")
        self.empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_desc.setStyleSheet("color:#9A9A9A; font-size:12px; font-weight:700; border:none;")
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_desc)
        empty_layout.addStretch(1)
        self.empty_card.hide()
        outer.addWidget(self.empty_card, 1)

        outer.addStretch(0)

        self._set_audio_state(busy=False, playing=False, available=False)
        self._update_counter()

    # --------------------------------------------------------------- helpers
    def _show_main(self) -> None:
        self.main_shell.show()
        self.empty_card.hide()

    def _show_empty(self, title: str, desc: str) -> None:
        self.empty_title.setText(title)
        self.empty_desc.setText(desc)
        self.main_shell.hide()
        self.empty_card.show()

    def _active_deck_id(self) -> int | None:
        try:
            return self.session.active_deck_id()
        except Exception:
            return None

    def _update_counter(self) -> None:
        try:
            answered, milestone = self.session.study_progress()
            self.counter_lbl.setText(f"{answered} / {milestone}")
        except Exception:
            self.counter_lbl.setText("0 / 30")

    def _show_milestone_banner(self) -> None:
        answered = getattr(self.session, "study_answered", 0)
        self.milestone_lbl.setText(f"Milestone! {answered} items reviewed this session. Keep going!")
        self.counter_lbl.setStyleSheet(
            "color:#FFD700; font-size:12px; font-weight:800; background:#2A2000; "
            "border:1px solid #FFD700; border-radius:8px; padding:6px 10px;"
        )
        self.milestone_bar.show()
        QTimer.singleShot(6000, self._dismiss_milestone_banner)
        self._update_counter()

    def _dismiss_milestone_banner(self) -> None:
        self.milestone_bar.hide()
        self.counter_lbl.setStyleSheet(
            "color:#FFFFFF; font-size:12px; font-weight:800; background:#1A1A1A; "
            "border:1px solid #2E2E2E; border-radius:8px; padding:6px 10px;"
        )

    # ------------------------------------------------------------- lifecycle
    def on_show(self) -> None:
        # This tab is always the listening objective.
        try:
            self.session.state.objective = "listening"
        except Exception:
            pass

        deck_id = self._active_deck_id()
        if not deck_id:
            self._show_empty(
                "No listening items available.",
                "Choose a level, book, and lektion first.",
            )
            self._update_counter()
            return

        # Resume an unanswered card instead of pulling a fresh one.
        if (
            self.current_item is not None
            and not self._answered
            and int(getattr(self.current_item, "deck_id", -1)) == int(deck_id)
        ):
            self._show_main()
            self._render_item(self.current_item, reshuffle=False)
            self._update_counter()
            return

        try:
            if self.session.remaining() == 0:
                self.session.start_new_session()
        except Exception:
            pass

        self._load_next()

    def _start_session(self) -> None:
        deck_id = self._active_deck_id()
        if not deck_id:
            self._show_empty(
                "No listening items available.",
                "Choose a level, book, and lektion first.",
            )
            self._update_counter()
            return
        try:
            self.session.start_new_session()
        except Exception:
            pass
        self._load_next()

    def _load_next(self) -> None:
        self._cleanup_audio(delete=True)
        self._update_counter()

        try:
            self.current_item = self.session.next_listening_item()
        except Exception:
            self.current_item = None

        self._answered = False
        self._was_skipped = False
        self._options = []
        self._replay_count = 0
        self.card_started_at = time.time()

        if not self.current_item:
            self._show_empty(
                "Session finished.",
                "You've answered all queued listening items. Press Start for another set.",
            )
            self._update_counter()
            return

        self._show_main()
        self._render_item(self.current_item, reshuffle=True)
        self._update_counter()

    def _render_item(self, item: Any, *, reshuffle: bool) -> None:
        """Paint a (possibly resumed) item. Resume keeps the option order."""
        self.question_lbl.setText(getattr(item, "question", "") or "")

        if reshuffle or not self._options:
            try:
                self._options = self.session.listening_options(item)
            except Exception:
                opts = [getattr(item, "answer", "") or ""]
                opts += list(getattr(item, "distractors", None) or [])
                self._options = [o for o in opts if o][:4]

        for i, btn in enumerate(self.option_btns):
            if i < len(self._options):
                btn.setText(self._options[i])
                btn.setStyleSheet(_OPT_IDLE)
                btn.setEnabled(True)
                btn.show()
            else:
                btn.hide()

        self.result_lbl.hide()
        self.reveal_frame.hide()
        self.next_btn.hide()

        # Audio resets to idle; a previously cached clip (resume) can still play.
        have_text = bool((getattr(item, "text", "") or "").strip())
        self.audio_btn.setText("▶  Play audio")
        self.audio_status.setText("")
        self._set_audio_state(busy=False, playing=False, available=have_text)

    # --------------------------------------------------------------- answer
    def _on_option_clicked(self, idx: int) -> None:
        if self._answered or not self.current_item:
            return
        if idx >= len(self._options):
            return

        chosen = self._options[idx]
        self._answered = True

        try:
            res = self.session.check_listening(self.current_item, chosen)
            ok = bool(res.get("ok"))
            answer = res.get("answer") or (getattr(self.current_item, "answer", "") or "")
        except Exception:
            answer = getattr(self.current_item, "answer", "") or ""
            ok = (chosen or "").strip().lower() == answer.strip().lower()

        response_ms = int(max(0.0, time.time() - float(self.card_started_at or time.time())) * 1000)

        try:
            self.session.submit_listening(
                item=self.current_item,
                chosen=chosen,
                was_checked=True,
                was_skipped=False,
                response_ms=response_ms,
                replay_count=int(self._replay_count),
            )
        except Exception:
            pass

        # Colour the options.
        for i, btn in enumerate(self.option_btns):
            if i >= len(self._options):
                continue
            opt = self._options[i]
            btn.setEnabled(False)
            if opt.strip().lower() == answer.strip().lower():
                btn.setStyleSheet(_OPT_CORRECT)
            elif i == idx:
                btn.setStyleSheet(_OPT_WRONG)
            else:
                btn.setStyleSheet(_OPT_DIM)

        if ok:
            self.result_lbl.setText("✓ Correct!")
            self.result_lbl.setStyleSheet("color:#7AE582; font-size:13px; font-weight:900; border:none;")
        else:
            self.result_lbl.setText(f"✗ Not quite — correct answer: {answer}")
            self.result_lbl.setStyleSheet("color:#F2A0A0; font-size:13px; font-weight:900; border:none;")
        self.result_lbl.show()

        # Reveal the transcript and translation.
        self.transcript_lbl.setText(getattr(self.current_item, "text", "") or "")
        translation = getattr(self.current_item, "translation", None)
        if translation and str(translation).strip():
            self.translation_lbl.setText(str(translation).strip())
            self.translation_lbl.show()
        else:
            self.translation_lbl.hide()
        self.reveal_frame.show()

        self.audio_btn.setText("🔊  Repeat audio")
        self.next_btn.show()

        milestone_hit = False
        if hasattr(self.session, "record_item_answered"):
            try:
                milestone_hit = bool(self.session.record_item_answered())
            except Exception:
                pass
        self._update_counter()
        if milestone_hit:
            self._show_milestone_banner()

    def _on_next(self) -> None:
        self._load_next()

    # ----------------------------------------------------------------- audio
    def _set_audio_state(self, *, busy: bool, playing: bool, available: bool | None = None) -> None:
        if available is not None:
            self._audio_available = bool(available)
        available = getattr(self, "_audio_available", True)

        # Busy (generating) disables the button so it can't be spammed into a
        # second synthesis. Playing keeps it enabled so a click just restarts
        # the same cached clip.
        self.audio_btn.setEnabled(bool(available) and not busy)

        if busy:
            self.audio_status.setText("Preparing audio…")
        elif playing:
            self.audio_status.setText("Playing…")
        else:
            self.audio_status.setText("")

        base = (
            "QPushButton { background-color: %s; color: %s; border: 1px solid %s; "
            "border-radius: 12px; padding: 8px 16px; font-weight: 900; font-size: 13px; }"
            "QPushButton:hover { border: 1px solid #8FB8FF; }"
            "QPushButton:disabled { background-color: #151515; color: #6B6B6B; border: 1px solid #252525; }"
        )
        if playing:
            self.audio_btn.setStyleSheet(base % ("#10243A", "#BBD6FF", "#24537D"))
        else:
            self.audio_btn.setStyleSheet(base % ("#162A40", "#DCEBFF", "#24537D"))

    def _play_passage(self) -> None:
        if not self.current_item:
            return
        text = (getattr(self.current_item, "text", "") or "").strip()
        if not text:
            self._set_audio_state(busy=False, playing=False, available=False)
            return

        # Spam guard: ignore while a synthesis is in flight.
        if self._audio_thread is not None and self._audio_thread.isRunning():
            return

        self._replay_count += 1

        # Reuse the exact cached clip if we already have it (Repeat path).
        if self._audio_text == text and self._audio_path and Path(self._audio_path).exists():
            self.playback_service.stop()
            self._set_audio_state(busy=True, playing=False)
            self.playback_service.play_file(self._audio_path)
            return

        # Otherwise synthesize once, off-thread, then play.
        self._audio_text = text
        self._audio_path = ""
        self.playback_service.stop()
        self._set_audio_state(busy=True, playing=False)

        self._audio_thread = QThread(self)
        self._audio_worker = PronunciationWorker(self.pronunciation_service, text)
        self._audio_worker.moveToThread(self._audio_thread)
        self._audio_thread.started.connect(self._audio_worker.run)
        self._audio_worker.finished.connect(self._on_audio_ready)
        self._audio_worker.failed.connect(self._on_audio_failed)
        self._audio_worker.finished.connect(self._audio_thread.quit)
        self._audio_worker.failed.connect(self._audio_thread.quit)
        self._audio_worker.finished.connect(self._audio_worker.deleteLater)
        self._audio_worker.failed.connect(self._audio_worker.deleteLater)
        self._audio_thread.finished.connect(self._on_audio_thread_finished)
        self._audio_thread.finished.connect(self._audio_thread.deleteLater)
        self._audio_thread.start()

    @Slot(str, str)
    def _on_audio_ready(self, text: str, wav_path: str) -> None:
        # Cache the path even if we've moved on, but only auto-play if this is
        # still the current text AND the tab is visible (don't play into a
        # backgrounded tab).
        if text != self._audio_text:
            return
        self._audio_path = wav_path
        if not self.isVisible():
            self._set_audio_state(busy=False, playing=False)
            return
        self._set_audio_state(busy=True, playing=False)
        self.playback_service.play_file(wav_path)

    @Slot(str, str)
    def _on_audio_failed(self, text: str, message: str) -> None:
        if text == self._audio_text:
            self._set_audio_state(busy=False, playing=False)
            self.audio_status.setText("Audio unavailable")

    @Slot()
    def _on_audio_thread_finished(self) -> None:
        self._audio_thread = None
        self._audio_worker = None

    @Slot(str)
    def _on_playback_started(self, path: str) -> None:
        self._set_audio_state(busy=False, playing=True)

    @Slot()
    def _on_playback_finished(self) -> None:
        self._set_audio_state(busy=False, playing=False)

    @Slot(str)
    def _on_playback_failed(self, message: str) -> None:
        self._set_audio_state(busy=False, playing=False)
        self.audio_status.setText("Audio unavailable")

    def _cleanup_audio(self, *, delete: bool) -> None:
        """Stop playback. When `delete`, also remove the cached WAV (used when
        advancing to a new item); on a plain tab-switch we keep it so a resumed
        card can replay without re-synthesizing."""
        self.playback_service.stop()
        if delete:
            if self._audio_path:
                try:
                    self.pronunciation_service.delete_cached_file(self._audio_path)
                except Exception:
                    pass
            if self._audio_text:
                try:
                    self.pronunciation_service.delete_cached_audio(self._audio_text)
                except Exception:
                    pass
            self._audio_text = ""
            self._audio_path = ""
        self._set_audio_state(busy=False, playing=False)

    def cleanup_audio_cache_on_startup(self) -> None:
        try:
            self.pronunciation_service.clear_all_cached_audio()
        except Exception:
            pass

    # Stop audio the moment the user leaves this tab.
    def hideEvent(self, event) -> None:
        try:
            self.playback_service.stop()
            self._set_audio_state(busy=False, playing=False)
        except Exception:
            pass
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        try:
            self._cleanup_audio(delete=True)
        except Exception:
            pass
        super().closeEvent(event)
