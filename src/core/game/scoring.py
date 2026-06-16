"""osu-style scoring for one Blitz round.

Each connect is judged PERFECT / GOOD / OK by how much approach time was left
(connect fast = PERFECT), worth 300 / 100 / 50 before the combo multiplier. A
miss (wrong connect or an expired pair) breaks the combo and scores zero.
Accuracy is the osu weighted ratio. Pure and Qt-free so it's unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Hit value per judgment before the combo multiplier.
JUDGMENT_VALUE = {"perfect": 300, "good": 100, "ok": 50}
#: Combo counts that earn a celebratory flourish (sound + on-screen burst).
MILESTONES = (10, 25, 50, 100, 200)


@dataclass
class ScoreState:
    score: int = 0
    combo: int = 0
    max_combo: int = 0
    perfect: int = 0
    good: int = 0
    ok: int = 0
    misses: int = 0

    def multiplier(self) -> int:
        """Escalating multiplier driven by the current combo."""
        c = self.combo
        if c >= 32:
            return 8
        if c >= 16:
            return 4
        if c >= 8:
            return 2
        return 1

    @property
    def hits(self) -> int:
        return self.perfect + self.good + self.ok

    def register_hit(self, judgment: str) -> int:
        """Record a correct connect with its timing judgment; returns the points
        gained (for the floating '+N')."""
        base = JUDGMENT_VALUE.get(judgment, 50)
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        if judgment == "perfect":
            self.perfect += 1
        elif judgment == "good":
            self.good += 1
        else:
            self.ok += 1
        gained = base * self.multiplier()
        self.score += gained
        return gained

    def register_miss(self) -> None:
        self.misses += 1
        self.combo = 0

    def crosses_milestone(self) -> int | None:
        return self.combo if self.combo in MILESTONES else None

    def accuracy(self) -> float:
        """osu weighted accuracy: earned value / max possible value."""
        total = self.hits + self.misses
        if not total:
            return 0.0
        got = 300 * self.perfect + 100 * self.good + 50 * self.ok
        return got / (300 * total)
