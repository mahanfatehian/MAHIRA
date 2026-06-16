"""Blitz — the game tab.

A fast connect-the-pairs round played over the current Lektion's vocab: article
to noun, noun to plural, word to meaning. Correct connects build a combo and
score with arcade SFX; a correct connect also speaks the German word (offline
TTS, pre-cached in the background) so the ear learns too. The personal best is
saved per Lektion and surfaced on the Blitz card in the objective selector.

This page owns the chrome (top-bar HUD, intro/end screens, audio) and delegates
the play field to GameBoard and the rules to core.game.*.
"""

from __future__ import annotations

import random
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.audio import PiperModelManager, PlaybackService, PronunciationService
from core.audio.sfx import SfxEngine
from core.game import build_pairs, make_waves
from core.session import SessionService
from ui.widgets.game_board import GameBoard

_ACCENT = "#FF4D6D"  # Blitz red/pink — distinct from the four study objectives.
_ROUND_SECONDS = 60


class _PrecacheWorker(QObject):
    """Warms the TTS cache for the round's words off the UI thread, so speaking a
    word on a correct connect is instant (or silently skipped if not ready)."""

    done = Signal()

    def __init__(self, service: PronunciationService, words: list[str]) -> None:
        super().__init__()
        self.service = service
        self.words = list(words)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    @Slot()
    def run(self) -> None:
        for w in self.words:
            if self._stop:
                break
            try:
                self.service.generate_wav(w)
            except Exception:
                pass
        self.done.emit()


