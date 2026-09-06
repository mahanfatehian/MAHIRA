# src/ui/pages/learn.py
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QScrollArea,
    QHBoxLayout,
    QFrame,
    QStackedWidget,
    QTextBrowser,
    QSizePolicy,
    QGraphicsDropShadowEffect,
)

from ui.book_covers import level_cover_paths
from ui.widgets.images import rounded_cover_pixmap

CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

# -------------------------
# File-based curriculum index
# -------------------------

@dataclass(frozen=True)
class LessonRef:
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


def _norm_level(level: str) -> str:
    return (level or "").strip().upper()


def _find_project_root() -> Path:
    # Prefer the shared resource root so lessons resolve in a packaged build.
    try:
        from mahira.config import resource_root
        return resource_root()
    except Exception:
        pass
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


def _parse_md_filename(
    md_path: Path, level_hint: str | None = None
) -> Tuple[str, str, str, int, int, str] | None:
    """
    The CEFR level is taken from the FOLDER (data/pages/<level>/...) via
    `level_hint`; it is optional in the filename. Supported forms:

    FOLDER-BASED (recommended):
      data/pages/a1/5.2_objective_lesson_name_here.md
      => level="A1" (from folder), objective_key="objective",
         lesson_key="lesson_name_here", obj_no=5, lesson_no=2

      data/pages/a1/objective_lesson_name_here.md  (no number)
      => obj_no=999, lesson_no=999 (sorted after numbered ones)

    LEGACY (level encoded in filename, still accepted):
      a1_5.2_objective_lesson_name_here.md
      a1_objective_lesson_name_here.md
    """
    stem = md_path.stem.strip()
    parts = stem.split("_")
    if not parts or not parts[0]:
        return None

    # Optional leading CEFR level in the filename (legacy flat layout).
    level: Optional[str] = None
    if _norm_level(parts[0]) in CEFR_LEVELS:
        level = _norm_level(parts[0])
        parts = parts[1:]
    elif level_hint and _norm_level(level_hint) in CEFR_LEVELS:
        level = _norm_level(level_hint)

    if level is None or len(parts) < 2:
        return None

    # NEW format: <number>_<objective>_<lesson...>
    maybe_num = _parse_number_token(parts[0])
    if maybe_num is not None and len(parts) >= 3:
        obj_no, lesson_no, token = maybe_num
        objective_key = parts[1].strip().lower()
        lesson_key = "_".join(parts[2:]).strip().lower()
        if objective_key and lesson_key:
            return level, objective_key, lesson_key, obj_no, lesson_no, token

    # OLD fallback: <objective>_<lesson...> (no number)
    objective_key = parts[0].strip().lower()
    lesson_key = "_".join(parts[1:]).strip().lower()
    if not objective_key or not lesson_key:
        return None

    return level, objective_key, lesson_key, 999, 999, ""


class CurriculumIndex:
    """
    Scans data/pages for German .md lessons (German-only app).

    Folder-driven, like the seed library: the CEFR level comes from the folder,
    so lessons live at

      data/pages/<level>/<num>_<objective>_<lesson>.md
      e.g. data/pages/a1/1.1_nouns_articles_(der, die, das).md

    The level is read from the immediate parent folder. Legacy flat files with
    the level encoded in the filename (data/pages/a1_1.1_..._.md) are still
    picked up.
    """

    def __init__(self):
        self.root = _pages_root()
        self._by_level: Dict[str, Dict[str, List[LessonRef]]] = {}

    def reload(self) -> None:
        self._by_level = {}
        root = self.root
        if not root.exists():
            return

        for md in root.rglob("*.md"):
            self._add_md(md)

    def _add_md(self, md_path: Path) -> None:
        # The parent folder name (e.g. "a1") supplies the level when the
        # filename omits it.
        level_hint = md_path.parent.name
        parsed = _parse_md_filename(md_path, level_hint=level_hint)
        if not parsed:
            return

        level, objective_key, lesson_key, obj_no, lesson_no, token = parsed

        ref = LessonRef(
            level=level,
            objective_key=objective_key,
            lesson_key=lesson_key,
            path=md_path,
            obj_no=obj_no,
            lesson_no=lesson_no,
            order_token=token,
        )

        self._by_level.setdefault(level, {}).setdefault(objective_key, []).append(ref)

    def levels(self) -> List[str]:
        return sorted(self._by_level.keys(), key=lambda x: CEFR_LEVELS.index(x))

    def objectives_for(self, level: str) -> Dict[str, List[LessonRef]]:
        level = _norm_level(level)
        return self._by_level.get(level, {})

    def resolve_reference(self, level: str, order_token: str) -> LessonRef | None:
        normalized_level = _norm_level(level)
        normalized_token = (order_token or '').strip()
        if normalized_level not in CEFR_LEVELS or not normalized_token:
            return None

        matches = [
            ref
            for lessons in self.objectives_for(normalized_level).values()
            for ref in lessons
            if ref.level == normalized_level
            and (ref.order_token or '').strip() == normalized_token
        ]
        return matches[0] if len(matches) == 1 else None


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
    start = md.find(ANSWERS_START)
    if start < 0:
        return md.strip(), None

    answer_start = start + len(ANSWERS_START)
    end = md.find(ANSWERS_END, answer_start)
    if end < 0:
        return md.strip(), None

    before = md[:start]
    ans = md[answer_start:end]
    after = md[end + len(ANSWERS_END):]
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


