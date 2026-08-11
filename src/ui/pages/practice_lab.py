from __future__ import annotations

import time

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.audio import PiperModelManager, PlaybackService, PronunciationService
from ui.theme import (
    COLORS,
    INPUT_STYLE,
    PRIMARY_BUTTON_STYLE,
    SYSTEM_BUTTON_STYLE,
    TOP_BAR_STYLE,
    card_style,
    set_feature_font,
)
from ui.widgets.audio_button import AudioButton
from ui.widgets.special_char_keyboard import SpecialCharKeyboard


def _set_font(widget: QWidget, size: int, weight: QFont.Weight) -> None:
    set_feature_font(widget, size, weight)


class _SpeechWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, service, text: str, length_scale: float | None):
        super().__init__()
        self.service = service
        self.text = text
        self.length_scale = length_scale

    @Slot()
    def run(self) -> None:
        try:
            if QThread.currentThread().isInterruptionRequested():
                self.cancelled.emit()
                return
            path = self.service.generate_wav(self.text, length_scale=self.length_scale)
            if QThread.currentThread().isInterruptionRequested():
                self.cancelled.emit()
                return
            self.finished.emit(str(path))
        except Exception as exc:
            self.failed.emit(str(exc))


class PracticeLabPage(QWidget):
    """Active German recall and dictation with independent scheduling lanes."""

    def __init__(self, session, _nav=None):
        super().__init__()
        self.setObjectName("PracticeLabPage")
        self.setProperty("mahiraFeaturePage", True)
        self.session = session
        self.current = None
        self._ids: list[int] = []
        self._pending_target_ids: list[int] | None = None
        self._targeted_drill = False
        self._mode = "production"
        self._started_at = 0.0
        self._checked = False
        self._seen = 0
        self._audio_generation = 0
        self._audio_thread = None
        self._audio_worker = None
        self._audio_service = None
        self._playback = PlaybackService(self)
        self._playback.finished.connect(self._playback_finished)
        self._playback.failed.connect(self._audio_failed)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)

        top_bar = QFrame()
        top_bar.setObjectName("TopBarCard")
        top_bar.setStyleSheet(TOP_BAR_STYLE)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 12, 16, 12)
        top_layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Practice Lab")
        _set_font(title, 15, QFont.Weight.Black)
        self.context = QLabel("Choose a vocabulary lesson in Setup to begin.")
        self.context.setWordWrap(True)
        _set_font(self.context, 9, QFont.Weight.DemiBold)
        self.context.setStyleSheet(f"color:{COLORS['muted']};")
        title_col.addWidget(title)
        title_col.addWidget(self.context)

        self.session_chip = QLabel("0 practiced")
        self.session_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _set_font(self.session_chip, 9, QFont.Weight.Bold)
        self.session_chip.setStyleSheet(
            "QLabel { color:#FFFFFF; background:#1A1A1A; border:1px solid #2E2E2E; "
            "border-radius:8px; padding:6px 10px; }"
        )
        top_layout.addLayout(title_col, 1)
        top_layout.addWidget(self.session_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(top_bar)

        mode_switch = QFrame()
        mode_switch.setObjectName("PracticeModeSwitch")
        mode_switch.setStyleSheet(
            "QFrame#PracticeModeSwitch { background:#101010; border:1px solid #2A2A2A; "
            "border-radius:12px; }"
        )
        mode_layout = QHBoxLayout(mode_switch)
        mode_layout.setContentsMargins(4, 4, 4, 4)
        mode_layout.setSpacing(4)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        mode_style = f"""
            QPushButton {{ background:transparent; color:{COLORS['muted']}; border:1px solid transparent;
                border-radius:9px; padding:8px 14px; font-weight:800; }}
            QPushButton:hover {{ background:#1B1B1B; color:#FFFFFF; border-color:#2E2E2E; }}
            QPushButton:checked {{ background:{COLORS['action']}; color:{COLORS['action_text']};
                border-color:{COLORS['action_border']}; }}
            QPushButton:checked:hover {{ background:{COLORS['action_hover']};
                border-color:{COLORS['action_focus']}; }}
            QPushButton:focus {{ border-color:{COLORS['action_focus']}; }}
        """
        for label, mode in (
            ("Meaning → German", "production"),
            ("Audio → German", "dictation"),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setStyleSheet(mode_style)
            button.setAccessibleName(f"Practice mode: {label}")
            button.clicked.connect(
                lambda _checked=False, selected=mode: self._set_mode(selected)
            )
            self.mode_group.addButton(button)
            self.mode_buttons[mode] = button
            mode_layout.addWidget(button, 1)
        self.mode_buttons[self._mode].setChecked(True)
        root.addWidget(mode_switch)

        card = QFrame()
        card.setObjectName("PracticeCard")
        card.setStyleSheet(card_style(radius=18))
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 17, 18, 18)
        card_layout.setSpacing(12)

        prompt_meta = QHBoxLayout()
        prompt_meta.setSpacing(8)
        self.mode_label = QLabel("MEANING → GERMAN")
        _set_font(self.mode_label, 8, QFont.Weight.Black)
        self.mode_label.setStyleSheet(f"color:{COLORS['action_focus']};")
        self.card_position = QLabel()
        self.card_position.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.card_position.setStyleSheet(f"color:{COLORS['muted']};")
        prompt_meta.addWidget(self.mode_label)
        prompt_meta.addStretch(1)
        prompt_meta.addWidget(self.card_position)
        card_layout.addLayout(prompt_meta)

        prompt_row = QHBoxLayout()
        prompt_row.setSpacing(12)
        self.prompt = QLabel("Choose a vocabulary lesson in Setup to begin.")
        self.prompt.setWordWrap(True)
        self.prompt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.prompt.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        _set_font(self.prompt, 17, QFont.Weight.Black)
        self.play_btn = AudioButton()
        self.play_btn.setAccessibleName("Play German prompt")
        self.play_btn.clicked.connect(self._play)
        self.play_btn.hide()
        prompt_row.addWidget(self.prompt, 1)
        prompt_row.addWidget(self.play_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        card_layout.addLayout(prompt_row)

        input_frame = QFrame()
        input_frame.setObjectName("PracticeInputFrame")
        input_frame.setStyleSheet(
            "QFrame#PracticeInputFrame { background:#101010; border:1px solid #2A2A2A; "
            "border-radius:14px; }"
            "QFrame#PracticeInputFrame QLabel { background:transparent; border:none; }"
        )
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(14, 12, 14, 12)
        input_layout.setSpacing(8)
        answer_label = QLabel("YOUR GERMAN ANSWER")
        _set_font(answer_label, 8, QFont.Weight.Black)
        answer_label.setStyleSheet(f"color:{COLORS['muted']};")
        self.answer = QLineEdit()
        self.answer.setObjectName("PracticeAnswer")
        self.answer.setPlaceholderText("Type the word with its article when needed…")
        self.answer.setAccessibleName("German answer")
        self.answer.setClearButtonEnabled(True)
        self.answer.setMinimumHeight(46)
        _set_font(self.answer, 12, QFont.Weight.DemiBold)
        self.answer.setStyleSheet(INPUT_STYLE)
        self.answer.returnPressed.connect(self._check_or_next)
        self.special_chars = SpecialCharKeyboard()
        self.special_chars.set_language("de")
        self.special_chars.char_clicked.connect(self.answer.insert)
        input_layout.addWidget(answer_label)
        input_layout.addWidget(self.answer)
        input_layout.addWidget(self.special_chars)
        card_layout.addWidget(input_frame)

        self.feedback = QLabel()
        self.feedback.setObjectName("PracticeFeedback")
        self.feedback.setWordWrap(True)
        self.feedback.setMinimumHeight(42)
        self.feedback.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        card_layout.addWidget(self.feedback)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.skip_button = QPushButton("Skip")
        self.skip_button.setObjectName("PracticeSkipButton")
        self.skip_button.setAccessibleName("Skip this practice card")
        self.skip_button.setStyleSheet(SYSTEM_BUTTON_STYLE)
        self.skip_button.clicked.connect(self._skip)
        self.action = QPushButton("Check answer")
        self.action.setObjectName("PracticeCheckButton")
        self.action.setAccessibleName("Check German answer")
        self.action.setProperty("primary", True)
        self.action.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.action.setMinimumWidth(150)
        self.action.clicked.connect(self._check_or_next)
        actions.addWidget(self.skip_button)
        actions.addStretch(1)
        actions.addWidget(self.action)
        card_layout.addLayout(actions)
        root.addWidget(card)
        root.addStretch(1)

    def on_show(self) -> None:
        self.context.setText(self.session.context_label() or "No lesson selected")
        pending = self._pending_target_ids
        self._pending_target_ids = None
        if pending is None:
            self._ids = []
            self._targeted_drill = False
        else:
            # The page consumes IDs with pop(), so reverse the visible order.
            self._ids = list(reversed(pending))
            self._targeted_drill = True
        self._seen = 0
        self.session_chip.setText("0 practiced")
        self._load_next()

    def _set_mode(self, mode: str) -> None:
        self.select_mode(mode, reload=True)

    def select_mode(self, mode: str, *, reload: bool = True) -> bool:
        """Select a practice lane, optionally deferring its database load.

        Navigation can call this with ``reload=False`` immediately before
        showing the page; :meth:`on_show` then performs the one intended load.
        Direct mode-button clicks retain the existing immediate-reload behavior.
        """

        normalized = str(mode or "").strip().lower()
        if normalized not in self.mode_buttons:
            return False
        self._mode = normalized
        self.mode_buttons[normalized].setChecked(True)
        self.mode_label.setText(
            "MEANING → GERMAN"
            if normalized == "production"
            else "AUDIO → GERMAN"
        )
        self._ids = []
        self._pending_target_ids = None
        self._targeted_drill = False
        if reload:
            self._load_next()
        return True

    def start_targeted_drill(
        self,
        item_ids,
        practice_mode: str,
    ) -> bool:
        """Validate and stage a one-off Lab queue for the next on_show call."""
        normalized = str(practice_mode or "").strip().lower()
        if normalized not in self.mode_buttons:
            return False

        validator = getattr(self.session, "targeted_item_ids", None)
        if callable(validator):
            selected = list(validator("vocab", item_ids, limit=50))
        else:
            selected = []
            seen: set[int] = set()
            for value in item_ids:
                if isinstance(value, bool):
                    continue
                try:
                    item_id = int(value)
                except (TypeError, ValueError, OverflowError):
                    continue
                if item_id <= 0 or item_id in seen:
                    continue
                seen.add(item_id)
                selected.append(item_id)
                if len(selected) >= 50:
                    break
        if not selected:
            return False

        if not self.select_mode(normalized, reload=False):
            return False
        self._pending_target_ids = selected
        return True

    def _pick_ids(self, deck_id: int) -> list[int]:
        limit = max(5, int(self.session.plan.limit))
        session_picker = getattr(self.session, "pick_vocab_practice_ids", None)
        if callable(session_picker):
            return list(
                session_picker(
                    self._mode,
                    limit=limit,
                    mode="mixed",
                    cooldown_hours=0,
                )
            )
        picker = getattr(self.session.repo, "pick_practice_vocab_ids", None)
        if callable(picker):
            return list(picker(deck_id, self._mode, limit=limit))
        return self.session.repo.pick_session_vocab_ids(
            deck_id,
            limit,
            mode="mixed",
            cooldown_hours=0,
        )

    def _load_next(self) -> None:
        # Moving cards/modes must stop old playback. A synthesis worker cannot
        # be force-killed safely, so its generation is invalidated and any late
        # result is discarded below.
        self._audio_generation += 1
        self._playback.stop()
        self.play_btn.reset_state()
        deck_id = self.session.vocab_deck_id()
        if deck_id is None:
            self._show_empty("Choose a lesson with vocabulary in Setup to begin.")
            return

        if not self._ids and self._targeted_drill:
            self._targeted_drill = False
            self._show_empty(
                "Targeted drill complete.",
                detail=(
                    "Your drill ratings were saved in this practice lane; "
                    "the recognition schedule remains unchanged."
                ),
            )
            return
        if not self._ids:
            self._ids = self._pick_ids(deck_id)
        self.current = self.session.repo.get_vocab_by_id(self._ids.pop()) if self._ids else None
        if self.current is None:
            self._show_empty(
                "No cards are available in this lane. Suspended and hidden cards stay out of practice."
            )
            return

        label = "Production" if self._mode == "production" else "Dictation"
        self.context.setText(f"{self.session.context_label()} · {label}")
        self.prompt.setText(
            self.current.meaning
            if self._mode == "production"
            else "Listen, then write exactly what you hear."
        )
        self.card_position.setText(f"{len(self._ids) + 1} in this set")
        self.play_btn.setVisible(self._mode == "dictation")
        self.play_btn.set_available(self._mode == "dictation")
        self.answer.setEnabled(True)
        self.skip_button.setEnabled(True)
        self.action.setEnabled(True)
        self.answer.clear()
        self.feedback.clear()
        self.feedback.setStyleSheet("background:transparent;border:none;")
        self.action.setText("Check answer")
        self._checked = False
        self._started_at = time.monotonic()
        self.answer.setFocus()

        autoplay = bool(
            getattr(
                getattr(getattr(self.session, "settings", None), "value", None),
                "audio_autoplay",
                False,
            )
        )
        if self._mode == "dictation" and autoplay:
            self._play()

    def _show_empty(self, message: str, *, detail: str | None = None) -> None:
        self.current = None
        self.prompt.setText(message)
        self.card_position.clear()
        self.play_btn.hide()
        self.answer.clear()
        self.answer.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.action.setEnabled(False)
        self.feedback.setText(
            detail or "Your recognition review schedule is unchanged."
        )
        self.feedback.setStyleSheet(f"color:{COLORS['muted']};background:transparent;")

    def _check_or_next(self) -> None:
        if self._checked:
            self._load_next()
            return
        if self.current is None:
            return
        typed = self.answer.text().strip()
        if not typed:
            self.answer.setFocus()
            return

        elapsed = int((time.monotonic() - self._started_at) * 1000)
        result = self.session.submit_vocab_production(
            self.current,
            typed,
            practice_mode=self._mode,
            response_ms=elapsed,
        )
        if result["ok"]:
            text = "Correct. This practice lane moves forward."
            background, edge, color = "#17271E", "#315F42", COLORS["action_focus"]
        else:
            text = f"{result['message']}  Expected: {result['expected']}"
            background, edge, color = "#24191B", "#6B303A", COLORS["danger_text"]
        self.feedback.setText(text)
        self.feedback.setStyleSheet(
            f"QLabel {{ background:{background}; color:{color}; border:1px solid {edge}; "
            "border-radius:10px; padding:9px 12px; font-weight:800; }"
        )
        self.answer.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.action.setText("Next card")
        self._checked = True
        self._seen += 1
        self.session_chip.setText(f"{self._seen} practiced")

    def _skip(self) -> None:
        if self.current is not None:
            self._load_next()

    def _play(self) -> None:
        if self.current is None or self._audio_thread is not None:
            return
        article = (self.current.article or "").strip()
        text = f"{article} {self.current.word}".strip()
        try:
            if self._audio_service is None:
                self._audio_service = PronunciationService(PiperModelManager())
            speed = float(
                getattr(
                    getattr(getattr(self.session, "settings", None), "value", None),
                    "audio_speed",
                    1.0,
                )
            )
            length_scale = 1.0 / max(0.5, min(1.5, speed))
            cached = self._audio_service.get_cached_path(text, length_scale)
            if cached.exists():
                self.play_btn.set_playing(True)
                self._playback.play_file(cached)
                return

            self.play_btn.set_busy(True)
            request_generation = self._audio_generation
            thread = QThread(self)
            worker = _SpeechWorker(self._audio_service, text, length_scale)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.finished.connect(
                lambda path, generation=request_generation: self._audio_ready(
                    path, generation
                )
            )
            worker.failed.connect(
                lambda message, generation=request_generation: self._audio_failed(
                    message, generation
                )
            )
            worker.finished.connect(thread.quit)
            worker.failed.connect(thread.quit)
            worker.cancelled.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            worker.failed.connect(worker.deleteLater)
            worker.cancelled.connect(worker.deleteLater)
            thread.finished.connect(self._audio_finished)
            self._audio_thread = thread
            self._audio_worker = worker
            thread.start()
        except Exception as exc:
            self._audio_failed(str(exc))

    def _audio_ready(self, path: str, generation: int | None = None) -> None:
        if generation is not None and generation != self._audio_generation:
            return
        self.play_btn.set_playing(True)
        self._playback.play_file(path)

    def _audio_failed(self, message: str, generation: int | None = None) -> None:
        if generation is not None and generation != self._audio_generation:
            return
        self.play_btn.reset_state()
        self.feedback.setText(f"Audio is unavailable: {message}")
        self.feedback.setStyleSheet(
            f"QLabel {{ background:#24191B; color:{COLORS['danger_text']}; "
            "border:1px solid #6B303A; border-radius:10px; padding:9px 12px; }"
        )

    def _audio_finished(self) -> None:
        thread = self._audio_thread
        self._audio_thread = None
        self._audio_worker = None
        if thread is not None:
            thread.deleteLater()

    def _playback_finished(self) -> None:
        self.play_btn.reset_state()

    def _stop_audio(self) -> None:
        self._audio_generation += 1
        self._playback.stop()
        self.play_btn.reset_state()
        thread = self._audio_thread
        if thread is not None and thread.isRunning():
            thread.requestInterruption()
            thread.quit()

    def hideEvent(self, event) -> None:
        self._stop_audio()
        super().hideEvent(event)
