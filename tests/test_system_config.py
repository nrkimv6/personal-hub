"""
system/config.py 및 SystemService.get_worker_status() 테스트

RIGHT-BICEP + CORRECT 기반 테스트 케이스
"""

import os
import sys
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.system.config import MANAGED_PROJECTS
from app.modules.system.services.worker_service import WorkerService as SystemService


# ============================================================
# MANAGED_PROJECTS config 검증
# ============================================================

class TestChatExecutorConfig:
    """chat_executor config 등록 검증 (A3)"""

    def test_monitor_page_workers_items_Re_contains_chat_executor(self):
        """REFERENCE/EXISTENCE: MANAGED_PROJECTS["monitor-page"]["workers"]["items"]에 chat_executor 항목 존재"""
        items = MANAGED_PROJECTS["monitor-page"]["workers"]["items"]
        names = [item["name"] for item in items]
        assert "chat_executor" in names, f"chat_executor 항목 없음. 현재 items: {names}"

    def test_monitor_page_workers_items_Co_chat_executor_tier_worker(self):
        """CONFORMANCE: chat_executor의 tier == 'worker' 계약 검증"""
        items = MANAGED_PROJECTS["monitor-page"]["workers"]["items"]
        chat_item = next((i for i in items if i["name"] == "chat_executor"), None)
        assert chat_item is not None
        assert chat_item["tier"] == "worker"

    def test_monitor_page_workers_items_Re_chat_executor_pid_file_names(self):
        """REFERENCE: worker_pid_file == 'chat_executor_admin.pid', watchdog_pid_file == 'chat_executor_watchdog_admin.pid'"""
        items = MANAGED_PROJECTS["monitor-page"]["workers"]["items"]
        chat_item = next((i for i in items if i["name"] == "chat_executor"), None)
        assert chat_item is not None
        assert chat_item["worker_pid_file"] == "chat_executor_admin.pid"
        assert chat_item["watchdog_pid_file"] == "chat_executor_watchdog_admin.pid"


class TestSleepNowConfig:
    """sleep-now 설정 검증"""

    def test_config_sleepnow_startup_prefix_right(self):
        """R: sleep-now의 startup_prefix가 'SleepNow-'인지 검증"""
        assert "sleep-now" in MANAGED_PROJECTS
        assert MANAGED_PROJECTS["sleep-now"]["startup_prefix"] == "SleepNow-"

    def test_config_sleepnow_workers_registered_right(self):
        """R: sleep-now workers.items에 session_worker 항목 존재, pid 파일 및 watchdog 검증"""
        workers = MANAGED_PROJECTS["sleep-now"]["workers"]
        assert workers is not None
        items = workers["items"]
        assert len(items) >= 1
        session = next((w for w in items if w["name"] == "session_worker"), None)
        assert session is not None
        assert session["worker_pid_file"] == "session_worker.pid"
        assert session["watchdog_pid_file"] is None

    def test_config_sleepnow_workers_path_right(self):
        """R: sleep-now path와 pid_dir 검증"""
        cfg = MANAGED_PROJECTS["sleep-now"]
        assert "sleep-now" in cfg["path"]
        assert cfg["workers"]["pid_dir"] == ".pids"


class TestOllamaConfig:
    """ollama 설정 검증"""

    def test_config_ollama_registered_right(self):
        """R: 'ollama' 키가 MANAGED_PROJECTS에 존재, startup_prefix 검증"""
        assert "ollama" in MANAGED_PROJECTS
        assert MANAGED_PROJECTS["ollama"]["startup_prefix"] == "Ollama"

    def test_config_ollama_no_workers_boundary(self):
        """B: ollama의 workers/nssm_prefix/task_folder가 None인지 검증 (오탐 방지)"""
        cfg = MANAGED_PROJECTS["ollama"]
        assert cfg["workers"] is None
        assert cfg["nssm_prefix"] is None
        assert cfg["task_folder"] is None


# ============================================================
# SystemService.get_worker_status() 검증
# ============================================================

class TestGetWorkerStatus:
    """SystemService.get_worker_status() 단위 테스트"""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_get_worker_status_no_watchdog_right(self, tmp_path):
        """R: watchdog_pid_file=None인 워커에서 반환값의 watchdog가 None인지 검증"""
        pid_dir = tmp_path / ".pids"
        pid_dir.mkdir()
        pid_file = pid_dir / "session_worker.pid"
        pid_file.write_text(str(os.getpid()))

        fake_projects = {
            "test-project": {
                "path": str(tmp_path),
                "workers": {
                    "pid_dir": ".pids",
                    "items": [
                        {
                            "name": "session_worker",
                            "label": "세션 워커",
                            "tier": "worker",
                            "watchdog_pid_file": None,
                            "worker_pid_file": "session_worker.pid",
                        }
                    ]
                }
            }
        }
        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake_projects):
            svc = SystemService()
            result = self._run(svc.get_worker_status())

        assert len(result) == 1
        entry = result[0]
        assert entry["name"] == "session_worker"
        assert entry["watchdog"] is None  # watchdog_pid_file=None → watchdog 키 None
        assert entry["worker"] is not None
        assert entry["worker"]["running"] is True

    def test_get_worker_status_external_path_right(self, tmp_path):
        """R: 외부 프로젝트 경로의 PID 파일을 정상 해석하는지 검증"""
        pid_dir = tmp_path / ".pids"
        pid_dir.mkdir()
        pid_file = pid_dir / "session_worker.pid"
        pid_file.write_text(str(os.getpid()))

        fake_projects = {
            "sleep-now": {
                "path": str(tmp_path),
                "workers": {
                    "pid_dir": ".pids",
                    "items": [
                        {
                            "name": "session_worker",
                            "label": "세션 워커",
                            "tier": "worker",
                            "watchdog_pid_file": None,
                            "worker_pid_file": "session_worker.pid",
                        }
                    ]
                }
            }
        }
        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake_projects):
            svc = SystemService()
            result = self._run(svc.get_worker_status())

        assert len(result) == 1
        assert result[0]["project"] == "sleep-now"
        assert result[0]["worker"]["running"] is True

    def test_get_worker_status_external_path_missing_error(self, tmp_path):
        """E: 외부 프로젝트 경로가 존재하지 않을 때 running=False 반환 검증"""
        nonexistent = tmp_path / "does_not_exist"

        fake_projects = {
            "sleep-now": {
                "path": str(nonexistent),
                "workers": {
                    "pid_dir": ".pids",
                    "items": [
                        {
                            "name": "session_worker",
                            "label": "세션 워커",
                            "tier": "worker",
                            "watchdog_pid_file": None,
                            "worker_pid_file": "session_worker.pid",
                        }
                    ]
                }
            }
        }
        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake_projects):
            svc = SystemService()
            result = self._run(svc.get_worker_status())

        assert len(result) == 1
        worker = result[0]["worker"]
        # PID 파일 없으므로 pid=None, running=False
        assert worker["pid"] is None
        assert worker["running"] is False
