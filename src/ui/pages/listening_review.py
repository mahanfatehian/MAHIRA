from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.audio import PiperModelManager, PlaybackService, PronunciationService
from core.session import SessionService
from ui.widgets.review_save_error import ReviewSaveError


# ---------------------------------------------------------------------------
# Centralized style constants — same card vibe as the Vocab/Grammar/Sentence
# review tabs (see GrammarCardWidget). Kept here so the QSS lives in one place
# instead of being scattered through the layout code.
# ---------------------------------------------------------------------------
STYLE_TOPBAR_CARD = "QFrame#TopBarCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 14px; }"
STYLE_PROMPT_CARD = "QFrame#PromptCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 18px; }"
STYLE_SECTION_CARD = "QFrame#SectionCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 18px; }"
STYLE_REVEAL_CARD = "QFrame#RevealCard { background-color: #101010; border: 1px solid #2A2A2A; border-radius: 14px; }"
STYLE_EMPTY_CARD = "QFrame#EmptyCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 14px; }"
STYLE_MILESTONE_BAR = "QFrame#MilestoneBar { background: #1A3A20; border: 1px solid #4CAF50; border-radius: 12px; }"

STYLE_KICKER = "QLabel { color:#9A9A9A; font-size:11px; font-weight:850; border:none; background:transparent; }"
STYLE_QUESTION = "QLabel { color:#FFFFFF; font-size:21px; font-weight:950; border:none; background:transparent; line-height:1.25; }"
STYLE_TRANSCRIPT = "QLabel { color:#E6E6E6; font-size:13px; font-weight:650; border:none; background:transparent; line-height:1.4; }"
STYLE_TRANSLATION = "QLabel { color:#9A9A9A; font-size:12px; font-weight:650; border:none; background:transparent; font-style:italic; }"

STYLE_COUNTER = "color:#FFFFFF; font-size:12px; font-weight:800; background:#1A1A1A; border:1px solid #2E2E2E; border-radius:8px; padding:6px 10px;"
STYLE_COUNTER_HL = "color:#FFD700; font-size:12px; font-weight:800; background:#2A2000; border:1px solid #FFD700; border-radius:8px; padding:6px 10px;"

STYLE_OPTION_IDLE = (
    "QPushButton { background-color:#161616; color:#F0F0F0; border:1px solid #2E2E2E; border-radius:12px; "
    "padding:13px 16px; font-size:14px; font-weight:800; text-align:left; }"
    "QPushButton:hover { background-color:#1E1E1E; border:1px solid #4A4A4A; }"
    "QPushButton:disabled { color:#9A9A9A; }"
)
STYLE_OPTION_CORRECT = (
    "QPushButton { background-color:#1F3427; color:#C8F7D4; border:1px solid #66E39A; border-radius:12px; "
    "padding:13px 16px; font-size:14px; font-weight:900; text-align:left; }"
    "QPushButton:disabled { color:#C8F7D4; }"
)
STYLE_OPTION_WRONG = (
    "QPushButton { background-color:#3A1F1F; color:#F7C8C8; border:1px solid #FF6B6B; border-radius:12px; "
    "padding:13px 16px; font-size:14px; font-weight:900; text-align:left; }"
    "QPushButton:disabled { color:#F7C8C8; }"
)
STYLE_OPTION_DIM = (
    "QPushButton { background-color:#141414; color:#6F6F6F; border:1px solid #242424; border-radius:12px; "
    "padding:13px 16px; font-size:14px; font-weight:700; text-align:left; }"
    "QPushButton:disabled { color:#6F6F6F; }"
)

