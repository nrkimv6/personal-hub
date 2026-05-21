#!/usr/bin/env sh
# Non-blocking wrapper for the PowerShell plan-write postcommit hook.

surface="codex"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --surface)
      shift
      [ "$#" -gt 0 ] || exit 0
      surface="$1"
      ;;
    --surface=*)
      surface="${1#--surface=}"
      ;;
  esac
  shift
done

case "$surface" in
  claude|codex|gemini) ;;
  *) surface="codex" ;;
esac

case "$(uname -s 2>/dev/null || echo "$OS")" in
  *MINGW*|*MSYS*|*CYGWIN*|*Windows*|*windows*|Windows_NT)
    script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)
    script_path="$script_dir/plan-write-postcommit.ps1"
    if command -v powershell.exe >/dev/null 2>&1; then
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$script_path" -Surface "$surface" || true
    elif command -v pwsh >/dev/null 2>&1; then
      pwsh -NoProfile -ExecutionPolicy Bypass -File "$script_path" -Surface "$surface" || true
    fi
    ;;
esac

exit 0
