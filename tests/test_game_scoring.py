"""Blitz osu-style scoring: judged hits, combo multiplier, accuracy, milestones."""

from core.game.scoring import ScoreState


def test_combo_raises_multiplier_in_tiers():
    s = ScoreState()
    for _ in range(7):
        s.register_hit("perfect")
    assert s.multiplier() == 1
    s.register_hit("perfect")  # combo 8
    assert s.multiplier() == 2
    for _ in range(8):
        s.register_hit("perfect")  # combo 16
    assert s.multiplier() == 4
    for _ in range(16):
        s.register_hit("perfect")  # combo 32
    assert s.multiplier() == 8


def test_judgments_score_and_count():
    s = ScoreState()
    assert s.register_hit("perfect") == 300  # x1
    assert s.register_hit("good") == 100
    assert s.register_hit("ok") == 50
    assert (s.perfect, s.good, s.ok) == (1, 1, 1)
    assert s.hits == 3 and s.score == 450


def test_multiplier_scales_points():
    s = ScoreState()
    s.combo = 8  # next hit -> combo 9 -> still x2 (>=8)
    assert s.register_hit("perfect") == 600


def test_miss_resets_combo_and_weighted_accuracy():
    s = ScoreState()
    s.register_hit("perfect")
    s.register_hit("perfect")
    assert s.combo == 2 and s.max_combo == 2
    s.register_miss()
    assert s.combo == 0 and s.misses == 1
    assert s.max_combo == 2  # sticky
    # 2 perfects + 1 miss -> 600 / 900.
    assert abs(s.accuracy() - (600 / 900)) < 1e-9


def test_accuracy_all_perfect_is_one():
    s = ScoreState()
    for _ in range(5):
        s.register_hit("perfect")
    assert s.accuracy() == 1.0


def test_milestone_detection_is_exact():
    s = ScoreState()
    for _ in range(9):
        s.register_hit("good")
    assert s.crosses_milestone() is None
    s.register_hit("good")  # combo 10
    assert s.crosses_milestone() == 10