STYLE_PRIMARY_BUTTON = (
    "QPushButton { background-color:#244B36; color:#F4FFF7; border:1px solid #4CAF50; border-radius:16px; "
    "padding:10px 16px; font-weight:900; font-size:13px; min-width:96px; }"
    "QPushButton:hover { background-color:#2B5B41; border:1px solid #7AE582; }"
    "QPushButton:pressed { background-color:#214734; }"
    "QPushButton:disabled { background-color:#1A1A1A; color:#6B6B6B; border:1px solid #252525; }"
)
STYLE_SKIP_BUTTON = (
    "QPushButton { background-color:#1B1B1B; color:#E6E6E6; border:1px solid #2E2E2E; border-radius:16px; "
    "padding:10px 16px; font-weight:850; font-size:13px; min-width:88px; }"
    "QPushButton:hover { background-color:#232323; border:1px solid #4A4A4A; color:#FFFFFF; }"
    "QPushButton:pressed { background-color:#2B2B2B; }"
    "QPushButton:disabled { background-color:#1A1A1A; color:#6B6B6B; border:1px solid #252525; }"
)
STYLE_UTILITY_BUTTON = (
    "QPushButton { background-color:#1B1B1B; color:#E6E6E6; border:1px solid #2E2E2E; border-radius:12px; "
    "padding:8px 14px; font-weight:850; font-size:12px; }"
    "QPushButton:hover { background-color:#232323; border:1px solid #4A4A4A; color:#FFFFFF; }"
)

# Compact top-bar New set/Stats (match the other review pages exactly).
STYLE_START_BTN = (
    "QPushButton { background-color:#244B36; color:#F4FFF7; border:1px solid #4CAF50; border-radius:10px; "
    "padding:8px; font-weight:900; font-size:12px; }"
    "QPushButton:hover { background-color:#2B5B41; border:1px solid #7AE582; }"
)
STYLE_STATS_BTN = (
    "QPushButton { background-color:#163A5C; color:#FFFFFF; border:1px solid #24537D; border-radius:10px; "
    "padding:8px; font-weight:900; font-size:12px; }"
    "QPushButton:hover { background-color:#1B4B78; border:1px solid #FFFFFF; }"
)

STYLE_AUDIO_IDLE = (
    "QPushButton { background-color:#162A40; color:#DCEBFF; border:1px solid #24537D; border-radius:12px; "
    "padding:11px 18px; font-weight:900; font-size:13px; }"
    "QPushButton:hover { border:1px solid #6B9FFF; }"
)
STYLE_AUDIO_PLAYING = (
    "QPushButton { background-color:#10243A; color:#BBD6FF; border:1px solid #24537D; border-radius:12px; "
    "padding:11px 18px; font-weight:900; font-size:13px; }"
    "QPushButton:hover { border:1px solid #6B9FFF; }"
)
STYLE_AUDIO_DISABLED = (
    "QPushButton { background-color:#151515; color:#6B6B6B; border:1px solid #252525; border-radius:12px; "
    "padding:11px 18px; font-weight:900; font-size:13px; }"
)


def _rating_style(rating: int, recommended: bool = False) -> str:
    """Again/Hard/Good/Easy button style — identical palette to the other tabs."""
    color_map = {
        0: ("#3A1F1F", "#FF6B6B"),
        1: ("#3A2A16", "#FFB020"),
        2: ("#1F3427", "#66E39A"),
        3: ("#17314A", "#6B9FFF"),
    }
    bg, accent = color_map.get(rating, ("#1B1B1B", "#FFFFFF"))
    if recommended:
        return (
            f"QPushButton {{ background-color:{bg}; color:#FFFFFF; border:2px solid {accent}; "
            "border-radius:14px; padding:9px 12px; font-weight:950; font-size:12px; }"
            "QPushButton:hover { border:2px solid #FFFFFF; }"
            "QPushButton:disabled { background-color:#101010; color:#6B6B6B; border:1px solid #252525; }"
        )
    return (
        f"QPushButton {{ background-color:#1B1B1B; color:{accent}; border:1px solid #2E2E2E; "
        "border-radius:14px; padding:9px 12px; font-weight:900; font-size:12px; }"
        f"QPushButton:hover {{ background-color:#232323; border:1px solid {accent}; color:#FFFFFF; }}"
        "QPushButton:disabled { background-color:#101010; color:#6B6B6B; border:1px solid #252525; }"
    )


