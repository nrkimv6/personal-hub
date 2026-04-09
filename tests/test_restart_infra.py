"""
restart_infra 단위 테스트 (T1)

SystemService.restart_infra() 및 get_worker_status() tier 필드 검증
"""

import asyncio
import copy
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.system.services.worker_service import WorkerService as SystemService


def run(coro):
    return asyncio.run(coro)


def _make_subprocess_result(returncode=0, stdout="완료", stderr=""):
    """subprocess.run 결과 mock"""
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


# ─── restart_infra ────────────────────────────────────────────────────────────

class TestRestartInfra:

    def test_restart_infra_sends_subprocess_command(self):
        """R(정상): restart_infra("api_watchdog") → subprocess.run에 browser_workers.py, restart-infra, api_watchdog 전달"""
        sp_result = _make_subprocess_result(returncode=0, stdout="완료")

        with patch("app.modules.system.services.worker_service.subprocess.run", return_value=sp_result) as mock_run:
            svc = SystemService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "browser_workers.py" in args[1]
        assert "restart-infra" in args
        assert "api_watchdog" in args

    def test_restart_infra_command_listener(self):
        """R(정상): restart_infra("command_listener") → restart-listener 액션, name 미포함"""
        sp_result = _make_subprocess_result(returncode=0, stdout="완료")

        with patch("app.modules.system.services.worker_service.subprocess.run", return_value=sp_result) as mock_run:
            svc = SystemService()
            result = run(svc.restart_infra("command_listener"))

        assert result["success"] is True
        args = mock_run.call_args[0][0]
        assert "restart-listener" in args
        assert "command_listener" not in args

    def test_restart_infra_invalid_name(self):
        """E(에러): 존재하지 않는 name → success=False, subprocess 미호출"""
        with patch("app.modules.system.services.worker_service.subprocess.run") as mock_run:
            svc = SystemService()
            result = run(svc.restart_infra("nonexistent_proc_xyz"))

        assert result["success"] is False
        assert "nonexistent_proc_xyz" in result["message"]
        mock_run.assert_not_called()

    def test_restart_infra_non_infra_tier(self):
        """B(경계): worker tier name(unified_worker) → infra 필터에 의해 거부"""
        with patch("app.modules.system.services.worker_service.subprocess.run") as mock_run:
            svc = SystemService()
            result = run(svc.restart_infra("unified_worker"))

        assert result["success"] is False
        mock_run.assert_not_called()

    def test_restart_infra_timeout(self):
        """E(에러): subprocess 60초 timeout → success=False, 타임아웃 메시지"""
        with patch("app.modules.system.services.worker_service.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="browser_workers.py", timeout=60)):
            svc = SystemService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is False
        assert "타임아웃" in result["message"]

    def test_restart_infra_subprocess_failure(self):
        """E(에러): subprocess 실패(returncode=1) → success=False, stderr 메시지 포함"""
        sp_result = _make_subprocess_result(returncode=1, stdout="", stderr="실행 실패")

        with patch("app.modules.system.services.worker_service.subprocess.run", return_value=sp_result):
            svc = SystemService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is False
        assert "실행 실패" in result["message"]

    def test_restart_infra_subprocess_exception(self):
        """E(에러): subprocess 예외 발생 → success=False"""
        with patch("app.modules.system.services.worker_service.subprocess.run",
                   side_effect=RuntimeError("permission denied")):
            svc = SystemService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is False
        assert "permission denied" in result["message"]


# ─── get_worker_status tier 필드 ─────────────────────────────────────────────

class TestGetWorkerStatusTier:

    def test_get_worker_status_includes_tier(self, tmp_path):
        """R(정상): get_worker_status() 반환값의 각 entry에 tier 키 존재"""
        from app.modules.system.config import MANAGED_PROJECTS
        fake = copy.deepcopy(MANAGED_PROJECTS)
        # monitor-page path를 tmp_path로 교체 (pid 파일 없음 → running=False, 에러 없음)
        fake["monitor-page"]["path"] = str(tmp_path)
        (tmp_path / ".pids").mkdir(exist_ok=True)

        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake):
            svc = SystemService()
            result = asyncio.run(svc.get_worker_status())

        monitor_entries = [e for e in result if e["project"] == "monitor-page"]
        assert len(monitor_entries) > 0
        for entry in monitor_entries:
            assert "tier" in entry
            assert entry["tier"] in ("worker", "infra")

    def test_get_worker_status_default_tier(self, tmp_path):
        """B(경계): config에 tier 미지정 항목 → 기본값 'worker'"""
        from app.modules.system.config import MANAGED_PROJECTS
        fake = copy.deepcopy(MANAGED_PROJECTS)
        fake["monitor-page"]["path"] = str(tmp_path)
        (tmp_path / ".pids").mkdir(exist_ok=True)
        # tier 필드 없는 항목 추가
        fake["monitor-page"]["workers"]["items"].append({
            "name": "no_tier_worker",
            "label": "tier 없음",
            # tier 키 없음
            "watchdog_pid_file": None,
            "worker_pid_file": None,
        })

        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake):
            svc = SystemService()
            result = asyncio.run(svc.get_worker_status())

        no_tier = next((e for e in result if e["name"] == "no_tier_worker"), None)
        assert no_tier is not None
        assert no_tier["tier"] == "worker"


# ─── restart_worker infra 제외 ────────────────────────────────────────────────

class TestRestartWorkerExcludesInfra:

    def test_restart_worker_excludes_infra(self, tmp_path):
        """R(정상): restart_worker("all") → infra tier 항목의 _kill_pid_file 호출되지 않음"""
        from app.modules.system.config import MANAGED_PROJECTS
        fake = copy.deepcopy(MANAGED_PROJECTS)
        fake["monitor-page"]["path"] = str(tmp_path)
        pid_dir = tmp_path / ".pids"
        pid_dir.mkdir()

        # worker tier PID 파일 생성 (통합 워커)
        (pid_dir / "unified_worker_admin.pid").write_text(str(os.getpid()))

        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake):
            svc = SystemService()
            killed_labels = []
            original_kill = svc._kill_pid_file

            async def tracking_kill(pid_file, label):
                killed_labels.append(label)
                return False, f"mock: {label}"

            svc._kill_pid_file = tracking_kill
            asyncio.run(svc.restart_worker("all"))

        # infra tier 항목이 kill 대상에 포함되지 않아야 함
        infra_items = [
            item for item in fake["monitor-page"]["workers"]["items"]
            if item.get("tier") == "infra"
        ]
        infra_labels = [item["label"] for item in infra_items]
        for label in infra_labels:
            assert not any(label in k for k in killed_labels), \
                f"infra 항목 '{label}'이 kill 대상에 포함됨"
