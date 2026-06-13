from __future__ import annotations

from typing import Dict, List, Optional, Tuple

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
_PAGE_LANG    = 0
_PAGE_LEVEL   = 1
_PAGE_BOOK    = 2
_PAGE_LEKTION = 3
_PAGE_OBJ     = 4


def _norm_lang(code: str) -> str:
    return (code or "").strip().lower()


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


# ---------------------------------------------------------------------------
# Shared button styles
# ---------------------------------------------------------------------------
_BTN_SELECTED = """
    QPushButton {
        background-color: #1B4B78;
        color: #FFFFFF;
        border: 2px solid #FFFFFF;
        border-radius: 12px;
        padding: 12px;
        font-weight: 900;
        text-align: left;
        padding-left: 12px;
    }
"""

_BTN_NORMAL = """
    QPushButton {
        background-color: #163A5C;
        color: #FFFFFF;
        border: 2px solid #2E2E2E;
        border-radius: 12px;
        padding: 12px;
        font-weight: 900;
        text-align: left;
        padding-left: 12px;
    }
    QPushButton:hover { background-color: #1B4B78; border: 2px solid #FFFFFF; }
    QPushButton:disabled {
        background-color: #101010; color: #6B6B6B; border: 1px solid #252525;
    }
"""

_BTN_LEKTION_NORMAL = """
    QPushButton {
        background-color: #1A1A2E;
        color: #FFFFFF;
        border: 2px solid #2E2E2E;
        border-radius: 12px;
        padding: 10px 14px;
        font-weight: 700;
        text-align: left;
        padding-left: 12px;
    }
    QPushButton:hover { background-color: #22223B; border: 2px solid #FFFFFF; }
    QPushButton:disabled {
        background-color: #101010; color: #6B6B6B; border: 1px solid #252525;
    }
"""

