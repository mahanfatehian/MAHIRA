"""Activity heat-calendar for MAHIRA.

A self-contained, custom-painted widget that renders one glowing dot per day for
the last ~year, where hotter (more active) days burn brighter. It is purely a
visualisation — feed it a {'YYYY-MM-DD': count} dict via set_data(). Brightness is
tied to the user's daily goal, so a day that hits the goal lights up to the
brightest cyan-mint and gives off a soft heat glow — that's the thing that makes
the calendar feel worth keeping lit.

Deliberately NOT a grid of flat green squares — rounded heat dots, a cool→hot
ramp drawn from the app's own accent colours, and a glow on busy days. No OS
integration, no timers — it just paints. Dot size is responsive so the grid
always fits its column without a scrollbar.
"""
from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

# --- palette: a true COLD -> HOT ramp. An inactive day is icy blue-white (cold);
# as you do more it warms up and a goal-hitting day burns bright orange-red.
# That ice<->fire contrast is the whole point — a frosty calendar you set alight.
_EMPTY_FILL = "#7FA6C6"      # a day with no activity (icy blue — cold)
_EMPTY_RING = "#A6C7DE"      # frosty rim
_LEVELS = ("#F3CE85", "#EE9B45", "#E4641E", "#FF5A28")  # 1..4: warm -> hot fire
_GLOW = "#FF7A2E"            # halo tint for the hottest days
_LABEL = "#8A8A8A"           # month / weekday captions
_LEGEND = "#8A8A8A"

_WEEKDAY_LABELS = {0: "Mon", 2: "Wed", 4: "Fri"}  # only label a few rows
_WEEKDAY_FULL = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_GAP = 4              # a touch more breathing room than a tight GitHub grid
_LEFT_PAD = 30        # room for weekday labels
_TOP_PAD = 18         # room for month labels
_LEGEND_H = 26        # room for the legend row beneath the grid (no clipping)
_MIN_CELL = 9
_MAX_CELL = 15


class ActivityHeatmap(QWidget):
    def __init__(self, weeks: int = 53, parent=None):
        super().__init__(parent)
        self._weeks = max(8, int(weeks))
        self._counts: dict[str, int] = {}
        self._goal = 20
        self._today = _dt.date.today()
        # Filled during paint, reused for hover hit-testing: (rect, date, count).
        self._hot: list[tuple[QRectF, _dt.date, int]] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(int(_TOP_PAD + 7 * (12 + _GAP) + _LEGEND_H))
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    def resizeEvent(self, event) -> None:
        # Height must track the responsive cell size, otherwise the bottom rows
        # or the legend clip. Pin it to exactly what the current width needs.
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
        """Monday of the leftmost column."""
        monday_this_week = self._today - _dt.timedelta(days=self._today.weekday())
        return monday_this_week - _dt.timedelta(weeks=self._weeks - 1)

    # -- painting ------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        step = self._cell_step()
        cell = step - _GAP
        first_monday = self._first_monday()
        self._hot.clear()

        cap_font = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        p.setFont(cap_font)

        # weekday captions (left column)
        p.setPen(QColor(_LABEL))
        for row, label in _WEEKDAY_LABELS.items():
            y = _TOP_PAD + row * step
            p.drawText(QRectF(0, y, _LEFT_PAD - 4, cell),
                       Qt.AlignRight | Qt.AlignVCenter, label)

        # Collect every day cell (and draw month captions) up front, so glow
        # halos can be painted as a layer *behind* all the dots.
        cells: list[tuple[QRectF, int]] = []
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
                    continue  # leave the rest of the current week blank
                y = _TOP_PAD + row * step
                rect = QRectF(x, y, cell, cell)
                count = int(self._counts.get(day.isoformat(), 0))
                lvl = self._level(count)
                cells.append((rect, lvl))
                self._hot.append((rect, day, count))

        # pass 1 — soft heat glow behind the busiest days
        p.setPen(Qt.NoPen)
        for rect, lvl in cells:
            if lvl >= 3:
                self._paint_glow(p, rect, lvl)
        # pass 2 — the dots themselves
        for rect, lvl in cells:
            self._paint_dot(p, rect, lvl)

        # legend: cold ▢▢▢▢▢ on fire (bottom-right), with its own roomy row
        grid_bottom = _TOP_PAD + 7 * step
        legend_y = grid_bottom + 5
        row_h = 14.0
        lc = min(cell, 12.0)
        lstep = lc + _GAP
        dot_voff = (row_h - lc) / 2.0
        total_w = 5 * lstep + 96
        lx = max(_LEFT_PAD, self.width() - total_w)
        p.setPen(QColor(_LEGEND))
        p.drawText(QRectF(lx, legend_y, 30, row_h),
                   Qt.AlignRight | Qt.AlignVCenter, "cold")
        bx = lx + 34
        for i in range(5):
            r = QRectF(bx + i * lstep, legend_y + dot_voff, lc, lc)
            self._paint_dot(p, r, i)  # i == 0 is the empty square, 1..4 the heat ramp
        p.setPen(QColor(_LEGEND))
        p.drawText(QRectF(bx + 5 * lstep + 4, legend_y, 60, row_h),
                   Qt.AlignLeft | Qt.AlignVCenter, "on fire")
        p.end()

    @staticmethod
    def _paint_dot(p: QPainter, rect: QRectF, lvl: int) -> None:
        rad = rect.width() * 0.22  # softly rounded squares
        if lvl <= 0:
            p.setPen(QPen(QColor(_EMPTY_RING), 1.0))
            p.setBrush(QColor(_EMPTY_FILL))
            p.drawRoundedRect(rect, rad, rad)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(_LEVELS[lvl - 1]))
            p.drawRoundedRect(rect, rad, rad)

    @staticmethod
    def _paint_glow(p: QPainter, rect: QRectF, lvl: int) -> None:
        base = QColor(_GLOW) if lvl >= 4 else QColor(_LEVELS[lvl - 1])
        cx = rect.x() + rect.width() / 2.0
        cy = rect.y() + rect.height() / 2.0
        p.setPen(Qt.NoPen)
        # two concentric low-alpha halos give a soft, warm falloff
        for grow, alpha in ((1.95, 22 if lvl == 3 else 36),
                            (1.45, 42 if lvl == 3 else 72)):
            halo = QColor(base)
            halo.setAlpha(alpha)
            w = rect.width() * grow
            rr = w * 0.28
            p.drawRoundedRect(QRectF(cx - w / 2.0, cy - w / 2.0, w, w), rr, rr)

    # -- hover tooltips ------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:
        pos = event.position() if hasattr(event, "position") else event.pos()
        px, py = pos.x(), pos.y()
        for rect, day, count in self._hot:
            if rect.contains(px, py):
                noun = "review" if count == 1 else "reviews"
                when = f"{_WEEKDAY_FULL[day.weekday()]}, {_MONTHS[day.month - 1]} {day.day}, {day.year}"
                gpos = (event.globalPosition().toPoint() if hasattr(event, "globalPosition")
                        else event.globalPos())
                QToolTip.showText(gpos, f"{count} {noun} · {when}", self)
                return
        QToolTip.hideText()
        super().mouseMoveEvent(event)
