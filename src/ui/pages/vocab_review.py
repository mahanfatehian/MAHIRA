from __future__ import annotations

import random
import time
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
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

from core.session import SessionService
from core.audio import PiperModelManager, PronunciationService, PlaybackService
from ui.widgets.audio_button import AudioButton
from ui.widgets.card_widget import CardWidget, VocabCheckPayload
from ui.widgets.special_char_keyboard import SpecialCharKeyboard


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _gender_norm(s: str) -> str:
    s = _norm(s)
    mapping = {"der": "m", "die": "f", "das": "n"}
    return mapping.get(s, s)


class PronunciationWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, service: PronunciationService, text: str) -> None:
        super().__init__()
        self.service = service
        self.text = text

    @Slot()
    def run(self) -> None:
        try:
            wav_path = self.service.generate_wav(self.text)
            self.finished.emit(str(wav_path))
        except Exception as e:
            self.failed.emit(str(e))


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
        try:
            self.pronunciation_service.clear_all_cached_audio()
        except Exception:
            pass

        self.playback_service = PlaybackService(self)
        self.playback_service.started.connect(self._on_playback_started)
        self.playback_service.finished.connect(self._on_playback_finished)
        self.playback_service.failed.connect(self._on_playback_failed)

        self._audio_thread: QThread | None = None
        self._audio_worker: PronunciationWorker | None = None

        self._current_audio_text: str = ""
        self._current_audio_path: str = ""

        self.setObjectName("SentenceReviewPage")
        self.setStyleSheet(
            """
            QWidget#SentenceReviewPage {
                background-color: #0F0F10;
            }

            QLabel {
                color: #E6E6E6;
            }

            QFrame#TopBarCard, QFrame#MainShell, QFrame#EmptyCard, QFrame#AudioCard {
                background-color: #141414;
                border: 1px solid #2A2A2A;
                border-radius: 14px;
            }

            QPushButton {
                background-color: #1B1B1B;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 800;
            }

            QPushButton:hover {
                border: 1px solid #FFFFFF;
                background-color: #232323;
            }

            QPushButton:pressed {
                background-color: #2B2B2B;
            }
            """
        )

        self._build_ui()
        self.audio_button.setEnabled(False)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        top_bar = QFrame()
        top_bar.setObjectName("TopBarCard")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(18, 14, 18, 14)
        top_bar_layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        self.page_title = QLabel("Vocab Review")
        self.page_title.setStyleSheet(
            "color:#FFFFFF; font-size:24px; font-weight:950; border:none;"
        )

        self.page_subtitle = QLabel("Interactive vocabulary practice")
        self.page_subtitle.setStyleSheet(
            "color:#9A9A9A; font-size:12px; font-weight:700; border:none;"
        )

        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)

        top_bar_layout.addLayout(title_col)
        top_bar_layout.addStretch(1)

        self.counter_lbl = QLabel("0 / 0")
        self.counter_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.counter_lbl.setMinimumWidth(70)
        self.counter_lbl.setStyleSheet(
            """
            color:#FFFFFF;
            font-size:13px;
            font-weight:900;
            border:none;
            background-color:#101010;
            border:1px solid #2A2A2A;
            border-radius:10px;
            padding:8px 12px;
            """
        )

        self.start_btn = QPushButton("Start")
        self.stats_btn = QPushButton("Stats")

        self.start_btn.clicked.connect(self._start_session)
        self.stats_btn.clicked.connect(self.go_progress.emit)

        top_bar_layout.addWidget(self.counter_lbl)
        top_bar_layout.addWidget(self.start_btn)
        top_bar_layout.addWidget(self.stats_btn)

        outer.addWidget(top_bar)

        self.main_shell = QFrame()
        self.main_shell.setObjectName("MainShell")
        self.main_shell.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        shell_layout = QVBoxLayout(self.main_shell)
        shell_layout.setContentsMargins(18, 18, 18, 18)
        shell_layout.setSpacing(12)

        self.audio_card = QFrame()
        self.audio_card.setObjectName("AudioCard")
        audio_layout = QHBoxLayout(self.audio_card)
        audio_layout.setContentsMargins(14, 12, 14, 12)
        audio_layout.setSpacing(10)

        self.word_preview = QLabel("")
        self.word_preview.setStyleSheet(
            "color:#FFFFFF; font-size:15px; font-weight:800; border:none;"
        )

        self.audio_button = AudioButton()
        self.audio_button.clicked.connect(self._play_current_word_pronunciation)

        self.audio_status = QLabel("")
        self.audio_status.setStyleSheet(
            "color:#9A9A9A; font-size:12px; font-weight:700; border:none;"
        )

        audio_layout.addWidget(self.word_preview)
        audio_layout.addStretch(1)
        audio_layout.addWidget(self.audio_button)
        audio_layout.addWidget(self.audio_status)

        self.special_kbd = SpecialCharKeyboard()
        self.special_kbd.setVisible(False)

        self.card = CardWidget()
        self.card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.special_kbd.char_clicked.connect(self.card.insert_special_char)
        self.card.check_clicked.connect(self._on_check)
        self.card.rated.connect(self._on_rated)
        self.card.tip_clicked.connect(self._on_tip)
        self.card.gender_tip_clicked.connect(self._on_gender_tip)
        self.card.skipped.connect(self._on_skipped)

        shell_layout.addWidget(self.audio_card, 0)
        shell_layout.addWidget(self.special_kbd, 0)
        shell_layout.addWidget(self.card, 1)

        outer.addWidget(self.main_shell, 1)

        self.empty_card = QFrame()
        self.empty_card.setObjectName("EmptyCard")
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(30, 28, 30, 28)
        empty_layout.setSpacing(8)

        self.empty_title = QLabel("No vocabulary reviews available.")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet(
            "color:#FFFFFF; font-size:22px; font-weight:950; border:none;"
        )

        self.empty_desc = QLabel("Choose a level and start a vocab session.")
        self.empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_desc.setStyleSheet(
            "color:#9A9A9A; font-size:13px; font-weight:700; border:none;"
        )

        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_desc)
        empty_layout.addStretch(1)

        self.empty_card.hide()
        outer.addWidget(self.empty_card, 1)

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
            self.card.set_helper("Go to Home and select language, level, and objective.")
            self.card.configure_fields(ask_gender=False, ask_plural=False)
            self.card.lock_after_check()

            self.word_preview.setText("")
            self.audio_status.setText("")
            self.audio_button.setEnabled(False)

            self._show_empty(
                "No vocabulary reviews available.",
                "Choose language, level, and objective first.",
            )
            self._update_counter()
            return

        self._show_main()

        if hasattr(self.session, "remaining") and callable(self.session.remaining):
            try:
                if self.session.remaining() == 0 and hasattr(self.session, "start_new_session"):
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
            self.card.set_helper("Go to language, level, then objective.")
            self.card.configure_fields(False, False)
            self.card.lock_after_check()

            self.word_preview.setText("")
            self.audio_status.setText("")
            self.audio_button.setEnabled(False)

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
                ids = self.session.repo.pick_session_vocab_ids(deck_id, limit, mode="mixed")
                self._fallback_ids = list(ids)
                return
            except Exception:
                pass

        with self.session.repo._conn() as conn:
            rows = conn.execute("SELECT id FROM vocab WHERE deck_id=?", (deck_id,)).fetchall()
            all_ids = [int(r["id"]) for r in rows]
            random.shuffle(all_ids)
            self._fallback_ids = all_ids[:limit]

    def _update_counter(self) -> None:
        if hasattr(self.session, "remaining") and callable(self.session.remaining):
            try:
                remaining = int(self.session.remaining())
                limit = int(getattr(getattr(self.session, "plan", None), "limit", 0) or 0)
                completed = max(0, limit - remaining) if limit > 0 else 0

                if limit > 0:
                    shown = min(limit, completed + 1) if remaining > 0 else completed
                    self.counter_lbl.setText(f"{shown} / {limit}")
                else:
                    self.counter_lbl.setText(f"{completed} / ?")
                return
            except Exception:
                pass

        fallback_total = len(self._fallback_ids)
        self.counter_lbl.setText(f"{fallback_total} / {fallback_total if fallback_total else '?'}")

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

    def _clear_current_audio_cache(self) -> None:
        self.playback_service.stop()

        deleted = False

        if self._current_audio_path:
            deleted = self.pronunciation_service.delete_cached_file(self._current_audio_path)

        if not deleted and self._current_audio_text:
            self.pronunciation_service.delete_cached_audio(self._current_audio_text)

        self._current_audio_text = ""
        self._current_audio_path = ""

    def _load_next(self) -> None:
        self.playback_service.stop()
        self.audio_status.setText("")
        self.audio_button.set_busy(False)

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
            self.card.set_example_de_visible_en_blurred("", None)
            self.card.set_gender_tip(None)
            self.card.configure_fields(ask_gender=False, ask_plural=False)
            self.card.set_helper("Click Start to practice another set.")
            self.card.lock_after_check()

            self.word_preview.setText("")
            self.audio_status.setText("")
            self.audio_button.setEnabled(False)

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

        self.word_preview.setText(word)
        self.audio_status.setText("")
        self.audio_button.setEnabled(bool(word))

        pos = (getattr(item, "pos", "") or "").lower()

        tip_text = getattr(item, "gender_tip", None)
        if pos != "noun":
            tip_text = None

        self.card.set_gender_tip(tip_text)

        ask_gender = pos == "noun" and bool(getattr(item, "gender", None))
        ask_plural = pos == "noun" and bool(getattr(item, "plural", None))

        self.card.configure_fields(
            ask_gender=ask_gender,
            ask_plural=ask_plural,
        )

        if hasattr(self.session.repo, "get_examples"):
            exs = self.session.repo.get_examples(item.id, limit=1)
            if exs:
                self.example_de, self.example_en = exs[0]

        self.card.set_example_de_visible_en_blurred(self.example_de, self.example_en)
        self.card.set_helper("")
        self._update_counter()

    def _check_fields_fallback(self, item, typed_meaning: str, typed_gender: str, typed_plural: str) -> dict:
        expected_meaning = getattr(item, "meaning", "") or ""
        meaning_ok = (_norm(typed_meaning) == _norm(expected_meaning)) if expected_meaning else None

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

    def _on_check(self, typed_meaning: str, typed_gender: str, typed_plural: str) -> None:
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

        response_ms = None if self.card_started_at is None else int((time.time() - self.card_started_at) * 1000)

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
        self._load_next()

    def _play_current_word_pronunciation(self) -> None:
        if not self.current_item:
            return

        word = self._extract_word_for_audio(self.current_item)
        if not word:
            return

        self._current_audio_text = word

        self.playback_service.stop()
        self.audio_button.set_busy(True)
        self.audio_status.setText("Generating...")

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
        self._audio_thread.finished.connect(self._audio_thread.deleteLater)

        self._audio_thread.start()

    @Slot(str)
    def _on_audio_ready(self, wav_path: str) -> None:
        self._current_audio_path = wav_path
        self.audio_button.set_busy(False)
        self.audio_status.setText("Playing...")
        self.playback_service.play_file(wav_path)

    @Slot(str)
    def _on_audio_failed(self, message: str) -> None:
        self.audio_button.set_busy(False)
        self.audio_status.setText("Failed")
        QMessageBox.warning(self, "Pronunciation Error", message)

    @Slot(str)
    def _on_playback_started(self, path: str) -> None:
        self.audio_status.setText("Playing...")

    @Slot()
    def _on_playback_finished(self) -> None:
        self.audio_status.setText("")

    @Slot(str)
    def _on_playback_failed(self, message: str) -> None:
        self.audio_status.setText("Playback failed")
        QMessageBox.warning(self, "Playback Error", message)

    def closeEvent(self, event) -> None:
        try:
            self._clear_current_audio_cache()
        except Exception:
            pass
        super().closeEvent(event)
