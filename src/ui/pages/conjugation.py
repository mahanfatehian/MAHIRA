from __future__ import annotations

"""
Conjugation — a read-only tab showing a verb's full paradigm.

Opened from the Vocab Table when the learner taps a verb's "Type" tag. It looks
the verb up in the bundled Wiktionary-derived dataset (core.conjugation) and
lays out every tense as its own accent-coloured card: Präsens, Präteritum,
Perfekt, Plusquamperfekt, Futur I, Konjunktiv II, plus the Imperativ. Nothing
is scheduled or scored — it is a calm reference view in the app's house style.
"""

from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.conjugation import Conjugator, PERSONS

# Per-tense accent, reusing the app's palette so each tense reads distinctly.
_TENSE_ACCENT = {
    "Präsens": "#66E39A",
    "Präteritum": "#6B9FFF",
    "Perfekt": "#FFB020",
    "Plusquamperfekt": "#B983FF",
    "Futur I": "#34D2E0",
    "Konjunktiv II": "#FF6FB5",
}
_IMP_ACCENT = "#FF8A5B"

# The displayed person label vs. the single pronoun we actually speak before the
# verb (so "er/sie/es liebt" is read as "er liebt", not the whole slash list).
_SPOKEN_PRONOUN = {
    "ich": "ich", "du": "du", "er/sie/es": "er",
    "wir": "wir", "ihr": "ihr", "sie/Sie": "sie",
}


class _Speaker(QPushButton):
    """A compact 🔊 button for a single conjugated form, with the same idle /
    busy / playing states as the app's main AudioButton but table-row sized."""

    def __init__(self, parent=None):
        super().__init__("🔊", parent)
        self._available = True
        self._busy = False
        self._playing = False
        self._audio_text = ""
        self.setObjectName("ConjSpeaker")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedSize(28, 24)
        self.setToolTip("Play pronunciation")
        self._sync()

    def set_available(self, v: bool) -> None:
        available = bool(v)
        if available == self._available:
            return
        self._available = available
        self._sync()

    def set_audio_text(self, text: str) -> None:
        self._audio_text = (text or "").strip()
        label = self._audio_text or "this form"
        self.setAccessibleName(f"Play pronunciation for {label}")
        self.setToolTip(f"Play pronunciation for {label}")

    def audio_text(self) -> str:
        return self._audio_text

    def set_busy(self, v: bool) -> None:
        self._busy = bool(v)
        if self._busy:
            self._playing = False
        self._sync()

    def set_playing(self, v: bool) -> None:
        self._playing = bool(v)
        if self._playing:
            self._busy = False
        self._sync()

    def reset_state(self) -> None:
        if not self._busy and not self._playing:
            return
        self._busy = False
        self._playing = False
        self._sync()

    def _sync(self) -> None:
        self.setText("…" if self._busy else ("🔈" if self._playing else "🔊"))
        self.setEnabled(self._available and not self._busy and not self._playing)
        label = self._audio_text or "this form"
        if self._busy:
            self.setToolTip(f"Preparing pronunciation for {label}…")
        elif self._playing:
            self.setToolTip(f"Playing pronunciation for {label}…")
        else:
            self.setToolTip(f"Play pronunciation for {label}")


class _TtsWorker(QObject):
    """Renders one phrase to a cached WAV off the UI thread."""

    done = Signal(str, str)   # (text, wav_path)
    fail = Signal(str, str)   # (text, message)

    def __init__(self, service, text: str):
        super().__init__()
        self._service = service
        self._text = text

    @Slot()
    def run(self) -> None:
        try:
            path = self._service.generate_wav(self._text)
            self.done.emit(self._text, str(path))
        except Exception as e:  # noqa: BLE001 - reported to the UI, never raised
            self.fail.emit(self._text, str(e))


def _chip(text: str, color: str = "#D7DAE0") -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
    lbl.setStyleSheet(
        f"QLabel {{ color:{color}; border:1px solid #2E2E2E; background:#101010; "
        f"border-radius:9px; padding:3px 10px; }}"
    )
    return lbl


