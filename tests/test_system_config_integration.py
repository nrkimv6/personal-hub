"""
system 모듈 통합 테스트 (T3: 실제 파일시스템 사용, mock 없음)

sleep-now PID 감지 및 시작 프로그램 탐색 통합 검증
"""

import os
import sys
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.system.services.system_service import SystemService


class TestSleepNowPidDetectionIntegration:
    """sleep-now PID 감지 통합 테스트 — 실제 파일시스템 사용"""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_integration_sleepnow_pid_detection(self, tmp_path):
        """
        T3: 실제 파일시스템에 임시 session_worker.pid 생성 후
        get_worker_status()가 해당 워커를 running=True로 반환하는지 검증.
        config의 sleep-now path를 tmp_path로 monkeypatch (실물 파일시스템).
        """
        # 실제 .pids 디렉토리와 PID 파일 생성
        pid_dir = tmp_path / ".pids"
        pid_dir.mkdir()
        pid_file = pid_dir / "session_worker.pid"
        pid_file.write_text(str(os.getpid()))  # 현재 프로세스 PID (살아있는 PID)

        # MANAGED_PROJECTS의 sleep-now path만 tmp_path로 교체
        from app.modules.system.config import MANAGED_PROJECTS
        import copy
        fake_projects = copy.deepcopy(MANAGED_PROJECTS)
        fake_projects["sleep-now"]["path"] = str(tmp_path)

        with patch("app.modules.system.services.system_service.MANAGED_PROJECTS", fake_projects):
            svc = SystemService()
            result = self._run(svc.get_worker_status())

        # sleep-now session_worker가 결과에 포함되어야 함
        sleepnow_workers = [w for w in result if w["project"] == "sleep-now"]
        assert len(sleepnow_workers) >= 1

        session = next((w for w in sleepnow_workers if w["name"] == "session_worker"), None)
        assert session is not None, "session_worker가 결과에 없음"
        assert session["watchdog"] is None, "session_worker의 watchdog은 None이어야 함"
        assert session["worker"] is not None
        assert session["worker"]["running"] is True, "PID가 살아있으므로 running=True여야 함"
        assert session["worker"]["pid"] == os.getpid()

    def test_integration_startup_prefix_finds_lnk(self):
        """
        T3: 실제 startup 디렉토리에서 SleepNow- prefix로 시작하는 .lnk 파일 존재 여부를
        SystemService().get_startup_programs() 호출로 검증.
        실제 파일시스템 사용, mock 없음.
        """
        svc = SystemService()
        result = self._run(svc.get_startup_programs())

        # SleepNow- prefix 시작 프로그램이 등록되어 있어야 함
        sleepnow_startups = [p for p in result if p.get("project") == "sleep-now"]

        # 실제 시스템에 SleepNow-SessionWorker.lnk가 있으면 감지됨
        startup_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        expected_lnks = list(startup_dir.glob("SleepNow-*.lnk"))

        assert len(sleepnow_startups) == len(expected_lnks), (
            f"startup 디렉토리의 SleepNow- lnk 파일 수({len(expected_lnks)})와 "
            f"get_startup_programs() 결과({len(sleepnow_startups)})가 일치해야 함"
        )
