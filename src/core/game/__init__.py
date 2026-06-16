"""Blitz — a fast click-to-connect word game built on the existing vocab decks.

The package is split so the rules are testable without Qt:

- `pairs`   : turn a Lektion's vocab rows into connectable circle-pairs and
              shuffle them into ambiguity-free waves.
- `scoring` : the combo / multiplier / accuracy bookkeeping for a round.

The Qt board (`ui/widgets/game_board.py`) and page (`ui/pages/game_page.py`)
consume these; the SFX live in `core/audio/sfx.py`.
"""

from core.game.pairs import ARTICLE, MEANING, PLURAL, Pair, build_pairs, make_waves
from core.game.scoring import ScoreState

__all__ = [
    "ARTICLE",
    "PLURAL",
    "MEANING",
    "Pair",
    "build_pairs",
    "make_waves",
    "ScoreState",
]