_BTN_LEKTION_SELECTED = """
    QPushButton {
        background-color: #22223B;
        color: #FFFFFF;
        border: 2px solid #FFFFFF;
        border-radius: 12px;
        padding: 10px 14px;
        font-weight: 700;
        text-align: left;
        padding-left: 12px;
    }
"""

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

        self.lang: Optional[str] = None
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

        self.page_lang    = self._make_language_page()
        self.page_level   = self._make_level_page()
        self.page_book    = self._make_book_page()
        self.page_lektion = self._make_lektion_page()
        self.page_obj     = self._make_objective_page()

        self.stack.addWidget(self.page_lang)    # 0
        self.stack.addWidget(self.page_level)   # 1
        self.stack.addWidget(self.page_book)    # 2
        self.stack.addWidget(self.page_lektion) # 3
        self.stack.addWidget(self.page_obj)     # 4

        self._sync_from_state()
        self._goto(self.stack.currentIndex() or 0)
        self._refresh_languages()
        self._refresh_levels_enabled()
        self._refresh_books()
        self._refresh_lektions()
        self._refresh_objectives()

        QTimer.singleShot(0, self._post_init_refresh)

    def _post_init_refresh(self):
        self._sync_from_state()
        self._refresh_languages()
        self._refresh_levels_enabled()
        self._refresh_books()
        self._refresh_lektions()
        self._refresh_objectives()
        self._coerce_step_to_state()
        self._update_breadcrumb()

    def on_show(self):
        self._sync_from_state()
        self._refresh_languages()
        self._refresh_levels_enabled()
        self._refresh_books()
        self._refresh_lektions()
        self._refresh_objectives()
        self._coerce_step_to_state()
        self._update_breadcrumb()

    def _goto(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self.back_btn.setEnabled(idx != _PAGE_LANG)
        self._update_breadcrumb()

    def _back(self):
        idx = self.stack.currentIndex()
        if idx == _PAGE_OBJ:
            self._goto(_PAGE_LEKTION)
        elif idx == _PAGE_LEKTION:
            self._goto(_PAGE_BOOK)
        elif idx == _PAGE_BOOK:
            self._goto(_PAGE_LEVEL)
        elif idx == _PAGE_LEVEL:
            self._goto(_PAGE_LANG)

    def _coerce_step_to_state(self):
        idx = self.stack.currentIndex()
        if idx >= _PAGE_LEVEL and not self.lang:
            self._goto(_PAGE_LANG)
            return
        if idx >= _PAGE_BOOK and not self.level:
            self._goto(_PAGE_LEVEL if self.lang else _PAGE_LANG)
            return
        if idx >= _PAGE_LEKTION and not self.book_slug:
            self._goto(_PAGE_BOOK)
            return
        if idx >= _PAGE_OBJ and not self.lektion_number:
            self._goto(_PAGE_LEKTION)
            return

    def _update_breadcrumb(self):
        parts = []
        if self.lang:
            parts.append(self.lang.upper())
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
        self.lang = _norm_lang(getattr(self.session.state, "language_code", "") or "") or None
        self.level = _norm_level(getattr(self.session.state, "level", "") or "") or None
        self.book_slug = (getattr(self.session.state, "book_slug", "") or "").strip() or None
        ln = getattr(self.session.state, "lektion_number", 0) or 0
        self.lektion_number = int(ln) if ln else None
        obj = _norm_objective(getattr(self.session.state, "objective", "") or "")
        self.objective = obj or None

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------
    def _db_language_names(self) -> Dict[str, str]:
        names: Dict[str, str] = {}
        try:
            with self.session.repo._conn() as conn:
                rows = conn.execute("SELECT code, name FROM languages").fetchall()
            for r in rows:
                names[str(r["code"]).lower()] = str(r["name"])
        except Exception:
            pass
        return names

    def _available_languages(self) -> List[Tuple[str, str]]:
        names = self._db_language_names()
        codes: List[str] = []
        try:
            with self.session.repo._conn() as conn:
                rows = conn.execute("SELECT DISTINCT language_code AS code FROM decks ORDER BY code").fetchall()
            codes = [str(r["code"]).lower() for r in rows if r and r["code"]]
        except Exception:
            codes = []
        if not codes:
            codes = sorted(names.keys())
        if self.lang and self.lang not in codes:
            codes.insert(0, self.lang)
        if not codes:
            codes = ["de"]
        return [(c, names.get(c, c.upper())) for c in codes]

    def _deck_id(self, lang: str, level: str, objective: str, lektion_id: int | None = None) -> Optional[int]:
        try:
            return self.session.repo.get_deck_id(lang, level, objective, lektion_id=lektion_id)
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
        if not self.book_slug or not self.lektion_number or not self.lang:
            return None
        try:
            book_id = self.session.repo.get_book_id(self.lang, self.book_slug)
            if book_id is None:
                return None
            return self.session.repo.get_lektion_id(book_id, self.lektion_number)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Page: Language
    # ------------------------------------------------------------------
    def _make_language_page(self) -> QWidget:
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("Select Language")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("QLabel { color:#FFFFFF; }")
        lay.addWidget(title)

        group = QGroupBox("Available Languages")
        group.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        group.setStyleSheet(_GROUPBOX_STYLE)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self.lang_layout = QVBoxLayout(inner)
        self.lang_layout.setContentsMargins(16, 16, 16, 16)
        self.lang_layout.setSpacing(10)
        scroll.setWidget(inner)

        g_lay = QVBoxLayout(group)
        g_lay.setContentsMargins(0, 0, 0, 0)
        g_lay.addWidget(scroll)

        lay.addWidget(group, 1)
        return w

    def _clear_vbox(self, vbox: QVBoxLayout):
        while vbox.count():
            item = vbox.takeAt(0)
            ww = item.widget()
            if ww is not None:
                ww.deleteLater()

    def _refresh_languages(self):
        self._clear_vbox(self.lang_layout)
        for code, name in self._available_languages():
            selected = (code == self.lang)
            b = QPushButton(f"{name} ({code})")
            b.setMinimumHeight(62)
            b.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
            b.setStyleSheet(_BTN_SELECTED if selected else _BTN_NORMAL)
            b.clicked.connect(lambda checked=False, c=code: self._choose_language(c))
            self.lang_layout.addWidget(b)
        self.lang_layout.addStretch(1)

    def _choose_language(self, code: str):
        code = _norm_lang(code)
        if not code:
            return
        self.session.state.language_code = code
        self.session.state.level = ""
        self.session.state.book_slug = ""
        self.session.state.lektion_number = 0
        self.session.state.objective = ""
        self._sync_from_state()
        self._refresh_languages()
        self._refresh_levels_enabled()
        self._refresh_books()
        self._refresh_lektions()
        self._refresh_objectives()
        self._goto(_PAGE_LEVEL)

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
        if not self.lang:
            for btn in self.level_buttons.values():
                btn.setEnabled(False)
            return

        lang = self.lang
        for lvl, btn in self.level_buttons.items():
            try:
                has = self.session.repo.has_decks_for_level(lang, lvl)
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
        if not self.lang or not self.level:
            lbl = QLabel("Select a language and level first.")
            lbl.setStyleSheet("QLabel { color: #777; }")
            self.book_layout.addWidget(lbl)
            self.book_layout.addStretch(1)
            return

        try:
            books = self.session.repo.get_books_for_level(self.lang, self.level)
        except Exception:
            books = []

        if not books:
            lbl = QLabel(f"No books available for {self.lang.upper()} {self.level}.")
            lbl.setStyleSheet("QLabel { color: #777; }")
            self.book_layout.addWidget(lbl)
            self.book_layout.addStretch(1)
            return

        for book in books:
            selected = (book.slug == self.book_slug)
            b = QPushButton(book.title)
            b.setMinimumHeight(62)
            b.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
            b.setStyleSheet(_BTN_SELECTED if selected else _BTN_NORMAL)
            b.clicked.connect(lambda checked=False, slug=book.slug: self._choose_book(slug))
            self.book_layout.addWidget(b)

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
        self.lektion_layout = QVBoxLayout(inner)
        self.lektion_layout.setContentsMargins(16, 16, 16, 16)
        self.lektion_layout.setSpacing(10)
        scroll.setWidget(inner)

        g_lay = QVBoxLayout(group)
        g_lay.setContentsMargins(0, 0, 0, 0)
        g_lay.addWidget(scroll)

        lay.addWidget(group, 1)
        return w

    def _refresh_lektions(self):
        self._clear_vbox(self.lektion_layout)
        if not self.lang or not self.level or not self.book_slug:
            lbl = QLabel("Select a book first.")
            lbl.setStyleSheet("QLabel { color: #777; }")
            self.lektion_layout.addWidget(lbl)
            self.lektion_layout.addStretch(1)
            return

        try:
            book_id = self.session.repo.get_book_id(self.lang, self.book_slug)
            lektions = self.session.repo.get_lektions_for_book_level(book_id, self.level) if book_id else []
        except Exception:
            lektions = []

        if not lektions:
            lbl = QLabel("No Lektionen found for this book and level.")
            lbl.setStyleSheet("QLabel { color: #777; }")
            self.lektion_layout.addWidget(lbl)
            self.lektion_layout.addStretch(1)
            return

        for lek in lektions:
            selected = (lek.number == self.lektion_number)
            label = f"Lektion {lek.number}  —  {lek.title}"
            b = QPushButton(label)
            b.setMinimumHeight(56)
            b.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            b.setStyleSheet(_BTN_LEKTION_SELECTED if selected else _BTN_LEKTION_NORMAL)
            b.clicked.connect(lambda checked=False, n=lek.number: self._choose_lektion(n))
            self.lektion_layout.addWidget(b)

        self.lektion_layout.addStretch(1)

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
        if not self.lang or not self.level or not self.book_slug or not self.lektion_number:
            self.card_vocab.set_meta("")
            self.card_vocab.set_enabled(False)
            self.card_grammar.set_meta("")
            self.card_grammar.set_enabled(False)
            self.card_sentences.set_meta("")
            self.card_sentences.set_enabled(False)
            return

        lektion_id = self._current_lektion_id()

        dv = self._deck_id(self.lang, self.level, "vocab", lektion_id)
        dg = self._deck_id(self.lang, self.level, "grammar", lektion_id)
        ds = self._deck_id(self.lang, self.level, "sentences", lektion_id)

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
        if not self.lang or not self.level or not self.book_slug or not self.lektion_number:
            return

        key = _norm_objective(key)

        try:
            self.session.set_context(
                self.lang,
                self.level,
                key,
                book_slug=self.book_slug,
                lektion_number=self.lektion_number,
            )
        except Exception:
            self.session.state.language_code = self.lang
            self.session.state.level = self.level
            self.session.state.book_slug = self.book_slug or ""
            self.session.state.lektion_number = self.lektion_number or 0
            self.session.state.objective = key

        self._sync_from_state()
        self._update_breadcrumb()
        self.start_practice.emit()
