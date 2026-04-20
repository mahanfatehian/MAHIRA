# src/ui/pages/learn.py
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer, Qt
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
    QTextBrowser,
)

CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

# -------------------------
# File-based curriculum index
# -------------------------

@dataclass(frozen=True)
class LessonRef:
    lang: str
    level: str
    objective_key: str
    lesson_key: str
    path: Path

    # ordering from filename, e.g. 5.2
    obj_no: int
    lesson_no: int
    order_token: str  # "5.2" or "" if not present (old format)

    @property
    def objective_title(self) -> str:
        return _pretty(self.objective_key)

    @property
    def lesson_title(self) -> str:
        return _pretty(self.lesson_key)

    @property
    def lesson_label(self) -> str:
        # Display "Lesson 5.2" if numeric token exists, else just "Lesson"
        if self.order_token:
            return f"Lesson {self.order_token}"
        return "Lesson"


def _pretty(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("-", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.title() if s else ""


def _norm_lang(code: str) -> str:
    return (code or "").strip().lower()


def _norm_level(level: str) -> str:
    return (level or "").strip().upper()


def _find_project_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here] + list(here.parents):
        if (p / "data").exists():
            return p
        if p.name.lower() == "src" and (p.parent / "data").exists():
            return p.parent
    return here.parents[3]


def _pages_root() -> Path:
    return _find_project_root() / "data" / "pages"


_NUM_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?$")


def _parse_number_token(tok: str) -> tuple[int, int, str] | None:
    """
    Parses "5.2" => (5, 2, "5.2")
    Parses "5"   => (5, 0, "5")  (allowed, but you probably want 5.1, 5.2, ...)
    """
    tok = (tok or "").strip()
    if not tok or not _NUM_TOKEN_RE.match(tok):
        return None
    if "." in tok:
        a, b = tok.split(".", 1)
        try:
            return int(a), int(b), tok
        except Exception:
            return None
    try:
        return int(tok), 0, tok
    except Exception:
        return None


def _parse_md_filename(md_path: Path) -> Tuple[str, str, str, int, int, str] | None:
    """
    Supported formats:

    NEW (recommended):
      a1_5.2_objective_lesson_name_here.md
      => level="A1", objective_key="objective", lesson_key="lesson_name_here", obj_no=5, lesson_no=2

    OLD (fallback):
      a1_objective_lesson_name_here.md
      => obj_no=999, lesson_no=999 (sorted after numbered ones)
    """
    stem = md_path.stem.strip()
    parts = stem.split("_")

    if len(parts) < 3:
        return None

    level_raw = parts[0]
    level = _norm_level(level_raw)
    if level not in CEFR_LEVELS:
        return None

    # Try NEW format: level + number + objective + lesson...
    if len(parts) >= 4:
        maybe_num = _parse_number_token(parts[1])
        if maybe_num is not None:
            obj_no, lesson_no, token = maybe_num
            objective_key = parts[2].strip().lower()
            lesson_key = "_".join(parts[3:]).strip().lower()
            if objective_key and lesson_key:
                return level, objective_key, lesson_key, obj_no, lesson_no, token

    # OLD format fallback: level + objective + lesson...
    objective_key = parts[1].strip().lower()
    lesson_key = "_".join(parts[2:]).strip().lower()
    if not objective_key or not lesson_key:
        return None

    return level, objective_key, lesson_key, 999, 999, ""


class CurriculumIndex:
    """
    Scans data/pages for .md lessons.

    Preferred:
      data/pages/<lang>/<level>_<num>_<objective>_<lesson>.md

    Fallback:
      data/pages/<level>_<objective>_<lesson>.md (assumes 'de')
    """

    def __init__(self):
        self.root = _pages_root()
        self._by_lang_level: Dict[str, Dict[str, Dict[str, List[LessonRef]]]] = {}

    def reload(self) -> None:
        self._by_lang_level = {}
        root = self.root
        if not root.exists():
            return

        for p in root.iterdir():
            if p.is_dir():
                lang = _norm_lang(p.name)
                self._scan_dir(p, lang)

        # fallback files directly under pages/
        for md in root.glob("*.md"):
            self._add_md(md, "de")

    def _scan_dir(self, folder: Path, lang: str) -> None:
        for md in folder.rglob("*.md"):
            self._add_md(md, lang)

    def _add_md(self, md_path: Path, lang: str) -> None:
        parsed = _parse_md_filename(md_path)
        if not parsed:
            return

        level, objective_key, lesson_key, obj_no, lesson_no, token = parsed
        lang = _norm_lang(lang)

        ref = LessonRef(
            lang=lang,
            level=level,
            objective_key=objective_key,
            lesson_key=lesson_key,
            path=md_path,
            obj_no=obj_no,
            lesson_no=lesson_no,
            order_token=token,
        )

        self._by_lang_level.setdefault(lang, {}).setdefault(level, {}).setdefault(objective_key, []).append(ref)

    def languages(self) -> List[str]:
        return sorted(self._by_lang_level.keys())

    def levels_for(self, lang: str) -> List[str]:
        lang = _norm_lang(lang)
        return sorted(self._by_lang_level.get(lang, {}).keys(), key=lambda x: CEFR_LEVELS.index(x))

    def objectives_for(self, lang: str, level: str) -> Dict[str, List[LessonRef]]:
        lang = _norm_lang(lang)
        level = _norm_level(level)
        return self._by_lang_level.get(lang, {}).get(level, {})


# -------------------------
# Answers parsing + masking (MARKERS ONLY)
# -------------------------

ANSWERS_START = "<!-- ANSWERS_START -->"
ANSWERS_END = "<!-- ANSWERS_END -->"


def _mask_text_keep_layout(text: str) -> str:
    out = []
    for ch in text:
        if ch in ("\n", "\r", "\t", " "):
            out.append(ch)
        else:
            out.append("•")
    return "".join(out)


def _split_answers_markers_only(md: str) -> tuple[str, Optional[str]]:
    md = md or ""
    if ANSWERS_START not in md or ANSWERS_END not in md:
        return md.strip(), None

    before, rest = md.split(ANSWERS_START, 1)
    ans, after = rest.split(ANSWERS_END, 1)
    body = (before + after).strip()
    answers = ans.strip()
    return body, (answers if answers else None)


# -------------------------
# UI helpers: objective accent color (stable)
# -------------------------

_ACCENTS = [
    "#6B9FFF",  # blue
    "#66E39A",  # green
    "#FFD166",  # amber
    "#FF6B9A",  # pink
    "#B983FF",  # purple
    "#4DD0E1",  # cyan
    "#FFA07A",  # salmon
]


def _accent_for_key(key: str) -> str:
    k = (key or "").strip().lower()
    if not k:
        return _ACCENTS[0]
    h = 0
    for ch in k:
        h = (h * 33 + ord(ch)) & 0xFFFFFFFF
    return _ACCENTS[h % len(_ACCENTS)]


def _objective_group_number(lessons: List[LessonRef]) -> int:
    """
    Determines objective ordering number from lessons.
    If no numeric token exists (old filenames), returns 999.
    """
    if not lessons:
        return 999
    return min((r.obj_no for r in lessons), default=999)


def _sort_lessons_in_objective(lessons: List[LessonRef]) -> List[LessonRef]:
    """
    Sort by (obj_no, lesson_no), then by title as stable fallback.
    """
    return sorted(
        lessons,
        key=lambda r: (r.obj_no, r.lesson_no, r.lesson_title),
    )


# -------------------------
# Objective card widget (Curriculum map; no dictionaries)
# -------------------------

class CurriculumMapCard(QFrame):
    def __init__(self, objective_key: str, lessons: List[LessonRef], on_open):
        super().__init__()
        self._lessons = lessons
        self._on_open = on_open

        accent = _accent_for_key(objective_key)
        obj_num = _objective_group_number(lessons)

        self.setObjectName("CurriculumMapCard")
        self.setStyleSheet("""
            #CurriculumMapCard {
                background-color: #141414;
                border: 1px solid #2B2B2B;
                border-radius: 16px;
            }
            #CurriculumMapCard QLabel {
                background: transparent;
                border: none;
                padding: 0;
                margin: 0;
            }
            #CurriculumMapCard QWidget { background: transparent; }
        """)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QFrame()
        bar.setFixedWidth(7)
        bar.setStyleSheet(
            f"QFrame {{ background-color: {accent}; border-top-left-radius: 16px; border-bottom-left-radius: 16px; }}"
        )
        outer.addWidget(bar)

        body = QWidget()
        outer.addWidget(body, 1)

        lay = QVBoxLayout(body)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        if obj_num != 999:
            title_text = f"📘 Objective {obj_num}: {_pretty(objective_key)}"
        else:
            title_text = f"📘 Objective: {_pretty(objective_key)}"

        title = QLabel(title_text)
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Black))
        title.setStyleSheet(f"QLabel {{ color: {accent}; font-weight: 900; }}")
        lay.addWidget(title)

        meta = QLabel(f"{len(lessons)} lesson(s)")
        meta.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        meta.setStyleSheet("QLabel { color: #CFCFCF; }")
        lay.addWidget(meta)

        # Header row
        hdr = QWidget()
        hdr_lay = QGridLayout(hdr)
        hdr_lay.setContentsMargins(0, 0, 0, 0)
        hdr_lay.setHorizontalSpacing(10)
        hdr_lay.setVerticalSpacing(6)

        def _hdr(text: str) -> QLabel:
            lb = QLabel(text)
            lb.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            lb.setStyleSheet("QLabel { color:#CFCFCF; }")
            return lb

        hdr_lay.addWidget(_hdr("Lesson"), 0, 0)
        hdr_lay.addWidget(_hdr("Topic"), 0, 1)
        hdr_lay.setColumnStretch(0, 0)
        hdr_lay.setColumnStretch(1, 2)
        lay.addWidget(hdr)

        # Rows
        rows = QWidget()
        grid = QGridLayout(rows)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 0)

        for i, ref in enumerate(_sort_lessons_in_objective(lessons), start=1):
            lesson_no = QLabel(ref.lesson_label if ref.order_token else f"Lesson {i}")
            lesson_no.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            lesson_no.setStyleSheet("QLabel { color:#CFCFCF; }")

            topic = QLabel(ref.lesson_title)
            topic.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            topic.setStyleSheet("QLabel { color:#FFFFFF; }")

            btn = QPushButton("Open")
            btn.setFixedHeight(34)
            btn.setMinimumWidth(84)
            btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Black))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {accent};
                    color: #0B0B0B;
                    border: 1px solid #2E2E2E;
                    border-radius: 10px;
                    padding: 6px 12px;
                    font-weight: 900;
                }}
                QPushButton:hover {{ border: 1px solid #FFFFFF; }}
            """)
            btn.clicked.connect(lambda checked=False, r=ref: self._on_open(r))

            grid.addWidget(lesson_no, i - 1, 0, Qt.AlignTop)
            grid.addWidget(topic, i - 1, 1, Qt.AlignTop)
            grid.addWidget(btn, i - 1, 2, Qt.AlignTop)

        lay.addWidget(rows)


# -------------------------
# Learn Page
# -------------------------

class LearnPage(QWidget):
    def __init__(self, session, nav=None):
        super().__init__()
        self.session = session
        self.nav = nav

        self.setFont(QFont("Segoe UI", 10))

        self.setObjectName("LearnPage")
        self.setStyleSheet("""
            #LearnPage { background-color: #0F0F0F; color: #E6E6E6; }
            #LearnPage QLabel { background: transparent; }
            #LearnPage QScrollArea { background: transparent; border: none; }
            #LearnPage QStackedWidget { background: transparent; }
        """)

        self.index = CurriculumIndex()

        self.lang: Optional[str] = None
        self.level: Optional[str] = None
        self.current_objective: Optional[str] = None
        self.current_lesson: Optional[LessonRef] = None

        self._lesson_body_md: str = ""
        self._lesson_answers_md: Optional[str] = None
        self._answers_visible: bool = False

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

        self.title = QLabel("Learn")
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
        root.addWidget(self.stack, 1)

        self.page_lang = self._make_language_page()
        self.page_level = self._make_level_page()
        self.page_obj = self._make_objectives_page()
        self.page_reader = self._make_reader_page()

        self.stack.addWidget(self.page_lang)    # 0
        self.stack.addWidget(self.page_level)   # 1
        self.stack.addWidget(self.page_obj)     # 2
        self.stack.addWidget(self.page_reader)  # 3

        self._goto(0)

    def on_show(self):
        self.index.reload()
        self._refresh_language_buttons()
        self._refresh_levels_enabled()
        if self.stack.currentIndex() == 2:
            self._render_objectives()

    def _goto(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self.back_btn.setEnabled(idx != 0)
        self._update_breadcrumb()

    def _back(self):
        idx = self.stack.currentIndex()
        if idx == 3:
            self._goto(2)
        elif idx == 2:
            self._goto(1)
        elif idx == 1:
            self._goto(0)

    def _update_breadcrumb(self):
        parts = []
        if self.lang:
            parts.append(self.lang.upper())
        if self.level:
            parts.append(self.level)
        if self.current_lesson:
            parts.append(self.current_lesson.lesson_title)
        self.breadcrumb.setText("  •  ".join(parts) if parts else " ")

    # -------------------------
    # Language page
    # -------------------------

    def _make_language_page(self) -> QWidget:
        w = QWidget()
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
        group.setStyleSheet("""
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
        """)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        inner = QWidget()
        self.lang_layout = QVBoxLayout(inner)
        self.lang_layout.setContentsMargins(16, 16, 16, 16)
        self.lang_layout.setSpacing(10)
        scroll.setWidget(inner)

        g_lay = QVBoxLayout(group)
        g_lay.setContentsMargins(0, 0, 0, 0)
        g_lay.addWidget(scroll)

        self.lang_hint = QLabel("")
        self.lang_hint.setFont(QFont("Segoe UI", 9))
        self.lang_hint.setAlignment(Qt.AlignCenter)
        self.lang_hint.setStyleSheet("QLabel { color:#B0B0B0; }")

        lay.addWidget(group, 1)
        lay.addWidget(self.lang_hint)
        return w

    def _clear_vbox(self, vbox: QVBoxLayout):
        while vbox.count():
            item = vbox.takeAt(0)
            ww = item.widget()
            if ww is not None:
                ww.deleteLater()

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
        db_names = self._db_language_names()
        langs = self.index.languages()
        if not langs:
            langs = sorted(db_names.keys())
        if not langs:
            langs = ["de"]

        rows = []
        for code in langs:
            name = db_names.get(code, code.upper())
            rows.append((code, name))
        return rows

    def _refresh_language_buttons(self):
        self._clear_vbox(self.lang_layout)

        for code, name in self._available_languages():
            selected = (code == self.lang)
            b = QPushButton(f"{name} ({code})")
            b.setMinimumHeight(62)
            b.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))

            if selected:
                b.setStyleSheet("""
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
                """)
            else:
                b.setStyleSheet("""
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
                """)

            b.clicked.connect(lambda checked=False, c=code: self._choose_language(c))
            self.lang_layout.addWidget(b)

        self.lang_layout.addStretch(1)

        pr = _pages_root()
        self.lang_hint.setText(
            "Loading LOVE from MAHAN s heart for RAYA"
            if pr.exists()
            else "Create data/pages/<lang>/ and add .md lessons."
        )

    def _choose_language(self, code: str):
        self.lang = _norm_lang(code)
        self.level = None
        self.current_objective = None
        self.current_lesson = None
        self._goto(1)
        self._refresh_language_buttons()
        self._refresh_levels_enabled()

    # -------------------------
    # Level page
    # -------------------------

    def _make_level_page(self) -> QWidget:
        w = QWidget()
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
        group.setStyleSheet("""
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
        """)

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
                QPushButton:hover {
                    border: 2px solid #FFFFFF;
                    background-color: #1B1B1B;
                }
                QPushButton:disabled {
                    background-color: #101010;
                    color: #6B6B6B;
                    border: 1px solid #252525;
                }
            """)
            b.clicked.connect(lambda checked=False, l=lvl: self._choose_level(l))
            self.level_buttons[lvl] = b
            grid.addWidget(b, i // 3, i % 3)

        self.level_hint = QLabel("")
        self.level_hint.setFont(QFont("Segoe UI", 9))
        self.level_hint.setAlignment(Qt.AlignCenter)
        self.level_hint.setStyleSheet("QLabel { color:#B0B0B0; }")

        lay.addWidget(group, 1)
        lay.addWidget(self.level_hint)
        return w

    def _refresh_levels_enabled(self):
        if not self.lang:
            for btn in self.level_buttons.values():
                btn.setEnabled(False)
            self.level_hint.setText("Select a language first.")
            return

        available = set(self.index.levels_for(self.lang))
        for lvl, btn in self.level_buttons.items():
            btn.setEnabled(lvl in available)

        self.level_hint.setText(
            "No lessons found for this language. Add .md files into data/pages/<lang>/"
            if not available else
            "I LOVE RAYA THE MOST"
        )

    def _choose_level(self, lvl: str):
        self.level = _norm_level(lvl)
        self.current_objective = None
        self.current_lesson = None
        self._goto(2)
        self._render_objectives()

    # -------------------------
    # Objectives page
    # -------------------------

    def _make_objectives_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.obj_title = QLabel("Objectives")
        self.obj_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        self.obj_title.setAlignment(Qt.AlignCenter)
        self.obj_title.setStyleSheet("QLabel { color:#FFFFFF; }")
        lay.addWidget(self.obj_title)

        group = QGroupBox("Objectives & Lessons")
        group.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        group.setStyleSheet("""
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
        """)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.obj_inner = QWidget()
        self.obj_layout = QVBoxLayout(self.obj_inner)
        self.obj_layout.setContentsMargins(14, 14, 14, 14)
        self.obj_layout.setSpacing(14)
        scroll.setWidget(self.obj_inner)

        g_lay = QVBoxLayout(group)
        g_lay.setContentsMargins(0, 0, 0, 0)
        g_lay.addWidget(scroll)

        self.obj_hint = QLabel("")
        self.obj_hint.setText("")
        lay.addWidget(group, 1)
        lay.addWidget(self.obj_hint)
        return w

    def _render_objectives(self):
        self._clear_vbox(self.obj_layout)

        if not self.lang or not self.level:
            return

        obj_map = self.index.objectives_for(self.lang, self.level)
        self.obj_title.setText(f"{self.lang.upper()} {self.level} • Complete Curriculum Map")

        if not obj_map:
            return

        # Sort objectives purely by numeric group number from filenames (min obj_no)
        items = list(obj_map.items())
        items.sort(key=lambda kv: (_objective_group_number(kv[1]), _pretty(kv[0])))

        for obj_key, lessons in items:
            card = CurriculumMapCard(
                objective_key=obj_key,
                lessons=lessons,
                on_open=self._open_lesson,
            )
            self.obj_layout.addWidget(card)

        self.obj_layout.addStretch(1)

    # -------------------------
    # Reader page
    # -------------------------

    def _make_reader_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.reader_title = QLabel("Lesson")
        self.reader_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        self.reader_title.setStyleSheet("QLabel { color:#FFFFFF; }")

        self.show_answers_btn = QPushButton("Show answers")
        self.show_answers_btn.setFixedHeight(34)
        self.show_answers_btn.setVisible(False)
        self.show_answers_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.show_answers_btn.setStyleSheet("""
            QPushButton {
                background-color: #151515;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: 800;
            }
            QPushButton:hover { border: 1px solid #FFFFFF; background-color:#1B1B1B; }
        """)
        self.show_answers_btn.clicked.connect(self._toggle_answers)

        top_row.addWidget(self.reader_title, 1)
        top_row.addWidget(self.show_answers_btn, 0)
        lay.addLayout(top_row)

        group = QGroupBox("Reading")
        group.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        group.setStyleSheet("""
            QGroupBox {
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 12px;
                margin-top: 10px;
                padding-top: 12px;
                background-color: #141414;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 16px;
                padding: 0 10px 0 10px;
            }
        """)

        inner = QVBoxLayout(group)
        inner.setContentsMargins(12, 12, 12, 12)
        inner.setSpacing(10)

        self.reader = QTextBrowser()
        self.reader.setOpenExternalLinks(True)
        self.reader.setFont(QFont("Segoe UI", 10))

        self.reader.setStyleSheet("""
            QTextBrowser {
                background-color: #23262B;
                border: 1px solid #343842;
                border-radius: 12px;
                padding: 18px;
                color: #E8EAED;
                selection-background-color: #3A5070;
                selection-color: #FFFFFF;
            }
        """)

        self.reader.document().setDefaultStyleSheet("""
            body {
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 10pt;
                color: #E8EAED;
                line-height: 150%;
            }
            h1 { font-size: 16pt; margin: 18px 0 10px; font-weight: 800; color:#FFFFFF; }
            h2 { font-size: 13pt; margin: 16px 0 8px; font-weight: 800; color:#FFFFFF; }
            h3 { font-size: 11pt; margin: 14px 0 6px; font-weight: 800; color:#FFFFFF; }
            p { margin: 10px 0; }
            ul, ol { margin: 10px 0 10px 20px; }
            li { margin: 6px 0; }

            a { color: #86B7FF; text-decoration: none; }
            a:hover { text-decoration: underline; }

            code {
                background: #1A1C21;
                padding: 2px 6px;
                border-radius: 6px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 10pt;
                color: #E8EAED;
            }
            pre {
                background: #1A1C21;
                border: 1px solid #343842;
                padding: 12px;
                border-radius: 10px;
                overflow-x: auto;
                font-family: Consolas, "Courier New", monospace;
                font-size: 10pt;
                color: #E8EAED;
            }
            blockquote {
                border-left: 4px solid #4A4F5A;
                margin: 12px 0;
                padding: 8px 12px;
                color: #D7DAE0;
                background: #1C1F25;
                border-radius: 8px;
            }
            hr {
                border: none;
                border-top: 1px solid #343842;
                margin: 16px 0;
            }
        """)

        inner.addWidget(self.reader, 1)
        lay.addWidget(group, 1)
        return w

    def _set_reader_markdown_preserve_scroll(self, md: str) -> None:
        sb = self.reader.verticalScrollBar()
        old_max = max(1, sb.maximum())
        ratio = sb.value() / old_max

        self.reader.setMarkdown(md)

        def restore():
            new_max = max(1, sb.maximum())
            sb.setValue(int(ratio * new_max))

        QTimer.singleShot(0, restore)

    def _toggle_answers(self):
        self._answers_visible = not self._answers_visible
        self.show_answers_btn.setText("Hide answers" if self._answers_visible else "Show answers")
        self._render_lesson_md(preserve_scroll=True)

    def _render_lesson_md(self, preserve_scroll: bool):
        body = (self._lesson_body_md or "").strip()

        if not self._lesson_answers_md:
            if preserve_scroll:
                self._set_reader_markdown_preserve_scroll(body)
            else:
                self.reader.setMarkdown(body)
            return

        answers = (self._lesson_answers_md or "").strip()

        if self._answers_visible:
            md = f"{body}\n\n---\n\n## Answers\n\n{answers}\n"
        else:
            masked = _mask_text_keep_layout(answers)
            md = (
                f"{body}\n\n---\n\n## Answers (hidden)\n\n"
                f"Click **Show answers** to reveal.\n\n"
                f"```text\n{masked}\n```\n"
            )

        if preserve_scroll:
            self._set_reader_markdown_preserve_scroll(md)
        else:
            self.reader.setMarkdown(md)

    def _open_lesson(self, ref: LessonRef):
        self.current_lesson = ref
        self.current_objective = ref.objective_key
        self._update_breadcrumb()

        self.reader_title.setText(f"{ref.objective_title} • {ref.lesson_title}")

        try:
            raw = ref.path.read_text(encoding="utf-8")
        except Exception as e:
            raw = f"# Error\n\nCould not read file:\n\n`{ref.path}`\n\nReason: {e}"

        body, answers = _split_answers_markers_only(raw)
        self._lesson_body_md = body
        self._lesson_answers_md = answers
        self._answers_visible = False

        has_answers = bool(answers and answers.strip())
        self.show_answers_btn.setVisible(has_answers)
        self.show_answers_btn.setText("Show answers")

        try:
            self._render_lesson_md(preserve_scroll=False)
        except Exception:
            if has_answers:
                hidden = _mask_text_keep_layout(answers or "")
                self.reader.setPlainText(body + "\n\n---\n\nANSWERS (hidden)\n\n" + hidden)
            else:
                self.reader.setPlainText(body)

        self._goto(3)
