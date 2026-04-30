#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_EXE="$REPO_ROOT/.venv/Scripts/python.exe"

if [[ ! -x "$PYTHON_EXE" ]]; then
  echo "Python virtualenv not found: $PYTHON_EXE" >&2
  exit 1
fi

"$PYTHON_EXE" -m app.cli.tracking_add "$@"
