"""Command Listener 프로세스 관리 TC (Phase 5 보강 포함)

대상 소스: scripts/auto-next-command-listener.py (359줄)
Mock 대상: subprocess.Popen, redis.Redis → fakeredis
"""

import importlib.util
import json
import os
import subprocess
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import fakeredis


# ========== 모듈 로드 (하이픈 파일명 대응) ==========

_listener_mod = None

def _get_listener():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    script_path = Path("D:/work/project/tools/monitor-page/scripts/auto-next-command-listener.py")
    if not script_path.exists():
        pytest.skip(f"Listener script not found: {script_path}")
    spec = importlib.util.spec_from_file_location("auto_next_command_listener", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _listener_mod = mod
    return mod


@pytest.fixture(scope="module")
def listener_mod():
    return _get_listener()


# ========== Fixtures ==========

@pytest.fixture
def fr():
    """fakeredis (테스트간 격리)"""
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


@pytest.fixture
def mock_popen():
    p = MagicMock()
    p.pid = 12345
    p.poll.return_value = None
    p.wait.return_value = 0
    return p


@pytest.fixture(autouse=True)
def reset_globals(listener_mod):
    """테스트 간 전역변수 초기화"""
    listener_mod._current_process = None
    listener_mod._current_log_file = None
    yield
    listener_mod._current_process = None
    listener_mod._current_log_file = None


# ========== TestStartAutoNext ==========

class TestStartAutoNext:

    def test_start_creates_subprocess(self, listener_mod, fr, mock_popen, tmp_path):
        """Popen 호출 인수 검증"""
        command = {"action": "run", "plan_file": "common/docs/plan/test.md"}

        with patch.object(listener_mod, 'LOG_DIR', tmp_path):
            with patch.object(listener_mod.subprocess, 'Popen', return_value=mock_popen) as mp:
                result = listener_mod.start_auto_next(command, fr)

            assert mp.call_count == 1
            cmd = mp.call_args[0][0]
            assert "run" in cmd
            assert "--plan-file" in cmd
            assert "common/docs/plan/test.md" in cmd
            assert result["success"] is True
            assert result["pid"] == 12345

    def test_start_parallel_no_plan_file(self, listener_mod, fr, mock_popen, tmp_path):
        """parallel 모드: --plan-file 미포함"""
        command = {"action": "run", "parallel": True}

        with patch.object(listener_mod, 'LOG_DIR', tmp_path), \
             patch.object(listener_mod.subprocess, 'Popen', return_value=mock_popen) as mp:
            result = listener_mod.start_auto_next(command, fr)

        cmd = mp.call_args[0][0]
        assert "--plan-file" not in cmd
        assert "--parallel" in cmd

    def test_start_sets_redis_state(self, listener_mod, fr, mock_popen, tmp_path):
        """Redis 상태 저장 확인"""
        SK = listener_mod.STATE_KEY
        command = {"action": "run", "plan_file": "test.md"}

        with patch.object(listener_mod, 'LOG_DIR', tmp_path), \
             patch.object(listener_mod.subprocess, 'Popen', return_value=mock_popen):
            listener_mod.start_auto_next(command, fr)

        assert fr.get(SK + ":status") == "running"
        assert fr.get(SK + ":pid") == "12345"
        assert fr.get(SK + ":plan_file") == "test.md"

    def test_start_plan_file_none_saves_ALL(self, listener_mod, fr, mock_popen, tmp_path):
        """Phase5 - plan_file=None → Redis에 'ALL' 저장"""
        SK = listener_mod.STATE_KEY
        command = {"action": "run", "parallel": True}

        with patch.object(listener_mod, 'LOG_DIR', tmp_path), \
             patch.object(listener_mod.subprocess, 'Popen', return_value=mock_popen):
            listener_mod.start_auto_next(command, fr)

        assert fr.get(SK + ":plan_file") == "ALL"

    def test_start_already_running_returns_error(self, listener_mod, fr, mock_popen):
        """이미 실행 중이면 에러"""
        listener_mod._current_process = mock_popen  # poll() returns None = running

        result = listener_mod.start_auto_next({"action": "run", "plan_file": "test.md"}, fr)
        assert result["success"] is False
        assert "Already running" in result["message"]


# ========== TestStopAutoNext ==========

class TestStopAutoNext:

    def test_stop_terminates_process(self, listener_mod, fr, mock_popen):
        """terminate → wait 호출"""
        listener_mod._current_process = mock_popen
        result = listener_mod.stop_auto_next(fr)

        assert mock_popen.terminate.call_count == 1
        assert result["success"] is True

    def test_stop_force_kills_on_timeout(self, listener_mod, fr):
        """Phase5 - terminate 5초 내 미종료 → kill"""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]

        listener_mod._current_process = mock_process
        result = listener_mod.stop_auto_next(fr)

        assert mock_process.kill.call_count == 1

    def test_stop_clears_redis_state(self, listener_mod, fr, mock_popen):
        """Redis 상태 정리"""
        SK = listener_mod.STATE_KEY
        fr.set(SK + ":status", "running")
        fr.set(SK + ":pid", "12345")

        listener_mod._current_process = mock_popen
        listener_mod.stop_auto_next(fr)

        assert fr.get(SK + ":status") == "stopped"
        assert fr.get(SK + ":pid") is None

    def test_stop_not_running_returns_error(self, listener_mod, fr):
        """미실행 상태 stop → 실패"""
        result = listener_mod.stop_auto_next(fr)
        assert result["success"] is False


# ========== TestGetStatus ==========

class TestGetStatus:

    def test_status_running(self, listener_mod, fr, mock_popen):
        """poll()=None → running=True"""
        log_file = Path("D:/logs/test.log")
        listener_mod._current_process = mock_popen
        listener_mod._current_log_file = log_file

        result = listener_mod.get_status(fr)
        assert result["running"] is True
        assert result["pid"] == 12345

    def test_status_dead_process_cleanup(self, listener_mod, fr):
        """Phase5 - 죽은 프로세스 → Redis 자동 정리"""
        SK = listener_mod.STATE_KEY
        mock_process = MagicMock()
        mock_process.poll.return_value = 0

        fr.set(SK + ":status", "running")
        fr.set(SK + ":pid", "12345")

        listener_mod._current_process = mock_process
        result = listener_mod.get_status(fr)

        assert result["running"] is False
        assert fr.get(SK + ":status") == "stopped"
        assert fr.get(SK + ":pid") is None

    def test_status_no_process(self, listener_mod, fr):
        """프로세스 없음 → not running"""
        result = listener_mod.get_status(fr)
        assert result["running"] is False


# ========== TestExecuteCommand ==========

class TestExecuteCommand:

    def test_unknown_action(self, listener_mod, fr):
        """Phase5 - 알 수 없는 action → error"""
        result = listener_mod.execute_command({"action": "invalid"}, fr)
        assert result["success"] is False
        assert "Unknown action" in result["message"]

    def test_dispatch_status(self, listener_mod, fr):
        """status 디스패치"""
        result = listener_mod.execute_command({"action": "status"}, fr)
        assert result["success"] is True
        assert result["running"] is False
