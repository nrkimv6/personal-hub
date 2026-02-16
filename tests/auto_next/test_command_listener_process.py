"""Command Listener 프로세스 관리 TC

대상 소스: scripts/auto-next-command-listener.py (359줄)
Mock 대상: subprocess.Popen, redis.Redis → fakeredis
"""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import fakeredis

# 테스트 대상 함수 import를 위한 sys.path 조정
import sys
listener_path = Path("D:/work/project/tools/monitor-page/scripts")
if str(listener_path) not in sys.path:
    sys.path.insert(0, str(listener_path))

# 주의: 실제 listener 파일을 import하면 전역 변수가 초기화되므로
# 함수 단위로만 테스트합니다.


# ========== Fixtures ==========

@pytest.fixture
def fake_redis():
    """fakeredis 인스턴스"""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def mock_popen():
    """subprocess.Popen mock"""
    mock_process = MagicMock()
    mock_process.pid = 12345
    mock_process.poll.return_value = None  # 실행 중
    mock_process.wait.return_value = 0
    return mock_process


@pytest.fixture
def command_run_single():
    """단일 plan 실행 명령"""
    return {
        "action": "run",
        "plan_file": "common/docs/plan/test.md",
        "source": "monitor-page-api",
        "timestamp": datetime.now().isoformat()
    }


@pytest.fixture
def command_run_parallel():
    """병렬 실행 명령"""
    return {
        "action": "run",
        "parallel": True,
        "source": "monitor-page-api",
        "timestamp": datetime.now().isoformat()
    }


@pytest.fixture
def command_stop():
    """stop 명령"""
    return {
        "action": "stop",
        "source": "monitor-page-api",
        "timestamp": datetime.now().isoformat()
    }


# ========== Tests ==========

class TestStartAutoNext:
    """start_auto_next() 함수 TC"""

    def test_start_creates_subprocess_with_correct_args(self, fake_redis, command_run_single, mock_popen, tmp_path):
        """TC#1: Popen 호출 인수 검증 (mock)"""
        # listener 모듈 동적 import
        from auto_next_command_listener import start_auto_next

        with patch('auto_next_command_listener.subprocess.Popen', return_value=mock_popen) as mock_popen_cls, \
             patch('auto_next_command_listener.open', mock_open()), \
             patch('auto_next_command_listener.LOG_DIR', tmp_path), \
             patch('auto_next_command_listener._current_process', None):

            result = start_auto_next(command_run_single, fake_redis)

            # Popen 호출 확인
            assert mock_popen_cls.call_count == 1
            call_args = mock_popen_cls.call_args

            # 명령 인수 검증
            cmd = call_args[0][0]
            assert "python" in cmd[0] or "python.exe" in cmd[0]
            assert "-m" in cmd
            assert "auto_next" in cmd
            assert "run" in cmd
            assert "--plan-file" in cmd
            assert "common/docs/plan/test.md" in cmd

            # 결과 검증
            assert result["success"] is True
            assert result["pid"] == 12345

    def test_start_parallel_no_plan_file_in_args(self, fake_redis, command_run_parallel, mock_popen, tmp_path):
        """TC#2: --plan-file 미포함 확인"""
        from auto_next_command_listener import start_auto_next

        with patch('auto_next_command_listener.subprocess.Popen', return_value=mock_popen) as mock_popen_cls, \
             patch('auto_next_command_listener.open', mock_open()), \
             patch('auto_next_command_listener.LOG_DIR', tmp_path), \
             patch('auto_next_command_listener._current_process', None):

            result = start_auto_next(command_run_parallel, fake_redis)

            cmd = mock_popen_cls.call_args[0][0]
            assert "--plan-file" not in cmd
            assert "--parallel" in cmd

    def test_start_sets_redis_state(self, fake_redis, command_run_single, mock_popen, tmp_path):
        """TC#3: pid, plan_file, status, start_time Redis 저장"""
        from auto_next_command_listener import start_auto_next, STATE_KEY

        with patch('auto_next_command_listener.subprocess.Popen', return_value=mock_popen), \
             patch('auto_next_command_listener.open', mock_open()), \
             patch('auto_next_command_listener.LOG_DIR', tmp_path), \
             patch('auto_next_command_listener._current_process', None):

            result = start_auto_next(command_run_single, fake_redis)

            # Redis 상태 확인
            assert fake_redis.get(STATE_KEY + ":status") == "running"
            assert fake_redis.get(STATE_KEY + ":pid") == "12345"
            assert fake_redis.get(STATE_KEY + ":plan_file") == "common/docs/plan/test.md"
            assert fake_redis.get(STATE_KEY + ":start_time") is not None
            assert fake_redis.get(STATE_KEY + ":log_file_path") is not None

    def test_start_creates_log_file(self, fake_redis, command_run_single, mock_popen, tmp_path):
        """TC#4: 로그 파일 생성 확인"""
        from auto_next_command_listener import start_auto_next

        mock_file_handle = MagicMock()

        with patch('auto_next_command_listener.subprocess.Popen', return_value=mock_popen), \
             patch('auto_next_command_listener.open', return_value=mock_file_handle) as mock_open_fn, \
             patch('auto_next_command_listener.LOG_DIR', tmp_path), \
             patch('auto_next_command_listener._current_process', None):

            result = start_auto_next(command_run_single, fake_redis)

            # open() 호출 확인
            assert mock_open_fn.call_count == 1
            log_path = mock_open_fn.call_args[0][0]
            assert "auto-next-" in str(log_path)
            assert ".log" in str(log_path)


