from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
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
from ui.widgets.card_widget import CardWidget, VocabCheckPayload
from ui.widgets.special_char_keyboard import SpecialCharKeyboard


def _norm(s: str) -> str:
    return (s or " ").strip().lower()


def _gender_norm(s: str) -> str:
    s = _norm(s)
    mapping = {"der": "m", "die": "f", "das": "n"}
    return mapping.get(s, s)


def _gender_to_article(gender: str | None) -> str | None:
    value = _gender_norm(gender or "")
    mapping = {
        "m": "der",
        "masculine": "der",
        "f": "die",
        "feminine": "die",
        "n": "das",
        "neuter": "das",
    }
    return mapping.get(value)


class PronunciationWorker(QObject):
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
        except Exception as e:
            self.failed.emit(self.text, str(e))


class VocabReviewPage(QWidget):
    go_progress = Signal()

    def __init__(self, session: SessionService, nav=None) -> None:
        super().__init__()

        self.session = session
        self.nav = nav

        self.current_item: Any | None = None
        self.tip_used = False
        self.gender_tip_used = False
        self.was_checked = False
        self.was_skipped = False

        self.typed_meaning = ""
        self.typed_gender = ""
        self.typed_plural = ""

        self.example_de = ""
        self.example_en = None

        self.card_started_at: float | None = None
        self._fallback_ids: list[int] = []

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

        self.setObjectName("VocabReviewPage")
        self.setStyleSheet("VocabReviewPage { background-color: #0E0E0E; }")

        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)

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

        self.page_title = QLabel("Vocab Review")
        self.page_title.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:20px; font-weight:950; border:none; background:transparent; }"
        )

        self.page_subtitle = QLabel("Interactive vocabulary practice")
        self.page_subtitle.setStyleSheet(
            "QLabel { color:#9A9A9A; font-size:11px; font-weight:700; border:none; background:transparent; }"
        )

        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)

        top_bar_layout.addLayout(title_col)
        top_bar_layout.addStretch(1)

        self.counter_lbl = QLabel("0 / 0")
        self.counter_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.counter_lbl.setMinimumWidth(60)
        self.counter_lbl.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:12px; font-weight:800; background:#1A1A1A; border:1px solid #2E2E2E; border-radius:8px; padding:6px 10px; }"
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
            "QLabel { color: #7AE582; font-size: 13px; font-weight: 900; border: none; background: transparent; }"
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

        self.special_kbd = SpecialCharKeyboard()
        self.special_kbd.setVisible(False)
        outer.addWidget(self.special_kbd)

        self.main_shell = QFrame()
        self.main_shell.setObjectName("MainShell")
        self.main_shell.setStyleSheet(
            "QFrame#MainShell { background: transparent; border: none; }"
        )
        self.main_shell.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        shell_layout = QVBoxLayout(self.main_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(10)

        self.card = CardWidget()
        self.card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self.special_kbd.char_clicked.connect(self.card.insert_special_char)

        self.card.check_clicked.connect(self._on_check)
        self.card.rated.connect(self._on_rated)
        self.card.tip_clicked.connect(self._on_tip)
        self.card.gender_tip_clicked.connect(self._on_gender_tip)
        self.card.skipped.connect(self._on_skipped)
        self.card.audio_clicked.connect(self._play_current_word_pronunciation)

        shell_layout.addWidget(self.card)
        outer.addWidget(self.main_shell)

        self.empty_card = QFrame()
        self.empty_card.setObjectName("EmptyCard")
        self.empty_card.setMinimumHeight(420)
        self.empty_card.setStyleSheet(
            "QFrame#EmptyCard { background-color: #141414; border: 1px solid #2A2A2A; border-radius: 14px; }"
        )

        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(8)

        self.empty_title = QLabel("No vocabulary reviews available.")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:18px; font-weight:950; border:none; background:transparent; }"
        )

        self.empty_desc = QLabel("Choose a level and start a vocab session.")
        self.empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_desc.setStyleSheet(
            "QLabel { color:#9A9A9A; font-size:12px; font-weight:700; border:none; background:transparent; }"
        )

        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_desc)
        empty_layout.addStretch(1)

        self.empty_card.hide()
        outer.addWidget(self.empty_card)

        outer.addStretch(1)
        self._update_counter()

    def cleanup_audio_cache_on_startup(self) -> None:
        try:
            self.pronunciation_service.clear_all_cached_audio()
        except Exception:
            pass

    def _show_main(self) -> None:
        self.main_shell.show()
        self.empty_card.hide()

    def _show_empty(self, title: str, desc: str) -> None:
        self.empty_title.setText(title)
        self.empty_desc.setText(desc)
        self.main_shell.hide()
        self.empty_card.show()

    def _on_tip(self) -> None:
        self.tip_used = True

    def _on_gender_tip(self) -> None:
        self.gender_tip_used = True

    def _on_skipped(self) -> None:
        self.was_skipped = True
        self.was_checked = False
        self.typed_meaning = ""
        self.typed_gender = ""
        self.typed_plural = ""

    def _active_deck_id(self) -> int | None:
        if hasattr(self.session, "active_deck_id"):
            try:
                return self.session.active_deck_id()
            except Exception:
                return None

        lang = getattr(self.session.state, "language_code", None)
        level = getattr(self.session.state, "level", None)
        obj = getattr(self.session.state, "objective", None) or "vocab"

        if not lang or not level:
            return None

        if hasattr(self.session.repo, "get_deck_id"):
            return self.session.repo.get_deck_id(lang, level, obj)

        return None

    def on_show(self) -> None:
        lang = getattr(self.session.state, "language_code", "de") or "de"
        self.special_kbd.set_language(lang)

        deck_id = self._active_deck_id()

        if not deck_id:
            self.card.reset_for_next()
            self.card.set_prompt("Choose level first")
            self.card.set_meaning_blurred(None)
            self.card.set_example_blurred(None, None)
            self.card.set_gender_tip(None)
            self.card.configure_fields(ask_gender=False, ask_plural=False)
            self.card.lock_after_check()
            self._show_empty(
                "No vocabulary reviews available.",
                "Choose language, level, and objective first.",
            )
            self._update_counter()
            return

        self._show_main()

        if hasattr(self.session, "remaining") and callable(self.session.remaining):
            try:
                if self.session.remaining() == 0 and hasattr(
                    self.session,
                    "start_new_session",
                ):
                    self.session.start_new_session()
            except Exception:
                pass
        else:
            self._build_fallback_session(deck_id)

        self._load_next()

    def _start_session(self) -> None:
        deck_id = self._active_deck_id()

        if not deck_id:
            self.card.reset_for_next()
            self.card.set_prompt("Choose level first")
            self.card.set_meaning_blurred(None)
            self.card.set_example_blurred(None, None)
            self.card.set_gender_tip(None)
            self.card.configure_fields(False, False)
            self.card.lock_after_check()
            self._show_empty(
                "No vocabulary reviews available.",
                "Choose language, level, and objective first.",
            )
            self._update_counter()
            return

        self._show_main()

        if hasattr(self.session, "start_new_session"):
            ok = self.session.start_new_session()
            if not ok:
                self._build_fallback_session(deck_id)
        else:
            self._build_fallback_session(deck_id)

        self._load_next()

    def _build_fallback_session(self, deck_id: int) -> None:
        limit = 10

        if hasattr(self.session, "plan") and hasattr(self.session.plan, "limit"):
            try:
                limit = int(self.session.plan.limit)
            except Exception:
                pass

        if hasattr(self.session.repo, "pick_session_vocab_ids"):
            try:
                ids = self.session.repo.pick_session_vocab_ids(
                    deck_id,
                    limit,
                    mode="mixed",
                )
                self._fallback_ids = list(ids)
                return
            except Exception:
                pass

        with self.session.repo._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM vocab WHERE deck_id=?",
                (deck_id,),
            ).fetchall()
            all_ids = [int(r["id"]) for r in rows]
            random.shuffle(all_ids)
            self._fallback_ids = all_ids[:limit]

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
            "QLabel { color:#FFD700; font-size:12px; font-weight:800; "
            "background:#2A2000; border:1px solid #FFD700; border-radius:8px; padding:6px 10px; }"
        )
        self.milestone_bar.show()
        QTimer.singleShot(6000, self._dismiss_milestone_banner)
        self._update_counter()

    def _dismiss_milestone_banner(self) -> None:
        self.milestone_bar.hide()
        self.counter_lbl.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:12px; font-weight:800; "
            "background:#1A1A1A; border:1px solid #2E2E2E; border-radius:8px; padding:6px 10px; }"
        )

    def _next_item_any_api(self):
        for name in ("next_item", "next_vocab", "next"):
            fn = getattr(self.session, name, None)
            if callable(fn):
                return fn()
        return None

    def _extract_word_for_audio(self, item: Any) -> str:
        if not item:
            return ""

        word = getattr(item, "word", "") or ""

        if hasattr(self.session, "prompt_text"):
            try:
                prompt = self.session.prompt_text(item)
                if isinstance(prompt, str) and prompt.strip():
                    word = prompt.strip()
            except Exception:
                pass

        return word.strip()

    def _build_gender_tip(self, item: Any) -> str | None:
        pos = (getattr(item, "pos", "") or "").strip().lower()
        if pos != "noun":
            return None

        custom_tip = getattr(item, "gender_tip", None)
        if custom_tip and str(custom_tip).strip():
            return str(custom_tip).strip()

        article = _gender_to_article(getattr(item, "gender", None))
        word = self._extract_word_for_audio(item)

        if article and word:
            return f"This noun uses the article: {article} {word}."

        if article:
            return f"This noun uses the article: {article}."

        return "This is a noun, so pay attention to its article: der / die / das."

    def _clear_current_audio_cache(self) -> None:
        self.playback_service.stop()

        deleted = False

        if self._current_audio_path:
            deleted = self.pronunciation_service.delete_cached_file(
                self._current_audio_path
            )

        if not deleted and self._current_audio_text:
            self.pronunciation_service.delete_cached_audio(self._current_audio_text)

        self._current_audio_text = ""
        self._current_audio_path = ""

        self.card.set_audio_busy(False)
        self.card.set_audio_playing(False)

    def _load_next(self) -> None:
        self.playback_service.stop()

        self._current_audio_text = ""
        self._current_audio_path = ""

        self._update_counter()

        self.current_item = self._next_item_any_api()

        if self.current_item is None and self._fallback_ids:
            vid = self._fallback_ids.pop(0)
            if hasattr(self.session.repo, "get_vocab_by_id"):
                self.current_item = self.session.repo.get_vocab_by_id(vid)

        self.tip_used = False
        self.gender_tip_used = False
        self.was_checked = False
        self.was_skipped = False

        self.typed_meaning = ""
        self.typed_gender = ""
        self.typed_plural = ""

        self.example_de = ""
        self.example_en = None

        self.card.reset_for_next()

        if not self.current_item:
            self.card.set_prompt("Session finished")
            self.card.set_meaning_blurred(None)
            self.card.set_example_blurred(None, None)
            self.card.set_gender_tip(None)
            self.card.configure_fields(ask_gender=False, ask_plural=False)
            self.card.lock_after_check()
            self._show_empty(
                "No vocabulary reviews available.",
                "Start a new session to practice another set.",
            )
            self._update_counter()
            return

        self._show_main()
        self.card_started_at = time.time()

        item = self.current_item
        word = self._extract_word_for_audio(item)

        self.card.set_prompt(word)
        self.card.set_pos(getattr(item, "pos", ""))
        self.card.set_audio_enabled(bool(word))
        self.card.set_audio_busy(False)
        self.card.set_audio_playing(False)

        pos = (getattr(item, "pos", "") or "").lower()

        ask_gender = pos == "noun" and bool(getattr(item, "gender", None))
        ask_plural = pos == "noun" and bool(getattr(item, "plural", None))
        self.card.configure_fields(ask_gender=ask_gender, ask_plural=ask_plural)

        self.card.set_meaning_blurred(getattr(item, "meaning", None))

        if hasattr(self.session.repo, "get_examples"):
            try:
                exs = self.session.repo.get_examples(item.id, limit=1)
                if exs:
                    self.example_de, self.example_en = exs[0]
            except Exception:
                self.example_de = ""
                self.example_en = None

        self.card.set_example_blurred(self.example_de, self.example_en)
        self.card.set_gender_tip(self._build_gender_tip(item))

        self._update_counter()

    def _check_fields_fallback(
        self,
        item,
        typed_meaning: str,
        typed_gender: str,
        typed_plural: str,
    ) -> dict:
        expected_meaning = getattr(item, "meaning", "") or ""
        meaning_ok = (
            _norm(typed_meaning) == _norm(expected_meaning)
        ) if expected_meaning else None

        expected_gender = _gender_norm(getattr(item, "gender", "") or "")
        typed_g = _gender_norm(typed_gender or "")
        gender_ok = (typed_g == expected_gender) if expected_gender else None

        expected_plural = _norm(getattr(item, "plural", "") or "")
        typed_p = _norm(typed_plural or "")
        plural_ok = (typed_p == expected_plural) if expected_plural else None

        return {
            "meaning_ok": meaning_ok,
            "expected_meaning": expected_meaning,
            "gender_ok": gender_ok,
            "expected_gender": expected_gender or None,
            "plural_ok": plural_ok,
            "expected_plural": expected_plural or None,
        }

    def _on_check(
        self,
        typed_meaning: str,
        typed_gender: str,
        typed_plural: str,
    ) -> None:
        if not self.current_item:
            return

        self.was_checked = True
        self.was_skipped = False

        self.typed_meaning = typed_meaning or ""
        self.typed_gender = typed_gender or ""
        self.typed_plural = typed_plural or ""

        if hasattr(self.session, "check_vocab_fields"):
            try:
                res = self.session.check_vocab_fields(
                    self.current_item,
                    self.typed_meaning,
                    self.typed_gender,
                    self.typed_plural,
                )
            except Exception:
                res = self._check_fields_fallback(
                    self.current_item,
                    self.typed_meaning,
                    self.typed_gender,
                    self.typed_plural,
                )
        else:
            res = self._check_fields_fallback(
                self.current_item,
                self.typed_meaning,
                self.typed_gender,
                self.typed_plural,
            )

        payload = VocabCheckPayload(
            meaning_ok=res.get("meaning_ok"),
            expected_meaning=res.get("expected_meaning"),
            typed_meaning=self.typed_meaning,
            gender_ok=res.get("gender_ok"),
            expected_gender=res.get("expected_gender"),
            typed_gender=self.typed_gender,
            plural_ok=res.get("plural_ok"),
            expected_plural=res.get("expected_plural"),
            typed_plural=self.typed_plural,
            meaning_label="Meaning",
        )

        self.card.apply_check_results(payload)
        self.card.lock_after_check()

    def _on_rated(self, rating: int) -> None:
        if not self.current_item:
            return

        response_ms = None
        if self.card_started_at is not None:
            response_ms = int((time.time() - self.card_started_at) * 1000)

        if hasattr(self.session, "submit_vocab"):
            try:
                self.session.submit_vocab(
                    item=self.current_item,
                    typed_meaning=self.typed_meaning,
                    typed_gender=self.typed_gender,
                    typed_plural=self.typed_plural,
                    rating=rating,
                    tip_used=self.tip_used,
                    gender_tip_used=self.gender_tip_used,
                    was_checked=self.was_checked,
                    was_skipped=self.was_skipped,
                    response_ms=response_ms,
                )
            except Exception:
                pass

        self._clear_current_audio_cache()

        milestone_hit = False
        if hasattr(self.session, "record_item_answered"):
            try:
                milestone_hit = bool(self.session.record_item_answered())
            except Exception:
                pass

        self._load_next()

        if milestone_hit:
            self._show_milestone_banner()

    def _play_current_word_pronunciation(self) -> None:
        if not self.current_item:
            return

        if self._audio_thread is not None and self._audio_thread.isRunning():
            return

        word = self._extract_word_for_audio(self.current_item)

        if not word:
            self.card.set_audio_enabled(False)
            self.card.set_audio_busy(False)
            self.card.set_audio_playing(False)
            return

        if self._current_audio_text == word and self._current_audio_path:
            cached_path = Path(self._current_audio_path)
            if cached_path.exists():
                self.playback_service.stop()
                self.card.set_audio_busy(True)
                self.card.set_audio_playing(False)
                self.playback_service.play_file(cached_path)
                return

        self._current_audio_text = word
        self._current_audio_path = ""

        self.playback_service.stop()

        self.card.set_audio_enabled(True)
        self.card.set_audio_busy(True)
        self.card.set_audio_playing(False)

        self._audio_thread = QThread(self)
        self._audio_worker = PronunciationWorker(
            service=self.pronunciation_service,
            text=word,
        )
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
            self.card.set_audio_busy(False)
            self.card.set_audio_playing(False)
            return

        self._current_audio_path = wav_path

        self.card.set_audio_enabled(True)
        self.card.set_audio_busy(True)
        self.card.set_audio_playing(False)

        self.playback_service.play_file(wav_path)

    @Slot(str, str)
    def _on_audio_failed(self, text: str, message: str) -> None:
        if text == self._current_audio_text:
            self.card.set_audio_enabled(True)
            self.card.set_audio_busy(False)
            self.card.set_audio_playing(False)

        QMessageBox.warning(self, "Pronunciation Error", message)

    @Slot()
    def _on_audio_thread_finished(self) -> None:
        self._audio_thread = None
        self._audio_worker = None

    @Slot(str)
    def _on_playback_started(self, path: str) -> None:
        self.card.set_audio_busy(False)
        self.card.set_audio_playing(True)

    @Slot()
    def _on_playback_finished(self) -> None:
        self.card.set_audio_busy(False)
        self.card.set_audio_playing(False)

    @Slot(str)
    def _on_playback_failed(self, message: str) -> None:
        self.card.set_audio_busy(False)
        self.card.set_audio_playing(False)
        QMessageBox.warning(self, "Playback Error", message)

    def closeEvent(self, event) -> None:
        try:
            self._clear_current_audio_cache()
        except Exception:
            pass

        super().closeEvent(event)