class _TenseCard(QFrame):
    """One persistent tense card whose row values can be updated in place."""

    def __init__(
        self,
        title_de: str,
        title_en: str,
        accent: str,
        rows: list,
        on_audio=None,
        parent=None,
    ):
        super().__init__(parent)
        self._on_audio = on_audio
        self._rows: list[tuple[QLabel, QLabel, _Speaker]] = []
        self.setObjectName("TenseCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "#TenseCard { background:#141414; border:1px solid #262626; border-radius:14px; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel(title_de)
        t.setFont(QFont("Segoe UI", 12, QFont.Weight.Black))
        t.setStyleSheet(f"QLabel {{ color:{accent}; background:transparent; border:none; }}")
        en = QLabel(title_en)
        en.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        en.setStyleSheet("QLabel { color:#7C7C7C; background:transparent; border:none; }")
        head.addWidget(t, 0)
        head.addWidget(en, 0)
        head.addStretch(1)
        lay.addLayout(head)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background:{accent}33; border:none;")
        lay.addWidget(rule)

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(0, 0)   # pronoun
        grid.setColumnStretch(1, 1)   # form
        grid.setColumnStretch(2, 0)   # speaker
        for r, (pronoun, _form, _speak) in enumerate(rows):
            pl = QLabel(pronoun)
            pl.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            pl.setStyleSheet("QLabel { color:#8A8A8A; background:transparent; border:none; }")
            pl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            pl.setMinimumWidth(64)
            fl = QLabel("—")
            fl.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
            fl.setStyleSheet("QLabel { color:#4E4E4E; background:transparent; border:none; }")
            fl._conj_has_form = False
            fl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            spk = _Speaker(self)
            spk.set_available(False)
            spk.hide()
            spk.clicked.connect(lambda _=False, b=spk: self._play_speaker(b))
            grid.addWidget(pl, r, 0)
            grid.addWidget(fl, r, 1)
            grid.addWidget(spk, r, 2, Qt.AlignRight | Qt.AlignVCenter)
            self._rows.append((pl, fl, spk))
        lay.addLayout(grid)
        self.set_rows(rows)

    def _play_speaker(self, spk: _Speaker) -> None:
        text = spk.audio_text()
        if text and callable(self._on_audio):
            self._on_audio(text, spk)

    def set_rows(self, rows: list) -> bool:
        """Update row labels/forms/audio payloads; return whether any form exists."""
        values = list(rows or [])
        any_form = False
        for index, (pl, fl, spk) in enumerate(self._rows):
            if index >= len(values):
                pl.hide()
                fl.hide()
                spk.set_audio_text("")
                spk.set_available(False)
                spk.hide()
                continue

            pronoun, form, speak = values[index]
            form = str(form or "")
            speak = str(speak or "").strip()
            has = bool(form.strip())
            any_form = any_form or has

            pl.setText(str(pronoun or ""))
            pl.show()
            fl.setText(form if has else "—")
            fl.show()
            if bool(getattr(fl, "_conj_has_form", False)) != has:
                fl._conj_has_form = has
                fl.setStyleSheet(
                    f"QLabel {{ color:{'#F0F0F0' if has else '#4E4E4E'}; "
                    "background:transparent; border:none; }"
                )

            available = has and bool(speak) and callable(self._on_audio)
            spk.set_audio_text(speak if available else "")
            spk.set_available(available)
            spk.setVisible(available)
        return any_form


class ConjugationPage(QWidget):
    go_back = Signal()

    def __init__(self, session=None, nav=None):
        super().__init__()
        self.session = session
        self.nav = nav
        self._infinitive = ""
        self._meaning = ""
        self._conj = Conjugator()

        # Audio (lazily created on the first play so the page costs nothing at
        # startup). One synthesis thread at a time; the active speaker button is
        # tracked so its busy/playing state can be driven and reset.
        self._model_mgr = None
        self._pron = None
        self._play_svc = None
        self._audio_thread: Optional[QThread] = None
        self._audio_worker: Optional[_TtsWorker] = None
        self._active_spk: Any | None = None
        self._cur_text = ""
        self._cur_path = ""

        # The expensive paradigm widgets are created lazily on the first known
        # verb, then retained for the lifetime of the page. Subsequent verbs only
        # update their labels, audio payloads, and visibility.
        self._rendered_key: tuple[str, str] | None = None
        self._known_content_built = False
        self._header_widget: Optional[QFrame] = None
        self._grid_host: Optional[QWidget] = None
        self._tense_grid: Optional[QGridLayout] = None
        self._tense_cards: dict[str, _TenseCard] = {}
        self._imperative_card: Optional[_TenseCard] = None
        self._empty_widget: Optional[QFrame] = None
        self._empty_subtitle: Optional[QLabel] = None

        self.setObjectName("ConjugationPage")
        self.setFont(QFont("Segoe UI", 10))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "#ConjugationPage { background-color:#0E0E0E; }"
            "#ConjugationPage QLabel { background: transparent; }"
            "#ConjugationPage QPushButton#ConjSpeaker { background:#1B1B1B; color:#FFFFFF; "
            "border:1px solid #2E2E2E; border-radius:7px; font-size:11px; padding:0px; }"
            "#ConjugationPage QPushButton#ConjSpeaker:hover { background:#232323; "
            "border:1px solid #FFFFFF; }"
            "#ConjugationPage QPushButton#ConjSpeaker:disabled { background:#151515; "
            "color:#6B6B6B; border:1px solid #252525; }"
        )
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)

        # ---- Top bar ----
        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBarCard")
        self.top_bar.setStyleSheet(
            "QFrame#TopBarCard { background-color:#141414; border:1px solid #2A2A2A; border-radius:14px; }"
        )
        tb = QHBoxLayout(self.top_bar)
        tb.setContentsMargins(16, 12, 16, 12)
        tb.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.page_title = QLabel("Conjugation")
        self.page_title.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:20px; font-weight:950; border:none; background:transparent; }"
        )
        self.page_subtitle = QLabel("Full verb paradigm")
        self.page_subtitle.setStyleSheet(
            "QLabel { color:#9A9A9A; font-size:11px; font-weight:700; border:none; background:transparent; }"
        )
        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)
        tb.addLayout(title_col)
        tb.addStretch(1)
        self.back_btn = QPushButton("← Back")
        self.back_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.back_btn.setStyleSheet(
            "QPushButton { background-color:#1B1B1B; color:#FFFFFF; border:1px solid #2E2E2E; "
            "border-radius:10px; padding:8px 12px; font-weight:800; font-size:12px; }"
            "QPushButton:hover { border:1px solid #FFFFFF; background-color:#232323; }"
        )
        self.back_btn.clicked.connect(self.go_back.emit)
        tb.addWidget(self.back_btn)
        outer.addWidget(self.top_bar)

        # ---- Scroll area holding persistent content updated per verb ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.host = QWidget()
        self.host.setStyleSheet("background: transparent;")
        self.host_lay = QVBoxLayout(self.host)
        self.host_lay.setContentsMargins(0, 0, 6, 0)
        self.host_lay.setSpacing(12)
        self.host_lay.addStretch(1)
        self.scroll.setWidget(self.host)
        outer.addWidget(self.scroll, 1)

    # --------------------------------------------------------------- data
    def set_verb(self, infinitive: str, meaning: str = "") -> None:
        self._infinitive = (infinitive or "").strip()
        self._meaning = (meaning or "").strip()

    def on_show(self) -> None:
        self._render()

    def _request_key(self) -> tuple[str, str]:
        # Match Conjugator's case/whitespace-insensitive input semantics while
        # retaining a distinct key for reflexive "sich …" requests.
        verb = " ".join((self._infinitive or "").casefold().split())
        return verb, self._meaning

    def _render(self) -> None:
        key = self._request_key()
        if key == self._rendered_key:
            return

        # Payloads on the persistent speaker buttons are about to change.
        self._stop_audio()
        verb = self._infinitive
        self.page_subtitle.setText(verb or "Full verb paradigm")

        conj = None
        try:
            conj = self._conj.conjugate(verb) if verb else None
        except Exception:
            conj = None

        self.host.setUpdatesEnabled(False)
        try:
            if conj is None:
                self._show_empty(verb)
            else:
                self._show_conjugation(conj)
            self._rendered_key = key
            self.scroll.verticalScrollBar().setValue(0)
        finally:
            self.host.setUpdatesEnabled(True)
            self.host.update()

    def _dispatch_audio(self, text: str, spk: _Speaker) -> None:
        # Resolve self._play at click time so tests and integrations can replace
        # the audio handler without reconnecting all persistent buttons.
        self._play(text, spk)

    def _ensure_known_content(self, conj) -> None:
        if self._known_content_built:
            return

        self._header_widget = self._header_card()
        self.host_lay.insertWidget(self.host_lay.count() - 1, self._header_widget)

        self._grid_host = QWidget(self.host)
        self._grid_host.setStyleSheet("background: transparent;")
        self._tense_grid = QGridLayout(self._grid_host)
        self._tense_grid.setContentsMargins(0, 0, 0, 0)
        self._tense_grid.setHorizontalSpacing(12)
        self._tense_grid.setVerticalSpacing(12)
        self._tense_grid.setColumnStretch(0, 1)
        self._tense_grid.setColumnStretch(1, 1)

        blank_rows = [(person, "", "") for person in PERSONS]
        for de, en, _forms in conj.tenses():
            card = _TenseCard(
                de,
                en,
                _TENSE_ACCENT.get(de, "#9AA0A6"),
                blank_rows,
                on_audio=self._dispatch_audio,
                parent=self._grid_host,
            )
            card.hide()
            self._tense_cards[de] = card

        imp_rows = [(person, "", "") for person in ("du", "ihr", "Sie")]
        self._imperative_card = _TenseCard(
            "Imperativ",
            "Imperative",
            _IMP_ACCENT,
            imp_rows,
            on_audio=self._dispatch_audio,
            parent=self._grid_host,
        )
        self._imperative_card.hide()

        self.host_lay.insertWidget(self.host_lay.count() - 1, self._grid_host)
        self._known_content_built = True

    def _show_conjugation(self, conj) -> None:
        self._ensure_known_content(conj)
        self._update_header(conj)
        if self._empty_widget is not None:
            self._empty_widget.hide()

        grid = self._tense_grid
        if grid is None:
            return

        all_cards = list(self._tense_cards.values())
        if self._imperative_card is not None:
            all_cards.append(self._imperative_card)
        for card in all_cards:
            grid.removeWidget(card)
            card.hide()

        visible_cards: list[_TenseCard] = []
        for de, _en, forms in conj.tenses():
            card = self._tense_cards.get(de)
            if card is None:
                continue
            rows = [
                (
                    person,
                    form,
                    f"{_SPOKEN_PRONOUN.get(person, person)} {form}".strip()
                    if (form or "").strip()
                    else "",
                )
                for person, form in zip(PERSONS, forms)
            ]
            if card.set_rows(rows):
                visible_cards.append(card)

        if self._imperative_card is not None:
            order = [key for key in ("du", "ihr", "Sie") if key in conj.imperativ]
            rows = [(key, conj.imperativ[key], conj.imperativ[key]) for key in order]
            if self._imperative_card.set_rows(rows):
                visible_cards.append(self._imperative_card)

        # Compact the cards exactly as before when a rare verb lacks a tense.
        for index, card in enumerate(visible_cards):
            grid.addWidget(card, index // 2, index % 2, Qt.AlignmentFlag.AlignTop)
            card.show()

        if self._header_widget is not None:
            self._header_widget.show()
        if self._grid_host is not None:
            self._grid_host.show()

    def _header_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("ConjHeader")
        card.setStyleSheet(
            "#ConjHeader { background:#151515; border:1px solid #2A2A2A; border-radius:16px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(12)
        self._header_infinitive = QLabel("")
        self._header_infinitive.setFont(QFont("Segoe UI", 22, QFont.Weight.Black))
        self._header_infinitive.setStyleSheet(
            "QLabel { color:#FFFFFF; background:transparent; border:none; }"
        )
        top.addWidget(self._header_infinitive, 0)
        self._header_meaning = QLabel("")
        self._header_meaning.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self._header_meaning.setStyleSheet(
            "QLabel { color:#9AA0A6; background:transparent; border:none; }"
        )
        self._header_meaning.hide()
        top.addWidget(self._header_meaning, 0)
        top.addStretch(1)
        lay.addLayout(top)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self._aux_chip = _chip("")
        self._participle_chip = _chip("", "#FFB020")
        self._separable_chip = _chip("trennbar · separable", "#B983FF")
        self._reflexive_chip = _chip("reflexiv · sich", "#FF6FB5")
        chips.addWidget(self._aux_chip)
        chips.addWidget(self._participle_chip)
        chips.addWidget(self._separable_chip)
        chips.addWidget(self._reflexive_chip)
        self._participle_chip.hide()
        self._separable_chip.hide()
        self._reflexive_chip.hide()
        chips.addStretch(1)
        lay.addLayout(chips)
        return card

    def _update_header(self, conj) -> None:
        self._header_infinitive.setText(conj.infinitive)
        self._header_meaning.setText(self._meaning)
        self._header_meaning.setVisible(bool(self._meaning))

        aux = (conj.hilfsverb or "haben").strip()
        aux_color = "#66E39A" if aux == "haben" else "#34D2E0"
        self._aux_chip.setText(f"Perfekt mit „{aux}“")
        self._aux_chip.setStyleSheet(
            f"QLabel {{ color:{aux_color}; border:1px solid #2E2E2E; background:#101010; "
            "border-radius:9px; padding:3px 10px; }"
        )
        self._participle_chip.setText(f"Partizip II: {conj.partizip2}")
        self._participle_chip.setVisible(bool(conj.partizip2))
        self._separable_chip.setVisible(bool(conj.separable))
        self._reflexive_chip.setVisible(bool(conj.reflexive))

    def _empty_card(self, verb: str) -> QFrame:
        if self._empty_widget is not None:
            self._update_empty_subtitle(verb)
            return self._empty_widget

        card = QFrame()
        card.setObjectName("ConjEmpty")
        card.setStyleSheet(
            "#ConjEmpty { background:#141414; border:1px solid #262626; border-radius:16px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 28, 20, 28)
        lay.setSpacing(6)
        title = QLabel("No conjugation available")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Black))
        title.setStyleSheet("QLabel { color:#D0D0D0; background:transparent; border:none; }")
        self._empty_subtitle = QLabel("")
        self._empty_subtitle.setAlignment(Qt.AlignCenter)
        self._empty_subtitle.setStyleSheet(
            "QLabel { color:#7C7C7C; font-size:12px; background:transparent; border:none; }"
        )
        lay.addWidget(title)
        lay.addWidget(self._empty_subtitle)
        self._empty_widget = card
        self._update_empty_subtitle(verb)
        return card

    def _update_empty_subtitle(self, verb: str) -> None:
        if self._empty_subtitle is None:
            return
        self._empty_subtitle.setText(
            f"“{verb}” isn’t in the verb dataset." if verb else "No verb selected."
        )

    def _show_empty(self, verb: str) -> None:
        card = self._empty_card(verb)
        if card.parent() is None:
            self.host_lay.insertWidget(self.host_lay.count() - 1, card)
        if self._header_widget is not None:
            self._header_widget.hide()
        if self._grid_host is not None:
            self._grid_host.hide()
        card.show()

    # -------------------------------------------------------------- audio
    def _ensure_audio(self) -> bool:
        if self._play_svc is not None:
            return True
        try:
            from core.audio import PiperModelManager, PlaybackService, PronunciationService
            self._model_mgr = PiperModelManager()
            self._pron = PronunciationService(self._model_mgr)
            self._play_svc = PlaybackService(self)
            self._play_svc.started.connect(self._on_play_started)
            self._play_svc.finished.connect(self._on_play_finished)
            self._play_svc.failed.connect(self._on_play_failed)
            return True
        except Exception:
            self._play_svc = None
            return False

    def _play(self, text: str, spk) -> None:
        text = (text or "").strip()
        if not text or spk is None or not self._ensure_audio():
            return
        # One synthesis at a time (a fresh click waits for the current render).
        if self._audio_thread is not None and self._audio_thread.isRunning():
            return

        prev = self._active_spk
        if prev is not None and prev is not spk:
            try:
                prev.set_busy(False)
                prev.set_playing(False)
            except Exception:
                pass

        # Reuse the exact cached clip if we still have it.
        if self._cur_text == text and self._cur_path and Path(self._cur_path).exists():
            self._play_svc.stop()
            self._active_spk = spk
            spk.set_busy(True)
            self._play_svc.play_file(self._cur_path)
            return

        self._cur_text = text
        self._cur_path = ""
        self._active_spk = spk
        self._play_svc.stop()
        spk.set_busy(True)

        # Reuse any clip produced earlier in this page or another audio tab.
        # PronunciationService maintains a bounded shared disk cache.
        try:
            cached = self._pron.get_cached_path(text)
            if cached.exists():
                self._cur_path = str(cached)
                self._play_svc.play_file(cached)
                return
        except Exception:
            pass

        self._audio_thread = QThread(self)
        self._audio_worker = _TtsWorker(self._pron, text)
        self._audio_worker.moveToThread(self._audio_thread)
        self._audio_thread.started.connect(self._audio_worker.run)
        self._audio_worker.done.connect(self._on_tts_done)
        self._audio_worker.fail.connect(self._on_tts_fail)
        self._audio_worker.done.connect(self._audio_thread.quit)
        self._audio_worker.fail.connect(self._audio_thread.quit)
        self._audio_worker.done.connect(self._audio_worker.deleteLater)
        self._audio_worker.fail.connect(self._audio_worker.deleteLater)
        self._audio_thread.finished.connect(self._on_thread_finished)
        self._audio_thread.finished.connect(self._audio_thread.deleteLater)
        self._audio_thread.start()

    @Slot(str, str)
    def _on_tts_done(self, text: str, path: str) -> None:
        if text != self._cur_text:
            # Superseded (a newer click, or the user left the tab): retain the
            # completed clip in the bounded cache for a later visit.
            return
        self._cur_path = path
        if self._active_spk is not None:
            self._active_spk.set_busy(True)
        if self._play_svc is not None:
            self._play_svc.play_file(path)

    @Slot(str, str)
    def _on_tts_fail(self, text: str, message: str) -> None:
        if self._active_spk is not None:
            self._active_spk.reset_state()

    @Slot()
    def _on_thread_finished(self) -> None:
        self._audio_thread = None
        self._audio_worker = None

    @Slot(str)
    def _on_play_started(self, path: str) -> None:
        if self._active_spk is not None:
            self._active_spk.set_playing(True)

    @Slot()
    def _on_play_finished(self) -> None:
        if self._active_spk is not None:
            self._active_spk.set_playing(False)
            self._active_spk.set_busy(False)

    @Slot(str)
    def _on_play_failed(self, message: str) -> None:
        if self._active_spk is not None:
            self._active_spk.reset_state()

    def _stop_audio(self) -> None:
        if self._play_svc is not None:
            try:
                self._play_svc.stop()
            except Exception:
                pass
        if self._active_spk is not None:
            try:
                self._active_spk.reset_state()
            except Exception:
                pass
        self._active_spk = None
        self._cur_text = ""
        self._cur_path = ""

    def hideEvent(self, event):
        # Leaving the tab stops any audio (and releases the speaker buttons we
        # are about to lose on the next render).
        self._stop_audio()
        super().hideEvent(event)

    # ---------------------------------------------------------- focus mode
    def set_focus_mode(self, on: bool) -> None:
        try:
            self.top_bar.setVisible(not bool(on))
        except Exception:
            pass
