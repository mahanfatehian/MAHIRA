"""Frozen → Fire activity calendar for MAHIRA.

The emotional core: an inactive day must look like a **dead, cold pane of frosted
glass** — near-black navy, an icy rim, a faint frost glint — never a cheerful blue
"completed" square. Studying melts the ice: a little warmth turns a day to thawing
cyan, more to amber, and hitting the goal sets it on fire (orange → red, glowing).
The user should want to melt the frozen field into a fire trail and keep it lit.

Feed it a {'YYYY-MM-DD': count} dict via set_data(). Pure painting, no timers.

Each level's tile is rendered once into a cached pixmap (the frozen tile is
genuinely layered glass), so the grid + hover stay smooth. Glows are painted live
behind the tiles. Tile size is responsive; the grid fits its column without a
scrollbar.
"""
from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt, QPointF, QRectF, QSize
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QToolTip, QWidget

# --- ACTIVE palette (cold thaw -> hot fire). Frozen has its own glass renderer.
# 1 Thawing: dark teal (still cold) lifted by a cyan glow.
# 2 Warming: amber.  3 Warm: hot orange.  4 On fire: orange->red gradient.
_LEVELS = ("#0D2A34", "#D97706", "#F97316")   # levels 1, 2, 3
_FIRE_TOP = "#F97316"
_FIRE_BOTTOM = "#EF4444"                        # level 4

_GLOW_COOL = (64, 211, 255)    # thawing cyan
_GLOW_WARM = (245, 158, 11)    # warming amber
_GLOW_FIRE = (249, 115, 22)    # on-fire orange

_TODAY_WARM = "#FFC368"        # today ring when the day is alive
_TODAY_COLD = "#A6C2D8"        # today ring when the day is still frozen
_LABEL = "#8A8A8A"
_LEGEND = "#9A9A9A"

_STATE_NAME = ("Frozen day", "Thawing", "Warming up", "Warm", "On fire")
_LEGEND_ITEMS = (("Frozen", 0), ("Thawing", 1), ("Warm", 2), ("On Fire", 4))

_WEEKDAY_LABELS = {0: "Mon", 2: "Wed", 4: "Fri"}
_WEEKDAY_FULL = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_GAP = 4
_LEFT_PAD = 30
_TOP_PAD = 18
_LEGEND_H = 26
_MIN_CELL = 9
_MAX_CELL = 15


# ---------------------------------------------------------------------------
# Tile renderers (paint into a small rect; called once per level into a cache)
# ---------------------------------------------------------------------------
def _paint_frozen_tile(p: QPainter, rect: QRectF, rad: float) -> None:
    """A dead, cold pane of frosted glass — dark, glassy, icy-rimmed, not blue."""
    # base: deep navy -> near-black
    base = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    base.setColorAt(0.0, QColor("#111A24"))
    base.setColorAt(1.0, QColor("#080D13"))
    p.setPen(Qt.NoPen)
    p.setBrush(base)
    p.drawRoundedRect(rect, rad, rad)

    path = QPainterPath()
    path.addRoundedRect(rect, rad, rad)
    p.save()
    p.setClipPath(path)
    x0, y0, w, h = rect.x(), rect.y(), rect.width(), rect.height()

    # diagonal glass sheen (very low-alpha white)
    sheen = QLinearGradient(rect.topLeft(), rect.bottomRight())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 14))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 1))
    p.setBrush(sheen)
    p.drawRect(rect)

    # icy frost glint, top-left
    glint = QRadialGradient(x0 + w * 0.30, y0 + h * 0.20, w * 0.55)
    glint.setColorAt(0.0, QColor(210, 240, 255, 33))
    glint.setColorAt(0.7, QColor(210, 240, 255, 0))
    p.setBrush(glint)
    p.drawRect(rect)

    # inner bottom shadow (inset feel)
    ish = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    ish.setColorAt(0.55, QColor(0, 0, 0, 0))
    ish.setColorAt(1.0, QColor(0, 0, 0, 82))
    p.setBrush(ish)
    p.drawRect(rect)

    # two faint frost lines (the little glass facets)
    p.setPen(QPen(QColor(230, 250, 255, 40), max(1.0, w * 0.06)))
    p.drawLine(QPointF(x0 + w * 0.10, y0 + h * 0.52), QPointF(x0 + w * 0.52, y0 + h * 0.10))
    p.setPen(QPen(QColor(230, 250, 255, 24), max(1.0, w * 0.05)))
    p.drawLine(QPointF(x0 + w * 0.46, y0 + h * 0.86), QPointF(x0 + w * 0.84, y0 + h * 0.50))

    # 1px inner top highlight
    p.setPen(QPen(QColor(255, 255, 255, 20), 1.0))
    p.drawLine(QPointF(x0 + rad * 0.6, y0 + 1.0), QPointF(x0 + w - rad * 0.6, y0 + 1.0))
    p.restore()

    # thin icy border
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(185, 225, 245, 52), 1.0))
    p.drawRoundedRect(rect, rad, rad)