def _accent_for_level(level: str) -> str:
    """Stable accent per CEFR level, matching the order on the level page."""
    try:
        return _ACCENTS[CEFR_LEVELS.index(_norm_level(level)) % len(_ACCENTS)]
    except Exception:
        return _ACCENTS[0]


def _level_blurb(level: str) -> str:
    """Short, level-appropriate one-liner (mirrors the Practice/setup tab)."""
    return {
        "A1": "Beginner German — articles, present tense, and core sentence structure.",
        "A2": "Elementary German — past tense, cases, and connected sentences.",
        "B1": "Intermediate German — opinions, connected text, and broader grammar.",
        "B2": "Upper-intermediate German — nuanced expression and complex grammar.",
        "C1": "Advanced German — fluent, flexible language for demanding topics.",
        "C2": "Mastery German — precise, idiomatic command of the language.",
    }.get(_norm_level(level), "Structured German grammar lessons.")


def _level_icon_path(level: str) -> Optional[str]:
    """Pick a book cover icon for this CEFR level from assets/books/.

    Reuses the book-cover naming convention <camelBook>_<level>.<image>. A level
    can have several books, so one is chosen at random. Returns None when no
    cover exists for the level, in which case the card uses its gradient tile.
    """
    matches = level_cover_paths(level)
    return random.choice(matches) if matches else None


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
# Cards (match the Practice tab's vibe: dark cards, accent bar, hover engine)
# -------------------------

class _ClickableCard(QFrame):
    """A QFrame whose whole surface is clickable, with code-driven hover so the
    border/accents react together (same pattern as the book/Lektion cards)."""

    def __init__(self, on_click=None):
        super().__init__()
        self._on_click = on_click
        self._hover = False
        if callable(on_click):
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
        if event.button() == Qt.LeftButton and callable(self._on_click):
            try:
                inside = self.rect().contains(event.position().toPoint())
            except Exception:
                inside = True
            if inside:
                self._on_click()
        super().mouseReleaseEvent(event)