class GamePage(QWidget):
    go_progress = Signal()

    def __init__(self, session: SessionService, nav=None) -> None:
        super().__init__()
        self.session = session
        self.nav = nav

        self._deck_id: int | None = None
        self._best: dict = {"best_score": 0, "best_combo": 0, "plays": 0}
        self._audio_on = True

        # Arcade SFX (synthesized, offline; built lazily on first play so it never
        # taxes app startup) + word TTS (reuses the app's Piper).
        self.sfx: SfxEngine | None = None
        self.model_manager = PiperModelManager()
        self.pronunciation_service = PronunciationService(self.model_manager)
        self.tts = PlaybackService(self)
        self.tts.started.connect(self._on_tts_started)
        self.tts.finished.connect(self._on_tts_done)
        self.tts.failed.connect(self._on_tts_done)
        self._tts_busy = False
        # Watchdog: if neither finished nor failed ever arrives (e.g. stop() lands
        # in the 40 ms window before playback starts), self-clear so speech isn't
        # silenced for the rest of the session.
        self._tts_guard = QTimer(self)
        self._tts_guard.setSingleShot(True)
        self._tts_guard.timeout.connect(self._on_tts_done)

        self._precache_thread: QThread | None = None
        self._precache_worker: _PrecacheWorker | None = None
        self._orphans: list[QThread] = []

        self.setObjectName("GamePage")
        self.setStyleSheet("GamePage { background-color: #0C0C0C; }")
        self._build_ui()

    # -------------------------------------------------------------- audio glue
    def _ensure_sfx(self) -> SfxEngine:
        if self.sfx is None:
            self.sfx = SfxEngine(self)
            self.sfx.set_muted(not self._audio_on)
        return self.sfx

    @Slot()
    def _on_tts_started(self, *args) -> None:
        self._tts_busy = True

    @Slot()
    def _on_tts_done(self, *args) -> None:
        self._tts_busy = False
        self._tts_guard.stop()

    def _stop_tts(self) -> None:
        self._on_tts_done()
        try:
            self.tts.stop()
        except Exception:
            pass

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)

        outer.addWidget(self._build_top_bar())

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.stack.addWidget(self._build_intro())   # 0
        self.stack.addWidget(self._build_play())     # 1
        self.stack.addWidget(self._build_end())      # 2
        outer.addWidget(self.stack, 1)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBarCard")
        bar.setStyleSheet(
            "QFrame#TopBarCard { background-color:#141414; border:1px solid #2A2A2A; border-radius:14px; }"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        col = QVBoxLayout()
        col.setSpacing(1)
        title = QLabel("Blitz ⚡")
        title.setStyleSheet(f"color:{_ACCENT}; font-size:20px; font-weight:950; border:none;")
        self.subtitle = QLabel("Connect the pairs — fast")
        self.subtitle.setStyleSheet("color:#9A9A9A; font-size:11px; font-weight:700; border:none;")
        col.addWidget(title)
        col.addWidget(self.subtitle)
        lay.addLayout(col)
        lay.addStretch(1)

        self.time_lbl = self._chip("⏱ 60")
        self.score_lbl = self._chip("0")
        self.combo_lbl = self._chip("x0")
        self.best_lbl = self._chip("Best 0")
        for c in (self.time_lbl, self.score_lbl, self.combo_lbl, self.best_lbl):
            lay.addWidget(c)

        self.audio_btn = QPushButton("🔊")
        self.audio_btn.setFixedSize(38, 32)
        self.audio_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.audio_btn.setStyleSheet(self._tool_btn_style())
        self.audio_btn.clicked.connect(self._toggle_audio)
        lay.addWidget(self.audio_btn)

        self.stats_btn = QPushButton("Stats")
        self.stats_btn.setFixedWidth(60)
        self.stats_btn.setStyleSheet(
            "QPushButton { background-color:#163A5C; color:#FFFFFF; border:1px solid #24537D; "
            "border-radius:10px; padding:8px; font-weight:900; font-size:12px; }"
            "QPushButton:hover { background-color:#1B4B78; border:1px solid #FFFFFF; }"
        )
        self.stats_btn.clicked.connect(self.go_progress.emit)
        lay.addWidget(self.stats_btn)

        self.top_bar = bar
        return bar

    def _chip(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setMinimumWidth(58)
        lbl.setStyleSheet(
            "color:#FFFFFF; font-size:12px; font-weight:800; background:#1A1A1A; "
            "border:1px solid #2E2E2E; border-radius:8px; padding:6px 10px;"
        )
        return lbl

    def _tool_btn_style(self) -> str:
        return (
            "QPushButton { background-color:#1B1B1B; color:#FFFFFF; border:1px solid #2E2E2E; "
            "border-radius:9px; font-size:15px; font-weight:900; }"
            "QPushButton:hover { background-color:#232323; border:1px solid #4A4A4A; }"
        )

    def _primary_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setMinimumHeight(48)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{ background-color:{_ACCENT}; color:#1A0008; border:1px solid #FF7591; "
            "border-radius:16px; padding:12px 26px; font-weight:950; font-size:16px; }"
            "QPushButton:hover { background-color:#FF6985; border:1px solid #FFFFFF; }"
            "QPushButton:disabled { background-color:#2A2A2A; color:#6B6B6B; border:1px solid #353535; }"
        )
        return b

    def _build_intro(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(30, 24, 30, 24)
        lay.setSpacing(14)
        lay.addStretch(1)

        head = QLabel("Blitz ⚡")
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.setStyleSheet(f"color:{_ACCENT}; font-size:40px; font-weight:950; border:none;")
        lay.addWidget(head)

        rules = QLabel(
            "Connect the matching circles before the clock runs out.\n"
            "der / die / das → its noun   ·   noun → its plural   ·   word → its meaning\n"
            "Chain correct connects to build your combo — the faster, the more points."
        )
        rules.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rules.setWordWrap(True)
        rules.setStyleSheet("color:#C8C8C8; font-size:13px; font-weight:650; border:none; line-height:1.5;")
        lay.addWidget(rules)

        self.intro_best = QLabel("")
        self.intro_best.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.intro_best.setStyleSheet("color:#FFD700; font-size:13px; font-weight:900; border:none;")
        lay.addWidget(self.intro_best)

        self.play_btn = self._primary_btn("▶  Play")
        self.play_btn.clicked.connect(self._start_round)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.play_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self.intro_hint = QLabel("")
        self.intro_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.intro_hint.setStyleSheet("color:#9A9A9A; font-size:12px; font-weight:700; border:none;")
        lay.addWidget(self.intro_hint)

        lay.addStretch(2)
        return page

    def _build_play(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.board = GameBoard()
        self.board.scoreChanged.connect(lambda s: self.score_lbl.setText(f"{s}"))
        self.board.comboChanged.connect(self._on_combo)
        self.board.timeChanged.connect(lambda s: self.time_lbl.setText(f"⏱ {s}"))
        self.board.hitMade.connect(self._on_hit)
        self.board.missMade.connect(self._on_miss)
        self.board.milestoneReached.connect(
            lambda _c: self.sfx.play_milestone() if self.sfx is not None else None
        )
        self.board.roundFinished.connect(self._on_finished)
        lay.addWidget(self.board)
        return page

    def _build_end(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(30, 24, 30, 24)
        lay.setSpacing(12)
        lay.addStretch(1)

        self.end_title = QLabel("Round complete")
        self.end_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.end_title.setStyleSheet("color:#FFFFFF; font-size:30px; font-weight:950; border:none;")
        lay.addWidget(self.end_title)

        self.end_newbest = QLabel("")
        self.end_newbest.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.end_newbest.setStyleSheet("color:#FFD700; font-size:16px; font-weight:950; border:none;")
        lay.addWidget(self.end_newbest)

        self.end_score = QLabel("")
        self.end_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.end_score.setStyleSheet(f"color:{_ACCENT}; font-size:54px; font-weight:950; border:none;")
        lay.addWidget(self.end_score)

        self.end_detail = QLabel("")
        self.end_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.end_detail.setStyleSheet("color:#C8C8C8; font-size:13px; font-weight:700; border:none;")
        lay.addWidget(self.end_detail)

        self.again_btn = self._primary_btn("↻  Play again")
        self.again_btn.clicked.connect(self._start_round)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.again_btn)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addStretch(2)
        return page

    # ------------------------------------------------------------- lifecycle
    def on_show(self) -> None:
        try:
            self.subtitle.setText(self.session.context_label() or "Connect the pairs — fast")
        except Exception:
            pass

        self._deck_id = self.session.game_deck_id()
        self._best = self.session.game_best(self._deck_id)
        self.best_lbl.setText(f"Best {self._best.get('best_score', 0)}")

        pairs = self._build_pairs()
        playable = len(pairs) >= 1

        if not playable:
            self.intro_best.setText("")
            self.intro_hint.setText("No vocab in this Lektion yet — pick a Lektion with vocabulary to play.")
            self.play_btn.setEnabled(False)
        else:
            best = self._best.get("best_score", 0)
            self.intro_best.setText(f"Your best: {best}" if best else "")
            self.intro_hint.setText(f"{len(pairs)} pairs in this Lektion")
            self.play_btn.setEnabled(True)

        self.stack.setCurrentIndex(0)

    def hideEvent(self, event) -> None:
        try:
            self.board.stop()
        except Exception:
            pass
        self._stop_precache()
        self._stop_tts()
        super().hideEvent(event)

    def set_focus_mode(self, on: bool) -> None:
        try:
            self.top_bar.setVisible(not bool(on))
        except Exception:
            pass

    # ------------------------------------------------------------- gameplay
    def _build_pairs(self) -> list:
        try:
            items = self.session.game_vocab_items()
            return build_pairs(items)
        except Exception:
            return []

    def _start_round(self) -> None:
        pairs = self._build_pairs()
        if not pairs:
            self.stack.setCurrentIndex(0)
            return
        waves = make_waves(pairs, wave_size=3, rng=random)
        self.score_lbl.setText("0")
        self.combo_lbl.setText("x0")
        self.stack.setCurrentIndex(1)
        sfx = self._ensure_sfx()
        if self._audio_on:
            sfx.play_start()
        self._start_precache([p.word for p in pairs])
        self.board.start_game(waves, duration_s=_ROUND_SECONDS)

    def _on_combo(self, combo: int) -> None:
        self.combo_lbl.setText(f"x{combo}")
        # Brighten the combo chip as the streak grows.
        if combo >= 8:
            color, border, bg = "#FFD700", "#FFD700", "#2A2000"
        elif combo >= 4:
            color, border, bg = "#7AE582", "#2D6A45", "#13251B"
        else:
            color, border, bg = "#FFFFFF", "#2E2E2E", "#1A1A1A"
        self.combo_lbl.setStyleSheet(
            f"color:{color}; font-size:12px; font-weight:800; background:{bg}; "
            f"border:1px solid {border}; border-radius:8px; padding:6px 10px;"
        )

    def _on_hit(self, word: str, points: int, combo: int) -> None:
        if not self._audio_on:
            return
        if self.sfx is not None:
            self.sfx.play_hit(combo)
        self._speak(word)

    def _on_miss(self) -> None:
        if self._audio_on and self.sfx is not None:
            self.sfx.play_miss()

    def _on_finished(self, score: int, max_combo: int, hits: int, misses: int) -> None:
        if self._audio_on and self.sfx is not None:
            self.sfx.play_finish()
        self._stop_precache()

        result = self.session.record_game_score(score, max_combo, self._deck_id)
        self._best = self.session.game_best(self._deck_id)
        self.best_lbl.setText(f"Best {self._best.get('best_score', 0)}")

        total = hits + misses
        acc = (hits / total * 100.0) if total else 0.0
        is_new_best = bool(result.get("is_new_best"))

        self.end_title.setText("Time! ⚡" if (hits or misses) else "Round complete")
        self.end_newbest.setText("★  New personal best!  ★" if is_new_best else "")
        self.end_score.setText(f"{score}")
        self.end_detail.setText(
            f"Max combo  x{max_combo}     ·     Accuracy  {acc:.0f}%     ·     {hits} connects"
        )
        self.stack.setCurrentIndex(2)

    def _toggle_audio(self) -> None:
        self._audio_on = not self._audio_on
        self.audio_btn.setText("🔊" if self._audio_on else "🔇")
        if self.sfx is not None:
            self.sfx.set_muted(not self._audio_on)
        if not self._audio_on:
            self._stop_tts()

    # ----------------------------------------------------------------- TTS
    def _speak(self, word: str) -> None:
        # Debounced, best-effort: only speak a word we've already cached, and only
        # when nothing else is playing, so rapid connects don't stutter.
        if not self._audio_on or self._tts_busy or not word:
            return
        try:
            if self.pronunciation_service.has_cached_audio(word):
                self._tts_busy = True
                self._tts_guard.start(4000)
                self.tts.play_file(self.pronunciation_service.get_cached_path(word))
        except Exception:
            self._on_tts_done()

    def _start_precache(self, words: list[str]) -> None:
        self._stop_precache()
        uniq = list(dict.fromkeys(w for w in words if w))
        if not uniq:
            return
        self._precache_thread = QThread(self)
        self._precache_worker = _PrecacheWorker(self.pronunciation_service, uniq)
        self._precache_worker.moveToThread(self._precache_thread)
        self._precache_thread.started.connect(self._precache_worker.run)
        self._precache_worker.done.connect(self._precache_thread.quit)
        self._precache_worker.done.connect(self._precache_worker.deleteLater)
        self._precache_thread.finished.connect(self._precache_thread.deleteLater)
        self._precache_thread.finished.connect(self._on_precache_thread_finished)
        self._precache_thread.start()

    def _stop_precache(self) -> None:
        # Non-blocking: flag the worker and drop our handles. The first
        # generate_wav loads the ONNX model and can't be interrupted mid-word, so
        # we must NOT wait() on the UI thread here (that froze tab-switches). The
        # worker's done->quit->deleteLater chain self-cleans; a still-running
        # thread is parked in _orphans so closeEvent can join it before exit.
        t = self._precache_thread
        w = self._precache_worker
        self._precache_thread = None
        self._precache_worker = None
        if w is not None:
            try:
                w.stop()
            except Exception:
                pass
        if t is not None:
            try:
                t.finished.disconnect(self._on_precache_thread_finished)
            except Exception:
                pass
            try:
                if t.isRunning():
                    self._orphans.append(t)
            except Exception:
                pass

    @Slot()
    def _on_precache_thread_finished(self) -> None:
        # Only the CURRENT round's thread may clear the slots — a stale thread
        # from a previous round must never null a live round's references.
        if self.sender() is self._precache_thread:
            self._precache_thread = None
            self._precache_worker = None

    def closeEvent(self, event) -> None:
        try:
            self.board.stop()
        except Exception:
            pass
        if self._precache_worker is not None:
            try:
                self._precache_worker.stop()
            except Exception:
                pass
        # Real app teardown: join the current + any orphaned precache threads
        # (bounded) so no QThread is destroyed while still running.
        for t in [self._precache_thread, *self._orphans]:
            if t is None:
                continue
            try:
                t.quit()
                t.wait(2000)
            except Exception:
                pass
        self._precache_thread = None
        self._precache_worker = None
        self._orphans.clear()
        super().closeEvent(event)
