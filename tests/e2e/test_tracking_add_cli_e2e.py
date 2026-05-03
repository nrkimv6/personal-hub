import shutil
import subprocess
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


def _utf8_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def test_powershell_wrapper_forwards_dry_run_args():
    script = REPO_ROOT / "scripts" / "tracking" / "add-tracking-item.ps1"
    result = subprocess.run(
        [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "--dry-run",
            "--title",
            "T",
            "--wait-until",
            "2w",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=_utf8_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "DRY-RUN: tracking item payload" in result.stdout
    assert '"title": "T"' in result.stdout
    assert '"start_at"' in result.stdout
    assert "마감기한(due_at) = <없음>" in result.stdout


def test_powershell_wrapper_has_worktree_venv_fallback_contract():
    script = REPO_ROOT / "scripts" / "tracking" / "add-tracking-item.ps1"
    source = script.read_text(encoding="utf-8")
    assert ".worktrees" in source
    assert ".venv\\Scripts\\python.exe" in source
    assert "$fallbackPython" in source


def test_bash_wrapper_forwards_dry_run_args():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is not available")
    if "system32" in bash.lower():
        pytest.skip("WSL bash cannot execute the Windows .venv wrapper contract")
    script = REPO_ROOT / "scripts" / "tracking" / "add-tracking-item.sh"
    result = subprocess.run(
        [
            bash,
            str(script),
            "--dry-run",
            "--title",
            "T",
            "--wait-until",
            "2w",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=_utf8_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "DRY-RUN: tracking item payload" in result.stdout
    assert '"title": "T"' in result.stdout
    assert '"start_at"' in result.stdout
    assert "마감기한(due_at) = <없음>" in result.stdout


def test_bash_wrapper_has_worktree_venv_fallback_contract():
    script = REPO_ROOT / "scripts" / "tracking" / "add-tracking-item.sh"
    source = script.read_text(encoding="utf-8")
    assert "/.worktrees/" in source
    assert "FALLBACK_PYTHON" in source
    assert ".venv/Scripts/python.exe" in source
