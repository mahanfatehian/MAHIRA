from __future__ import annotations

import random
import re
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.audio import PiperModelManager, PlaybackService, PronunciationService
from core.session import SessionService
from ui.widgets.sentence_builder_widget import SentenceBuilderWidget


class PronunciationWorker(QObject):
    """Synthesizes the target sentence to a cached WAV off the UI thread."""

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
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            self.failed.emit(self.text, str(e))


class SentenceReviewPage(QWidget):
    go_progress = Signal()

    def __init__(self, session: SessionService, nav=None) -> None:
        super().__init__()
        self.session = session
        self.nav = nav

        self.current_item: Any = None
        self.tip_used = False
        self.translation_used = False
        self.was_checked = False
        self.was_skipped = False
        self.card_started_at = 0.0

        # Audio: hear the correct German sentence once it's revealed.
        self.model_manager = PiperModelManager()
        self.pronunciation_service = PronunciationService(self.model_manager)
        self.playback_service = PlaybackService(self)
        self.playback_service.started.connect(self._on_playback_started)
        self.playback_service.finished.connect(self._on_playback_finished)
        self.playback_service.failed.connect(self._on_playback_failed)
        self._audio_thread: QThread | None = None
        self._audio_worker: PronunciationWorker | None = None
        self._current_audio_text: str = ""
        self._current_audio_path: str = ""

        self.setObjectName("SentenceReviewPage")
        self.setStyleSheet("SentenceReviewPage { background-color: #0E0E0E; }")

        self._build_ui()

        self._undo_sc = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._undo_sc.activated.connect(self._on_undo)

        # Keyboard rating: 1/2/3/4 = Again/Hard/Good/Easy, active only after a
        # sentence has been checked (the builder has no free-text input).
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
        if self.current_item is None:
            return
        self._on_rated(int(rating))

    def set_focus_mode(self, on: bool) -> None:
        """Focus/Zen mode: hide this tab's own top bar."""
        try:
            self.top_bar.setVisible(not bool(on))
        except Exception:
            pass

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)

        # Top bar - compact
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

        self.page_title = QLabel("Sentence Review")
        self.page_title.setStyleSheet(
            "color:#FFFFFF; font-size:20px; font-weight:950; border:none;"
        )

        self.page_subtitle = QLabel("Interactive language construction")
        self.page_subtitle.setStyleSheet(
            "color:#9A9A9A; font-size:11px; font-weight:700; border:none;"
        )

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

        self.top_bar = top_bar
        outer.addWidget(top_bar)

        # Milestone celebration banner (hidden by default)
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
        self.milestone_lbl.setStyleSheet(
            "QLabel { color: #7AE582; font-size: 13px; font-weight: 900; border: none; }"
        )
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

        # Main content - compact
        self.main_shell = QFrame()
        self.main_shell.setObjectName("MainShell")
        self.main_shell.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        shell_layout = QVBoxLayout(self.main_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(10)

        self.card = SentenceBuilderWidget(accent="#FFB020")
        self.card.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.card.check_clicked.connect(self._on_check)
        self.card.rated.connect(self._on_rated)
        self.card.tip_clicked.connect(self._on_tip)
        self.card.translation_clicked.connect(self._on_translation)
        self.card.skipped.connect(self._on_skipped)
        self.card.audio_clicked.connect(self._play_target_audio)

        shell_layout.addWidget(self.card)

        outer.addWidget(self.main_shell, 1)

        # Empty state
        self.empty_card = QFrame()
        self.empty_card.setObjectName("EmptyCard")
        self.empty_card.setStyleSheet(
            "QFrame#EmptyCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 14px; }"
        )
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)

        self.empty_title = QLabel("No sentence reviews available.")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet(
            "color:#FFFFFF; font-size:18px; font-weight:950; border:none;"
        )

        self.empty_desc = QLabel("Start learning or import sentence decks.")
        self.empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_desc.setStyleSheet(
            "color:#9A9A9A; font-size:12px; font-weight:700; border:none;"
        )

        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_desc)
        empty_layout.addStretch(1)

        self.empty_card.hide()
        outer.addWidget(self.empty_card, 1)

        outer.addStretch(1)

        self._update_counter()

    def on_show(self) -> None:
        self.page_subtitle.setText(self.session.context_label() or "Interactive language construction")
        if self.session.remaining() == 0:
            self._start_session()
            return
        self._load_next()

    def _start_session(self) -> None:
        self.session.start_new_session()
        self._load_next()

    def _update_counter(self) -> None:
        try:
            answered, milestone = self.session.study_progress()
            self.counter_lbl.setText(f"{answered} / {milestone}")
        except Exception:
            self.counter_lbl.setText("0 / 30")

    def _show_milestone_banner(self) -> None:
        answered = getattr(self.session, "study_answered", 0)
        self.milestone_lbl.setText(
            f"Milestone! {answered} items reviewed this session. Keep going!"
        )
        self.counter_lbl.setStyleSheet(
            "color:#FFD700; font-size:12px; font-weight:800; "
            "background:#2A2000; border:1px solid #FFD700; border-radius:8px; padding:6px 10px;"
        )
        self.milestone_bar.show()
        QTimer.singleShot(6000, self._dismiss_milestone_banner)
        self._update_counter()

    def _dismiss_milestone_banner(self) -> None:
        self.milestone_bar.hide()
        self.counter_lbl.setStyleSheet(
            "color:#FFFFFF; font-size:12px; font-weight:800; "
            "background:#1A1A1A; border:1px solid #2E2E2E; border-radius:8px; padding:6px 10px;"
        )

    def _normalize_sentence(self, text: str) -> str:
        text = str(text or "").strip()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s+([.,!?;:])", r"\1", text)
        text = re.sub(r'([\(\[\{„"“])\s+', r"\1", text)
        text = re.sub(r'\s+([\)\]\}»"”])', r"\1", text)
        text = re.sub(r"\s+'\s*", "'", text)
        return text.strip()

    def _extract_expected_sentence(self, item: Any) -> str:
        for attr in ("target_text", "sentence", "text"):
            value = getattr(item, attr, None)
            if value:
                return self._normalize_sentence(str(value))
        return ""

    def _extract_words(self, item: Any) -> list[str]:
        words = getattr(item, "words", None)

        if isinstance(words, list):
            result = [str(w) for w in words if str(w).strip()]
            if result:
                return result

        if isinstance(words, str) and words.strip():
            if "|" in words:
                result = [part.strip() for part in words.split("|") if part.strip()]
                if result:
                    return result
            result = [part for part in words.split() if part.strip()]
            if result:
                return result

        words_json = getattr(item, "words_json", None)
        if isinstance(words_json, str) and words_json.strip():
            if "|" in words_json:
                result = [part.strip() for part in words_json.split("|") if part.strip()]
                if result:
                    return result

        expected = self._extract_expected_sentence(item)
        if expected:
            if "|" in expected:
                return [part.strip() for part in expected.split("|") if part.strip()]
            return expected.split()

        return []

    def _extract_tip(self, item: Any) -> str | None:
        for attr in ("tip", "hint"):
            value = getattr(item, attr, None)
            if value:
                return str(value)
        return None

    def _extract_translation(self, item: Any) -> str | None:
        for attr in ("translation", "translation_en", "english", "meaning"):
            value = getattr(item, attr, None)
            if value:
                return str(value)
        return None

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
        self._cleanup_audio(delete=True)
        self._set_rating_keys_enabled(False)
        self._update_counter()
        self.current_item = self.session.next_sentence_item()

        self.tip_used = False
        self.translation_used = False
        self.was_checked = False
        self.was_skipped = False

        self.card.reset_for_next()

        if not self.current_item:
            self.main_shell.hide()
            self.empty_card.show()
            self.card.lock_after_finish("Session finished")
            self._update_counter()
            return

        self.main_shell.show()
        self.empty_card.hide()

        self.card_started_at = time.time()

        words = self._extract_words(self.current_item)
        random.shuffle(words)

        tip = self._extract_tip(self.current_item)
        translation = self._extract_translation(self.current_item)

        self.card.set_item(
            words=words,
            tip=tip,
            translation=translation,
        )
        self._update_counter()

    def _on_tip(self) -> None:
        self.tip_used = True

    def _on_translation(self) -> None:
        self.translation_used = True

    def _on_skipped(self) -> None:
        self.was_skipped = True
        self.was_checked = False
        self._on_rated(0)

    def _on_check(self, typed_text: str) -> None:
        if not self.current_item:
            return

        self.was_checked = True

        expected = self._extract_expected_sentence(self.current_item)
        typed_norm = self._normalize_sentence(typed_text)
        expected_norm = self._normalize_sentence(expected)

        ok = typed_norm == expected_norm

        details: list[str] = []

        if not ok:
            typed_compact = re.sub(r"\s+", " ", typed_norm)
            expected_compact = re.sub(r"\s+", " ", expected_norm)

            if typed_compact == expected_compact:
                details.append("Spacing needs attention.")
            else:
                typed_lower = typed_norm.lower()
                expected_lower = expected_norm.lower()

                if typed_lower == expected_lower:
                    details.append("Capitalization needs attention.")
                else:
                    typed_no_punct = re.sub(r"[.,!?;:]", "", typed_lower)
                    expected_no_punct = re.sub(r"[.,!?;:]", "", expected_lower)

                    if typed_no_punct == expected_no_punct:
                        details.append("Punctuation needs attention.")
                    else:
                        typed_words = typed_no_punct.split()
                        expected_words = expected_no_punct.split()
                        if sorted(typed_words) == sorted(expected_words) and typed_words != expected_words:
                            details.append("Word order needs attention.")

        self.card.show_result(
            ok=ok,
            expected=expected_norm,
            details=" ".join(details),
        )
        self._set_rating_keys_enabled(True)
        try:
            self.card.set_rating_intervals(
                self.session.sentence_interval_labels(self.current_item)
            )
        except Exception:
            pass

    def _on_rated(self, rating: int) -> None:
        if not self.current_item:
            return

        typed = self._normalize_sentence(self.card.typed_text())
        response_ms = int(
            max(0.0, time.time() - float(self.card_started_at or time.time())) * 1000
        )

        self.session.submit_sentence(
            item=self.current_item,
            typed_text=typed,
            rating=int(rating),
            tip_used=bool(self.tip_used),
            translation_used=bool(self.translation_used),
            was_checked=bool(self.was_checked),
            was_skipped=bool(self.was_skipped),
            response_ms=response_ms,
        )

        milestone_hit = False
        if hasattr(self.session, "record_item_answered"):
            try:
                milestone_hit = bool(self.session.record_item_answered())
            except Exception:
                pass

        self._load_next()

        if milestone_hit:
            self._show_milestone_banner()

    # ----------------------------------------------------------------- audio
    def _play_target_audio(self) -> None:
        if not self.current_item:
            return
        text = self._extract_expected_sentence(self.current_item)
        if not text:
            self.card.audio_btn.set_available(False)
            return

        # Spam guard: ignore while a synthesis is in flight.
        if self._audio_thread is not None and self._audio_thread.isRunning():
            return

        # Reuse the exact cached clip if we already have it.
        if (self._current_audio_text == text and self._current_audio_path
                and Path(self._current_audio_path).exists()):
            self.playback_service.stop()
            self.card.audio_btn.set_busy(True)
            self.playback_service.play_file(self._current_audio_path)
            return

        self._current_audio_text = text
        self._current_audio_path = ""
        self.playback_service.stop()
        self.card.audio_btn.set_available(True)
        self.card.audio_btn.set_busy(True)

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
        if text != self._current_audio_text:
            self.card.audio_btn.set_busy(False)
            return
        self._current_audio_path = wav_path
        if not self.isVisible():
            self.card.audio_btn.set_busy(False)
            return
        self.card.audio_btn.set_busy(True)
        self.playback_service.play_file(wav_path)

    @Slot(str, str)
    def _on_audio_failed(self, text: str, message: str) -> None:
        # Ignore failures for a request the user has already moved past, so a
        # late error never throws a modal over the next sentence.
        if text != self._current_audio_text:
            return
        self.card.audio_btn.set_busy(False)
        self.card.audio_btn.set_playing(False)
        if self.isVisible():
            QMessageBox.warning(self, "Pronunciation Error", message)

    @Slot()
    def _on_audio_thread_finished(self) -> None:
        self._audio_thread = None
        self._audio_worker = None

    @Slot(str)
    def _on_playback_started(self, path: str) -> None:
        self.card.audio_btn.set_busy(False)
        self.card.audio_btn.set_playing(True)

    @Slot()
    def _on_playback_finished(self) -> None:
        self.card.audio_btn.set_busy(False)
        self.card.audio_btn.set_playing(False)

    @Slot(str)
    def _on_playback_failed(self, message: str) -> None:
        self.card.audio_btn.set_busy(False)
        self.card.audio_btn.set_playing(False)

    def _cleanup_audio(self, *, delete: bool) -> None:
        self.playback_service.stop()
        if delete:
            if self._current_audio_path:
                try:
                    self.pronunciation_service.delete_cached_file(self._current_audio_path)
                except Exception:
                    pass
            elif self._current_audio_text:
                try:
                    self.pronunciation_service.delete_cached_audio(self._current_audio_text)
                except Exception:
                    pass
            self._current_audio_text = ""
            self._current_audio_path = ""
        try:
            self.card.audio_btn.set_busy(False)
            self.card.audio_btn.set_playing(False)
        except Exception:
            pass

    def hideEvent(self, event) -> None:
        try:
            self.playback_service.stop()
            self.card.audio_btn.set_busy(False)
            self.card.audio_btn.set_playing(False)
        except Exception:
            pass
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        try:
            self._cleanup_audio(delete=True)
        except Exception:
            pass
        super().closeEvent(event)