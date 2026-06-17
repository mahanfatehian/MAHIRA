from __future__ import annotations

"""
Conjugation — a read-only tab showing a verb's full paradigm.

Opened from the Vocab Table when the learner taps a verb's "Type" tag. It looks
the verb up in the bundled Wiktionary-derived dataset (core.conjugation) and
lays out every tense as its own accent-coloured card: Präsens, Präteritum,
Perfekt, Plusquamperfekt, Futur I, Konjunktiv II, plus the Imperativ. Nothing
is scheduled or scored — it is a calm reference view in the app's house style.
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal
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


def _chip(text: str, color: str = "#D7DAE0") -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
    lbl.setStyleSheet(
        f"QLabel {{ color:{color}; border:1px solid #2E2E2E; background:#101010; "
        f"border-radius:9px; padding:3px 10px; }}"
    )
    return lbl


class _TenseCard(QFrame):
    """One tense as a card: an accented header + the six person/form rows."""

    def __init__(self, title_de: str, title_en: str, accent: str, rows: list):
        super().__init__()
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
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        for r, (pronoun, form) in enumerate(rows):
            pl = QLabel(pronoun)
            pl.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            pl.setStyleSheet("QLabel { color:#8A8A8A; background:transparent; border:none; }")
            pl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            pl.setMinimumWidth(64)
            has = bool((form or "").strip())
            fl = QLabel(form if has else "—")
            fl.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
            fl.setStyleSheet(
                f"QLabel {{ color:{'#F0F0F0' if has else '#4E4E4E'}; background:transparent; border:none; }}"
            )
            fl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(pl, r, 0)
            grid.addWidget(fl, r, 1)
        lay.addLayout(grid)


class ConjugationPage(QWidget):
    go_back = Signal()

    def __init__(self, session=None, nav=None):
        super().__init__()
        self.session = session
        self.nav = nav
        self._infinitive = ""
        self._meaning = ""
        self._conj = Conjugator()

        self.setObjectName("ConjugationPage")
        self.setFont(QFont("Segoe UI", 10))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "#ConjugationPage { background-color:#0E0E0E; }"
            "#ConjugationPage QLabel { background: transparent; }"
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

        # ---- Scroll area holding a content host we rebuild per verb ----
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
        self.scroll.setWidget(self.host)
        outer.addWidget(self.scroll, 1)

    # --------------------------------------------------------------- data
    def set_verb(self, infinitive: str, meaning: str = "") -> None:
        self._infinitive = (infinitive or "").strip()
        self._meaning = (meaning or "").strip()

    def on_show(self) -> None:
        self._render()

    def _clear_host(self) -> None:
        while self.host_lay.count():
            item = self.host_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            else:
                lay = item.layout()
                if lay is not None:
                    self._delete_layout(lay)

    def _delete_layout(self, lay) -> None:
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif it.layout() is not None:
                self._delete_layout(it.layout())

    def _render(self) -> None:
        self._clear_host()
        verb = self._infinitive
        self.page_subtitle.setText(verb or "Full verb paradigm")

        conj = None
        try:
            conj = self._conj.conjugate(verb) if verb else None
        except Exception:
            conj = None

        if conj is None:
            self.host_lay.addWidget(self._empty_card(verb))
            self.host_lay.addStretch(1)
            return

        self.host_lay.addWidget(self._header_card(conj))

        # Tense cards, two per row.
        grid_host = QWidget()
        grid_host.setStyleSheet("background: transparent;")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        cards = []
        for de, en, forms in conj.tenses():
            if not any((f or "").strip() for f in forms):
                continue  # skip a tense the dataset can't fill (rare verbs)
            accent = _TENSE_ACCENT.get(de, "#9AA0A6")
            rows = list(zip(PERSONS, forms))
            cards.append(_TenseCard(de, en, accent, rows))

        # Imperativ as a final card (only when the verb actually has one).
        if conj.imperativ:
            order = [k for k in ("du", "ihr", "Sie") if k in conj.imperativ]
            imp_rows = [(k, conj.imperativ[k]) for k in order]
            cards.append(_TenseCard("Imperativ", "Imperative", _IMP_ACCENT, imp_rows))

        for i, card in enumerate(cards):
            grid.addWidget(card, i // 2, i % 2, Qt.AlignmentFlag.AlignTop)

        self.host_lay.addWidget(grid_host)
        self.host_lay.addStretch(1)

    def _header_card(self, conj) -> QFrame:
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
        inf = QLabel(conj.infinitive)
        inf.setFont(QFont("Segoe UI", 22, QFont.Weight.Black))
        inf.setStyleSheet("QLabel { color:#FFFFFF; background:transparent; border:none; }")
        top.addWidget(inf, 0)
        if self._meaning:
            mean = QLabel(self._meaning)
            mean.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
            mean.setStyleSheet("QLabel { color:#9AA0A6; background:transparent; border:none; }")
            top.addWidget(mean, 0)
        top.addStretch(1)
        lay.addLayout(top)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        aux = (conj.hilfsverb or "haben").strip()
        chips.addWidget(_chip(f"Perfekt mit „{aux}“", "#66E39A" if aux == "haben" else "#34D2E0"))
        if conj.partizip2:
            chips.addWidget(_chip(f"Partizip II: {conj.partizip2}", "#FFB020"))
        if conj.separable:
            chips.addWidget(_chip("trennbar · separable", "#B983FF"))
        if conj.reflexive:
            chips.addWidget(_chip("reflexiv · sich", "#FF6FB5"))
        chips.addStretch(1)
        lay.addLayout(chips)
        return card

    def _empty_card(self, verb: str) -> QFrame:
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
        sub = QLabel(
            f"“{verb}” isn’t in the verb dataset."
            if verb else "No verb selected."
        )
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("QLabel { color:#7C7C7C; font-size:12px; background:transparent; border:none; }")
        lay.addWidget(title)
        lay.addWidget(sub)
        return card

    # ---------------------------------------------------------- focus mode
    def set_focus_mode(self, on: bool) -> None:
        try:
            self.top_bar.setVisible(not bool(on))
        except Exception:
            pass
