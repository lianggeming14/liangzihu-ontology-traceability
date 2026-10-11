"""Install the PostgreSQL driver into this workspace only."""
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
target = root / ".deps"
target.mkdir(exist_ok=True)
subprocess.run([
    sys.executable, "-m", "pip", "install", "--no-user", "--no-cache-dir",
    "--disable-pip-version-check", "--index-url", "https://pypi.org/simple",
    "--target", str(target), "psycopg[binary]==3.3.6",
], cwd=root, check=True)
