from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QScrollArea,
    QGridLayout,
    QHBoxLayout,
    QFrame,
    QStackedWidget,
    QSizePolicy,
)

CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

# Page indices inside the stacked widget
_PAGE_LEVEL   = 0
_PAGE_BOOK    = 1
_PAGE_LEKTION = 2
_PAGE_OBJ     = 3


def _norm_level(level: str) -> str:
    return (level or "").strip().upper()


def _norm_objective(obj: str) -> str:
    return (obj or "").strip().lower()


def _fmt_int(n: int) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


_ACCENT_VOCAB     = "#66E39A"
_ACCENT_GRAMMAR   = "#B983FF"
_ACCENT_SENTENCES = "#FFB020"

# Stable accent palette for book cards (varied so books are visually distinct)
_BOOK_ACCENTS = ["#6B9FFF", "#66E39A", "#FFD166", "#FF6B9A", "#B983FF", "#4DD0E1", "#FFA07A"]


def _accent_for_index(i: int) -> str:
    return _BOOK_ACCENTS[i % len(_BOOK_ACCENTS)]


def _make_chip(text: str, color: str = "#D7DAE0") -> QLabel:
    """Small rounded info pill used inside cards."""
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
    lbl.setStyleSheet(
        f"QLabel {{ color:{color}; border:1px solid #2E2E2E; "
        f"background:#101010; border-radius:9px; padding:3px 9px; }}"
    )
    return lbl


