#!/bin/sh
set -eu
LZO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
LZO_PY="$LZO_ROOT/.venv-local-server/bin/python"
if [ ! -x "$LZO_PY" ]; then
  echo 'Run: sh infra/local-server/setup.sh' >&2
  exit 1
fi
LZO_CONFIG=${LZO_LOCAL_CONFIG:-"$LZO_ROOT/.runtime/local-server/config.json"}
if [ "$#" -eq 0 ]; then set -- status; fi
exec "$LZO_PY" "$LZO_ROOT/scripts/run_local_server.py" --config "$LZO_CONFIG" "$@"
