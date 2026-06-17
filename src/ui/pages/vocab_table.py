from __future__ import annotations

"""
Vocab Table — a read-only study grid for the current Lektion's vocabulary.

Reached from the Vocabulary card on the objective-selection screen. It lays the
deck out as four columns — Vocab · Article · Plural · Meaning — and lets the
learner hide any column (via a top button OR by clicking the column header).
A hidden column blanks every cell to "• • •"; tapping a blanked cell reveals
just that one entry, so the learner can quiz themselves column by column:
recall the article for each word, or the plural, or the meaning, then tap to
check. Nothing here is scheduled or scored — it is a calm, self-directed
reference/quiz view that complements the timed review tabs.
"""

from typing import Callable

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


# Column key -> (header title, accent). Accents reuse the app's existing palette.
# These four are the quizzable columns (each gets a hide toggle + clickable header).
_COLUMNS = [
    ("word", "Vocab", "#66E39A"),
    ("article", "Article", "#6B9FFF"),
    ("plural", "Plural", "#FFB020"),
    ("meaning", "Meaning", "#34D2E0"),
]
_COL_STRETCH = {"word": 3, "article": 2, "plural": 3, "meaning": 4}
_HIDDEN_GLYPH = "• • •"

# Trailing informational column: the part of speech. It is read-only — no hide
# toggle, no clickable header, no reveal — just a muted reference tag.
_POS_TITLE = "Type"
_POS_ACCENT = "#8E9AA6"
_POS_STRETCH = 2


def _rgba(hex_color: str, alpha: float) -> str:
    """'#RRGGBB' + alpha(0..1) -> 'rgba(r,g,b,a)' for translucent tints."""
    h = (hex_color or "#000000").lstrip("#")
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        r, g, b = 0, 0, 0
    return f"rgba({r},{g},{b},{max(0.0, min(1.0, alpha)):.3f})"


class _HeaderCell(QFrame):
    """A clickable column header. Clicking it toggles that column's hidden
    state (kept in sync with the matching top button)."""

    def __init__(self, title: str, accent: str, on_click: Callable[[], None]):
        super().__init__()
        self._title = title
        self._accent = accent
        self._on_click = on_click
        self._masked = False
        self.setObjectName("VTHeaderCell")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(8)

        self._lbl = QLabel(title)
        self._lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
        self._lbl.setStyleSheet("QLabel { background: transparent; border: none; }")

        self._eye = QLabel("")
        self._eye.setFont(QFont("Segoe UI", 9, QFont.Weight.Black))
        self._eye.setStyleSheet("QLabel { background: transparent; border: none; }")

        lay.addWidget(self._lbl, 0)
        lay.addStretch(1)
        lay.addWidget(self._eye, 0)
        self._apply()

    def set_masked(self, on: bool) -> None:
        self._masked = bool(on)
        self._apply()

    def _apply(self) -> None:
        accent = self._accent
        if self._masked:
            self.setStyleSheet(
                f"#VTHeaderCell {{ background:{_rgba(accent, 0.16)}; "
                f"border:1px solid {accent}; border-radius:10px; }}"
            )
            self._lbl.setStyleSheet(f"QLabel {{ color:{accent}; background:transparent; border:none; }}")
            self._eye.setText("hidden")
            self._eye.setStyleSheet(f"QLabel {{ color:{accent}; background:transparent; border:none; }}")
            self.setToolTip(f"Show the {self._title} column")
        else:
            self.setStyleSheet(
                "#VTHeaderCell { background:#1A1A1A; border:1px solid #2E2E2E; border-radius:10px; }"
            )
            self._lbl.setStyleSheet(f"QLabel {{ color:{accent}; background:transparent; border:none; }}")
            self._eye.setText("")
            self.setToolTip(f"Hide the {self._title} column")

    def mouseReleaseEvent(self, event):
        try:
            inside = self.rect().contains(event.position().toPoint())
        except Exception:
            inside = True
        if event.button() == Qt.LeftButton and inside and callable(self._on_click):
            self._on_click()
        super().mouseReleaseEvent(event)


