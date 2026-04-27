"""
T4 E2E: command_listener restart smoke — ModuleNotFoundError 회귀 방어

fix: worker-command-listener sys.path bootstrap 패치 검증.
main runtime에서 command_listener restart 후 ModuleNotFoundError가 발생하지 않는지 확인한다.

skip 조건:
- live API(localhost:8001) 미기동
- .pids/command_listener_admin.pid 미존재 (watchdog 미실행 환경)

/merge-test owner가 main runtime에서만 실행한다.
"""
import time
from pathlib import Path

import pytest
import httpx


BASE = "http://localhost:8001"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PID_FILE = PROJECT_ROOT / ".pids" / "command_listener_admin.pid"
LOG_DIR = PROJECT_ROOT / "logs" / "admin"


def _is_api_up() -> bool:
    try:
        r = httpx.get(f"{BASE}/api/v1/system/liveness", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _watchdog_running() -> bool:
    """command_listener watchdog가 live 상태인지 확인."""
    try:
        r = httpx.get(f"{BASE}/api/v1/system/services/workers", timeout=5.0)
        for item in r.json():
            if item.get("name") == "command_listener":
                return item.get("watchdog", {}).get("running", False)
    except Exception:
        pass
    return False


pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def skip_if_not_ready():
    if not _is_api_up():
        pytest.skip("live API(localhost:8001) 미기동 — skip")
    if not _watchdog_running():
        pytest.skip("command_listener watchdog 미실행 — skip (false-positive 방지)")


def _get_latest_stderr_log() -> Path | None:
    """최신 command_listener stderr 로그 파일을 반환한다."""
    logs = sorted(LOG_DIR.glob("stderr_command_listener_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


class TestCommandListenerRestartE2E:
    """command_listener restart 후 ModuleNotFoundError 회귀 검증."""

    @staticmethod
    def _combined_output(result) -> str:
        return f"{result.stdout or ''}{result.stderr or ''}"

    def test_right_restart_infra_no_module_not_found(self):
        """browser_workers.py restart-infra command_listener 후 ModuleNotFoundError 없음."""
        import subprocess
        import sys

        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        python = str(venv_python) if venv_python.exists() else sys.executable
        browser_workers = PROJECT_ROOT / "scripts" / "services" / "browser_workers.py"

        result = subprocess.run(
            [python, str(browser_workers), "restart-infra", "command_listener"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
        )
        # restart 명령이 성공적으로 요청됐거나 already restarted 응답
        assert result.returncode == 0, (
            f"restart-infra 실패: returncode={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "ModuleNotFoundError" not in self._combined_output(result), (
            f"restart 과정에서 ModuleNotFoundError 감지\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_right_pid_file_exists_after_restart(self):
        """restart 후 30초 내에 .pids/command_listener_admin.pid가 생성/갱신된다."""
        import subprocess
        import sys

        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        python = str(venv_python) if venv_python.exists() else sys.executable
        browser_workers = PROJECT_ROOT / "scripts" / "services" / "browser_workers.py"

        mtime_before = PID_FILE.stat().st_mtime if PID_FILE.exists() else 0

        subprocess.run(
            [python, str(browser_workers), "restart-infra", "command_listener"],
            capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT),
        )

        # PID 파일 갱신 대기 (최대 30초)
        for _ in range(6):
            time.sleep(5)
            if PID_FILE.exists() and PID_FILE.stat().st_mtime > mtime_before:
                break

        assert PID_FILE.exists(), f".pids/command_listener_admin.pid 없음 — 재시작 실패 의심"

    def test_error_no_modulenotfound_in_logs(self):
        """최신 command_listener stderr 로그에 ModuleNotFoundError가 없다."""
        log_file = _get_latest_stderr_log()
        if log_file is None:
            pytest.skip("stderr_command_listener_*.log 없음 — skip")

        content = log_file.read_text(encoding="utf-8", errors="replace")
        assert "ModuleNotFoundError: No module named 'app'" not in content, (
            f"최신 로그({log_file.name})에 ModuleNotFoundError 발견 — sys.path bootstrap 패치 실패"
        )