def _book_initials(title: str) -> str:
    """Up to two uppercase initials for a book's cover tile."""
    words = [w for w in (title or "").split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


_GROUPBOX_STYLE = """
    QGroupBox {
        color: #FFFFFF;
        border: 1px solid #2E2E2E;
        border-radius: 12px;
        margin-top: 10px;
        padding-top: 12px;
        background-color: #151515;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 16px;
        padding: 0 10px 0 10px;
    }
"""


class ObjectiveSelectCard(QFrame):
    def __init__(self, *, title: str, accent: str, on_start):
        super().__init__()
        self._accent = accent
        self._on_start = on_start

        self.setMinimumHeight(86)
        self.setMaximumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.setStyleSheet("""
            QFrame {
                background-color: #141414;
                border: 1px solid #2B2B2B;
                border-radius: 16px;
            }
            QLabel { background: transparent; border: none; }
            QWidget { background: transparent; }
        """)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QFrame()
        bar.setFixedWidth(6)
        bar.setStyleSheet(
            f"QFrame {{ background-color: {accent}; border-top-left-radius: 16px; border-bottom-left-radius: 16px; }}"
        )
        outer.addWidget(bar)

        body = QWidget()
        outer.addWidget(body, 1)

        lay = QHBoxLayout(body)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.title_lbl = QLabel(title)
        self.title_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
        self.title_lbl.setStyleSheet(f"QLabel {{ color: {accent}; font-weight: 900; }}")

        self.meta_badge = QLabel("")
        self.meta_badge.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.meta_badge.setAlignment(Qt.AlignCenter)
        self.meta_badge.setStyleSheet("""
            QLabel {
                color: #D7DAE0;
                border: 1px solid #2E2E2E;
                background-color: #101010;
                border-radius: 10px;
                padding: 4px 10px;
            }
        """)

        top_row.addWidget(self.title_lbl, 0)
        top_row.addStretch(1)
        top_row.addWidget(self.meta_badge, 0)

        left.addLayout(top_row)
        left.addStretch(1)
        lay.addLayout(left, 1)

        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedHeight(36)
        self.start_btn.setMinimumWidth(96)
        self.start_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Black))
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {accent};
                color: #0B0B0B;
                border: 1px solid #2E2E2E;
                border-radius: 12px;
                padding: 6px 14px;
                font-weight: 900;
            }}
            QPushButton:hover {{ border: 1px solid #FFFFFF; }}
            QPushButton:disabled {{
                background-color:#101010;
                color:#6B6B6B;
                border:1px solid #252525;
            }}
        """)
        self.start_btn.clicked.connect(self._on_start_clicked)
        lay.addWidget(self.start_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def _on_start_clicked(self):
        self._on_start()

    def set_meta(self, text: str):
        self.meta_badge.setText(text or "")
        self.meta_badge.setVisible(bool(text and text.strip()))

    def set_enabled(self, enabled: bool):
        self.start_btn.setEnabled(enabled)


class _ClickCard(QFrame):
    """
    A QFrame that behaves like a button: the whole surface is clickable and
    hover state is driven in code (enter/leave) so child accents — the left
    bar, chevron, badge — can all react together, not just the outer border.
    """

    def __init__(self, on_click):
        super().__init__()
        self._on_click = on_click
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def enterEvent(self, event):
        self._hover = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._apply_style()
        super().leaveEvent(event)

    def _apply_style(self):  # overridden by subclasses
        pass

    def mouseReleaseEvent(self, event):
        try:
            inside = self.rect().contains(event.position().toPoint())
        except Exception:
            inside = True
        if event.button() == Qt.LeftButton and inside and callable(self._on_click):
            self._on_click()
        super().mouseReleaseEvent(event)


class BookCard(_ClickCard):
    def __init__(self, *, title, level, lektion_count, vocab_n, grammar_n, sentences_n, accent, selected, on_click):
        super().__init__(on_click)
        self._accent = accent
        self._selected = selected
        self.setObjectName("BookCard")
        self.setMinimumHeight(118)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._bar = QFrame()
        self._bar.setFixedWidth(6)
        outer.addWidget(self._bar)

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        outer.addWidget(body, 1)

        lay = QHBoxLayout(body)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)

        # Book "cover" tile with initials
        self._cover = QLabel(_book_initials(title))
        self._cover.setAlignment(Qt.AlignCenter)
        self._cover.setFixedSize(52, 66)
        self._cover.setFont(QFont("Segoe UI", 17, QFont.Weight.Black))
        lay.addWidget(self._cover, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Black))
        title_lbl.setStyleSheet("QLabel { color: #FFFFFF; font-weight: 900; background: transparent; border: none; }")
        text_col.addWidget(title_lbl)

        # Meta row: level badge + Lektionen count
        meta = QHBoxLayout()
        meta.setSpacing(8)
        lvl_badge = QLabel((level or "").upper())
        lvl_badge.setFont(QFont("Segoe UI", 9, QFont.Weight.Black))
        lvl_badge.setStyleSheet(
            f"QLabel {{ color:#0B0B0B; background:{accent}; border-radius:8px; "
            f"padding:2px 9px; font-weight:900; }}"
        )
        meta.addWidget(lvl_badge)
        lek_word = "Lektion" if lektion_count == 1 else "Lektionen"
        meta.addWidget(_make_chip(f"{lektion_count} {lek_word}"))
        meta.addStretch(1)
        text_col.addLayout(meta)

        # Color-coded content totals (consistent with the Lektion cards)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        if vocab_n:
            chips.addWidget(_make_chip(f"{_fmt_int(vocab_n)} Vocab", _ACCENT_VOCAB))
        if grammar_n:
            chips.addWidget(_make_chip(f"{_fmt_int(grammar_n)} Grammar", _ACCENT_GRAMMAR))
        if sentences_n:
            chips.addWidget(_make_chip(f"{_fmt_int(sentences_n)} Sentences", _ACCENT_SENTENCES))
        chips.addStretch(1)
        text_col.addLayout(chips)

        lay.addLayout(text_col, 1)

        self._chevron = QLabel("›")
        self._chevron.setFont(QFont("Segoe UI", 24, QFont.Weight.Black))
        lay.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply_style()

    def _apply_style(self):
        accent = self._accent
        if self._hover:
            border, bg, bar, chev = f"2px solid {accent}", "#1C1C1C", "#FFFFFF", "#FFFFFF"
        elif self._selected:
            border, bg, bar, chev = f"2px solid {accent}", "#181818", accent, "#FFFFFF"
        else:
            border, bg, bar, chev = "1px solid #2B2B2B", "#141414", accent, "#6B6B6B"

        self.setStyleSheet(
            f"#BookCard {{ background-color: {bg}; border: {border}; border-radius: 16px; }}"
        )
        self._bar.setStyleSheet(
            f"QFrame {{ background-color: {bar}; "
            f"border-top-left-radius: 15px; border-bottom-left-radius: 15px; }}"
        )
        # Book-spine style cover: subtle vertical gradient in the book's accent.
        self._cover.setStyleSheet(
            f"QLabel {{ color: #FFFFFF; border: 1px solid {accent}; border-radius: 8px; "
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {accent}, stop:1 rgba(10,10,10,0.85)); }}"
        )
        self._chevron.setStyleSheet(f"QLabel {{ color: {chev}; background: transparent; border: none; }}")


class LektionCard(_ClickCard):
    _ACCENT = "#6B9FFF"

    def __init__(self, *, number, title, topic, vocab_n, grammar_n, sentences_n, selected, on_click):
        super().__init__(on_click)
        self._selected = selected
        self.setObjectName("LektionCard")
        # Compact + fixed height so a full book of Lektionen fits a 2-column grid
        # without scrolling. Lead with the real Lektion name, then its topic.
        self.setMinimumHeight(94)
        self.setMaximumHeight(100)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 14, 9)
        lay.setSpacing(12)

        # Round number badge
        self._badge = QLabel(str(number))
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setFixedSize(40, 40)
        self._badge.setFont(QFont("Segoe UI", 14, QFont.Weight.Black))
        lay.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)

        title_lbl = QLabel(title or f"Lektion {number}")
        title_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Black))
        title_lbl.setStyleSheet("QLabel { color: #FFFFFF; font-weight: 900; background: transparent; border: none; }")
        text_col.addWidget(title_lbl)

        if topic:
            topic_lbl = QLabel(topic)
            topic_lbl.setFont(QFont("Segoe UI", 9))
            topic_lbl.setWordWrap(True)
            topic_lbl.setMaximumHeight(30)
            topic_lbl.setStyleSheet("QLabel { color: #9AA0A6; background: transparent; border: none; }")
            text_col.addWidget(topic_lbl)

        # Compact, color-coded counts on a single line (rich text).
        bits = []
        if vocab_n:
            bits.append(f'<span style="color:{_ACCENT_VOCAB}">{vocab_n} Vocab</span>')
        if grammar_n:
            bits.append(f'<span style="color:{_ACCENT_GRAMMAR}">{grammar_n} Grammar</span>')
        if sentences_n:
            bits.append(f'<span style="color:{_ACCENT_SENTENCES}">{sentences_n} Sentences</span>')
        if bits:
            counts = QLabel("&nbsp;&nbsp;·&nbsp;&nbsp;".join(bits))
            counts.setTextFormat(Qt.RichText)
            counts.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            counts.setStyleSheet("QLabel { color: #6B6B6B; background: transparent; border: none; }")
            text_col.addWidget(counts)

        text_col.addStretch(1)
        lay.addLayout(text_col, 1)

        self._apply_style()

    def _apply_style(self):
        accent = self._ACCENT
        if self._hover:
            border, bg = f"2px solid {accent}", "#1C2230"
        elif self._selected:
            border, bg = f"2px solid {accent}", "#1A1F2E"
        else:
            border, bg = "1px solid #2B2B2B", "#141414"

        self.setStyleSheet(
            f"#LektionCard {{ background-color: {bg}; border: {border}; border-radius: 14px; }}"
        )
        badge_bg = "#FFFFFF" if self._hover else accent
        self._badge.setStyleSheet(
            f"QLabel {{ background-color: {badge_bg}; color: #0B0B0B; "
            f"border-radius: 20px; font-weight: 900; }}"
        )


class SetupPage(QWidget):
    start_practice = Signal()

    def __init__(self, session, nav=None):
        super().__init__()
        self.session = session
        self.nav = nav

        self.setFont(QFont("Segoe UI", 10))
        self.setObjectName("SetupPage")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet("""
            #SetupPage { background-color: #0F0F0F; color: #E6E6E6; }
            #SetupPage QLabel { background: transparent; }
            #SetupPage QScrollArea { background: transparent; border: none; }
            #SetupPage QStackedWidget { background: transparent; }
        """)

        self.level: Optional[str] = None
        self.book_slug: Optional[str] = None
        self.lektion_number: Optional[int] = None
        self.objective: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)

        self.back_btn = QPushButton("← Back")
        self.back_btn.setFixedHeight(36)
        self.back_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.back_btn.setStyleSheet("""
            QPushButton {
                background-color: #1B1B1B;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 6px 10px;
                font-weight: 700;
            }
            QPushButton:hover { border: 1px solid #FFFFFF; background-color:#232323; }
            QPushButton:disabled {
                background-color: #101010;
                color: #6B6B6B;
                border: 1px solid #252525;
            }
        """)
        self.back_btn.clicked.connect(self._back)

        self.title = QLabel("Setup")
        self.title.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
        self.title.setStyleSheet("QLabel { color:#FFFFFF; }")

        self.breadcrumb = QLabel(" ")
        self.breadcrumb.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        self.breadcrumb.setStyleSheet("""
            QLabel {
                color: #B0B0B0;
                padding: 6px 10px;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                background-color: #151515;
            }
        """)

        header.addWidget(self.back_btn, 0)
        header.addWidget(self.title, 0)
        header.addStretch(1)
        header.addWidget(self.breadcrumb, 0)
        root.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        root.addWidget(self.stack, 1)

        self.page_level   = self._make_level_page()
        self.page_book    = self._make_book_page()
        self.page_lektion = self._make_lektion_page()
        self.page_obj     = self._make_objective_page()

        self.stack.addWidget(self.page_level)   # 0
        self.stack.addWidget(self.page_book)    # 1
        self.stack.addWidget(self.page_lektion) # 2
        self.stack.addWidget(self.page_obj)     # 3

        self._sync_from_state()
        self._goto(self.stack.currentIndex() or 0)
        self._refresh_levels_enabled()
        self._refresh_books()
        self._refresh_lektions()
        self._refresh_objectives()

        QTimer.singleShot(0, self._post_init_refresh)

    def _post_init_refresh(self):
        self._sync_from_state()
        self._refresh_levels_enabled()
        self._refresh_books()
        self._refresh_lektions()
        self._refresh_objectives()
        self._coerce_step_to_state()
        self._update_breadcrumb()

    def on_show(self):
        self._sync_from_state()
        self._refresh_levels_enabled()
        self._refresh_books()
        self._refresh_lektions()
        self._refresh_objectives()
        self._coerce_step_to_state()
        self._update_breadcrumb()

    def _goto(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self.back_btn.setEnabled(idx != _PAGE_LEVEL)
        self._update_breadcrumb()

    def _back(self):
        idx = self.stack.currentIndex()
        if idx == _PAGE_OBJ:
            self._goto(_PAGE_LEKTION)
        elif idx == _PAGE_LEKTION:
            self._goto(_PAGE_BOOK)
        elif idx == _PAGE_BOOK:
            self._goto(_PAGE_LEVEL)

    def _coerce_step_to_state(self):
        idx = self.stack.currentIndex()
        if idx >= _PAGE_BOOK and not self.level:
            self._goto(_PAGE_LEVEL)
            return
        if idx >= _PAGE_LEKTION and not self.book_slug:
            self._goto(_PAGE_BOOK)
            return
        if idx >= _PAGE_OBJ and not self.lektion_number:
            self._goto(_PAGE_LEKTION)
            return

    def _update_breadcrumb(self):
        parts = []
        if self.level:
            parts.append(self.level)
        if self.book_slug:
            parts.append(" ".join(w.capitalize() for w in self.book_slug.split("_")))
        if self.lektion_number:
            parts.append(f"Lektion {self.lektion_number}")
        if self.objective:
            label = {
                "vocab": "Vocabulary",
                "grammar": "Grammar",
                "sentences": "Sentences",
            }.get(self.objective, self.objective)
            parts.append(label)
        self.breadcrumb.setText("  •  ".join(parts) if parts else " ")

    def _sync_from_state(self):
        self.level = _norm_level(getattr(self.session.state, "level", "") or "") or None
        self.book_slug = (getattr(self.session.state, "book_slug", "") or "").strip() or None
        ln = getattr(self.session.state, "lektion_number", 0) or 0
        self.lektion_number = int(ln) if ln else None
        obj = _norm_objective(getattr(self.session.state, "objective", "") or "")
        self.objective = obj or None

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------
    def _deck_id(self, level: str, objective: str, lektion_id: int | None = None) -> Optional[int]:
        try:
            return self.session.repo.get_deck_id(level, objective, lektion_id=lektion_id)
        except Exception:
            return None

    def _count_table(self, table: str, deck_id: int) -> int:
        try:
            with self.session.repo._conn() as conn:
                row = conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE deck_id=?", (deck_id,)).fetchone()
            return int(row["c"]) if row else 0
        except Exception:
            return 0

    def _current_lektion_id(self) -> Optional[int]:
        if not self.book_slug or not self.lektion_number:
            return None
        try:
            book_id = self.session.repo.get_book_id(self.book_slug)
            if book_id is None:
                return None
            return self.session.repo.get_lektion_id(book_id, self.level, self.lektion_number)
        except Exception:
            return None

    def _book_summary(self, book_id: int, level: str) -> tuple[int, int, int, int]:
        """Return (lektion_count, vocab_n, grammar_n, sentences_n) for a book at a level."""
        try:
            with self.session.repo._conn() as conn:
                row = conn.execute(
                    """
                    SELECT
                        (SELECT COUNT(DISTINCT l.id) FROM lektions l JOIN decks d ON d.lektion_id=l.id
                         WHERE l.book_id=? AND l.level=? AND d.level=?) AS lek,
                        (SELECT COUNT(*) FROM vocab v JOIN decks d ON v.deck_id=d.id
                         JOIN lektions l ON d.lektion_id=l.id WHERE l.book_id=? AND d.level=?) AS vocab_n,
                        (SELECT COUNT(*) FROM grammar g JOIN decks d ON g.deck_id=d.id
                         JOIN lektions l ON d.lektion_id=l.id WHERE l.book_id=? AND d.level=?) AS grammar_n,
                        (SELECT COUNT(*) FROM sentences s JOIN decks d ON s.deck_id=d.id
                         JOIN lektions l ON d.lektion_id=l.id WHERE l.book_id=? AND d.level=?) AS sentences_n
                    """,
                    (book_id, level, level, book_id, level, book_id, level, book_id, level),
                ).fetchone()
            return (
                int(row["lek"] or 0),
                int(row["vocab_n"] or 0),
                int(row["grammar_n"] or 0),
                int(row["sentences_n"] or 0),
            )
        except Exception:
            return 0, 0, 0, 0

    def _lektion_summaries(self, book_id: int, level: str) -> list:
        """Return per-lektion rows (number, title, vocab_n, grammar_n, sentences_n)."""
        try:
            with self.session.repo._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT l.number AS number, l.title AS title, l.description AS topic,
                        (SELECT COUNT(*) FROM vocab v JOIN decks d ON v.deck_id=d.id
                         WHERE d.lektion_id=l.id AND d.level=?) AS vocab_n,
                        (SELECT COUNT(*) FROM grammar g JOIN decks d ON g.deck_id=d.id
                         WHERE d.lektion_id=l.id AND d.level=?) AS grammar_n,
                        (SELECT COUNT(*) FROM sentences s JOIN decks d ON s.deck_id=d.id
                         WHERE d.lektion_id=l.id AND d.level=?) AS sentences_n
                    FROM lektions l
                    WHERE l.book_id=? AND l.level=?
                      AND EXISTS (SELECT 1 FROM decks d WHERE d.lektion_id=l.id AND d.level=?)
                    ORDER BY l.number
                    """,
                    (level, level, level, book_id, level, level),
                ).fetchall()
            return list(rows)
        except Exception:
            return []

    def _clear_vbox(self, vbox: QVBoxLayout):
        while vbox.count():
            item = vbox.takeAt(0)
            ww = item.widget()
            if ww is not None:
                ww.deleteLater()

    # ------------------------------------------------------------------
    # Page: CEFR Level
    # ------------------------------------------------------------------
    def _make_level_page(self) -> QWidget:
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("Select CEFR Level")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("QLabel { color:#FFFFFF; }")
        lay.addWidget(title)

        group = QGroupBox("Levels")
        group.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        group.setStyleSheet(_GROUPBOX_STYLE)

        grid = QGridLayout(group)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setSpacing(10)

        self.level_buttons: Dict[str, QPushButton] = {}
        for i, lvl in enumerate(CEFR_LEVELS):
            b = QPushButton(lvl)
            b.setMinimumSize(110, 58)
            b.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
            b.setStyleSheet("""
                QPushButton {
                    background-color: #151515;
                    color: #FFFFFF;
                    border: 2px solid #2E2E2E;
                    border-radius: 12px;
                    padding: 10px;
                    font-weight: 900;
                }
                QPushButton:hover { border: 2px solid #FFFFFF; background-color: #1B1B1B; }
                QPushButton:disabled {
                    background-color: #101010;
                    color: #6B6B6B;
                    border: 1px solid #252525;
                }
            """)
            b.clicked.connect(lambda checked=False, l=lvl: self._choose_level(l))
            self.level_buttons[lvl] = b
            grid.addWidget(b, i // 3, i % 3)

        lay.addWidget(group, 1)
        return w

    def _refresh_levels_enabled(self):
        for lvl, btn in self.level_buttons.items():
            try:
                has = self.session.repo.has_decks_for_level(lvl)
            except Exception:
                has = False
            btn.setEnabled(has)

    def _choose_level(self, lvl: str):
        lvl = _norm_level(lvl)
        if lvl not in CEFR_LEVELS:
            return
        self.session.state.level = lvl
        self.session.state.book_slug = ""
        self.session.state.lektion_number = 0
        self.session.state.objective = ""
        self._sync_from_state()
        self._refresh_levels_enabled()
        self._refresh_books()
        self._goto(_PAGE_BOOK)

    # ------------------------------------------------------------------
    # Page: Book
    # ------------------------------------------------------------------
    def _make_book_page(self) -> QWidget:
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("Select Book")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("QLabel { color:#FFFFFF; }")
        lay.addWidget(title)

        group = QGroupBox("Available Books")
        group.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        group.setStyleSheet(_GROUPBOX_STYLE)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self.book_layout = QVBoxLayout(inner)
        self.book_layout.setContentsMargins(16, 16, 16, 16)
        self.book_layout.setSpacing(10)
        scroll.setWidget(inner)

        g_lay = QVBoxLayout(group)
        g_lay.setContentsMargins(0, 0, 0, 0)
        g_lay.addWidget(scroll)

        lay.addWidget(group, 1)
        return w

    def _refresh_books(self):
        self._clear_vbox(self.book_layout)
        if not self.level:
            lbl = QLabel("Select a level first.")
            lbl.setStyleSheet("QLabel { color: #777; }")
            self.book_layout.addWidget(lbl)
            self.book_layout.addStretch(1)
            return

        try:
            books = self.session.repo.get_books_for_level(self.level)
        except Exception:
            books = []

        if not books:
            lbl = QLabel(f"No books available for {self.level}.")
            lbl.setStyleSheet("QLabel { color: #777; }")
            self.book_layout.addWidget(lbl)
            self.book_layout.addStretch(1)
            return

        for i, book in enumerate(books):
            lek_n, vocab_n, grammar_n, sentences_n = self._book_summary(book.id, self.level)
            card = BookCard(
                title=book.title,
                level=self.level,
                lektion_count=lek_n,
                vocab_n=vocab_n,
                grammar_n=grammar_n,
                sentences_n=sentences_n,
                accent=_accent_for_index(i),
                selected=(book.slug == self.book_slug),
                on_click=lambda slug=book.slug: self._choose_book(slug),
            )
            self.book_layout.addWidget(card)

        self.book_layout.addStretch(1)

    def _choose_book(self, slug: str):
        slug = slug.strip().lower()
        if not slug:
            return
        self.session.state.book_slug = slug
        self.session.state.lektion_number = 0
        self.session.state.objective = ""
        self._sync_from_state()
        self._refresh_books()
        self._refresh_lektions()
        self._goto(_PAGE_LEKTION)

    # ------------------------------------------------------------------
    # Page: Lektion
    # ------------------------------------------------------------------
    def _make_lektion_page(self) -> QWidget:
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("Select Lektion")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("QLabel { color:#FFFFFF; }")
        lay.addWidget(title)

        group = QGroupBox("Lektionen")
        group.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        group.setStyleSheet(_GROUPBOX_STYLE)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self.lektion_grid = QGridLayout(inner)
        self.lektion_grid.setContentsMargins(14, 14, 14, 14)
        self.lektion_grid.setHorizontalSpacing(10)
        self.lektion_grid.setVerticalSpacing(10)
        self.lektion_grid.setColumnStretch(0, 1)
        self.lektion_grid.setColumnStretch(1, 1)
        scroll.setWidget(inner)

        g_lay = QVBoxLayout(group)
        g_lay.setContentsMargins(0, 0, 0, 0)
        g_lay.addWidget(scroll)

        lay.addWidget(group, 1)
        return w

    def _refresh_lektions(self):
        self._clear_vbox(self.lektion_grid)
        if not self.level or not self.book_slug:
            lbl = QLabel("Select a book first.")
            lbl.setStyleSheet("QLabel { color: #777; }")
            self.lektion_grid.addWidget(lbl, 0, 0, 1, 2)
            return

        try:
            book_id = self.session.repo.get_book_id(self.book_slug)
            rows = self._lektion_summaries(book_id, self.level) if book_id else []
        except Exception:
            rows = []

        if not rows:
            lbl = QLabel("No Lektionen found for this book and level.")
            lbl.setStyleSheet("QLabel { color: #777; }")
            self.lektion_grid.addWidget(lbl, 0, 0, 1, 2)
            return

        for i, r in enumerate(rows):
            card = LektionCard(
                number=int(r["number"]),
                title=str(r["title"]),
                topic=(str(r["topic"]) if r["topic"] else None),
                vocab_n=int(r["vocab_n"] or 0),
                grammar_n=int(r["grammar_n"] or 0),
                sentences_n=int(r["sentences_n"] or 0),
                selected=(int(r["number"]) == self.lektion_number),
                on_click=lambda n=int(r["number"]): self._choose_lektion(n),
            )
            self.lektion_grid.addWidget(card, i // 2, i % 2, Qt.AlignmentFlag.AlignTop)

        # Push cards to the top
        self.lektion_grid.setRowStretch((len(rows) + 1) // 2, 1)

    def _choose_lektion(self, number: int):
        if not number:
            return
        self.session.state.lektion_number = int(number)
        self.session.state.objective = ""
        self._sync_from_state()
        self._refresh_lektions()
        self._refresh_objectives()
        self._goto(_PAGE_OBJ)

    # ------------------------------------------------------------------
    # Page: Objective
    # ------------------------------------------------------------------
    def _make_objective_page(self) -> QWidget:
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("Choose what to practice")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("QLabel { color:#FFFFFF; }")
        lay.addWidget(title, 0)

        group = QGroupBox("Objectives")
        group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        group.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        group.setStyleSheet(_GROUPBOX_STYLE)

        inner = QVBoxLayout(group)
        inner.setContentsMargins(14, 14, 14, 14)
        inner.setSpacing(12)

        self.card_vocab = ObjectiveSelectCard(
            title="Vocabulary",
            accent=_ACCENT_VOCAB,
            on_start=lambda: self._choose_objective("vocab"),
        )
        self.card_grammar = ObjectiveSelectCard(
            title="Grammar",
            accent=_ACCENT_GRAMMAR,
            on_start=lambda: self._choose_objective("grammar"),
        )
        self.card_sentences = ObjectiveSelectCard(
            title="Sentences",
            accent=_ACCENT_SENTENCES,
            on_start=lambda: self._choose_objective("sentences"),
        )

        inner.addWidget(self.card_vocab, 0)
        inner.addWidget(self.card_grammar, 0)
        inner.addWidget(self.card_sentences, 0)
        inner.addStretch(1)

        lay.addWidget(group, 0)
        lay.addStretch(1)
        return w

    def _refresh_objectives(self):
        if not self.level or not self.book_slug or not self.lektion_number:
            self.card_vocab.set_meta("")
            self.card_vocab.set_enabled(False)
            self.card_grammar.set_meta("")
            self.card_grammar.set_enabled(False)
            self.card_sentences.set_meta("")
            self.card_sentences.set_enabled(False)
            return

        lektion_id = self._current_lektion_id()

        dv = self._deck_id(self.level, "vocab", lektion_id)
        dg = self._deck_id(self.level, "grammar", lektion_id)
        ds = self._deck_id(self.level, "sentences", lektion_id)

        vocab_n  = self._count_table("vocab",     dv) if dv is not None else 0
        gram_n   = self._count_table("grammar",   dg) if dg is not None else 0
        sent_n   = self._count_table("sentences", ds) if ds is not None else 0

        self.card_vocab.set_enabled(dv is not None)
        self.card_vocab.set_meta(f"{_fmt_int(vocab_n)} items" if dv is not None else "")

        self.card_grammar.set_enabled(dg is not None)
        self.card_grammar.set_meta(f"{_fmt_int(gram_n)} items" if dg is not None else "")

        self.card_sentences.set_enabled(ds is not None)
        self.card_sentences.set_meta(f"{_fmt_int(sent_n)} items" if ds is not None else "")

    def _choose_objective(self, key: str):
        if not self.level or not self.book_slug or not self.lektion_number:
            return

        key = _norm_objective(key)

        try:
            self.session.set_context(
                self.level,
                key,
                book_slug=self.book_slug,
                lektion_number=self.lektion_number,
            )
        except Exception:
            self.session.state.level = self.level
            self.session.state.book_slug = self.book_slug or ""
            self.session.state.lektion_number = self.lektion_number or 0
            self.session.state.objective = key

        self._sync_from_state()
        self._update_breadcrumb()
        self.start_practice.emit()
