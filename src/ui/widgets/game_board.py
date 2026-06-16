"""The Blitz play field — an osu-style connect game.

Pairs stream onto the field over time, each wearing a shrinking **approach ring**
that collapses onto the circle. Connect a pair before its ring closes or the pair
**expires** and drains your **HP**; let HP hit zero and you fail. Connect fast for
a **PERFECT**, build combo and the multiplier, and survive as the spawn rate and
approach time **accelerate**.

Colour never reveals a pair: the only coloured circles are der/die/das (blue /
pink / green — the German gender convention), purely as a learning aid; their
partner noun and every other circle are neutral, so the player must *read* to
decide which two connect. Two identical captions never coexist on the field.

Three difficulty presets scale the tempo and HP pressure; "Insane" is the fast
end (and brutal by design).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from core.game.scoring import ScoreState

# der/die/das gender colours (the only colour on the board). Everything else is
# neutral so colour can't betray which circles pair up.
_GENDER_COLOR = {"der": "#4DA6FF", "die": "#FF6FB5", "das": "#66E39A"}
_NEUTRAL = "#D2D2D2"

_APPROACH_GAP = 52.0
_FRAME_MS = 16
_HP_TOP = 0.66

# Difficulty presets: approach (start,end) ms, spawn (start,end) ms, HP drain/s,
# miss & expire HP cost, and the live-pair cap. "insane" matches the old (fast)
# tempo and is deliberately near-unwinnable.
DIFFICULTIES = {
    "relaxed": dict(approach=(2600.0, 2050.0), spawn=(1700.0, 1300.0),
                    drain=0.026, miss=0.10, expire=0.08, max_live=3, label="Relaxed"),
    "normal": dict(approach=(2050.0, 1300.0), spawn=(1350.0, 920.0),
                   drain=0.044, miss=0.13, expire=0.11, max_live=3, label="Normal"),
    "insane": dict(approach=(1700.0, 820.0), spawn=(1150.0, 520.0),
                   drain=0.085, miss=0.17, expire=0.15, max_live=4, label="Insane"),
}
_HP_HEAL = {"perfect": 0.090, "good": 0.060, "ok": 0.035}

# A share of pairs are osu-style sliders: press the gold-marked start, hold, drag
# to the partner you identify, and release on it. Sliders get a little extra
# approach time to allow for the drag.
_SLIDER_FRACTION = 0.42
_SLIDER_MARK = "#FFC857"   # gold — distinct from the der/die/das gender colours
_SLIDER_TIME_BONUS = 1.35


def _ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1.0 - (1.0 - x) ** 3


def _lerp(a: float, b: float, t: float) -> float:
    t = max(0.0, min(1.0, t))
    return a + (b - a) * t


def _circle_color(text: str) -> str:
    return _GENDER_COLOR.get((text or "").strip().lower(), _NEUTRAL)


def _radius_for(text: str) -> float:
    # Bigger circles for longer words so the text stays readable.
    n = len(text or "")
    return max(40.0, min(80.0, 34.0 + n * 3.4))


def _font_for(text: str) -> int:
    n = len(text or "")
    if n <= 6:
        return 17
    if n <= 10:
        return 15
    return 13


@dataclass
class _Circle:
    text: str
    x: float = 0.0
    y: float = 0.0
    r: float = 46.0
    pop: float = 0.0
    shake: float = 0.0


@dataclass
class _LivePair:
    uid: int
    vocab_id: int
    word: str
    kind: str
    a: _Circle
    b: _Circle
    spawn_t: float
    approach_ms: float
    matched: bool = False
    slider: bool = False

    def circles(self):
        return (self.a, self.b)


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
    size: int = 16


@dataclass
class _ComboFlash:
    text: str
    life: float = 0.0
    max_life: float = 0.9


@dataclass
class _Trail:
    x: float
    y: float
    life: float = 0.0


class GameBoard(QWidget):
    started = Signal()
    scoreChanged = Signal(int)
    comboChanged = Signal(int)
    accuracyChanged = Signal(float)
    hpChanged = Signal(float)
    hitMade = Signal(str, str, int, int)            # word, judgment, points, combo
    missMade = Signal()
    milestoneReached = Signal(int)
    roundFinished = Signal(bool, int, int, int, int, int, int)
    # cleared, score, max_combo, perfect, good, ok, misses

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("GameBoard")
        self.setMinimumHeight(520)
        self.setMouseTracking(True)
        self.setStyleSheet("GameBoard { background: transparent; }")

        self._queue: list = []
        self._live: list[_LivePair] = []
        self._sel: tuple[_LivePair, _Circle] | None = None
        self._drag: tuple[_LivePair, _Circle] | None = None   # slider in progress
        self._drag_pos: QPointF | None = None
        self._uid = 0
        self._total = 0
        self._done = 0

        self._diff = DIFFICULTIES["normal"]
        self._score = ScoreState()
        self._hp = _HP_TOP
        self._running = False

        self._next_spawn_t = 0.0
        self._particles: list[_Particle] = []
        self._floats: list[_Float] = []
        self._flash: _ComboFlash | None = None
        self._trail: list[_Trail] = []
        self._shake = 0.0

        self._last_tick = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._tick)

    # ----------------------------------------------------------------- API
    @property
    def is_running(self) -> bool:
        return self._running

    def start_game(self, pairs: list, max_pairs: int = 48, difficulty: str = "normal") -> None:
        self._diff = DIFFICULTIES.get(difficulty, DIFFICULTIES["normal"])
        pool = [p for p in pairs if p]
        random.shuffle(pool)
        if max_pairs and len(pool) > max_pairs:
            pool = pool[:max_pairs]
        self._queue = pool
        self._total = len(pool)
        self._done = 0
        self._uid = 0
        self._live = []
        self._sel = None
        self._drag = None
        self._drag_pos = None
        self._score = ScoreState()
        self._hp = _HP_TOP
        self._particles.clear()
        self._floats.clear()
        self._trail.clear()
        self._flash = None
        self._shake = 0.0
        self._running = bool(self._queue)

        self.scoreChanged.emit(0)
        self.comboChanged.emit(0)
        self.accuracyChanged.emit(0.0)
        self.hpChanged.emit(self._hp)

        if not self._running:
            self.roundFinished.emit(False, 0, 0, 0, 0, 0, 0)
            return

        now = time.monotonic()
        self._last_tick = now
        self._next_spawn_t = now
        self.started.emit()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._running = False
        self._drag = None
        self._drag_pos = None
        if self._timer.isActive():
            self._timer.stop()

    # ----------------------------------------------------------- difficulty
    def _progress(self) -> float:
        return (self._done / self._total) if self._total else 1.0

    def _approach_ms(self) -> float:
        lo, hi = self._diff["approach"]
        return _lerp(lo, hi, self._progress())

    def _spawn_interval_ms(self) -> float:
        lo, hi = self._diff["spawn"]
        return _lerp(lo, hi, self._progress())

    # --------------------------------------------------------------- spawn
    def _next_spawnable(self):
        """Pop the next queued pair whose captions don't already sit on the
        field, so two identical circles never coexist (no ambiguous connect)."""
        live_texts = {c.text for lp in self._live for c in lp.circles()}
        for i, pair in enumerate(self._queue):
            if pair.a not in live_texts and pair.b not in live_texts:
                return self._queue.pop(i)
        return None

    def _spawn_one(self, now: float) -> bool:
        pair = self._next_spawnable()
        if pair is None:
            return False
        a = _Circle(pair.a, r=_radius_for(pair.a))
        b = _Circle(pair.b, r=_radius_for(pair.b))
        self._place(a)
        self._place(b, avoid=a)
        self._uid += 1
        slider = random.random() < _SLIDER_FRACTION
        approach = self._approach_ms() * (_SLIDER_TIME_BONUS if slider else 1.0)
        self._live.append(
            _LivePair(self._uid, pair.vocab_id, pair.word, pair.kind, a, b, now, approach, slider=slider)
        )
        return True

    def _place(self, c: _Circle, avoid: _Circle | None = None) -> None:
        w = max(self.width(), 640)
        h = max(self.height(), 480)
        top = 72.0
        mx = c.r + 22
        best = None
        for _ in range(80):
            x = random.uniform(mx, w - mx)
            y = random.uniform(top + c.r + 6, h - c.r - 16)
            ok = True
            for lp in self._live:
                for o in lp.circles():
                    if (x - o.x) ** 2 + (y - o.y) ** 2 < (c.r + o.r + 22) ** 2:
                        ok = False
                        break
                if not ok:
                    break
            if ok and avoid is not None:
                if (x - avoid.x) ** 2 + (y - avoid.y) ** 2 < (c.r + avoid.r + 30) ** 2:
                    ok = False
            if ok:
                c.x, c.y = x, y
                return
            if best is None:
                best = (x, y)
        c.x, c.y = best if best else (w / 2, h / 2)

    # ---------------------------------------------------------------- input
    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        self._trail.append(_Trail(pos.x(), pos.y()))
        if len(self._trail) > 18:
            self._trail = self._trail[-18:]
        if self._drag is not None:
            self._drag_pos = QPointF(pos.x(), pos.y())

    def _circle_at(self, x: float, y: float):
        for lp in reversed(self._live):
            if lp.matched:
                continue
            for c in lp.circles():
                if (x - c.x) ** 2 + (y - c.y) ** 2 <= (c.r + 5) ** 2:
                    return lp, c
        return None

    def mousePressEvent(self, event) -> None:
        if not self._running:
            return
        pos = event.position()
        hit = self._circle_at(pos.x(), pos.y())
        if hit is None:
            self._sel = None  # clicking empty cancels a pending tap selection
            return
        lp, c = hit
        if lp.slider:
            # A slider is completed by dragging FROM its gold start TO the partner.
            if c is lp.a:
                self._drag = (lp, c)
                self._drag_pos = QPointF(pos.x(), pos.y())
                self._sel = None
            return
        self._handle_click(lp, c)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is None:
            return
        lp, start = self._drag
        self._drag = None
        self._drag_pos = None
        if not self._running or lp.matched:
            return
        pos = event.position()
        hit = self._circle_at(pos.x(), pos.y())
        if hit is None:
            return  # released on empty space -> cancel, no penalty
        tlp, tc = hit
        if tlp.uid == lp.uid:
            if tc is lp.b:
                self._on_match(lp)        # dragged to the correct partner
            # released back on the start -> cancel (no penalty)
        else:
            self._on_mismatch(start, tc)  # dragged onto a wrong circle

    def _handle_click(self, lp: _LivePair, c: _Circle) -> None:
        if lp.matched:
            return
        if self._sel is None:
            self._sel = (lp, c)
            return
        sel_lp, sel_c = self._sel
        if sel_c is c:
            self._sel = None
            return
        self._sel = None
        if lp.uid == sel_lp.uid:
            self._on_match(lp)
        else:
            self._on_mismatch(sel_c, c)

    # ------------------------------------------------------------- events
    def _judge(self, lp: _LivePair, now: float) -> str:
        remaining = 1.0 - min(1.0, (now - lp.spawn_t) * 1000.0 / lp.approach_ms)
        if remaining > 0.5:
            return "perfect"
        if remaining > 0.2:
            return "good"
        return "ok"

    def _on_match(self, lp: _LivePair) -> None:
        now = time.monotonic()
        judgment = self._judge(lp, now)
        points = self._score.register_hit(judgment)
        lp.matched = True
        lp.a.pop = lp.b.pop = 0.0001

        self._hp = min(1.0, self._hp + _HP_HEAL.get(judgment, 0.035))
        for c in lp.circles():
            self._spawn_particles(c.x, c.y, QColor(_circle_color(c.text)))
        mx, my = (lp.a.x + lp.b.x) / 2.0, (lp.a.y + lp.b.y) / 2.0
        jcol = {"perfect": "#66E3FF", "good": "#7AE582", "ok": "#FFD700"}.get(judgment, "#FFFFFF")
        label = {"perfect": "PERFECT", "good": "GOOD", "ok": "OK"}.get(judgment, "")
        self._floats.append(_Float(mx, my - 14, label, 0.0, 0.7, QColor(jcol), 13))
        self._floats.append(_Float(mx, my + 10, f"+{points}", 0.0, 0.8, QColor("#FFFFFF"), 16))

        self._emit_hud()
        self.hitMade.emit(lp.word, judgment, points, self._score.combo)

        milestone = self._score.crosses_milestone()
        if milestone is not None:
            self._flash = _ComboFlash(f"{milestone} COMBO!")
            self._shake = min(1.0, self._shake + 0.35)
            self.milestoneReached.emit(milestone)
        elif self._score.multiplier() > 1 and self._score.combo % 5 == 0:
            self._flash = _ComboFlash(f"x{self._score.multiplier()}")

    def _on_mismatch(self, c1: _Circle, c2: _Circle) -> None:
        self._score.register_miss()
        self._hp -= self._diff["miss"]
        c1.shake = c2.shake = 1.0
        self._shake = min(1.0, self._shake + 0.5)
        self._floats.append(_Float(c2.x, c2.y - 10, "MISS", 0.0, 0.6, QColor("#FF6B6B"), 16))
        self._emit_hud()
        self.missMade.emit()
        if self._hp <= 0:
            self._finish(cleared=False)

    def _expire(self, lp: _LivePair) -> None:
        self._score.register_miss()
        self._hp -= self._diff["expire"]
        self._shake = min(1.0, self._shake + 0.35)
        mx, my = (lp.a.x + lp.b.x) / 2.0, (lp.a.y + lp.b.y) / 2.0
        self._floats.append(_Float(mx, my, "MISS", 0.0, 0.6, QColor("#FF6B6B"), 16))
        self._emit_hud()
        self.missMade.emit()
        if self._sel is not None and self._sel[0].uid == lp.uid:
            self._sel = None
        if self._drag is not None and self._drag[0].uid == lp.uid:
            self._drag = None
            self._drag_pos = None

    def _emit_hud(self) -> None:
        self.scoreChanged.emit(self._score.score)
        self.comboChanged.emit(self._score.combo)
        self.accuracyChanged.emit(self._score.accuracy())
        self.hpChanged.emit(max(0.0, self._hp))

    def _finish(self, cleared: bool) -> None:
        if not self._running:
            return
        self._running = False
        if self._timer.isActive():
            self._timer.stop()
        s = self._score
        self.roundFinished.emit(cleared, s.score, s.max_combo, s.perfect, s.good, s.ok, s.misses)
        self.update()

    # ------------------------------------------------------------- effects
    def _spawn_particles(self, x: float, y: float, color: QColor) -> None:
        for _ in range(16):
            ang = random.uniform(0, math.tau)
            spd = random.uniform(80, 280)
            self._particles.append(
                _Particle(x, y, math.cos(ang) * spd, math.sin(ang) * spd,
                          0.0, random.uniform(0.35, 0.6), QColor(color))
            )

    # -------------------------------------------------------------- tick
    def _tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now

        if self._running:
            self._hp -= self._diff["drain"] * dt
            if self._hp <= 0:
                self._hp = 0.0
                self._emit_hud()
                self._finish(cleared=False)
            else:
                self.hpChanged.emit(self._hp)

        if self._running:
            live_unmatched = sum(1 for lp in self._live if not lp.matched)
            if now >= self._next_spawn_t and self._queue and live_unmatched < self._diff["max_live"]:
                if self._spawn_one(now):
                    self._next_spawn_t = now + self._spawn_interval_ms() / 1000.0
                else:
                    self._next_spawn_t = now + 0.2  # all candidates blocked; retry soon

            for lp in list(self._live):
                if lp.matched:
                    continue
                if (now - lp.spawn_t) * 1000.0 >= lp.approach_ms:
                    self._expire(lp)
                    self._live.remove(lp)
                    self._done += 1
                    if not self._running:
                        break

        for lp in list(self._live):
            if lp.matched:
                lp.a.pop = min(1.0, lp.a.pop + dt * 3.4)
                lp.b.pop = lp.a.pop
                if lp.a.pop >= 1.0:
                    self._live.remove(lp)
                    self._done += 1
            for c in lp.circles():
                if c.shake > 0.0:
                    c.shake = max(0.0, c.shake - dt * 3.4)

        for p in self._particles:
            p.life += dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vy += 340.0 * dt
        self._particles = [p for p in self._particles if p.life < p.max_life]

        for f in self._floats:
            f.life += dt
            f.y -= 30.0 * dt
        self._floats = [f for f in self._floats if f.life < f.max_life]

        if self._flash is not None:
            self._flash.life += dt
            if self._flash.life >= self._flash.max_life:
                self._flash = None

        for tr in self._trail:
            tr.life += dt
        self._trail = [tr for tr in self._trail if tr.life < 0.4]

        self._shake = max(0.0, self._shake - dt * 3.0)

        if self._running and not self._queue and not self._live:
            self._finish(cleared=True)

        self.update()

    # -------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#0A0A0A"))

        if self._shake > 0.001:
            amp = 8.0 * self._shake
            p.translate(random.uniform(-amp, amp), random.uniform(-amp, amp))

        self._paint_hp_bar(p, w)

        for tr in self._trail:
            t = tr.life / 0.4
            col = QColor("#FF4D6D")
            col.setAlphaF(max(0.0, 0.5 * (1.0 - t)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(tr.x, tr.y), 5 * (1 - t) + 1, 5 * (1 - t) + 1)

        for f in self._particles:
            t = f.life / f.max_life
            col = QColor(f.color)
            col.setAlphaF(max(0.0, 1.0 - t))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            rad = 4.5 * (1.0 - t) + 1.0
            p.drawEllipse(QPointF(f.x, f.y), rad, rad)

        now = time.monotonic()
        for lp in self._live:
            self._paint_pair(p, lp, now)

        self._paint_drag(p)

        for fl in self._floats:
            self._paint_float(p, fl)

        if self._flash is not None:
            self._paint_flash(p, w, h)

        p.end()

    def _paint_drag(self, p: QPainter) -> None:
        if self._drag is None or self._drag_pos is None:
            return
        _lp, start = self._drag
        sx, sy = start.x, start.y
        ex, ey = self._drag_pos.x(), self._drag_pos.y()
        gold = QColor(_SLIDER_MARK)
        # osu slider body: a fat translucent tube, a bright core, and a follow ball.
        tube = QColor(gold)
        tube.setAlphaF(0.22)
        p.setPen(QPen(tube, 30.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(sx, sy), QPointF(ex, ey))
        core = QColor(gold)
        core.setAlphaF(0.9)
        p.setPen(QPen(core, 4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(sx, sy), QPointF(ex, ey))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gold)
        p.drawEllipse(QPointF(ex, ey), 13, 13)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(ex, ey), 5, 5)

    def _paint_hp_bar(self, p: QPainter, w: int) -> None:
        track = QRectF(20, 16, w - 40, 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1A1A1A"))
        p.drawRoundedRect(track, 6, 6)
        hp = max(0.0, min(1.0, self._hp))
        if hp > 0:
            col = QColor("#66E39A") if hp > 0.4 else (QColor("#FFB020") if hp > 0.2 else QColor("#FF4D4D"))
            p.setBrush(col)
            p.drawRoundedRect(QRectF(20, 16, (w - 40) * hp, 12), 6, 6)

    def _paint_pair(self, p: QPainter, lp: _LivePair, now: float) -> None:
        # No connector between partners — the player must read to find them.
        elapsed = (now - lp.spawn_t) * 1000.0
        remaining = max(0.0, 1.0 - elapsed / lp.approach_ms)
        for c in lp.circles():
            self._paint_circle(p, c, lp, remaining)

    def _paint_circle(self, p, c, lp, remaining) -> None:
        accent = QColor(_circle_color(c.text))
        scale = 1.0
        alpha = 1.0
        if lp.matched:
            scale = 1.0 + 0.5 * c.pop
            alpha = max(0.0, 1.0 - c.pop)
        shake_dx = math.sin(c.shake * 40.0) * 9.0 * c.shake
        cx, cy, r = c.x + shake_dx, c.y, c.r * scale
        if r <= 1 or alpha <= 0.01:
            return

        selected = (self._sel is not None and self._sel[1] is c) or (
            self._drag is not None and self._drag[1] is c)

        if not lp.matched and remaining > 0:
            ring_r = r + _APPROACH_GAP * remaining
            ring = QColor("#FFFFFF") if remaining > 0.35 else (
                QColor("#FFB020") if remaining > 0.18 else QColor("#FF4D4D"))
            ring.setAlphaF(0.85)
            p.setPen(QPen(ring, 3.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), ring_r, ring_r)

        if selected:
            pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 8.0)
            sring = QColor("#FFFFFF")
            sring.setAlphaF(0.4 + 0.4 * pulse)
            p.setPen(QPen(sring, 3.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r + 6 + 3 * pulse, r + 6 + 3 * pulse)

        grad = QRadialGradient(cx, cy - r * 0.35, r * 1.6)
        top = QColor("#2A2A2A")
        bot = QColor("#121212")
        top.setAlphaF(alpha)
        bot.setAlphaF(alpha)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.setBrush(grad)
        border = QColor("#FFFFFF") if selected else accent
        border.setAlphaF(alpha)
        p.setPen(QPen(border, 3.0 if selected else 2.5))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Slider start gets a pulsing gold ring — "hold & drag me to your match".
        if lp.slider and c is lp.a and not lp.matched:
            mark = QColor(_SLIDER_MARK)
            pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 5.0)
            mark.setAlphaF((0.55 + 0.4 * pulse) * alpha)
            p.setPen(QPen(mark, 3.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r + 5, r + 5)

        txt = QColor("#FFFFFF")
        txt.setAlphaF(alpha)
        p.setPen(txt)
        p.setFont(QFont("Segoe UI", _font_for(c.text), QFont.Weight.Black))
        p.drawText(QRectF(cx - r, cy - r * 0.7, 2 * r, r * 1.4),
                   Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, c.text)

    def _paint_float(self, p: QPainter, fl: _Float) -> None:
        t = fl.life / fl.max_life
        col = QColor(fl.color)
        col.setAlphaF(max(0.0, 1.0 - t))
        p.setPen(col)
        p.setFont(QFont("Segoe UI", fl.size, QFont.Weight.Black))
        p.drawText(QRectF(fl.x - 70, fl.y - 20, 140, 40), Qt.AlignmentFlag.AlignCenter, fl.text)

    def _paint_flash(self, p: QPainter, w: int, h: int) -> None:
        fl = self._flash
        t = fl.life / fl.max_life
        scale = 1.0 + 0.4 * _ease_out(min(1.0, t * 2))
        col = QColor("#FFD700")
        col.setAlphaF(max(0.0, 1.0 - t))
        p.setPen(col)
        p.setFont(QFont("Segoe UI", int(34 * scale), QFont.Weight.Black))
        p.drawText(QRectF(0, h * 0.16, w, 80), Qt.AlignmentFlag.AlignCenter, fl.text)
