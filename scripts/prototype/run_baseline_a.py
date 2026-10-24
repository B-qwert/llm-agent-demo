"""Run from any directory; default is a no-network request preview."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bizcodeqa.baseline import main

if __name__ == '__main__':
    raise SystemExit(main())
