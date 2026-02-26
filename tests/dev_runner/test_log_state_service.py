"""Phase 7: LogService + RunState 단위 테스트"""

import subprocess
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest
import redis

from app.modules.dev_runner.services.log_service import LogService
from app.modules.dev_runner.services.state import RunState
from app.modules.dev_runner.schemas import LogResponse


# ========== LogService 테스트 ==========


class TestLogServiceTailLogFile:
    """tail_log_file() 테스트"""

    def test_file_exists_returns_last_n_lines(self, tmp_path):
        """파일 존재 시 마지막 N줄 반환"""
        log_file = tmp_path / "test.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")

        service = LogService.__new__(LogService)
        service.redis_client = MagicMock()
        with patch.object(service, "_find_current_log", return_value=log_file):
            result = service.tail_log_file("test_runner", n_lines=50)

        assert isinstance(result, LogResponse)
        assert len(result.lines) == 50
        assert result.lines[-1] == "line 199"
        assert result.total_lines == 50

    def test_file_not_found_returns_empty(self):
        """파일 미존재 시 빈 응답"""
        service = LogService.__new__(LogService)
        service.redis_client = MagicMock()
        with patch.object(service, "_find_current_log", return_value=None):
            result = service.tail_log_file("test_runner")

        assert result.lines == []
        assert result.total_lines == 0

    def test_file_path_doesnt_exist_returns_empty(self, tmp_path):
        """경로는 반환되지만 파일이 없는 경우"""
        missing = tmp_path / "missing.log"
        service = LogService.__new__(LogService)
        service.redis_client = MagicMock()
        with patch.object(service, "_find_current_log", return_value=missing):
            result = service.tail_log_file("test_runner")

        assert result.lines == []
        assert result.total_lines == 0

    def test_read_error_returns_error_message(self, tmp_path):
        """읽기 에러 시 에러 메시지 반환"""
        log_file = tmp_path / "test.log"
        log_file.write_text("some content", encoding="utf-8")

        service = LogService.__new__(LogService)
        service.redis_client = MagicMock()
        with patch.object(service, "_find_current_log", return_value=log_file), \
             patch("builtins.open", side_effect=PermissionError("Access denied")):
            result = service.tail_log_file("test_runner")

        assert result.total_lines == 1
        assert "Error reading log" in result.lines[0]

    def test_default_n_lines_is_100(self, tmp_path):
        """기본값 100줄"""
        log_file = tmp_path / "test.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(300)), encoding="utf-8")

        service = LogService.__new__(LogService)
        service.redis_client = MagicMock()
        with patch.object(service, "_find_current_log", return_value=log_file):
            result = service.tail_log_file("test_runner")

        assert len(result.lines) == 100


class TestLogServiceFindCurrentLog:
    """_find_current_log() 테스트"""

    def test_stream_log_path_priority(self, tmp_path):
        """stream_log_path 우선 탐색"""
        stream_log = tmp_path / "stream.log"
        stream_log.write_text("stream", encoding="utf-8")
        fallback_log = tmp_path / "fallback.log"
        fallback_log.write_text("fallback", encoding="utf-8")

        service = LogService.__new__(LogService)
        mock_redis = MagicMock()
        mock_redis.get.side_effect = lambda key: {
            "plan-runner:runners:test_runner:stream_log_path": str(stream_log),
            "plan-runner:runners:test_runner:log_file_path": str(fallback_log),
        }.get(key)
        service.redis_client = mock_redis

        result = service._find_current_log("test_runner")
        assert result == stream_log

    def test_fallback_to_log_file_path(self, tmp_path):
        """stream 없으면 log_file_path fallback"""
        fallback_log = tmp_path / "fallback.log"
        fallback_log.write_text("data", encoding="utf-8")

        service = LogService.__new__(LogService)
        mock_redis = MagicMock()
        mock_redis.get.side_effect = lambda key: {
            "plan-runner:runners:test_runner:stream_log_path": None,
            "plan-runner:runners:test_runner:log_file_path": str(fallback_log),
        }.get(key)
        service.redis_client = mock_redis

        result = service._find_current_log("test_runner")
        assert result == fallback_log

    def test_redis_connection_error_returns_none(self):
        """Redis 미연결 시 None"""
        service = LogService.__new__(LogService)
        mock_redis = MagicMock()
        mock_redis.get.side_effect = redis.ConnectionError("Connection refused")
        service.redis_client = mock_redis

        result = service._find_current_log("test_runner")
        assert result is None

    def test_both_paths_missing_returns_none(self):
        """두 경로 모두 None이면 None 반환"""
        service = LogService.__new__(LogService)
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        service.redis_client = mock_redis

        result = service._find_current_log("test_runner")
        assert result is None

    def test_path_exists_but_file_deleted(self, tmp_path):
        """경로가 반환되지만 실제 파일 없음"""
        service = LogService.__new__(LogService)
        mock_redis = MagicMock()
        mock_redis.get.side_effect = lambda key: {
            "plan-runner:runners:test_runner:stream_log_path": str(tmp_path / "gone.log"),
            "plan-runner:runners:test_runner:log_file_path": None,
        }.get(key)
        service.redis_client = mock_redis

        result = service._find_current_log("test_runner")
        assert result is None


