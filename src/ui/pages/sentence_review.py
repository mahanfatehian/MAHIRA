from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QSizePolicy,
)

from core.session import SessionService
from ui.widgets.sentence_builder_widget import SentenceBuilderWidget


class SentenceReviewPage(QWidget):
    """Sentence builder review page."""

    go_progress = Signal()

    def __init__(self, session: SessionService, nav=None) -> None:
        super().__init__()
        self.session = session
        self.nav = nav

        self.current_item: Any | None = None
        self.tip_used = False
        self.translation_used = False
        self.was_checked = False
        self.was_skipped = False
        self.card_started_at: float | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)

        self.title = QLabel("Sentence Builder")
        self.title.setStyleSheet("font-size:16px; font-weight:700;")

        self.counter = QLabel("")
        self.counter.setStyleSheet("opacity:0.8;")

        btn_start = QPushButton("Start New Session")
        btn_start.clicked.connect(self._start_session)

        btn_progress = QPushButton("Progress")
        btn_progress.clicked.connect(self.go_progress.emit)

        top.addWidget(self.title)
        top.addWidget(self.counter)
        top.addStretch(1)
        top.addWidget(btn_start)
        top.addWidget(btn_progress)

        layout.addLayout(top)

        self.card = SentenceBuilderWidget(accent="#FFB020")
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.card.check_clicked.connect(self._on_check)
        self.card.rated.connect(self._on_rated)
        self.card.tip_clicked.connect(self._on_tip)
        self.card.translation_clicked.connect(self._on_translation)
        self.card.skipped.connect(self._on_skipped)

        layout.addWidget(self.card, 1)

    def _on_tip(self) -> None:
        self.tip_used = True

    def _on_translation(self) -> None:
        self.translation_used = True

    def _on_skipped(self) -> None:
        self.was_skipped = True
        self.was_checked = False
        if self.current_item is not None:
            self._on_rated(0)

    def on_show(self) -> None:
        if self.session.remaining() == 0:
            self.session.start_new_session()
        self._load_next()

    def _start_session(self) -> None:
        self.session.start_new_session()
        self._load_next()

    def _update_counter(self) -> None:
        lim = getattr(getattr(self.session, "plan", None), "limit", None)
        lim_txt = str(lim) if lim is not None else "?"
        try:
            self.counter.setText(f"Remaining: {self.session.remaining()}/{lim_txt}")
        except Exception:
            self.counter.setText("")

    def _load_next(self) -> None:
        self._update_counter()

        self.current_item = self.session.next_sentence_item()

        self.tip_used = False
        self.translation_used = False
        self.was_checked = False
        self.was_skipped = False
        self.card.reset_for_next()

        if not self.current_item:
            self.card.lock_after_finish("Session finished")
            self._update_counter()
            return

        self.card_started_at = time.time()
        item = self.current_item

        target = (getattr(item, "target_text", "") or "").strip()
        words = list(getattr(item, "words", []) or [])


        self.card.set_item(
            words=words,
            tip=getattr(item, "tip", None),
            translation=getattr(item, "translation", None),
        )

        self._update_counter()

    def _on_check(self, typed_text: str) -> None:
        if not self.current_item:
            return

        self.was_checked = True
        self.was_skipped = False

        res = self.session.check_sentence(self.current_item, typed_text)

        details = []
        if int(res.get("cap_errors") or 0) > 0:
            details.append(f"Capitalization issues: {int(res.get('cap_errors') or 0)}")
        if int(res.get("punct_errors") or 0) > 0:
            details.append(f"Punctuation issues: {int(res.get('punct_errors') or 0)}")

        ok = bool(res.get("ok"))
        self.card.show_result(
            ok=ok,
            expected=str(res.get("expected") or getattr(self.current_item, "target_text", "")),
            details="\n".join(details) if details else None,
        )

    def _on_rated(self, rating: int) -> None:
        if not self.current_item:
            return

        typed = self.card.typed_text()
        response_ms = (
            int((time.time() - self.card_started_at) * 1000)
            if self.card_started_at
            else None
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

        self._load_next()
