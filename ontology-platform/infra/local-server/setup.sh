#!/bin/sh
set -eu
LZO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
LZO_PYTHON=${LZO_PYTHON:-python3.12}
"$LZO_PYTHON" -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 is required"'
if [ ! -x "$LZO_ROOT/.venv-local-server/bin/python" ]; then
  "$LZO_PYTHON" -m venv "$LZO_ROOT/.venv-local-server"
fi
"$LZO_ROOT/.venv-local-server/bin/python" -m pip install --disable-pip-version-check -r "$LZO_ROOT/infra/local-server/requirements.lock"
echo 'Python runtime ready. Configure independent native databases, private.env and config.json before init.'
