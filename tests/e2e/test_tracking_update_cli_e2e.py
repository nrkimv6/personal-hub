import os
import shutil
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


def _utf8_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def test_powershell_update_wrapper_forwards_dry_run_args():
    script = REPO_ROOT / "scripts" / "tracking" / "update-tracking-item.ps1"
    result = subprocess.run(
        [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "--dry-run",
            "--id",
            "3",
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
    assert "DRY-RUN: tracking item update payload" in result.stdout
    assert "item id=3" in result.stdout
    assert '"start_at"' in result.stdout
    assert "마감기한(due_at) = <변경 없음>" in result.stdout


def test_bash_update_wrapper_forwards_dry_run_args():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is not available")
    if "system32" in bash.lower():
        pytest.skip("WSL bash cannot execute the Windows .venv wrapper contract")
    script = REPO_ROOT / "scripts" / "tracking" / "update-tracking-item.sh"
    result = subprocess.run(
        [
            bash,
            str(script),
            "--dry-run",
            "--id",
            "3",
            "--clear-deadline",
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
    assert "DRY-RUN: tracking item update payload" in result.stdout
    assert "item id=3" in result.stdout
    assert '"due_at": null' in result.stdout
    assert "마감기한(due_at) = <지움>" in result.stdout