class LessonRow(_ClickableCard):
    """A single lesson: order token + title, with an Open affordance. The whole
    row is clickable; hover brightens it (Open button keeps the accent)."""

    def __init__(self, ref: LessonRef, accent: str, fallback_index: int, on_open):
        super().__init__(on_click=lambda: on_open(ref))
        self._accent = accent
        self.setObjectName("LessonRow")
        self.setMinimumHeight(56)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 12, 9)
        lay.setSpacing(14)

        token = ref.order_token if ref.order_token else str(fallback_index)
        num = QLabel(token)
        num.setFixedWidth(44)
        num.setAlignment(Qt.AlignCenter)
        num.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
        num.setStyleSheet(f"QLabel {{ color: {accent}; background: transparent; border: none; }}")

        title = QLabel(ref.lesson_title)
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        title.setWordWrap(True)
        title.setStyleSheet("QLabel { color: #FFFFFF; background: transparent; border: none; }")

        open_btn = QPushButton("Open")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setFixedHeight(32)
        open_btn.setMinimumWidth(78)
        open_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Black))
        open_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {accent};
                color: #0B0B0B;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 5px 14px;
                font-weight: 900;
            }}
            QPushButton:hover {{ border: 1px solid #FFFFFF; }}
        """)
        open_btn.clicked.connect(lambda: on_open(ref))

        lay.addWidget(num, 0)
        lay.addWidget(title, 1)
        lay.addWidget(open_btn, 0, Qt.AlignVCenter)

        self._apply_style()

    def _apply_style(self):
        bg = "rgba(255,255,255,0.065)" if self._hover else "rgba(255,255,255,0.035)"
        border = self._accent if self._hover else "rgba(255,255,255,0.08)"
        self.setStyleSheet(
            f"QFrame#LessonRow {{ background: {bg}; border: 1px solid {border}; border-radius: 14px; }}"
        )


class ObjectiveCard(QFrame):
    """An objective group: accent bar + number badge + title + its lesson rows.
    Static surface (interactivity lives in the rows) to avoid hover flicker."""

    def __init__(self, objective_key: str, lessons: List[LessonRef], accent: str, obj_no: int, on_open):
        super().__init__()
        self.setObjectName("ObjectiveCard")
        self.setStyleSheet(
            "QFrame#ObjectiveCard { background-color:#141414; border:1px solid #2B2B2B; border-radius:18px; }"
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QFrame()
        bar.setFixedWidth(6)
        bar.setStyleSheet(
            f"QFrame {{ background-color:{accent}; border-top-left-radius:18px; border-bottom-left-radius:18px; }}"
        )
        outer.addWidget(bar)

        body = QWidget()
        body.setStyleSheet("QWidget { background: transparent; }")
        outer.addWidget(body, 1)

        lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)

        badge = QLabel(str(obj_no) if obj_no != 999 else "•")
        badge.setFixedSize(42, 42)
        badge.setAlignment(Qt.AlignCenter)
        badge.setFont(QFont("Segoe UI", 14, QFont.Weight.Black))
        badge.setStyleSheet(f"QLabel {{ color:#0B0B0B; background-color:{accent}; border-radius:14px; }}")

        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        if obj_no != 999:
            title_text = f"Objective {obj_no}: {_pretty(objective_key)}"
        else:
            title_text = f"Objective: {_pretty(objective_key)}"
        title = QLabel(title_text)
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Black))
        title.setStyleSheet("QLabel { color:#FFFFFF; background: transparent; }")

        sub = QLabel(f"{len(lessons)} lesson(s)")
        sub.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        sub.setStyleSheet("QLabel { color:#A1A1AA; background: transparent; }")

        title_box.addWidget(title)
        title_box.addWidget(sub)

        chip = QLabel(str(len(lessons)))
        chip.setAlignment(Qt.AlignCenter)
        chip.setFont(QFont("Segoe UI", 10, QFont.Weight.Black))
        chip.setStyleSheet(
            "QLabel { color:#D7DAE0; background-color:#101010; border:1px solid #2E2E2E; "
            "border-radius:10px; padding:5px 12px; }"
        )

        header.addWidget(badge, 0)
        header.addLayout(title_box, 1)
        header.addWidget(chip, 0, Qt.AlignTop)
        lay.addLayout(header)

        for i, ref in enumerate(_sort_lessons_in_objective(lessons), start=1):
            lay.addWidget(LessonRow(ref, accent, i, on_open))


class LevelCard(_ClickableCard):
    """A CEFR level on the Learn landing page — gradient level tile, blurb, and
    a live lesson count. Disabled (dimmed) when the level has no lessons yet."""

    def __init__(self, level: str, accent: str, on_click, icon_path: Optional[str] = None):
        super().__init__(on_click=lambda: on_click(level))
        self._accent = accent
        self._level = level
        self._available = True
        self.setObjectName("LevelCard")
        self.setMinimumHeight(108)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(shadow)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 14, 18, 14)
        root.setSpacing(16)

        # Cover tile: a random book cover for this level.
        # rendered crisp + HiDPI-aware filling the tile; otherwise a gradient
        # level-code tile.
        cover = rounded_cover_pixmap(icon_path, 68, 80, 16) if icon_path else None
        if cover is not None:
            tile = QLabel()
            tile.setFixedSize(68, 80)
            tile.setAlignment(Qt.AlignCenter)
            tile.setStyleSheet("QLabel { background: transparent; border: none; }")
            tile.setPixmap(cover)
        else:
            tile = QFrame()
            tile.setFixedSize(68, 80)
            tile.setStyleSheet(
                f"QFrame {{ border-radius:16px; border:1px solid rgba(255,255,255,0.22); "
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {accent}, stop:1 #111827); }}"
            )
            tlay = QVBoxLayout(tile)
            tlay.setContentsMargins(4, 6, 4, 6)
            lvl_lbl = QLabel(level)
            lvl_lbl.setAlignment(Qt.AlignCenter)
            lvl_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
            lvl_lbl.setStyleSheet("QLabel { color:#FFFFFF; background:transparent; border:none; }")
            tlay.addWidget(lvl_lbl)

        mid = QVBoxLayout()
        mid.setSpacing(5)

        self.title = QLabel(f"{level} · German")
        self.title.setFont(QFont("Segoe UI", 13, QFont.Weight.Black))
        self.title.setStyleSheet("QLabel { color:#FFFFFF; background:transparent; }")

        self.blurb = QLabel(_level_blurb(level))
        self.blurb.setWordWrap(True)
        self.blurb.setFont(QFont("Segoe UI", 9))
        self.blurb.setStyleSheet("QLabel { color:#A1A1AA; background:transparent; }")

        self.count = QLabel("")
        self.count.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.count.setStyleSheet(
            "QLabel { color:#D7DAE0; background-color:#101010; border:1px solid #2E2E2E; "
            "border-radius:10px; padding:3px 10px; }"
        )
        count_row = QHBoxLayout()
        count_row.addWidget(self.count, 0)
        count_row.addStretch(1)

        mid.addWidget(self.title)
        mid.addWidget(self.blurb)
        mid.addLayout(count_row)

        self.chevron = QLabel("→")
        self.chevron.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        self.chevron.setStyleSheet(f"QLabel {{ color:{accent}; background:transparent; }}")

        root.addWidget(tile, 0)
        root.addLayout(mid, 1)
        root.addWidget(self.chevron, 0, Qt.AlignVCenter)

        self._apply_style()

    def set_available(self, available: bool, lesson_count: int):
        self._available = bool(available)
        self.setEnabled(self._available)  # disabled -> no clicks/hover + dimmed
        self.count.setText(f"{lesson_count} lesson(s)" if available else "Coming soon")
        self.chevron.setVisible(self._available)
        self._apply_style()

    def _apply_style(self):
        if not self._available:
            self.setStyleSheet(
                "QFrame#LevelCard { background-color:#0E0E0E; border:1px solid #232323; border-radius:18px; }"
            )
            return
        bg = "#161616" if self._hover else "#141414"
        border = "#FFFFFF" if self._hover else "#2B2B2B"
        self.setStyleSheet(
            f"QFrame#LevelCard {{ background-color:{bg}; border:1px solid {border}; border-radius:18px; }}"
        )


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

        self.page_level = self._make_level_page()
        self.page_obj = self._make_objectives_page()
        self.page_reader = self._make_reader_page()

        self.stack.addWidget(self.page_level)   # 0
        self.stack.addWidget(self.page_obj)     # 1
        self.stack.addWidget(self.page_reader)  # 2

        self._goto(0)

    def on_show(self):
        self.index.reload()
        self._refresh_levels_enabled()
        if self.stack.currentIndex() == 1:
            self._render_objectives()

    def open_reference(self, level: str, order_token: str) -> bool:
        self.index.reload()
        ref = self.index.resolve_reference(level, order_token)
        if ref is None:
            return False

        self.level = ref.level
        self._open_lesson(ref)
        return True

    def _goto(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self.back_btn.setEnabled(idx != 0)
        self._update_breadcrumb()

    def _back(self):
        idx = self.stack.currentIndex()
        if idx == 2:
            self._goto(1)
        elif idx == 1:
            self._goto(0)

    def _update_breadcrumb(self):
        parts = []
        if self.level:
            parts.append(self.level)
        if self.current_lesson:
            parts.append(self.current_lesson.lesson_title)
        self.breadcrumb.setText("  •  ".join(parts) if parts else " ")

    def _clear_vbox(self, vbox: QVBoxLayout):
        while vbox.count():
            item = vbox.takeAt(0)
            ww = item.widget()
            if ww is not None:
                ww.deleteLater()

    # -------------------------
    # Level page
    # -------------------------

    def _make_level_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel("Choose your level")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Black))
        title.setStyleSheet("QLabel { color:#FFFFFF; }")
        lay.addWidget(title)

        subtitle = QLabel("Pick a CEFR level to open its grammar curriculum, objective by objective.")
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("QLabel { color:#A1A1AA; }")
        lay.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")

        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        col = QVBoxLayout(inner)
        col.setContentsMargins(2, 6, 12, 8)
        col.setSpacing(14)

        self.level_cards: Dict[str, LevelCard] = {}
        for lvl in CEFR_LEVELS:
            card = LevelCard(
                lvl,
                _accent_for_level(lvl),
                self._choose_level,
                icon_path=_level_icon_path(lvl),
            )
            self.level_cards[lvl] = card
            col.addWidget(card)
        col.addStretch(1)

        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        self.level_hint = QLabel("")
        self.level_hint.setFont(QFont("Segoe UI", 9))
        self.level_hint.setAlignment(Qt.AlignCenter)
        # Full sentences, cut by 90 px at the default window size without one.
        self.level_hint.setWordWrap(True)
        self.level_hint.setStyleSheet("QLabel { color:#B0B0B0; }")
        lay.addWidget(self.level_hint)
        return w

    def _refresh_levels_enabled(self):
        available = set(self.index.levels())
        for lvl, card in self.level_cards.items():
            objs = self.index.objectives_for(lvl)
            n_lessons = sum(len(v) for v in objs.values())
            card.set_available(lvl in available, n_lessons)

        self.level_hint.setText(
            "No lessons found yet. Add .md files under data/pages/<level>/"
            if not available else
            "Tip: open a level, then pick a lesson to read the concept before you practice."
        )

    def _choose_level(self, lvl: str):
        self.level = _norm_level(lvl)
        self.current_objective = None
        self.current_lesson = None
        self._goto(1)
        self._render_objectives()

    # -------------------------
    # Objectives page
    # -------------------------

    def _make_objectives_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.obj_title = QLabel("Curriculum Map")
        self.obj_title.setFont(QFont("Segoe UI", 18, QFont.Weight.Black))
        self.obj_title.setStyleSheet("QLabel { color:#FFFFFF; }")
        lay.addWidget(self.obj_title)

        self.obj_subtitle = QLabel("")
        self.obj_subtitle.setFont(QFont("Segoe UI", 10))
        self.obj_subtitle.setStyleSheet("QLabel { color:#A1A1AA; }")
        lay.addWidget(self.obj_subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.obj_inner = QWidget()
        self.obj_inner.setStyleSheet("background:transparent;")
        self.obj_layout = QVBoxLayout(self.obj_inner)
        self.obj_layout.setContentsMargins(2, 6, 12, 8)
        self.obj_layout.setSpacing(16)
        scroll.setWidget(self.obj_inner)

        lay.addWidget(scroll, 1)
        return w

    def _render_objectives(self):
        self._clear_vbox(self.obj_layout)

        if not self.level:
            return

        obj_map = self.index.objectives_for(self.level)
        total_lessons = sum(len(v) for v in obj_map.values())

        self.obj_title.setText(f"{self.level} • Curriculum Map")
        self.obj_subtitle.setText(
            f"{len(obj_map)} objective(s) • {total_lessons} lesson(s) — open a lesson to read the concept."
        )

        if not obj_map:
            empty = QLabel("No lessons for this level yet.")
            empty.setFont(QFont("Segoe UI", 10))
            empty.setStyleSheet("QLabel { color:#A1A1AA; }")
            self.obj_layout.addWidget(empty)
            self.obj_layout.addStretch(1)
            return

        # Sort objectives purely by numeric group number from filenames (min obj_no)
        items = list(obj_map.items())
        items.sort(key=lambda kv: (_objective_group_number(kv[1]), _pretty(kv[0])))

        for obj_key, lessons in items:
            card = ObjectiveCard(
                obj_key,
                lessons,
                _accent_for_key(obj_key),
                _objective_group_number(lessons),
                self._open_lesson,
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

        self._goto(2)