def _paint_active_tile(p: QPainter, rect: QRectF, rad: float, lvl: int) -> None:
    """A warm/lit tile — clearly more rewarding than the frozen glass."""
    if lvl >= 4:
        top, bottom = QColor(_FIRE_TOP), QColor(_FIRE_BOTTOM)
    else:
        base = QColor(_LEVELS[lvl - 1])
        top, bottom = base.lighter(116), base.darker(110)
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, top)
    grad.setColorAt(1.0, bottom)
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(rect, rad, rad)

    path = QPainterPath()
    path.addRoundedRect(rect, rad, rad)
    p.save()
    p.setClipPath(path)
    sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 48))
    sheen.setColorAt(0.5, QColor(255, 255, 255, 0))
    p.setBrush(sheen)
    p.drawRect(rect)
    p.restore()

    if lvl == 1:
        border = QColor(90, 210, 240, 120)          # cool cyan rim (thawing)
    else:
        border = QColor(top.lighter(130))
        border.setAlpha(175)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(border, 1.0))
    p.drawRoundedRect(rect, rad, rad)


class ActivityHeatmap(QWidget):
    def __init__(self, weeks: int = 53, parent=None):
        super().__init__(parent)
        self._weeks = max(8, int(weeks))
        self._counts: dict[str, int] = {}
        self._goal = 20
        self._today = _dt.date.today()
        self._hover_day: _dt.date | None = None
        self._hot: list[tuple[QRectF, _dt.date, int]] = []
        self._tile_cache: dict[int, QPixmap] = {}
        self._cache_size: int = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(int(_TOP_PAD + 7 * (12 + _GAP) + _LEGEND_H))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        needed = int(_TOP_PAD + 7 * self._cell_step() + _LEGEND_H)
        if self.height() != needed:
            self.setFixedHeight(needed)

    # -- public API ----------------------------------------------------------
    def set_data(self, counts: dict[str, int], goal: int, today: _dt.date | None = None) -> None:
        self._counts = counts or {}
        self._goal = max(1, int(goal or 1))
        self._today = today or _dt.date.today()
        self.updateGeometry()
        self.update()

    # -- sizing --------------------------------------------------------------
    def _cell_step(self) -> float:
        avail = max(0, self.width() - _LEFT_PAD - 2)
        step = avail / self._weeks if self._weeks else _MAX_CELL + _GAP
        cell = max(_MIN_CELL, min(_MAX_CELL, step - _GAP))
        return cell + _GAP

    def sizeHint(self) -> QSize:
        step = _MAX_CELL + _GAP
        return QSize(int(_LEFT_PAD + self._weeks * step),
                     int(_TOP_PAD + 7 * step + _LEGEND_H))

    def heightForWidth(self, w: int) -> int:
        avail = max(0, w - _LEFT_PAD - 2)
        step = avail / self._weeks if self._weeks else _MAX_CELL + _GAP
        cell = max(_MIN_CELL, min(_MAX_CELL, step - _GAP))
        return int(_TOP_PAD + 7 * (cell + _GAP) + _LEGEND_H)

    # -- model ---------------------------------------------------------------
    def _level(self, count: int) -> int:
        """Map a day's review count to a temperature 0..4 against the goal.
        Tweak these cutoffs to change how fast a day heats up."""
        if count <= 0:
            return 0
        g = self._goal
        if count >= g:
            return 4
        if count >= g * 0.5:
            return 3
        if count >= g * 0.25:
            return 2
        return 1

    def _first_monday(self) -> _dt.date:
        monday_this_week = self._today - _dt.timedelta(days=self._today.weekday())
        return monday_this_week - _dt.timedelta(weeks=self._weeks - 1)

    # -- tile pixmap cache ---------------------------------------------------
    def _build_tile(self, isz: int, lvl: int) -> QPixmap:
        dpr = 2
        pm = QPixmap(isz * dpr, isz * dpr)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0.6, 0.6, isz - 1.2, isz - 1.2)
        rad = isz * 0.30
        if lvl <= 0:
            _paint_frozen_tile(p, rect, rad)
        else:
            _paint_active_tile(p, rect, rad, lvl)
        p.end()
        return pm

    def _ensure_cache(self, cell: float) -> None:
        isz = max(1, int(round(cell)))
        if isz != self._cache_size:
            self._cache_size = isz
            self._tile_cache = {lvl: self._build_tile(isz, lvl) for lvl in range(5)}

    # -- painting ------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        step = self._cell_step()
        cell = step - _GAP
        self._ensure_cache(cell)
        first_monday = self._first_monday()
        self._hot.clear()

        p.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))

        # weekday captions
        p.setPen(QColor(_LABEL))
        for row, label in _WEEKDAY_LABELS.items():
            y = _TOP_PAD + row * step
            p.drawText(QRectF(0, y, _LEFT_PAD - 4, cell),
                       Qt.AlignRight | Qt.AlignVCenter, label)

        cells: list[tuple[QRectF, int, _dt.date]] = []
        last_month = -1
        for col in range(self._weeks):
            x = _LEFT_PAD + col * step
            col_monday = first_monday + _dt.timedelta(weeks=col)
            if col_monday.month != last_month:
                last_month = col_monday.month
                p.setPen(QColor(_LABEL))
                p.drawText(QRectF(x, 0, step * 3, _TOP_PAD - 2),
                           Qt.AlignLeft | Qt.AlignVCenter, _MONTHS[col_monday.month - 1])
            for row in range(7):
                day = first_monday + _dt.timedelta(weeks=col, days=row)
                if day > self._today:
                    continue
                y = _TOP_PAD + row * step
                rect = QRectF(x, y, cell, cell)
                count = int(self._counts.get(day.isoformat(), 0))
                lvl = self._level(count)
                cells.append((rect, lvl, day))
                self._hot.append((rect, day, count))

        # pass 1 — glows behind tiles (none for frozen; hover lifts a tile)
        p.setPen(Qt.NoPen)
        for rect, lvl, day in cells:
            self._glow_for(p, rect, lvl)
            if day == self._hover_day:
                tint = (_GLOW_FIRE if lvl >= 3 else _GLOW_WARM if lvl == 2
                        else _GLOW_COOL)
                self._glow(p, rect, tint, ((1.85, 56),))

        # pass 2 — the cached tiles
        for rect, lvl, day in cells:
            p.drawPixmap(QPointF(rect.x(), rect.y()), self._tile_cache[lvl])

        # pass 3 — today highlight + hover border
        for rect, lvl, day in cells:
            if day == self._today:
                self._paint_today(p, rect, lvl)
            if day == self._hover_day:
                self._paint_hover_border(p, rect, lvl)

        self._paint_legend(p, step, cell)
        p.end()

    def _glow_for(self, p: QPainter, rect: QRectF, lvl: int) -> None:
        if lvl == 1:
            self._glow(p, rect, _GLOW_COOL, ((1.75, 34),))
        elif lvl == 2:
            self._glow(p, rect, _GLOW_WARM, ((1.65, 30),))
        elif lvl == 3:
            self._glow(p, rect, _GLOW_WARM, ((1.95, 36), (1.5, 58)))
        elif lvl >= 4:
            self._glow(p, rect, _GLOW_FIRE, ((2.05, 50), (1.5, 96)))

    @staticmethod
    def _glow(p: QPainter, rect: QRectF, rgb, layers) -> None:
        cx = rect.x() + rect.width() / 2.0
        cy = rect.y() + rect.height() / 2.0
        for grow, alpha in layers:
            c = QColor(rgb[0], rgb[1], rgb[2], alpha)
            w = rect.width() * grow
            rr = w * 0.3
            p.setBrush(c)
            p.drawRoundedRect(QRectF(cx - w / 2.0, cy - w / 2.0, w, w), rr, rr)

    @staticmethod
    def _paint_today(p: QPainter, rect: QRectF, lvl: int) -> None:
        ring = QColor(_TODAY_WARM) if lvl > 0 else QColor(_TODAY_COLD)
        r = rect.adjusted(-1.6, -1.6, 1.6, 1.6)
        rad = r.width() * 0.32
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ring, 1.7))
        p.drawRoundedRect(r, rad, rad)

    @staticmethod
    def _paint_hover_border(p: QPainter, rect: QRectF, lvl: int) -> None:
        col = QColor(*(_GLOW_FIRE if lvl >= 3 else _GLOW_WARM if lvl == 2 else (207, 230, 242)))
        rad = rect.width() * 0.30
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col, 1.4))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)

    def _paint_legend(self, p: QPainter, step: float, cell: float) -> None:
        grid_bottom = _TOP_PAD + 7 * step
        ly = grid_bottom + 6
        row_h = 14.0
        sw = min(int(round(cell)), 12)
        voff = (row_h - sw) / 2.0
        fm = p.fontMetrics()
        x = _LEFT_PAD
        for label, lvl in _LEGEND_ITEMS:
            p.drawPixmap(QPointF(x, ly + voff), self._tile_cache[lvl])
            x += sw + 5
            p.setPen(QColor(_LEGEND))
            tw = fm.horizontalAdvance(label)
            p.drawText(QRectF(x, ly, tw + 4, row_h), Qt.AlignLeft | Qt.AlignVCenter, label)
            x += tw + 18

    # -- hover + tooltips ----------------------------------------------------
    def mouseMoveEvent(self, event) -> None:
        pos = event.position() if hasattr(event, "position") else event.pos()
        px, py = pos.x(), pos.y()
        hover_day: _dt.date | None = None
        for rect, day, count in self._hot:
            if rect.contains(px, py):
                hover_day = day
                lvl = self._level(count)
                noun = "review" if count == 1 else "reviews"
                when = f"{_WEEKDAY_FULL[day.weekday()]}, {_MONTHS[day.month - 1]} {day.day}, {day.year}"
                tag = "  ·  Today" if day == self._today else ""
                if day == self._today and count == 0:
                    third = "Today is still frozen"
                else:
                    third = f"State: {_STATE_NAME[lvl]}"
                gpos = (event.globalPosition().toPoint() if hasattr(event, "globalPosition")
                        else event.globalPos())
                QToolTip.showText(gpos, f"{when}{tag}\n{count} {noun}\n{third}", self)
                break
        if hover_day != self._hover_day:
            self._hover_day = hover_day
            self.update()
        if hover_day is None:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_day is not None:
            self._hover_day = None
            self.update()
        super().leaveEvent(event)