class _MaskCell(QFrame):
    """One data cell. When its column is hidden it shows "• • •" and a single
    click reveals (or re-hides) just this entry. Cells with no value render a
    muted dash and never react to clicks."""

    def __init__(self, text: str, accent: str, *, striped: bool, emphasize: bool):
        super().__init__()
        self._text = (text or "").strip()
        self._accent = accent
        self._striped = striped
        self._emphasize = emphasize          # the Vocab column reads as the headword
        self._has = bool(self._text)
        self._masked = False
        self._revealed = False
        self.setObjectName("VTMaskCell")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(42)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 7, 12, 7)
        lay.setSpacing(0)
        self._lbl = QLabel(self._text or "—")
        self._lbl.setWordWrap(True)
        self._lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lay.addWidget(self._lbl)
        self._apply()

    def set_masked(self, on: bool) -> None:
        self._masked = bool(on)
        if not on:
            self._revealed = False
        self._apply()

    def _hidden_now(self) -> bool:
        return self._masked and self._has and not self._revealed

    def mouseReleaseEvent(self, event):
        try:
            inside = self.rect().contains(event.position().toPoint())
        except Exception:
            inside = True
        if event.button() == Qt.LeftButton and inside and self._masked and self._has:
            self._revealed = not self._revealed
            self._apply()
        super().mouseReleaseEvent(event)

    def _apply(self) -> None:
        accent = self._accent
        base_bg = "#161616" if self._striped else "#121212"
        weight = QFont.Weight.Black if self._emphasize else QFont.Weight.DemiBold
        self._lbl.setFont(QFont("Segoe UI", 11, weight))

        if not self._has:
            # Nothing to recall here — a quiet placeholder, not interactive.
            self.setCursor(QCursor(Qt.ArrowCursor))
            self.setToolTip("")
            self.setStyleSheet(
                f"#VTMaskCell {{ background:{base_bg}; border:1px solid #232323; border-radius:8px; }}"
            )
            self._lbl.setText("—")
            self._lbl.setStyleSheet("QLabel { color:#4E4E4E; background:transparent; border:none; }")
            return

        if self._hidden_now():
            self.setCursor(QCursor(Qt.PointingHandCursor))
            self.setToolTip("Tap to reveal")
            self.setStyleSheet(
                f"#VTMaskCell {{ background:{_rgba(accent, 0.05)}; "
                f"border:1px dashed {_rgba(accent, 0.55)}; border-radius:8px; }}"
            )
            self._lbl.setText(_HIDDEN_GLYPH)
            self._lbl.setStyleSheet(f"QLabel {{ color:{_rgba(accent, 0.65)}; background:transparent; border:none; }}")
            return

        if self._masked and self._revealed:
            # Peeked: show the real value, tinted so it reads as "just checked".
            self.setCursor(QCursor(Qt.PointingHandCursor))
            self.setToolTip("Tap to hide again")
            self.setStyleSheet(
                f"#VTMaskCell {{ background:{_rgba(accent, 0.12)}; "
                f"border:1px solid {accent}; border-radius:8px; }}"
            )
            self._lbl.setText(self._text)
            self._lbl.setStyleSheet(f"QLabel {{ color:{accent}; background:transparent; border:none; }}")
            return

        # Plain visible cell.
        self.setCursor(QCursor(Qt.ArrowCursor))
        self.setToolTip("")
        self.setStyleSheet(
            f"#VTMaskCell {{ background:{base_bg}; border:1px solid #262626; border-radius:8px; }}"
        )
        self._lbl.setText(self._text)
        color = "#FFFFFF" if self._emphasize else "#E2E2E2"
        self._lbl.setStyleSheet(f"QLabel {{ color:{color}; background:transparent; border:none; }}")


class _StaticHeader(QFrame):
    """A non-interactive column header — used for the informational POS column,
    which has no hide/reveal mechanism."""

    def __init__(self, title: str, accent: str):
        super().__init__()
        self.setObjectName("VTStaticHeader")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "#VTStaticHeader { background:#151515; border:1px solid #262626; border-radius:10px; }"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(0)
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
        lbl.setStyleSheet(f"QLabel {{ color:{accent}; background:transparent; border:none; }}")
        lay.addWidget(lbl)


