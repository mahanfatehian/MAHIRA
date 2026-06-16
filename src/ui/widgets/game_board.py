"""The Blitz play field: a custom-painted board of word circles the player
connects in pairs, with combo juice (pops, particles, floating scores, combo
flashes) and a round countdown.

The board owns the *interaction + animation*; it stays UI-only and emits
semantic signals (`hitMade`, `missMade`, `milestoneReached`, `roundFinished`,
plus HUD deltas) that the page turns into sound, speech, and persistence. The
scoring rules live in `core.game.scoring`; the pair/wave data is handed in by
the page from `core.game.pairs`.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from core.game.pairs import ARTICLE, MEANING, PLURAL
from core.game.scoring import ScoreState

# Per-relationship accent + caption. The accent tints only the ring/caption — the
# body stays neutral, so colour hints *what kind* of link to find without giving
# away *which two* circles match (several circles can share a kind).
_KIND_STYLE = {
    ARTICLE: ("#34D2E0", "article"),
    PLURAL: ("#FFB020", "plural"),
    MEANING: ("#66E39A", "meaning"),
}
_DEFAULT_ACCENT = "#9E9E9E"

_CIRCLE_R = 54.0
_FRAME_MS = 16


def _ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1.0 - (1.0 - x) ** 3


@dataclass
class _Circle:
    pair_id: int
    side: str
    text: str
    kind: str
    vocab_id: int
    word: str
    x: float = 0.0
    y: float = 0.0
    r: float = _CIRCLE_R
    jx: float = 0.0  # stable jitter fraction, assigned once at spawn
    jy: float = 0.0
    matched: bool = False
    done: bool = False
    appear: float = 0.0   # 0..1 spawn-in
    pop: float = 0.0      # 0..1 clear animation
    shake: float = 0.0    # 1 -> 0 wrong-answer wobble
    selected: bool = False


@dataclass
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: QColor


@dataclass
class _Float:
    x: float
    y: float
    text: str
    life: float
    max_life: float
    color: QColor


@dataclass
class _ComboFlash:
    text: str
    life: float = 0.0
    max_life: float = 0.9


class GameBoard(QWidget):
    started = Signal()
    scoreChanged = Signal(int)
    comboChanged = Signal(int)
    timeChanged = Signal(int)               # seconds remaining
    hitMade = Signal(str, int, int)         # word, points, combo
    missMade = Signal()
    milestoneReached = Signal(int)          # combo value
    roundFinished = Signal(int, int, int, int)  # score, max_combo, hits, misses

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("GameBoard")
        self.setMinimumHeight(520)
        self.setStyleSheet("GameBoard { background: transparent; }")

        self._waves: list[list] = []
        self._wave_idx: int = 0
        self._circles: list[_Circle] = []
        self._selected: _Circle | None = None
        self._selected_at: float = 0.0

        self._score = ScoreState()
        self._running = False
        self._duration_ms = 0.0
        self._remaining_ms = 0.0
        self._last_secs = -1

        self._particles: list[_Particle] = []
        self._floats: list[_Float] = []
        self._flash: _ComboFlash | None = None

        self._pending_spawn = False
        self._spawn_gap_ms = 0.0

        self._last_tick = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._tick)

    # ----------------------------------------------------------------- API
    @property
    def is_running(self) -> bool:
        return self._running

    def start_game(self, waves: list[list], duration_s: int = 60) -> None:
        self._waves = [list(w) for w in waves if w]
        self._wave_idx = 0
        self._score = ScoreState()
        self._selected = None
        self._particles.clear()
        self._floats.clear()
        self._flash = None
        self._pending_spawn = False
        self._duration_ms = float(duration_s) * 1000.0
        self._remaining_ms = self._duration_ms
        self._last_secs = -1
        self._running = bool(self._waves)

        self.scoreChanged.emit(0)
        self.comboChanged.emit(0)
        self.timeChanged.emit(int(duration_s))

        if not self._waves:
            self._running = False
            self.roundFinished.emit(0, 0, 0, 0)
            return

        self._spawn_wave(0)
        self._last_tick = time.monotonic()
        self.started.emit()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        """Halt the round without emitting a result (used when leaving the tab)."""
        self._running = False
        self._pending_spawn = False
        if self._timer.isActive():
            self._timer.stop()

    # ------------------------------------------------------------- layout
    def _spawn_wave(self, idx: int) -> None:
        self._wave_idx = idx
        pairs = self._waves[idx]
        circles: list[_Circle] = []
        for pid, pair in enumerate(pairs):
            circles.append(_Circle(pid, "a", pair.a, pair.kind, pair.vocab_id, pair.word))
            circles.append(_Circle(pid, "b", pair.b, pair.kind, pair.vocab_id, pair.word))
        random.shuffle(circles)
        # Freeze each circle's jitter once so a re-layout (window resize, focus
        # toggle) re-flows the grid without teleporting circles mid-connect.
        for c in circles:
            c.jx = random.uniform(-0.16, 0.16)
            c.jy = random.uniform(-0.16, 0.16)
        self._circles = circles
        self._selected = None
        self._layout_circles()

    def _layout_circles(self) -> None:
        if not self._circles:
            return
        w = max(self.width(), 640)
        h = max(self.height(), 480)
        margin = _CIRCLE_R + 18
        top = 64.0  # leave room for the timer bar
        n = len(self._circles)
        cols = 3 if n > 4 else max(1, min(n, 2))
        rows = max(1, math.ceil(n / cols))
        cell_w = (w - 2 * margin) / cols
        cell_h = (h - top - margin - _CIRCLE_R) / rows if rows else (h - top)
        for i, c in enumerate(self._circles):
            col = i % cols
            row = i // cols
            cx = margin + cell_w * (col + 0.5)
            cy = top + cell_h * (row + 0.5)
            c.x = max(margin, min(w - margin, cx + cell_w * c.jx))
            c.y = max(top + _CIRCLE_R, min(h - margin, cy + cell_h * c.jy))

    def resizeEvent(self, event) -> None:
        self._layout_circles()
        super().resizeEvent(event)

    # ------------------------------------------------------------- input
    def _circle_at(self, x: float, y: float) -> _Circle | None:
        for c in reversed(self._circles):
            if c.matched or c.done:
                continue
            if (x - c.x) ** 2 + (y - c.y) ** 2 <= (c.r + 4) ** 2:
                return c
        return None

    def mousePressEvent(self, event) -> None:
        if not self._running:
            return
        pos = event.position()
        c = self._circle_at(pos.x(), pos.y())
        if c is not None:
            self._handle_click(c)

    def _handle_click(self, circle: _Circle) -> None:
        if circle.matched or circle.done:
            return
        if self._selected is None:
            self._selected = circle
            circle.selected = True
            self._selected_at = time.monotonic()
            return
        if circle is self._selected:
            circle.selected = False
            self._selected = None
            return

        first = self._selected
        first.selected = False
        self._selected = None

        if circle.pair_id == first.pair_id and circle.side != first.side:
            self._on_match(first, circle)
        else:
            self._on_mismatch(first, circle)

    # ------------------------------------------------------------- events
    def _on_match(self, a: _Circle, b: _Circle) -> None:
        elapsed_ms = (time.monotonic() - self._selected_at) * 1000.0
        points = self._score.register_hit(elapsed_ms)
        a.matched = b.matched = True
        a.pop = b.pop = 0.0001

        accent = QColor(_KIND_STYLE.get(a.kind, (_DEFAULT_ACCENT, ""))[0])
        for c in (a, b):
            self._spawn_particles(c.x, c.y, accent)
        mx, my = (a.x + b.x) / 2.0, (a.y + b.y) / 2.0
        self._floats.append(_Float(mx, my, f"+{points}", 0.0, 0.85, QColor("#FFFFFF")))

        self.scoreChanged.emit(self._score.score)
        self.comboChanged.emit(self._score.combo)
        self.hitMade.emit(a.word, points, self._score.combo)

        milestone = self._score.crosses_milestone()
        if milestone is not None:
            self._flash = _ComboFlash(f"{milestone} COMBO!")
            self.milestoneReached.emit(milestone)
        elif self._score.multiplier() > 1 and self._score.combo % 4 == 0:
            self._flash = _ComboFlash(f"x{self._score.multiplier()}")

        if all(c.matched for c in self._circles):
            self._pending_spawn = True
            self._spawn_gap_ms = 430.0

    def _on_mismatch(self, a: _Circle, b: _Circle) -> None:
        self._score.register_miss()
        a.shake = b.shake = 1.0
        self._floats.append(_Float(b.x, b.y - 8, "MISS", 0.0, 0.7, QColor("#FF6B6B")))
        self.scoreChanged.emit(self._score.score)
        self.comboChanged.emit(self._score.combo)
        self.missMade.emit()

    def _advance_wave(self) -> None:
        nxt = self._wave_idx + 1
        if nxt >= len(self._waves):
            self._finish()
        else:
            self._spawn_wave(nxt)

    def _finish(self) -> None:
        if not self._running:
            return
        self._running = False
        self._pending_spawn = False
        if self._timer.isActive():
            self._timer.stop()
        s = self._score
        self.roundFinished.emit(s.score, s.max_combo, s.hits, s.misses)
        self.update()

    # ------------------------------------------------------------- effects
    def _spawn_particles(self, x: float, y: float, color: QColor) -> None:
        for _ in range(14):
            ang = random.uniform(0, math.tau)
            spd = random.uniform(60, 240)
            self._particles.append(
                _Particle(
                    x, y,
                    math.cos(ang) * spd, math.sin(ang) * spd,
                    0.0, random.uniform(0.35, 0.6), QColor(color),
                )
            )

    # -------------------------------------------------------------- tick
    def _tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        dt_ms = dt * 1000.0

        if self._running:
            self._remaining_ms -= dt_ms
            secs = max(0, int(math.ceil(self._remaining_ms / 1000.0)))
            if secs != self._last_secs:
                self._last_secs = secs
                self.timeChanged.emit(secs)
            if self._remaining_ms <= 0:
                self._finish()

        # Animate circles.
        for c in self._circles:
            if c.appear < 1.0:
                c.appear = min(1.0, c.appear + dt * 4.0)
            if c.matched and not c.done:
                c.pop = min(1.0, c.pop + dt * 3.2)
                if c.pop >= 1.0:
                    c.done = True
            if c.shake > 0.0:
                c.shake = max(0.0, c.shake - dt * 3.2)

        # Particles + floats + flash.
        for p in self._particles:
            p.life += dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vy += 320.0 * dt
        self._particles = [p for p in self._particles if p.life < p.max_life]

        for f in self._floats:
            f.life += dt
            f.y -= 34.0 * dt
        self._floats = [f for f in self._floats if f.life < f.max_life]

        if self._flash is not None:
            self._flash.life += dt
            if self._flash.life >= self._flash.max_life:
                self._flash = None

        if self._pending_spawn:
            self._spawn_gap_ms -= dt_ms
            if self._spawn_gap_ms <= 0:
                self._pending_spawn = False
                self._advance_wave()

        self.update()

    # -------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w, h = self.width(), self.height()

        # Backdrop.
        p.fillRect(self.rect(), QColor("#0C0C0C"))

        self._paint_timer_bar(p, w)

        for f in self._particles:
            t = f.life / f.max_life
            col = QColor(f.color)
            col.setAlphaF(max(0.0, 1.0 - t))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            rad = 4.0 * (1.0 - t) + 1.0
            p.drawEllipse(QPointF(f.x, f.y), rad, rad)

        for c in self._circles:
            if c.done:
                continue
            self._paint_circle(p, c)

        for fl in self._floats:
            self._paint_float(p, fl)

        if self._flash is not None:
            self._paint_flash(p, w, h)

        p.end()

    def _paint_timer_bar(self, p: QPainter, w: int) -> None:
        if self._duration_ms <= 0:
            return
        frac = max(0.0, min(1.0, self._remaining_ms / self._duration_ms))
        track = QRectF(20, 22, w - 40, 10)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1A1A1A"))
        p.drawRoundedRect(track, 5, 5)
        if frac > 0:
            col = QColor("#66E39A") if frac > 0.35 else (QColor("#FFB020") if frac > 0.15 else QColor("#FF6B6B"))
            fill = QRectF(20, 22, (w - 40) * frac, 10)
            p.setBrush(col)
            p.drawRoundedRect(fill, 5, 5)

    def _paint_circle(self, p: QPainter, c: _Circle) -> None:
        accent = QColor(_KIND_STYLE.get(c.kind, (_DEFAULT_ACCENT, ""))[0])
        caption = _KIND_STYLE.get(c.kind, (_DEFAULT_ACCENT, ""))[1]

        appear = _ease_out(c.appear)
        scale = appear
        alpha = appear
        if c.matched:
            scale = 1.0 + 0.45 * c.pop
            alpha = max(0.0, 1.0 - c.pop)
        shake_dx = math.sin(c.shake * 38.0) * 9.0 * c.shake

        cx, cy, r = c.x + shake_dx, c.y, c.r * scale
        if r <= 1 or alpha <= 0.01:
            return

        # Selected pulse ring.
        if c.selected:
            pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 6.0)
            ring = QColor("#FFFFFF")
            ring.setAlphaF(0.35 + 0.4 * pulse)
            pen = QPen(ring, 3.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r + 7 + 3 * pulse, r + 7 + 3 * pulse)

        grad = QRadialGradient(cx, cy - r * 0.35, r * 1.6)
        body_top = QColor("#262626")
        body_bot = QColor("#141414")
        body_top.setAlphaF(alpha)
        body_bot.setAlphaF(alpha)
        grad.setColorAt(0.0, body_top)
        grad.setColorAt(1.0, body_bot)
        p.setBrush(grad)
        border = QColor("#FFFFFF") if c.selected else accent
        border.setAlphaF(alpha)
        p.setPen(QPen(border, 3.0 if c.selected else 2.0))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Word text.
        txt_col = QColor("#FFFFFF")
        txt_col.setAlphaF(alpha)
        p.setPen(txt_col)
        font = QFont("Segoe UI", self._fit_font_size(c.text), QFont.Weight.Black)
        p.setFont(font)
        text_rect = QRectF(cx - r, cy - r * 0.78, 2 * r, r * 1.25)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, c.text)

        # Kind caption.
        cap_col = QColor(accent)
        cap_col.setAlphaF(0.85 * alpha)
        p.setPen(cap_col)
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        cap_rect = QRectF(cx - r, cy + r * 0.42, 2 * r, r * 0.5)
        p.drawText(cap_rect, Qt.AlignmentFlag.AlignCenter, caption)

    @staticmethod
    def _fit_font_size(text: str) -> int:
        n = len(text or "")
        if n <= 5:
            return 18
        if n <= 9:
            return 15
        if n <= 14:
            return 12
        return 10

    def _paint_float(self, p: QPainter, fl: _Float) -> None:
        t = fl.life / fl.max_life
        col = QColor(fl.color)
        col.setAlphaF(max(0.0, 1.0 - t))
        p.setPen(col)
        p.setFont(QFont("Segoe UI", 16, QFont.Weight.Black))
        p.drawText(QRectF(fl.x - 60, fl.y - 20, 120, 40), Qt.AlignmentFlag.AlignCenter, fl.text)

    def _paint_flash(self, p: QPainter, w: int, h: int) -> None:
        fl = self._flash
        t = fl.life / fl.max_life
        scale = 1.0 + 0.4 * _ease_out(min(1.0, t * 2))
        col = QColor("#FFD700")
        col.setAlphaF(max(0.0, 1.0 - t))
        p.setPen(col)
        p.setFont(QFont("Segoe UI", int(34 * scale), QFont.Weight.Black))
        p.drawText(QRectF(0, h * 0.18, w, 80), Qt.AlignmentFlag.AlignCenter, fl.text)