# ========== RunState 테스트 ==========


class TestRunStateIsRunning:
    """RunState.is_running() 테스트"""

    def test_no_process_returns_false(self):
        """process=None → False"""
        state = RunState()
        assert state.is_running() is False

    def test_running_process_returns_true(self):
        """process.poll() == None → True (실행 중)"""
        state = RunState()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = None
        state.process = mock_proc
        assert state.is_running() is True

    def test_terminated_process_returns_false(self):
        """process.poll() == 0 → False (종료됨)"""
        state = RunState()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = 0
        state.process = mock_proc
        assert state.is_running() is False

    def test_crashed_process_returns_false(self):
        """process.poll() == 1 → False (비정상 종료)"""
        state = RunState()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = 1
        state.process = mock_proc
        assert state.is_running() is False


class TestRunStateReset:
    """RunState.reset() 테스트"""

    def test_reset_preserves_crash_info_on_error_exit(self):
        """비정상 종료 시 crash 정보 보존"""
        state = RunState()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = 1
        state.process = mock_proc
        state.pid = 12345
        state.plan_file = "test.md"

        state.reset()

        assert state.last_exit_code == 1
        assert state.last_crashed is True
        assert state.last_plan_file == "test.md"
        assert state.last_pid == 12345
        # 기본 필드는 초기화
        assert state.process is None
        assert state.pid is None
        assert state.plan_file is None

    def test_reset_normal_exit_not_crashed(self):
        """정상 종료 시 last_crashed=False"""
        state = RunState()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = 0
        state.process = mock_proc

        state.reset()

        assert state.last_exit_code == 0
        assert state.last_crashed is False

    def test_reset_no_process(self):
        """process=None 상태에서 reset"""
        state = RunState()
        state.reset()

        assert state.process is None
        assert state.last_exit_code is None
        assert state.last_crashed is False

    def test_reset_closes_log_file_handle(self):
        """로그 파일 핸들 닫기"""
        state = RunState()
        mock_handle = MagicMock()
        mock_handle.closed = False
        state.log_file_handle = mock_handle

        state.reset()

        mock_handle.close.assert_called_once()
        assert state.log_file_handle is None

    def test_reset_skips_already_closed_handle(self):
        """이미 닫힌 핸들은 close 호출 안 함"""
        state = RunState()
        mock_handle = MagicMock()
        mock_handle.closed = True
        state.log_file_handle = mock_handle

        state.reset()

        mock_handle.close.assert_not_called()

    def test_reset_clears_all_runtime_fields(self):
        """모든 런타임 필드 초기화"""
        state = RunState()
        state.pid = 999
        state.plan_file = "plan.md"
        state.current_cycle = 5
        state.options = {"key": "val"}
        state.log_file_path = "/some/path"

        state.reset()

        assert state.pid is None
        assert state.plan_file is None
        assert state.current_cycle == 0
        assert state.options == {}
        assert state.log_file_path is None


class TestRunStateClearCrashInfo:
    """RunState.clear_crash_info() 테스트"""

    def test_clears_all_crash_fields(self):
        """crash 정보 완전 초기화"""
        state = RunState()
        state.last_exit_code = 1
        state.last_crashed = True
        state.last_plan_file = "plan.md"
        state.last_pid = 999

        state.clear_crash_info()

        assert state.last_exit_code is None
        assert state.last_crashed is False
        assert state.last_plan_file is None
        assert state.last_pid is None
