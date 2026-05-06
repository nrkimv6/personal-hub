#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_EXE="$REPO_ROOT/.venv/Scripts/python.exe"

if [[ ! -x "$PYTHON_EXE" && "$REPO_ROOT" == *"/.worktrees/"* ]]; then
  MAIN_ROOT="${REPO_ROOT%%/.worktrees/*}"
  FALLBACK_PYTHON="$MAIN_ROOT/.venv/Scripts/python.exe"
  if [[ -x "$FALLBACK_PYTHON" ]]; then
    PYTHON_EXE="$FALLBACK_PYTHON"
  fi
fi

if [[ ! -x "$PYTHON_EXE" ]]; then
  echo "Python virtualenv not found: $PYTHON_EXE" >&2
  exit 1
fi

"$PYTHON_EXE" -m app.cli.tracking_update "$@"
