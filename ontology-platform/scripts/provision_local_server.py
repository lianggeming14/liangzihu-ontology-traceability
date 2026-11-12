"""Portable fresh-deployment entry, using the local server's own interpreter."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_server.provision import main

if __name__ == "__main__":
    raise SystemExit(main())