class PronunciationWorker(QObject):
    """Synthesizes a passage to a cached WAV off the UI thread."""

    finished = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, service: PronunciationService, text: str, length_scale: float | None = None) -> None:
        super().__init__()
        self.service = service
        self.text = text
        self.length_scale = length_scale

    @Slot()
    def run(self) -> None:
        try:
            wav_path = self.service.generate_wav(self.text, length_scale=self.length_scale)
            self.finished.emit(self.text, str(wav_path))
        except Exception as e:  # noqa: BLE001 - surfaced to the UI as a status
            self.failed.emit(self.text, str(e))


class ListeningReviewPage(QWidget):
    """
    Listening comprehension panel, laid out in the same card rhythm as the other
    review tabs: a compact top bar, an audio prompt card, an answer-options card,
    a result line, a transcript reveal card, the "How did that feel?" rating row,
    and a bottom action row (Skip before answering / Next after).

    A passage is read aloud by the offline TTS but never shown; the learner picks
    one of four shuffled options. After answering, the correct option is
    highlighted (the right answer is named when wrong), the transcript + optional
    translation reveal, and the learner can self-rate or press Next to continue.

    Audio guarantees (unchanged): the passage is synthesized once and cached;
    Repeat reuses that exact WAV (no re-gen, spam-safe); Next / leaving the tab
    stops playback; a synthesis that finishes after the user has left never plays.

    Resume: a card that has not been advanced past is restored on return — either
    the fresh question or, if already answered, the revealed answered state.
    """

    go_progress = Signal()
    go_today = Signal()

    def __init__(self, session: SessionService, nav=None) -> None:
        super().__init__()
        self.session = session
        self.nav = nav

        self.current_item: Any = None
        self._options: list[str] = []
        self._answered = False
        self._chosen: str = ""
        self._ok = False
        self._recommended = 2
        self._response_ms = 0
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
        self._audio_ls: float | None = None  # speed of the cached clip
        self._audio_available = False
        self._replay_count: int = 0
        self._speed: float = 1.0  # 0.75 / 1.0 / 1.25 (Piper length_scale = 1/speed)

        self.setObjectName("ListeningReviewPage")
        self.setStyleSheet("ListeningReviewPage { background-color: #0E0E0E; }")

        self._build_ui()

        self._undo_sc = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._undo_sc.activated.connect(self._on_undo)

        # Keyboard rating: 1/2/3/4 = Again/Hard/Good/Easy, active only after the
        # learner has answered (no text input on this tab).
        self._rating_shortcuts: list[QShortcut] = []
        for key, r in (("1", 0), ("2", 1), ("3", 2), ("4", 3)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setEnabled(False)
            sc.activated.connect(lambda rr=r: self._rate_via_key(rr))
            self._rating_shortcuts.append(sc)

    def _set_rating_keys_enabled(self, on: bool) -> None:
        for sc in getattr(self, "_rating_shortcuts", []):
            sc.setEnabled(bool(on))

    def _rate_via_key(self, rating: int) -> None:
        if not self._answered:
            return
        self._on_rated(int(rating))

    def set_focus_mode(self, on: bool) -> None:
        """Focus/Zen mode: hide this tab's own top bar."""
        try:
            self.top_bar.setVisible(not bool(on))
        except Exception:
            pass

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)

        self.top_bar = self._build_top_bar()
        outer.addWidget(self.top_bar)
        outer.addWidget(self._build_milestone_bar())
        self.save_error = ReviewSaveError()
        outer.addWidget(self.save_error)

        # ---- Content stack (cards hug the top; no giant full-height shell) ----
        self.content = QWidget()
        content = QVBoxLayout(self.content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)

        content.addWidget(self._build_prompt_card())
        content.addWidget(self._build_options_card())
        content.addWidget(self._build_reveal_card())
        content.addWidget(self._build_rating_card())
        content.addLayout(self._build_action_row())

        outer.addWidget(self.content)
        outer.addWidget(self._build_empty_card())
        outer.addStretch(1)

        self._set_audio_state(busy=False, playing=False, available=False)
        self._update_counter()

    def _build_top_bar(self) -> QFrame:
        top_bar = QFrame()
        top_bar.setObjectName("TopBarCard")
        top_bar.setStyleSheet(STYLE_TOPBAR_CARD)
        lay = QHBoxLayout(top_bar)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title = QLabel("Listening")
        title.setStyleSheet("color:#FFFFFF; font-size:20px; font-weight:950; border:none;")
        self.page_subtitle = QLabel("Hear a passage, then answer")
        self.page_subtitle.setStyleSheet("color:#9A9A9A; font-size:11px; font-weight:700; border:none;")
        title_col.addWidget(title)
        title_col.addWidget(self.page_subtitle)
        lay.addLayout(title_col)
        lay.addStretch(1)

        self.counter_lbl = QLabel("0 / 0")
        self.counter_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.counter_lbl.setMinimumWidth(60)
        self.counter_lbl.setStyleSheet(STYLE_COUNTER)

        self.start_btn = QPushButton("New set")
        self.start_btn.setObjectName("NewReviewSetButton")
        self.start_btn.setAccessibleName("Start a new review set")
        self.start_btn.setToolTip("Start a fresh review set")
        self.start_btn.setMinimumWidth(78)
        self.start_btn.setStyleSheet(STYLE_START_BTN)
        self.start_btn.clicked.connect(self._start_session)

        self.stats_btn = QPushButton("Stats")
        self.stats_btn.setObjectName("ReviewStatsButton")
        self.stats_btn.setAccessibleName("Open review statistics")
        self.stats_btn.setFixedWidth(60)
        self.stats_btn.setStyleSheet(STYLE_STATS_BTN)
        self.stats_btn.clicked.connect(self.go_progress.emit)

        lay.addWidget(self.counter_lbl)
        lay.addWidget(self.start_btn)
        lay.addWidget(self.stats_btn)
        return top_bar

    def _build_milestone_bar(self) -> QFrame:
        self.milestone_bar = QFrame()
        self.milestone_bar.setObjectName("MilestoneBar")
        self.milestone_bar.setFixedHeight(48)
        self.milestone_bar.setStyleSheet(STYLE_MILESTONE_BAR)
        lay = QHBoxLayout(self.milestone_bar)
        lay.setContentsMargins(16, 6, 12, 6)
        lay.setSpacing(8)
        self.milestone_lbl = QLabel("Milestone reached!")
        self.milestone_lbl.setStyleSheet("QLabel { color:#7AE582; font-size:13px; font-weight:900; border:none; }")
        dismiss = QPushButton("×")
        dismiss.setFixedSize(26, 26)
        dismiss.setStyleSheet(
            "QPushButton { background:#2A2A2A; color:#888; border:1px solid #3A3A3A; border-radius:6px; font-size:14px; font-weight:700; }"
            "QPushButton:hover { color:#FFF; border-color:#666; }"
        )
        dismiss.clicked.connect(self._dismiss_milestone_banner)
        lay.addWidget(self.milestone_lbl, 1)
        lay.addWidget(dismiss)
        self.milestone_bar.hide()
        return self.milestone_bar

    def _build_prompt_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("PromptCard")
        card.setStyleSheet(STYLE_PROMPT_CARD)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        kicker = QLabel("Listen")
        kicker.setStyleSheet(STYLE_KICKER)
        lay.addWidget(kicker)

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
        lay.addLayout(audio_row)

        # Speed control: a one-tap slow pass to catch a missed word, without
        # ever revealing the transcript.
        speed_row = QHBoxLayout()
        speed_row.setSpacing(6)
        speed_lbl = QLabel("Speed")
        speed_lbl.setStyleSheet(STYLE_KICKER)
        speed_row.addWidget(speed_lbl)
        self.speed_btns: dict[float, QPushButton] = {}
        for spd, txt in ((0.75, "0.75×"), (1.0, "1×"), (1.25, "1.25×")):
            b = QPushButton(txt)
            b.setMinimumHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=spd: self._set_speed(s))
            self.speed_btns[spd] = b
            speed_row.addWidget(b)
        speed_row.addStretch(1)
        lay.addLayout(speed_row)
        self._update_speed_buttons()

        self.question_lbl = QLabel("")
        self.question_lbl.setWordWrap(True)
        self.question_lbl.setStyleSheet(STYLE_QUESTION)
        lay.addWidget(self.question_lbl)
        return card

    def _build_options_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("SectionCard")
        card.setStyleSheet(STYLE_SECTION_CARD)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(10)

        kicker = QLabel("Choose the correct answer")
        kicker.setStyleSheet(STYLE_KICKER)
        lay.addWidget(kicker)

        self.option_btns: list[QPushButton] = []
        for i in range(4):
            b = QPushButton("")
            b.setStyleSheet(STYLE_OPTION_IDLE)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(48)
            b.clicked.connect(lambda _=False, idx=i: self._on_option_clicked(idx))
            self.option_btns.append(b)
            lay.addWidget(b)
        return card

    def _build_reveal_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("RevealCard")
        card.setStyleSheet(STYLE_REVEAL_CARD)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(8)

        header = QLabel("Transcript")
        header.setStyleSheet(STYLE_KICKER)
        self.transcript_lbl = QLabel("")
        self.transcript_lbl.setWordWrap(True)
        self.transcript_lbl.setStyleSheet(STYLE_TRANSCRIPT)
        self.translation_lbl = QLabel("")
        self.translation_lbl.setWordWrap(True)
        self.translation_lbl.setStyleSheet(STYLE_TRANSLATION)

        lay.addWidget(header)
        lay.addWidget(self.transcript_lbl)
        lay.addWidget(self.translation_lbl)

        self.reveal_card = card
        self.reveal_card.hide()
        return card

    def _build_rating_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("SectionCard")
        card.setStyleSheet(STYLE_SECTION_CARD)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(9)

        title = QLabel("How did that feel?")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(STYLE_KICKER)
        lay.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_again = QPushButton("Again")
        self.btn_hard = QPushButton("Hard")
        self.btn_good = QPushButton("Good")
        self.btn_easy = QPushButton("Easy")
        self._rating_buttons = [
            (0, self.btn_again),
            (1, self.btn_hard),
            (2, self.btn_good),
            (3, self.btn_easy),
        ]
        for rating, button in self._rating_buttons:
            button.setMinimumHeight(40)
            button.setEnabled(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(_rating_style(rating, recommended=False))
            button.clicked.connect(lambda _=False, r=rating: self._on_rated(r))
            row.addWidget(button)
        lay.addLayout(row)

        self.rating_card = card
        return card

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setObjectName("ReviewSkipButton")
        self.skip_btn.setAccessibleName("Skip this review card")
        self.skip_btn.setMinimumHeight(42)
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.setStyleSheet(STYLE_SKIP_BUTTON)
        self.skip_btn.clicked.connect(self._on_skip)

        self.next_btn = QPushButton("Next  →")
        self.next_btn.setMinimumHeight(42)
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setStyleSheet(STYLE_PRIMARY_BUTTON)
        self.next_btn.clicked.connect(self._on_next)
        self.next_btn.hide()

        row.addWidget(self.skip_btn)
        row.addWidget(self.next_btn)
        return row

    def _build_empty_card(self) -> QFrame:
        self.empty_card = QFrame()
        self.empty_card.setObjectName("EmptyCard")
        self.empty_card.setStyleSheet(STYLE_EMPTY_CARD)
        lay = QVBoxLayout(self.empty_card)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(8)
        self.empty_title = QLabel("No listening items available.")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet("color:#FFFFFF; font-size:18px; font-weight:950; border:none;")
        self.empty_desc = QLabel("Choose a level, book, and lektion first.")
        self.empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_desc.setStyleSheet("color:#9A9A9A; font-size:12px; font-weight:700; border:none;")
        lay.addStretch(1)
        lay.addWidget(self.empty_title)
        lay.addWidget(self.empty_desc)
        self.today_btn = QPushButton("Return to Today")
        self.today_btn.setObjectName("ReturnToTodayButton")
        self.today_btn.setAccessibleName("Return to Today")
        self.today_btn.setStyleSheet(STYLE_PRIMARY_BUTTON)
        self.today_btn.clicked.connect(self.go_today.emit)
        self.today_btn.hide()
        lay.addWidget(self.today_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        self.empty_card.hide()
        return self.empty_card

    # --------------------------------------------------------------- helpers
    def _show_main(self) -> None:
        self.content.show()
        self.empty_card.hide()

    def _show_empty(self, title: str, desc: str) -> None:
        self.empty_title.setText(title)
        self.empty_desc.setText(desc)
        self.today_btn.setVisible(title.strip().lower().startswith("session finished"))
        self.content.hide()
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
        if bool(getattr(getattr(getattr(self.session, "settings", None), "value", None), "reduced_motion", False)):
            self._update_counter()
            return
        answered = getattr(self.session, "study_answered", 0)
        self.milestone_lbl.setText(f"Milestone! {answered} items reviewed this session. Keep going!")
        self.counter_lbl.setStyleSheet(STYLE_COUNTER_HL)
        self.milestone_bar.show()
        QTimer.singleShot(6000, self._dismiss_milestone_banner)
        self._update_counter()

    def _dismiss_milestone_banner(self) -> None:
        self.milestone_bar.hide()
        self.counter_lbl.setStyleSheet(STYLE_COUNTER)

    # ------------------------------------------------------------- lifecycle
    def on_show(self) -> None:
        try:
            self.session.state.objective = "listening"
        except Exception:
            pass

        self.page_subtitle.setText(self.session.context_label() or "Hear a passage, then answer")

        deck_id = self._active_deck_id()
        if not deck_id:
            self._show_empty(
                "No listening items available.",
                "Choose a level, book, and lektion first.",
            )
            self._update_counter()
            return

        # Resume: a card we haven't advanced past is restored (fresh OR answered).
        owns_current = True
        current_check = getattr(self.session, "is_current_item", None)
        if callable(current_check) and self.current_item is not None:
            owns_current = bool(
                current_check("listening", getattr(self.current_item, "id", None))
            )
        if (
            self.current_item is not None
            and int(getattr(self.current_item, "deck_id", -1)) == int(deck_id)
            and owns_current
        ):
            self._show_main()
            self._render_current_item(reshuffle=False)
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

    def _on_undo(self) -> None:
        """Ctrl+Z: reverse the last submitted answer (restore its schedule + drop
        its review row) and bring that card straight back to redo."""
        try:
            if not self.session.can_undo():
                return
            cur_id = getattr(self.current_item, "id", None)
            item = self.session.undo_last(requeue_current=cur_id)
        except Exception:
            return
        if item is not None:
            self._load_next()

    def _load_next(self) -> None:
        self.save_error.clear_failure()
        self._cleanup_audio(delete=True)
        self._update_counter()

        try:
            self.current_item = self.session.next_listening_item()
        except Exception:
            self.current_item = None

        self._answered = False
        self._chosen = ""
        self._ok = False
        self._options = []
        self._replay_count = 0
        self.card_started_at = time.time()

        if not self.current_item:
            self._show_empty(
                "Session finished.",
                "You've answered all queued listening items. Select New set for another set.",
            )
            self._update_counter()
            return

        self._show_main()
        self._render_current_item(reshuffle=True)
        self._update_counter()

    def _render_current_item(self, *, reshuffle: bool) -> None:
        """Paint the current item. Resume keeps the option order; if the card was
        already answered, the revealed/answered state is restored."""
        item = self.current_item
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
                btn.show()
            else:
                btn.hide()

        if self._answered:
            self._paint_answered()
        else:
            self._paint_question()

    def _paint_question(self) -> None:
        """Fresh, unanswered state."""
        for i, btn in enumerate(self.option_btns):
            if i < len(self._options):
                btn.setStyleSheet(STYLE_OPTION_IDLE)
                btn.setEnabled(True)
        self.reveal_card.hide()
        for rating, button in self._rating_buttons:
            button.setEnabled(False)
            button.setStyleSheet(_rating_style(rating, recommended=False))
        self._clear_rating_intervals()
        self._set_rating_keys_enabled(False)
        self.skip_btn.show()
        self.skip_btn.setEnabled(True)
        self.next_btn.hide()

        have_text = bool((getattr(self.current_item, "text", "") or "").strip())
        self.audio_btn.setText("▶  Play audio")
        self.audio_status.setText("")
        self._set_audio_state(busy=False, playing=False, available=have_text)

    def _paint_answered(self) -> None:
        """Answered/revealed state (also used to restore on resume)."""
        item = self.current_item
        answer = (getattr(item, "answer", "") or "").strip()

        for i, btn in enumerate(self.option_btns):
            if i >= len(self._options):
                continue
            opt = self._options[i]
            btn.setEnabled(False)
            if opt.strip().lower() == answer.lower():
                btn.setStyleSheet(STYLE_OPTION_CORRECT)
            elif opt == self._chosen:
                btn.setStyleSheet(STYLE_OPTION_WRONG)
            else:
                btn.setStyleSheet(STYLE_OPTION_DIM)

        self.transcript_lbl.setText(getattr(item, "text", "") or "")
        translation = getattr(item, "translation", None)
        if translation and str(translation).strip():
            self.translation_lbl.setText(str(translation).strip())
            self.translation_lbl.show()
        else:
            self.translation_lbl.hide()
        self.reveal_card.show()

        self._recommended = 2 if self._ok else 0
        for rating, button in self._rating_buttons:
            button.setEnabled(True)
            button.setStyleSheet(_rating_style(rating, recommended=(rating == self._recommended)))
        self._set_rating_keys_enabled(True)
        try:
            self._apply_rating_intervals()
        except Exception:
            pass

        self.skip_btn.hide()
        self.next_btn.show()

        self.audio_btn.setText("🔊  Repeat audio")
        have_text = bool((getattr(item, "text", "") or "").strip())
        self._set_audio_state(busy=False, playing=False, available=have_text)

    # --------------------------------------------------------------- answer
    def _on_option_clicked(self, idx: int) -> None:
        if self._answered or not self.current_item:
            return
        if idx >= len(self._options):
            return

        self._chosen = self._options[idx]
        self._response_ms = int(max(0.0, time.time() - float(self.card_started_at or time.time())) * 1000)

        try:
            res = self.session.check_listening(self.current_item, self._chosen)
            self._ok = bool(res.get("ok"))
        except Exception:
            answer = getattr(self.current_item, "answer", "") or ""
            self._ok = self._chosen.strip().lower() == answer.strip().lower()

        self._answered = True
        self._paint_answered()

    def _on_rated(self, rating: int) -> None:
        if not self._answered:
            return
        self._submit_and_advance(rating=int(rating), skipped=False)

    def _on_next(self) -> None:
        if not self._answered:
            return
        # No explicit rating chosen -> default to correctness (Good/Again).
        self._submit_and_advance(rating=None, skipped=False)

    def _on_skip(self) -> None:
        if self._answered or not self.current_item:
            return
        self._submit_and_advance(rating=0, skipped=True)

    def _submit_and_advance(self, *, rating: int | None, skipped: bool) -> None:
        item = self.current_item
        if item is None:
            return

        chosen = "" if skipped else self._chosen
        try:
            self.session.submit_listening(
                item=item,
                chosen=chosen,
                was_checked=(not skipped),
                was_skipped=skipped,
                response_ms=self._response_ms,
                replay_count=int(self._replay_count),
                rating=rating,
            )
        except Exception:
            # Stay on the card so the learner can retry; do not fake progress.
            self.save_error.show_failure()
            return

        milestone_hit = False
        if hasattr(self.session, "record_item_answered"):
            try:
                milestone_hit = bool(self.session.record_item_answered())
            except Exception:
                pass

        self._load_next()
        if milestone_hit:
            self._show_milestone_banner()

    # ------------------------------------------------------------- speed + rating intervals
    _SPEED_ACTIVE = (
        "QPushButton { background-color:#244B36; color:#F4FFF7; border:1px solid #4CAF50; "
        "border-radius:9px; padding:4px 11px; font-weight:900; font-size:11px; }"
    )
    _SPEED_IDLE = (
        "QPushButton { background-color:#161616; color:#C8C8C8; border:1px solid #2E2E2E; "
        "border-radius:9px; padding:4px 11px; font-weight:800; font-size:11px; }"
        "QPushButton:hover { border:1px solid #4A4A4A; color:#FFFFFF; }"
    )
    _RATING_BASE = {0: "Again", 1: "Hard", 2: "Good", 3: "Easy"}

    def _update_speed_buttons(self) -> None:
        for spd, b in getattr(self, "speed_btns", {}).items():
            b.setStyleSheet(self._SPEED_ACTIVE if abs(spd - self._speed) < 1e-6 else self._SPEED_IDLE)

    def _current_ls(self) -> float | None:
        # Piper length_scale = 1 / speed; None at normal speed keeps the base cache key.
        if abs(self._speed - 1.0) < 1e-6:
            return None
        return round(1.0 / self._speed, 3)

    def _set_speed(self, speed: float) -> None:
        self._speed = float(speed)
        self._update_speed_buttons()
        # Instant slow/fast pass: re-render + play at the new speed if a passage is up.
        if self.current_item is not None and (getattr(self.current_item, "text", "") or "").strip():
            self._play_passage()

    def _apply_rating_intervals(self) -> None:
        labels = {}
        if self.current_item is not None:
            labels = self.session.listening_interval_labels(self.current_item) or {}
        for rating, button in self._rating_buttons:
            base = self._RATING_BASE.get(rating, "")
            iv = labels.get(rating) or ""
            button.setText(f"{base}\n{iv}" if iv else base)

    def _clear_rating_intervals(self) -> None:
        for rating, button in self._rating_buttons:
            button.setText(self._RATING_BASE.get(rating, ""))

    # ----------------------------------------------------------------- audio
    def _set_audio_state(self, *, busy: bool, playing: bool, available: bool | None = None) -> None:
        if available is not None:
            self._audio_available = bool(available)
        available = self._audio_available

        self.audio_btn.setEnabled(bool(available) and not busy)

        if busy:
            self.audio_status.setText("Preparing audio…")
            self.audio_btn.setStyleSheet(STYLE_AUDIO_DISABLED)
        elif playing:
            self.audio_status.setText("Playing…")
            self.audio_btn.setStyleSheet(STYLE_AUDIO_PLAYING)
        else:
            self.audio_status.setText("")
            self.audio_btn.setStyleSheet(STYLE_AUDIO_IDLE if available else STYLE_AUDIO_DISABLED)

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
        ls = self._current_ls()

        # Reuse the exact cached clip if we already have it at THIS speed.
        if (self._audio_text == text and self._audio_ls == ls
                and self._audio_path and Path(self._audio_path).exists()):
            self.playback_service.stop()
            self._set_audio_state(busy=True, playing=False)
            self.playback_service.play_file(self._audio_path)
            return

        # Otherwise synthesize once at this speed, off-thread, then play.
        # Switching speed on the same passage: drop the previous variant clip so
        # cycling 1x -> 0.75x -> 1.25x doesn't orphan WAVs on disk.
        if self._audio_path:
            try:
                self.pronunciation_service.delete_cached_file(self._audio_path)
            except Exception:
                pass
        self._audio_text = text
        self._audio_ls = ls
        self._audio_path = ""
        self.playback_service.stop()
        self._set_audio_state(busy=True, playing=False)

        self._audio_thread = QThread(self)
        self._audio_worker = PronunciationWorker(self.pronunciation_service, text, length_scale=ls)
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
        if text != self._audio_text:
            return
        self._audio_path = wav_path
        if not self.isVisible():
            self._set_audio_state(busy=False, playing=False)
            return
        # The speed was changed while this was synthesizing: don't play the
        # stale-speed clip. _on_audio_thread_finished re-renders the passage at
        # the speed that's now selected, so the highlight and audio agree.
        if self._audio_ls != self._current_ls():
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
        # If the speed was changed mid-synthesis, the clip we just produced is at
        # the previous speed. Re-render the SAME passage at the now-selected
        # speed so the highlighted speed button and the audio match.
        if self.current_item is None or not self.isVisible():
            return
        cur_text = (getattr(self.current_item, "text", "") or "").strip()
        if cur_text and cur_text == self._audio_text and self._audio_ls != self._current_ls():
            self._play_passage()

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
                    # Pass the speed so a slow/fast clip (different cache key) is
                    # actually matched, not just the normal-speed one.
                    self.pronunciation_service.delete_cached_audio(self._audio_text, self._audio_ls)
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
