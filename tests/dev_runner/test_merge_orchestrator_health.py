"""MergeOrchestrator subprocess 생존 확인 및 health check 유닛 테스트"""
import importlib.util
import time
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
import fakeredis
import logging

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

# 하이픈 파일명이라 importlib 사용
_spec = importlib.util.spec_from_file_location(
    "dev_runner_command_listener",
    Path(__file__).parent.parent.parent / "scripts" / "dev-runner-command-listener.py",
)
mod = importlib.util.module_from_spec(_spec)
sys.modules["dev_runner_command_listener"] = mod
_spec.loader.exec_module(mod)


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def reset_globals():
    """각 테스트 전 전역 변수 초기화"""
    mod._merge_orchestrator_process = None
    mod._merge_orchestrator_log_path = None
    yield
    mod._merge_orchestrator_process = None
    mod._merge_orchestrator_log_path = None


# ── start_merge_orchestrator: 생존 확인 ──────────────────────────────────────

@pytest.mark.skip(reason="Deprecated: merge is now handled inline — 테스트 불필요")
class TestStartMergeOrchestratorSurvival:
    @patch("dev_runner_command_listener.subprocess.Popen")
    @patch("dev_runner_command_listener.time.sleep")
    def test_right_survival_check_success(self, mock_sleep, mock_popen, fake_redis, tmp_path):
        """R(Right): 정상 시작 시 2초 후 poll()=None → success=True"""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # 살아있음
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        import dev_runner_command_listener as mod  # noqa: F811 — uses global mod
        with patch.object(mod, "PROJECT_ROOT", tmp_path), \
             patch.object(mod, "PLAN_RUNNER_PYTHON", Path("python.exe")), \
             patch.object(mod, "PLAN_RUNNER_MODULE_PATH", tmp_path):
            (tmp_path / "logs" / "admin").mkdir(parents=True, exist_ok=True)
            result = mod.start_merge_orchestrator(fake_redis)

        assert result["success"] is True
        assert "12345" in result["message"]
        mock_sleep.assert_called_once_with(2)
        assert mock_proc.poll.call_count >= 1

    @patch("dev_runner_command_listener.subprocess.Popen")
    @patch("dev_runner_command_listener.time.sleep")
    def test_error_immediate_crash(self, mock_sleep, mock_popen, fake_redis, tmp_path):
        """E(Error): 프로세스 즉시 종료 → success=False + 에러 메시지 포함"""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # 즉시 종료
        mock_proc.pid = 99999
        mock_popen.return_value = mock_proc

        import dev_runner_command_listener as mod  # noqa: F811 — uses global mod
        with patch.object(mod, "PROJECT_ROOT", tmp_path), \
             patch.object(mod, "PLAN_RUNNER_PYTHON", Path("python.exe")), \
             patch.object(mod, "PLAN_RUNNER_MODULE_PATH", tmp_path):
            logs_dir = tmp_path / "logs" / "admin"
            logs_dir.mkdir(parents=True, exist_ok=True)
            # open()이 실제 파일 생성하므로 log_path에 에러 내용 직접 기록
            with patch("builtins.open", MagicMock()):
                # log_path.read_text 모킹
                with patch.object(Path, "read_text", return_value="ImportError: no module named foo"):
                    result = mod.start_merge_orchestrator(fake_redis)

        assert result["success"] is False
        assert "exit code: 1" in result["message"]
        assert mod._merge_orchestrator_process is None

    @patch("dev_runner_command_listener.subprocess.Popen")
    @patch("dev_runner_command_listener.time.sleep")
    def test_right_unbuffered_env(self, mock_sleep, mock_popen, fake_redis, tmp_path):
        """R(Right): Popen env에 PYTHONUNBUFFERED=1 포함"""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 11111
        mock_popen.return_value = mock_proc

        import dev_runner_command_listener as mod  # noqa: F811 — uses global mod
        with patch.object(mod, "PROJECT_ROOT", tmp_path), \
             patch.object(mod, "PLAN_RUNNER_PYTHON", Path("python.exe")), \
             patch.object(mod, "PLAN_RUNNER_MODULE_PATH", tmp_path):
            (tmp_path / "logs" / "admin").mkdir(parents=True, exist_ok=True)
            mod.start_merge_orchestrator(fake_redis)

        call_kwargs = mock_popen.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert env["PYTHONUNBUFFERED"] == "1"


# ── heartbeat: Orchestrator health check ─────────────────────────────────────

@pytest.mark.skip(reason="Deprecated: merge is now handled inline — 테스트 불필요")
class TestHeartbeatOrchestratorCheck:
    def test_right_detects_dead_orchestrator(self, caplog):
        """R(Right): 죽은 orchestrator 감지 → warning 로그 + 전역 None"""
        import dev_runner_command_listener as mod  # noqa: F811 — uses global mod

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1
        mod._merge_orchestrator_process = mock_proc

        log_path = MagicMock()
        log_path.exists.return_value = True
        log_path.read_text.return_value = "line1\nline2\nERROR: something broke"
        mod._merge_orchestrator_log_path = log_path

        # heartbeat 체크 로직 직접 실행
        with caplog.at_level(logging.WARNING):
            if mod._merge_orchestrator_process and mod._merge_orchestrator_process.poll() is not None:
                rc = mod._merge_orchestrator_process.returncode
                mod.logger.warning(f"[MergeOrch] 비정상 종료 감지 (exit code: {rc})")
                if mod._merge_orchestrator_log_path and mod._merge_orchestrator_log_path.exists():
                    lines = mod._merge_orchestrator_log_path.read_text(encoding="utf-8").strip().splitlines()
                    tail = lines[-5:] if len(lines) > 5 else lines
                    if tail:
                        mod.logger.warning(f"[MergeOrch] 마지막 로그:\n" + "\n".join(tail))
                mod._merge_orchestrator_process = None

        assert mod._merge_orchestrator_process is None
        assert any("[MergeOrch] 비정상 종료" in r.message for r in caplog.records)

    def test_boundary_healthy_orchestrator_no_warning(self, caplog):
        """B(Boundary): 살아있는 orchestrator → warning 미발생"""
        import dev_runner_command_listener as mod  # noqa: F811 — uses global mod

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # 살아있음
        mod._merge_orchestrator_process = mock_proc

        with caplog.at_level(logging.WARNING):
            if mod._merge_orchestrator_process and mod._merge_orchestrator_process.poll() is not None:
                mod.logger.warning("[MergeOrch] 비정상 종료")
                mod._merge_orchestrator_process = None

        assert mod._merge_orchestrator_process is not None
        assert not any("[MergeOrch]" in r.message for r in caplog.records)
