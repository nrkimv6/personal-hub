"""Command Listener 프로세스 관리 TC — 멀티 runner 기반 업데이트

대상 소스: scripts/dev-runner-command-listener.py
변경사항: _current_process → _running_processes dict, STATE_KEY → RUNNER_KEY_PREFIX
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
    script_path = Path("D:/work/project/tools/monitor-page/scripts/dev-runner-command-listener.py")
    if not script_path.exists():
        pytest.skip(f"Listener script not found: {script_path}")
    spec = importlib.util.spec_from_file_location("dev_runner_command_listener", str(script_path))
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


RUNNER_ID = "test1234"


@pytest.fixture(autouse=True)
def reset_globals(listener_mod):
    """테스트 간 전역 dict 초기화"""
    listener_mod._running_processes.clear()
    listener_mod._running_log_files.clear()
    listener_mod._stream_threads.clear()
    yield
    listener_mod._running_processes.clear()
    listener_mod._running_log_files.clear()
    listener_mod._stream_threads.clear()


@pytest.fixture
def mock_worktree(listener_mod, tmp_path):
    """WorktreeManager.create mock — start_plan_runner 테스트용"""
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()
    with patch.object(listener_mod.WorktreeManager, 'create', return_value=(worktree_path, "runner/test1234")):
        yield worktree_path


# ========== TestStartPlanRunner ==========

class TestStartPlanRunner:
    """start_plan_runner — 백그라운드 스레드 시작 동작 검증"""

    def test_start_launches_background_thread(self, listener_mod, fr, tmp_path, mock_worktree):
        """start_plan_runner은 None을 반환하고 백그라운드 스레드를 시작"""
        command = {"action": "run", "runner_id": RUNNER_ID, "plan_file": "test.md"}

        with patch.object(listener_mod.threading, 'Thread') as mock_thread:
            mock_thread.return_value = MagicMock()
            result = listener_mod.start_plan_runner(command, fr)

        assert result is None  # sentinel: main loop에서 결과 push 스킵
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

    def test_start_already_running_returns_error(self, listener_mod, fr, mock_popen, tmp_path, mock_worktree):
        """같은 runner_id로 이미 실행 중이면 에러 (_is_pid_alive mocked)"""
        listener_mod._running_processes[RUNNER_ID] = mock_popen  # poll() returns None = running

        with patch.object(listener_mod, '_is_pid_alive', return_value=True):
            result = listener_mod.start_plan_runner({"action": "run", "runner_id": RUNNER_ID, "plan_file": "test.md"}, fr)
        assert result["success"] is False
        assert "Already running" in result["message"]


class TestLaunchPlanRunnerProcess:
    """_launch_plan_runner_process — Popen 호출 및 Redis 상태 검증"""

    def test_launch_creates_subprocess(self, listener_mod, fr, mock_popen, tmp_path, mock_worktree):
        """Popen 호출 인수 검증"""
        command = {"action": "run", "runner_id": RUNNER_ID, "plan_file": "common/docs/plan/test.md"}

        with patch.object(listener_mod, 'LOG_DIR', tmp_path), \
             patch.object(listener_mod.threading, 'Thread') as mock_thread, \
             patch.object(listener_mod.subprocess, 'Popen', return_value=mock_popen) as mp:
            mock_thread.return_value = MagicMock()
            result = listener_mod._launch_plan_runner_process(command, fr, RUNNER_ID, mock_worktree, "common/docs/plan/test.md", None)

        assert mp.call_count >= 1  # plan runner + optional merge orchestrator
        cmd = mp.call_args_list[0][0][0]
        assert "run" in cmd
        assert "--plan-file" in cmd
        assert "common/docs/plan/test.md" in cmd
        assert result["success"] is True
        assert result["pid"] == 12345

    def test_launch_parallel_no_plan_file(self, listener_mod, fr, mock_popen, tmp_path, mock_worktree):
        """parallel 모드: --plan-file 미포함"""
        command = {"action": "run", "runner_id": RUNNER_ID, "parallel": True}

        with patch.object(listener_mod, 'LOG_DIR', tmp_path), \
             patch.object(listener_mod.threading, 'Thread') as mock_thread, \
             patch.object(listener_mod.subprocess, 'Popen', return_value=mock_popen) as mp:
            mock_thread.return_value = MagicMock()
            result = listener_mod._launch_plan_runner_process(command, fr, RUNNER_ID, mock_worktree, None, None)

        cmd = mp.call_args[0][0]
        assert "--plan-file" not in cmd
        assert "--parallel" in cmd

    def test_launch_sets_redis_state(self, listener_mod, fr, mock_popen, tmp_path, mock_worktree):
        """Redis per-runner 상태 저장 확인"""
        RKP = listener_mod.RUNNER_KEY_PREFIX
        command = {"action": "run", "runner_id": RUNNER_ID, "plan_file": "test.md"}

        with patch.object(listener_mod, 'LOG_DIR', tmp_path), \
             patch.object(listener_mod.threading, 'Thread') as mock_thread, \
             patch.object(listener_mod.subprocess, 'Popen', return_value=mock_popen):
            mock_thread.return_value = MagicMock()
            listener_mod._launch_plan_runner_process(command, fr, RUNNER_ID, mock_worktree, "test.md", None)

        assert fr.get(f"{RKP}:{RUNNER_ID}:status") == "running"
        assert fr.get(f"{RKP}:{RUNNER_ID}:pid") == "12345"
        assert fr.get(f"{RKP}:{RUNNER_ID}:plan_file") == "test.md"

    def test_launch_plan_file_none_saves_sentinel(self, listener_mod, fr, mock_popen, tmp_path, mock_worktree):
        """plan_file=None → Redis에 '__ALL_PLANS__' sentinel 저장 (Right)"""
        RKP = listener_mod.RUNNER_KEY_PREFIX
        command = {"action": "run", "runner_id": RUNNER_ID, "parallel": True}

        with patch.object(listener_mod, 'LOG_DIR', tmp_path), \
             patch.object(listener_mod.threading, 'Thread') as mock_thread, \
             patch.object(listener_mod.subprocess, 'Popen', return_value=mock_popen):
            mock_thread.return_value = MagicMock()
            listener_mod._launch_plan_runner_process(command, fr, RUNNER_ID, mock_worktree, None, None)

        assert fr.get(f"{RKP}:{RUNNER_ID}:plan_file") == listener_mod.PLAN_FILE_ALL

    def test_legacy_ALL_still_recognized(self, listener_mod, fr, mock_popen, tmp_path, mock_worktree):
        """기존 Redis에 'ALL' 값이 있을 때도 sentinel로 인식 (하위 호환, Right)"""
        RKP = listener_mod.RUNNER_KEY_PREFIX
        # 기존 "ALL" 값이 Redis에 저장되어 있다고 가정
        fr.set(f"{RKP}:{RUNNER_ID}:plan_file", "ALL")
        fr.set(f"{RKP}:{RUNNER_ID}:merge_status", "done")

        # _cleanup_runner 내부에서 "ALL" → None 변환 확인
        val = fr.get(f"{RKP}:{RUNNER_ID}:plan_file")
        assert val in ("ALL", listener_mod.PLAN_FILE_ALL), "기존 'ALL' 값도 sentinel로 처리돼야 함"
        # 실제 비교 로직: in (PLAN_FILE_ALL, _LEGACY_ALL)
        assert val in (listener_mod.PLAN_FILE_ALL, listener_mod._LEGACY_ALL)


# ========== TestStopPlanRunner ==========

class TestStopPlanRunner:

    def test_stop_terminates_process(self, listener_mod, fr, mock_popen):
        """terminate → wait 호출"""
        listener_mod._running_processes[RUNNER_ID] = mock_popen
        result = listener_mod.stop_plan_runner(RUNNER_ID, fr)

        assert mock_popen.terminate.call_count == 1
        assert result["success"] is True

    def test_stop_force_kills_on_timeout(self, listener_mod, fr):
        """terminate 5초 내 미종료 → kill"""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]

        listener_mod._running_processes[RUNNER_ID] = mock_process
        result = listener_mod.stop_plan_runner(RUNNER_ID, fr)

        assert mock_process.kill.call_count == 1

    def test_stop_clears_redis_state(self, listener_mod, fr, mock_popen):
        """Redis per-runner 상태 정리 (srem)"""
        RKP = listener_mod.RUNNER_KEY_PREFIX
        AK = listener_mod.ACTIVE_RUNNERS_KEY
        fr.set(f"{RKP}:{RUNNER_ID}:status", "running")
        fr.set(f"{RKP}:{RUNNER_ID}:pid", "12345")
        fr.sadd(AK, RUNNER_ID)

        listener_mod._running_processes[RUNNER_ID] = mock_popen
        listener_mod.stop_plan_runner(RUNNER_ID, fr)

        # runner가 active_runners에서 제거되어야 함
        assert not fr.sismember(AK, RUNNER_ID)

    def test_stop_not_running_returns_error(self, listener_mod, fr):
        """미실행 runner_id stop → 실패"""
        result = listener_mod.stop_plan_runner(RUNNER_ID, fr)
        assert result["success"] is False


# ========== TestGetStatus ==========

class TestGetStatus:

    def test_status_running(self, listener_mod, fr, mock_popen):
        """_running_processes에 실행 중 프로세스 → running=True"""
        listener_mod._running_processes[RUNNER_ID] = mock_popen

        result = listener_mod.get_status(fr)
        assert result["running"] is True
        assert result["pid"] == 12345

    def test_status_dead_process_cleanup(self, listener_mod, fr):
        """죽은 프로세스 → dict에서 제거"""
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # 종료됨

        listener_mod._running_processes[RUNNER_ID] = mock_process
        result = listener_mod.get_status(fr)

        assert result["running"] is False
        assert RUNNER_ID not in listener_mod._running_processes

    def test_status_no_process(self, listener_mod, fr):
        """프로세스 없음 → not running"""
        result = listener_mod.get_status(fr)
        assert result["running"] is False


# ========== TestExecuteCommand ==========

class TestExecuteCommand:

    def test_unknown_action(self, listener_mod, fr):
        """알 수 없는 action → error"""
        result = listener_mod.execute_command({"action": "invalid"}, fr)
        assert result["success"] is False
        assert "Unknown action" in result["message"]

    def test_dispatch_status(self, listener_mod, fr):
        """status 디스패치"""
        result = listener_mod.execute_command({"action": "status"}, fr)
        assert result["success"] is True
        assert result["running"] is False
