"""Combo / multiplier / accuracy bookkeeping for one Blitz round.

Pure and Qt-free so the rules are unit-testable. The board calls `register_hit`
on a correct connect and `register_miss` on a wrong one; the page reads the
fields for the HUD and the end screen.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Points for a connect before multipliers/bonuses.
BASE_POINTS = 100
#: Fastest connect that still earns the full speed bonus, and the slowest that
#: earns any. Faster than FAST_MS -> full bonus; slower than SLOW_MS -> none.
FAST_MS = 600
SLOW_MS = 3000
MAX_SPEED_BONUS = 60
#: Combo counts that earn a celebratory flourish (sound + on-screen burst).
MILESTONES = (10, 25, 50, 100)


@dataclass
class ScoreState:
    score: int = 0
    combo: int = 0
    max_combo: int = 0
    hits: int = 0
    misses: int = 0

    def multiplier(self) -> int:
        """osu-style escalating multiplier driven by the current combo."""
        c = self.combo
        if c >= 16:
            return 8
        if c >= 8:
            return 4
        if c >= 4:
            return 2
        return 1

    @staticmethod
    def _speed_bonus(elapsed_ms: float | None) -> int:
        if elapsed_ms is None:
            return 0
        if elapsed_ms <= FAST_MS:
            return MAX_SPEED_BONUS
        if elapsed_ms >= SLOW_MS:
            return 0
        frac = (SLOW_MS - elapsed_ms) / (SLOW_MS - FAST_MS)
        return int(round(MAX_SPEED_BONUS * frac))

    def register_hit(self, elapsed_ms: float | None = None) -> int:
        """Record a correct connect; returns the points gained for that connect
        (so the board can float a '+N' over the popped circle)."""
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self.hits += 1
        gained = BASE_POINTS * self.multiplier() + self._speed_bonus(elapsed_ms)
        self.score += gained
        return gained

    def register_miss(self) -> None:
        self.misses += 1
        self.combo = 0

    def crosses_milestone(self) -> int | None:
        """If the current combo exactly hit a milestone, return it (for a
        flourish), else None. Call right after `register_hit`."""
        return self.combo if self.combo in MILESTONES else None

    def accuracy(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0