class _PosCell(QFrame):
    """The trailing part-of-speech tag. Muted and static for most words; for
    verbs it becomes a clickable chip ("Verb ⤳") that opens the conjugation
    tab for that verb."""

    _VERB_ACCENT = "#8AB4FF"

    def __init__(self, text: str, *, striped: bool, on_conjugate=None):
        super().__init__()
        self.setObjectName("VTPosCell")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(42)
        self._striped = striped
        self._on_conjugate = on_conjugate
        self._interactive = callable(on_conjugate)
        self._hover = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 7, 12, 7)
        lay.setSpacing(0)
        t = (text or "").strip()
        if self._interactive:
            self.setCursor(QCursor(Qt.PointingHandCursor))
            self.setToolTip("Show full conjugation")
            disp = (t.capitalize() if t else "Verb") + "   ⤳"
        else:
            disp = t.capitalize() if t else "—"
        self._lbl = QLabel(disp)
        self._lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Black if self._interactive else QFont.Weight.DemiBold))
        self._lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lay.addWidget(self._lbl)
        self._has = bool(t)
        self._apply()

    def _apply(self) -> None:
        base_bg = "#151515" if self._striped else "#111111"
        if self._interactive:
            accent = self._VERB_ACCENT
            bg = _rgba(accent, 0.16 if self._hover else 0.09)
            border = accent if self._hover else _rgba(accent, 0.55)
            self.setStyleSheet(f"#VTPosCell {{ background:{bg}; border:1px solid {border}; border-radius:8px; }}")
            self._lbl.setStyleSheet(f"QLabel {{ color:{accent}; background:transparent; border:none; }}")
        else:
            self.setStyleSheet(f"#VTPosCell {{ background:{base_bg}; border:1px solid #232323; border-radius:8px; }}")
            self._lbl.setStyleSheet(
                f"QLabel {{ color:{'#9AA0A6' if self._has else '#4E4E4E'}; background:transparent; border:none; }}"
            )

    def enterEvent(self, event):
        if self._interactive:
            self._hover = True
            self._apply()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._interactive:
            self._hover = False
            self._apply()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        try:
            inside = self.rect().contains(event.position().toPoint())
        except Exception:
            inside = True
        if self._interactive and event.button() == Qt.LeftButton and inside:
            self._on_conjugate()
        super().mouseReleaseEvent(event)


