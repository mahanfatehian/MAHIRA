"""Blitz scoring: combos raise the multiplier, misses break it, accuracy tracks."""

from core.game.scoring import BASE_POINTS, MAX_SPEED_BONUS, ScoreState


def test_combo_raises_multiplier_in_tiers():
    s = ScoreState()
    # Combos 1..3 -> x1, 4..7 -> x2, 8..15 -> x4, 16+ -> x8.
    for _ in range(3):
        s.register_hit()
    assert s.multiplier() == 1
    s.register_hit()  # combo 4
    assert s.multiplier() == 2
    for _ in range(4):
        s.register_hit()  # combo 8
    assert s.multiplier() == 4
    for _ in range(8):
        s.register_hit()  # combo 16
    assert s.multiplier() == 8


def test_miss_resets_combo_and_counts_accuracy():
    s = ScoreState()
    s.register_hit()
    s.register_hit()
    assert s.combo == 2 and s.max_combo == 2
    s.register_miss()
    assert s.combo == 0
    assert s.misses == 1
    # max_combo is sticky.
    assert s.max_combo == 2
    # 2 hits / 3 attempts.
    assert abs(s.accuracy() - (2 / 3)) < 1e-9


def test_points_scale_with_multiplier_and_speed_bonus():
    s = ScoreState()
    # First hit (combo 1, x1) with a slow connect -> just base.
    gained = s.register_hit(elapsed_ms=5000)
    assert gained == BASE_POINTS
    # Fast connects earn the full speed bonus on top of the multiplier.
    s2 = ScoreState()
    s2.combo = 7  # next hit -> combo 8 -> x4
    gained2 = s2.register_hit(elapsed_ms=100)
    assert gained2 == BASE_POINTS * 4 + MAX_SPEED_BONUS


def test_milestone_detection_is_exact():
    s = ScoreState()
    for _ in range(9):
        s.register_hit()
    assert s.crosses_milestone() is None
    s.register_hit()  # combo 10
    assert s.crosses_milestone() == 10
