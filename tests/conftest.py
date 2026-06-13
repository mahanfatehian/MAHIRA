import sys
from pathlib import Path

# Make the app's `src` importable (mirrors `python -m mahira` run from src/).
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