class VocabTablePage(QWidget):
    go_back = Signal()
    conjugate_verb = Signal(str, str)   # (infinitive, meaning) — open the conjugation tab

    def __init__(self, session, nav=None):
        super().__init__()
        self.session = session
        self.nav = nav

        self.setObjectName("VocabTablePage")
        self.setFont(QFont("Segoe UI", 10))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "#VocabTablePage { background-color:#0E0E0E; }"
            "#VocabTablePage QLabel { background: transparent; }"
        )

        # Persisted across visits so a chosen hide-layout survives navigation.
        self._masked: dict[str, bool] = {key: False for key, _t, _a in _COLUMNS}
        self._headers: dict[str, _HeaderCell] = {}
        self._cells: dict[str, list[_MaskCell]] = {key: [] for key, _t, _a in _COLUMNS}
        self._toggle_btns: dict[str, QPushButton] = {}
        self._pos_cells: list[_PosCell] = []   # informational column; not maskable

        self._build_ui()
        self._load()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)

        # ---- Top bar (mirrors the review pages) ----
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
        self.page_title = QLabel("Vocab Table")
        self.page_title.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:20px; font-weight:950; border:none; background:transparent; }"
        )
        self.page_subtitle = QLabel("Self-quiz the vocabulary, column by column")
        self.page_subtitle.setStyleSheet(
            "QLabel { color:#9A9A9A; font-size:11px; font-weight:700; border:none; background:transparent; }"
        )
        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)
        tb.addLayout(title_col)
        tb.addStretch(1)

        self.count_chip = QLabel("0 words")
        self.count_chip.setAlignment(Qt.AlignCenter)
        self.count_chip.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:12px; font-weight:800; background:#1A1A1A; "
            "border:1px solid #2E2E2E; border-radius:8px; padding:6px 12px; }"
        )
        self.back_btn = QPushButton("← Back")
        self.back_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.back_btn.setStyleSheet(
            "QPushButton { background-color:#1B1B1B; color:#FFFFFF; border:1px solid #2E2E2E; "
            "border-radius:10px; padding:8px 12px; font-weight:800; font-size:12px; }"
            "QPushButton:hover { border:1px solid #FFFFFF; background-color:#232323; }"
        )
        self.back_btn.clicked.connect(self.go_back.emit)
        tb.addWidget(self.count_chip)
        tb.addWidget(self.back_btn)
        outer.addWidget(self.top_bar)

        # ---- Controls card: instruction + per-column hide toggles ----
        self.controls = QFrame()
        self.controls.setObjectName("ControlsCard")
        self.controls.setStyleSheet(
            "QFrame#ControlsCard { background-color:#131313; border:1px solid #262626; border-radius:14px; }"
        )
        cc = QVBoxLayout(self.controls)
        cc.setContentsMargins(14, 12, 14, 12)
        cc.setSpacing(10)

        hint = QLabel("Hide a column, recall each entry from memory, then tap a hidden cell to check yourself.")
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel { color:#8C8C8C; font-size:11px; font-weight:600; border:none; background:transparent; }")
        cc.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for key, title, accent in _COLUMNS:
            b = QPushButton()
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _=False, k=key: self._toggle_column(k))
            self._toggle_btns[key] = b
            btn_row.addWidget(b, 1)

        self.show_all_btn = QPushButton("Show all")
        self.show_all_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.show_all_btn.setMinimumHeight(34)
        self.show_all_btn.setStyleSheet(
            "QPushButton { background-color:#1B1B1B; color:#CFCFCF; border:1px solid #2E2E2E; "
            "border-radius:10px; padding:7px 14px; font-weight:800; font-size:12px; }"
            "QPushButton:hover { border:1px solid #FFFFFF; color:#FFFFFF; }"
        )
        self.show_all_btn.clicked.connect(self._show_all)
        btn_row.addWidget(self.show_all_btn, 0)
        cc.addLayout(btn_row)
        outer.addWidget(self.controls)

        # ---- Table card: header row + scrollable body, one shared grid so the
        # columns always line up exactly. ----
        self.table_card = QFrame()
        self.table_card.setObjectName("TableCard")
        self.table_card.setStyleSheet(
            "QFrame#TableCard { background-color:#101010; border:1px solid #262626; border-radius:16px; }"
        )
        tcl = QVBoxLayout(self.table_card)
        tcl.setContentsMargins(12, 12, 12, 12)
        tcl.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.grid_host = QWidget()
        self.grid_host.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 6, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(6)
        for col, (key, _t, _a) in enumerate(_COLUMNS):
            self.grid.setColumnStretch(col, _COL_STRETCH[key])
        self.grid.setColumnStretch(len(_COLUMNS), _POS_STRETCH)  # trailing POS column
        self.scroll.setWidget(self.grid_host)

        tcl.addWidget(self.scroll, 1)

        # Empty-state label (shown instead of the table when there is no vocab).
        self.empty_lbl = QLabel("No vocabulary in this Lektion yet.")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setStyleSheet("QLabel { color:#6B6B6B; font-size:13px; font-weight:700; border:none; background:transparent; }")
        self.empty_lbl.hide()
        tcl.addWidget(self.empty_lbl)

        outer.addWidget(self.table_card, 1)

    # --------------------------------------------------------------- data
    def on_show(self) -> None:
        self._load()

    def _load(self) -> None:
        try:
            rows = self.session.vocab_table_rows()
        except Exception:
            rows = []

        # Subtitle: the live context path, like the review pages.
        try:
            ctx = self.session.context_label()
        except Exception:
            ctx = ""
        self.page_subtitle.setText(ctx or "Self-quiz the vocabulary, column by column")
        n = len(rows)
        self.count_chip.setText("1 word" if n == 1 else f"{n} words")

        self._rebuild_grid(rows)
        # Re-apply (persisted) hidden columns and refresh the toggle buttons.
        for key, _t, _a in _COLUMNS:
            self._apply_column(key)

        has = n > 0
        self.scroll.setVisible(has)
        self.empty_lbl.setVisible(not has)
        self.controls.setEnabled(has)

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._headers.clear()
        for key in self._cells:
            self._cells[key] = []
        self._pos_cells = []

    def _rebuild_grid(self, rows: list[dict]) -> None:
        self._clear_grid()
        pos_col = len(_COLUMNS)

        # Row 0: clickable headers for the quiz columns, plus a static POS header.
        for col, (key, title, accent) in enumerate(_COLUMNS):
            header = _HeaderCell(title, accent, on_click=lambda k=key: self._toggle_column(k))
            self._headers[key] = header
            self.grid.addWidget(header, 0, col)
        self.grid.addWidget(_StaticHeader(_POS_TITLE, _POS_ACCENT), 0, pos_col)

        # Data rows.
        for r, row in enumerate(rows, start=1):
            striped = (r % 2) == 0
            for col, (key, _title, accent) in enumerate(_COLUMNS):
                cell = _MaskCell(
                    str(row.get(key, "") or ""),
                    accent,
                    striped=striped,
                    emphasize=(key == "word"),
                )
                self._cells[key].append(cell)
                self.grid.addWidget(cell, r, col)
            # Trailing part-of-speech tag. For verbs it's a clickable chip that
            # opens the conjugation tab for that verb.
            pos_val = str(row.get("pos", "") or "").strip().lower()
            on_conj = None
            if pos_val == "verb":
                word = str(row.get("word", "") or "")
                meaning = str(row.get("meaning", "") or "")
                on_conj = (lambda w=word, m=meaning: self.conjugate_verb.emit(w, m))
            pos_cell = _PosCell(str(row.get("pos", "") or ""), striped=striped, on_conjugate=on_conj)
            self._pos_cells.append(pos_cell)
            self.grid.addWidget(pos_cell, r, pos_col)

        # Keep the rows pinned to the top when the deck is short.
        self.grid.setRowStretch(len(rows) + 1, 1)

    # ------------------------------------------------------------- masking
    def _toggle_column(self, key: str) -> None:
        self._masked[key] = not self._masked.get(key, False)
        self._apply_column(key)

    def _show_all(self) -> None:
        for key, _t, _a in _COLUMNS:
            self._masked[key] = False
            self._apply_column(key)

    def _apply_column(self, key: str) -> None:
        on = bool(self._masked.get(key, False))
        header = self._headers.get(key)
        if header is not None:
            header.set_masked(on)
        for cell in self._cells.get(key, []):
            cell.set_masked(on)
        self._sync_toggle(key)

    def _sync_toggle(self, key: str) -> None:
        btn = self._toggle_btns.get(key)
        if btn is None:
            return
        title = next((t for k, t, _a in _COLUMNS if k == key), key)
        accent = next((a for k, _t, a in _COLUMNS if k == key), "#66E39A")
        on = bool(self._masked.get(key, False))
        if on:
            btn.setText(f"Show {title}")
            btn.setStyleSheet(
                f"QPushButton {{ background-color:{accent}; color:#0B0B0B; border:1px solid {accent}; "
                f"border-radius:10px; padding:7px 12px; font-weight:900; font-size:12px; }}"
                f"QPushButton:hover {{ border:1px solid #FFFFFF; }}"
            )
        else:
            btn.setText(f"Hide {title}")
            btn.setStyleSheet(
                f"QPushButton {{ background-color:#1B1B1B; color:{accent}; border:1px solid #2E2E2E; "
                f"border-radius:10px; padding:7px 12px; font-weight:800; font-size:12px; }}"
                f"QPushButton:hover {{ border:1px solid {accent}; background-color:#202020; }}"
            )

    # ---------------------------------------------------------- focus mode
    def set_focus_mode(self, on: bool) -> None:
        """Focus/Zen mode: drop the chrome and leave just the table."""
        try:
            self.top_bar.setVisible(not bool(on))
            self.controls.setVisible(not bool(on))
        except Exception:
            pass
