"""Portable entry point; distinct name avoids shadowing local_server package."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_server.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