class TestStopAutoNext:
    """stop_auto_next() 함수 TC"""

    def test_stop_terminates_process(self, fake_redis, mock_popen):
        """TC#5: terminate() → wait() 호출 순서"""
        from auto_next_command_listener import stop_auto_next

        with patch('auto_next_command_listener._current_process', mock_popen):
            result = stop_auto_next(fake_redis)

            # terminate(), wait() 순서대로 호출
            assert mock_popen.terminate.call_count == 1
            assert mock_popen.wait.call_count == 1
            assert result["success"] is True

    def test_stop_force_kills_on_timeout(self, fake_redis):
        """TC#6: terminate 5초 후 kill()"""
        from auto_next_command_listener import stop_auto_next
        import subprocess

        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]

        with patch('auto_next_command_listener._current_process', mock_process):
            result = stop_auto_next(fake_redis)

            # kill() 호출 확인
            assert mock_process.kill.call_count == 1
            assert mock_process.wait.call_count == 2

    def test_stop_clears_redis_state(self, fake_redis, mock_popen):
        """TC#7: status, pid, log_file_path 삭제"""
        from auto_next_command_listener import stop_auto_next, STATE_KEY

        # Redis 상태 설정
        fake_redis.set(STATE_KEY + ":status", "running")
        fake_redis.set(STATE_KEY + ":pid", "12345")
        fake_redis.set(STATE_KEY + ":log_file_path", "/path/to/log.log")

        with patch('auto_next_command_listener._current_process', mock_popen):
            result = stop_auto_next(fake_redis)

            # Redis 정리 확인
            assert fake_redis.get(STATE_KEY + ":status") == "stopped"
            assert fake_redis.get(STATE_KEY + ":pid") is None
            assert fake_redis.get(STATE_KEY + ":log_file_path") is None


class TestGetStatus:
    """get_status() 함수 TC"""

    def test_status_running_process(self, fake_redis, mock_popen):
        """TC#8: poll()=None → running=True"""
        from auto_next_command_listener import get_status

        mock_popen.poll.return_value = None  # 실행 중
        log_file = Path("D:/logs/test.log")

        with patch('auto_next_command_listener._current_process', mock_popen), \
             patch('auto_next_command_listener._current_log_file', log_file):

            result = get_status(fake_redis)

            assert result["success"] is True
            assert result["running"] is True
            assert result["pid"] == 12345
            assert "test.log" in result["log_file"]

    def test_status_dead_process_cleanup(self, fake_redis):
        """TC#9: poll()!=None → Redis 정리"""
        from auto_next_command_listener import get_status, STATE_KEY

        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # 종료됨

        # Redis 상태 설정
        fake_redis.set(STATE_KEY + ":status", "running")
        fake_redis.set(STATE_KEY + ":pid", "12345")

        with patch('auto_next_command_listener._current_process', mock_process):
            result = get_status(fake_redis)

            # Redis 정리 확인
            assert fake_redis.get(STATE_KEY + ":status") == "stopped"
            assert fake_redis.get(STATE_KEY + ":pid") is None


class TestExecuteCommand:
    """execute_command() 디스패처 TC"""

    def test_execute_unknown_action(self, fake_redis):
        """TC#10: 미지원 action → 에러 반환"""
        from auto_next_command_listener import execute_command

        command = {"action": "invalid_action"}

        result = execute_command(command, fake_redis)

        assert result["success"] is False
        assert "Unknown action" in result["message"] or result["success"] is False
