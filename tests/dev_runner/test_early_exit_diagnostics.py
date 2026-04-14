"""T1 + T3: exit code 15 진단 강화 TC

Phase 1-3 구현 검증:
  T1-1  test__stream_output_early_exit_detection()
  T1-2  test__stream_output_zero_lines_diagnostics()
  T1-3  test__build_failure_error_message_zero_lines()
  T1-4  test_memory_precheck_reject()
  T1-5  test_memory_precheck_warning()
  T1-6  test_env_header_in_log()
  T1-7  test_stderr_separate_capture()

T3-1  test_subprocess_early_death_integration()
T3-2  test_memory_precheck_integration()
"""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import fakeredis
import pytest

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# noise 필터 stub
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False
sys.modules.setdefault("listener_noise_filter", _mock_noise)


# ── 공통 픽스처 ───────────────────────────────────────────────────────────────

@pytest.fixture
def fr():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


def _make_process(returncode: int = 0, stdout_text: str = "", stderr_text: str = ""):
    """subprocess.Popen 모의 객체 생성."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.pid = 12345
    # stdout: StringIO로 readline 모방
    proc.stdout = io.StringIO(stdout_text)
    proc.stderr = io.StringIO(stderr_text) if stderr_text else None
    proc.poll = MagicMock(return_value=returncode)
    proc.wait = MagicMock(return_value=returncode)
    return proc


class _CapturingLog:
    """_stream_output이 close()를 호출해도 내용을 읽을 수 있는 log mock."""

    def __init__(self):
        self._lines: list[str] = []
        self._closed = False

    def write(self, s):
        self._lines.append(s)

    def flush(self):
        pass

    def close(self):
        self._closed = True  # 닫히더라도 내용은 유지

    def tell(self):
        return sum(len(l) for l in self._lines)

    def getvalue(self) -> str:
        return "".join(self._lines)


def _run_stream_output(proc, fr, runner_id="t-diag-test", stderr_text="", exit_reason="error"):
    """_stream_output을 동기적으로 실행하고 log 내용을 반환."""
    import _dr_plan_runner as mod

    log_cap = _CapturingLog()
    stderr_handle = io.StringIO(stderr_text) if stderr_text else None

    # 상태 mock 패치
    with (
        patch.object(mod, "get_running_log_files", return_value={}),
        patch.object(mod, "get_wf_manager", return_value=None),
        patch.object(mod, "_cleanup_process_state"),
        patch.object(mod, "_resolve_stop_stage", return_value=None),
        patch.object(mod, "_normalize_exit_reason", return_value=exit_reason),
        patch.object(mod, "_pick_error_detail_line", return_value=None),
        patch.object(mod, "_load_log_tail_lines", return_value=[]),
    ):
        mod._stream_output(proc, log_cap, fr, runner_id, stderr_handle=stderr_handle)

    return log_cap.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
#  T1 Unit Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestEarlyExitDetection:
    """T1-1: 조기 사망 감지 — [EARLY_EXIT] 로그 기록 검증"""

    def test__stream_output_early_exit_detection(self, fr):
        """프로세스가 시작 즉시 종료(returncode=15, stdout 비어있을 때) [EARLY_EXIT] 로그가 기록되는지 검증."""
        proc = _make_process(returncode=15, stdout_text="")
        # poll()이 즉시 15를 반환하여 진입 즉시 감지
        proc.poll = MagicMock(return_value=15)

        log_content = _run_stream_output(proc, fr, runner_id="t-early-1")

        assert "[EARLY_EXIT]" in log_content, (
            f"[EARLY_EXIT] 메시지가 로그에 없음:\n{log_content[:500]}"
        )
        assert "exit_code=15" in log_content, (
            f"exit_code=15 정보가 [EARLY_EXIT] 메시지에 없음:\n{log_content[:500]}"
        )

    def test__stream_output_early_exit_redis_publish(self, fr):
        """[EARLY_EXIT] 메시지가 Redis log 채널에도 publish되는지 검증."""
        import _dr_plan_runner as mod

        runner_id = "t-early-redis"
        log_cap = _CapturingLog()
        proc2 = _make_process(returncode=15, stdout_text="")
        proc2.poll = MagicMock(return_value=15)
        published = []

        def _fake_publish(rclient, channel, msg):
            published.append((channel, msg))
            return True

        with (
            patch.object(mod, "get_running_log_files", return_value={}),
            patch.object(mod, "get_wf_manager", return_value=None),
            patch.object(mod, "_cleanup_process_state"),
            patch.object(mod, "_resolve_stop_stage", return_value=None),
            patch.object(mod, "_normalize_exit_reason", return_value="error"),
            patch.object(mod, "_pick_error_detail_line", return_value=None),
            patch.object(mod, "_load_log_tail_lines", return_value=[]),
            patch.object(mod, "_publish_with_retry", side_effect=_fake_publish),
        ):
            mod._stream_output(proc2, log_cap, fr, runner_id, stderr_handle=None)

        early_publishes = [m for _, m in published if "[EARLY_EXIT]" in m]
        assert early_publishes, f"[EARLY_EXIT] Redis publish 없음. published={published[:5]}"


class TestZeroLinesDiagnostics:
    """T1-2: lines=0 + exit_code != 0 시 [DIAG] 진단 로그 기록 검증"""

    def test__stream_output_zero_lines_diagnostics(self, fr):
        """lines=0 + exit_code != 0일 때 finally 블록에서 [DIAG] prefix 진단 정보가 기록되는지."""
        proc = _make_process(returncode=15, stdout_text="")
        proc.poll = MagicMock(return_value=None)  # 초기 poll은 None (조기종료 미감지)

        content = _run_stream_output(proc, fr, runner_id="t-diag-2")

        assert "[DIAG]" in content, f"[DIAG] 메시지가 로그에 없음:\n{content[:600]}"
        assert "lines=0" in content, f"lines=0 정보가 [DIAG]에 없음:\n{content[:600]}"
        assert "exit_code=15" in content, f"exit_code 정보가 없음:\n{content[:600]}"
        assert "mem_available=" in content or "mem_check_failed" in content, (
            f"메모리 정보가 [DIAG]에 없음:\n{content[:600]}"
        )

    def test__stream_output_zero_lines_no_diag_on_success(self, fr):
        """exit_code=0이면 lines=0이어도 [DIAG]를 기록하지 않아야 함."""
        proc = _make_process(returncode=0, stdout_text="")
        proc.poll = MagicMock(return_value=None)

        content = _run_stream_output(proc, fr, runner_id="t-diag-success", exit_reason="completed")

        assert "[DIAG]" not in content, f"exit_code=0인데 [DIAG] 기록됨:\n{content[:400]}"


class TestBuildFailureErrorMessage:
    """T1-3: _build_failure_error_message lines_count=0 시 "subprocess 즉시 종료" 포함 검증"""

    def test__build_failure_error_message_zero_lines(self):
        """lines_count=0 전달 시 "subprocess 즉시 종료" 문구 포함 메시지 생성."""
        from _dr_plan_runner import _build_failure_error_message

        msg = _build_failure_error_message(
            exit_code=15,
            exit_reason="error",
            stop_stage=None,
            detail=None,
            lines_count=0,
        )
        assert "subprocess 즉시 종료" in msg, f"즉시 종료 문구 없음: {msg}"
        assert "15" in msg, f"exit_code 없음: {msg}"

    def test__build_failure_error_message_normal_lines(self):
        """lines_count > 0이면 "subprocess 즉시 종료" 문구가 없어야 함."""
        from _dr_plan_runner import _build_failure_error_message

        msg = _build_failure_error_message(
            exit_code=1,
            exit_reason="error",
            stop_stage=None,
            detail="some error",
            lines_count=7,
        )
        assert "subprocess 즉시 종료" not in msg, f"lines_count=7인데 즉시종료 문구 존재: {msg}"

    def test__build_failure_error_message_cleanup_version_zero_lines(self):
        """_dr_stream_cleanup.py의 함수도 동일하게 동작 확인."""
        from _dr_stream_cleanup import _build_failure_error_message as _cleanup_fn

        msg = _cleanup_fn(
            exit_code=15,
            exit_reason="error",
            stop_stage=None,
            detail=None,
            lines_count=0,
        )
        assert "subprocess 즉시 종료" in msg, f"_dr_stream_cleanup 즉시 종료 문구 없음: {msg}"


class TestMemoryPrecheck:
    """T1-4, T1-5: _launch_plan_runner_process() 메모리 사전 검증"""

    def _make_command(self, runner_id="t-mem-test"):
        return {
            "runner_id": runner_id,
            "trigger": "test",
            "engine": "claude",
            "fix_engine": "claude",
            "started_at": "2026-01-01T00:00:00",
            "execution_count": 1,
            "plan_key": "test.md",
        }

    def test_memory_precheck_reject(self, fr, tmp_path):
        """가용 메모리 300MB 미만일 때 _launch_plan_runner_process()가 success=False 반환."""
        import _dr_plan_runner as mod

        _vmem_mock = MagicMock()
        _vmem_mock.available = 200 * 1024 * 1024  # 200MB < 300MB

        _mock_log = _CapturingLog()

        with (
            patch.object(mod.psutil, "virtual_memory", return_value=_vmem_mock),
            patch.object(mod, "get_running_processes", return_value={}),
            patch.object(mod, "get_running_log_files", return_value={}),
            patch.object(mod, "get_stream_threads", return_value={}),
            patch("builtins.open", return_value=_mock_log),
        ):
            result = mod._launch_plan_runner_process(
                command=self._make_command(),
                redis_client=fr,
                runner_id="t-mem-reject",
                worktree_path=tmp_path,
                plan_file="test.md",
                engine="claude",
            )

        assert result["success"] is False, f"메모리 부족 시 success=True 반환: {result}"
        assert "메모리 부족" in result.get("message", ""), f"거부 메시지 없음: {result}"

    def test_memory_precheck_warning(self, fr, tmp_path):
        """가용 메모리 400MB (<500MB)일 때 warning 로그 기록되지만 실행은 계속 (Popen 호출됨)."""
        import _dr_plan_runner as mod

        _vmem_mock = MagicMock()
        _vmem_mock.available = 400 * 1024 * 1024  # 400MB (< 500MB)
        _vmem_mock.total = 8 * 1024 * 1024 * 1024

        _mock_proc = _make_process(returncode=0)
        _mock_log = _CapturingLog()
        _popen_called = []

        def _fake_popen(*args, **kwargs):
            _popen_called.append(True)
            return _mock_proc

        with (
            patch.object(mod.psutil, "virtual_memory", return_value=_vmem_mock),
            patch.object(mod, "get_running_processes", return_value={}),
            patch.object(mod, "get_running_log_files", return_value={}),
            patch.object(mod, "get_stream_threads", return_value={}),
            patch("builtins.open", return_value=_mock_log),
            patch.object(mod.subprocess, "Popen", side_effect=_fake_popen),
            patch.object(mod.threading, "Thread") as _mock_thread,
        ):
            _mock_thread.return_value.start = MagicMock()
            result = mod._launch_plan_runner_process(
                command=self._make_command("t-mem-warn"),
                redis_client=fr,
                runner_id="t-mem-warn",
                worktree_path=tmp_path,
                plan_file="test.md",
                engine="claude",
            )

        # warning 로그가 기록됐는지 확인
        all_written = _mock_log.getvalue()
        assert "[WARN]" in all_written or "낮음" in all_written, (
            f"메모리 warning 로그 없음:\n{all_written[:500]}"
        )
        # 실행은 계속 — Popen 호출됨
        assert _popen_called, "400MB인데 Popen이 호출되지 않음 (실행 차단됨)"


class TestEnvHeaderInLog:
    """T1-6: [ENV] 헤더가 TRIGGER/RUN_META 직후 로그에 기록되는지 검증"""

    def test_env_header_in_log(self, fr, tmp_path):
        """TRIGGER/RUN_META 직후 [ENV] 줄이 로그에 기록되는지 검증."""
        import _dr_plan_runner as mod

        _vmem_mock = MagicMock()
        _vmem_mock.available = 4 * 1024 * 1024 * 1024  # 4GB (정상)
        _vmem_mock.total = 16 * 1024 * 1024 * 1024

        _mock_proc = _make_process(returncode=0)
        _mock_log = _CapturingLog()

        with (
            patch.object(mod.psutil, "virtual_memory", return_value=_vmem_mock),
            patch.object(mod, "get_running_processes", return_value={}),
            patch.object(mod, "get_running_log_files", return_value={}),
            patch.object(mod, "get_stream_threads", return_value={}),
            patch("builtins.open", return_value=_mock_log),
            patch.object(mod.subprocess, "Popen", return_value=_mock_proc),
            patch.object(mod.threading, "Thread") as _mt,
        ):
            _mt.return_value.start = MagicMock()
            mod._launch_plan_runner_process(
                command={
                    "runner_id": "t-env-hdr",
                    "trigger": "test",
                    "engine": "claude",
                    "fix_engine": "claude",
                    "started_at": "2026-01-01T00:00:00",
                    "execution_count": 1,
                    "plan_key": "test.md",
                },
                redis_client=fr,
                runner_id="t-env-hdr",
                worktree_path=tmp_path,
                plan_file="test.md",
                engine="claude",
            )

        all_written = _mock_log.getvalue()
        assert "[ENV]" in all_written, f"[ENV] 헤더가 로그에 없음:\n{all_written[:600]}"
        assert "available_memory=" in all_written, f"available_memory 정보 없음:\n{all_written[:600]}"
        assert "total_memory=" in all_written, f"total_memory 정보 없음:\n{all_written[:600]}"
        assert "python=" in all_written, f"python 경로 정보 없음:\n{all_written[:600]}"


class TestStderrSeparateCapture:
    """T1-7: stderr 별도 파이프 캡처 — [STDERR] prefix로 log_handle 기록 검증"""

    def test_stderr_separate_capture(self, fr):
        """subprocess가 stderr에만 에러 출력 시 [STDERR] prefix로 log_handle에 기록되는지."""
        proc = _make_process(returncode=1, stdout_text="")
        proc.poll = MagicMock(return_value=None)

        content = _run_stream_output(
            proc, fr, runner_id="t-stderr-1",
            stderr_text="ImportError: No module named 'foo'\n",
        )
        assert "[STDERR]" in content, f"[STDERR] 기록 없음:\n{content[:600]}"
        assert "ImportError" in content, f"stderr 내용이 기록 안 됨:\n{content[:600]}"

    def test_stderr_none_no_error(self, fr):
        """stderr_handle=None이면 [STDERR] 관련 처리가 없어도 정상 동작."""
        proc = _make_process(returncode=0, stdout_text="done\n")
        proc.poll = MagicMock(return_value=None)

        content = _run_stream_output(proc, fr, runner_id="t-stderr-none", exit_reason="completed")
        # 오류 없이 완료되면 충분 — [STDERR]는 없어야 함
        assert "[STDERR]" not in content, f"stderr_handle=None인데 [STDERR] 기록됨:\n{content[:400]}"


# ═════════════════════════════════════════════════════════════════════════════
#  T3 Integration Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestSubprocessEarlyDeathIntegration:
    """T3-1: 실제 subprocess를 spawn하여 [EARLY_EXIT] + [DIAG] 통합 검증"""

    def test_subprocess_early_death_integration(self, fr):
        """실제 subprocess(`python -c "import sys; sys.exit(15)"`)를 spawn하여
        _stream_output()이 [EARLY_EXIT] + [DIAG] 진단 로그를 올바르게 생성하는지 통합 검증 (mock 없이 실제 프로세스).
        """
        import _dr_plan_runner as mod

        runner_id = "t-int-early"
        log_cap = _CapturingLog()

        # 실제 subprocess — sys.exit(15)로 즉시 종료
        real_proc = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.exit(15)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        with (
            patch.object(mod, "get_running_log_files", return_value={}),
            patch.object(mod, "get_wf_manager", return_value=None),
            patch.object(mod, "_cleanup_process_state"),
            patch.object(mod, "_resolve_stop_stage", return_value=None),
            patch.object(mod, "_normalize_exit_reason", return_value="error"),
            patch.object(mod, "_pick_error_detail_line", return_value=None),
            patch.object(mod, "_load_log_tail_lines", return_value=[]),
        ):
            mod._stream_output(
                real_proc, log_cap, fr, runner_id,
                stderr_handle=real_proc.stderr,
            )

        content = log_cap.getvalue()

        # exit code 15 프로세스이므로 [EARLY_EXIT] 또는 [DIAG] 중 하나 이상 있어야 함
        has_early = "[EARLY_EXIT]" in content
        has_diag = "[DIAG]" in content
        assert has_early or has_diag, (
            f"exit(15) 프로세스인데 [EARLY_EXIT]도 [DIAG]도 없음:\n{content[:800]}"
        )
        assert "15" in content, f"exit_code=15 정보 없음:\n{content[:400]}"


class TestMemoryPrecheckIntegration:
    """T3-2: psutil mock 없이 실제 메모리 상태에서 메모리 검증 로직 동작 확인"""

    def test_memory_precheck_integration(self, fr, tmp_path):
        """현재 시스템 메모리가 충분하므로 warning/reject 없이 정상 진행되는지 확인.

        실제 psutil.virtual_memory() 사용 — mock 없음.
        현재 시스템이 정상적으로 동작 중이므로 메모리가 300MB 이상이어야 함.
        """
        import psutil
        import _dr_plan_runner as mod

        vmem = psutil.virtual_memory()
        avail_mb = vmem.available // (1024 * 1024)

        if avail_mb < 300:
            pytest.skip(f"시스템 가용 메모리 {avail_mb}MB < 300MB — 테스트 환경에서 reject 경로 실행됨 (skip)")

        _mock_proc = _make_process(returncode=0)
        _mock_log = _CapturingLog()

        with (
            patch.object(mod, "get_running_processes", return_value={}),
            patch.object(mod, "get_running_log_files", return_value={}),
            patch.object(mod, "get_stream_threads", return_value={}),
            patch("builtins.open", return_value=_mock_log),
            patch.object(mod.subprocess, "Popen", return_value=_mock_proc),
            patch.object(mod.threading, "Thread") as _mt,
        ):
            _mt.return_value.start = MagicMock()
            result = mod._launch_plan_runner_process(
                command={
                    "runner_id": "t-int-mem",
                    "trigger": "test",
                    "engine": "claude",
                    "fix_engine": "claude",
                    "started_at": "2026-01-01T00:00:00",
                    "execution_count": 1,
                    "plan_key": "test.md",
                },
                redis_client=fr,
                runner_id="t-int-mem",
                worktree_path=tmp_path,
                plan_file="test.md",
                engine="claude",
            )

        # 메모리가 충분하면 reject 없이 성공
        assert result.get("success") is True, (
            f"메모리 충분({avail_mb}MB)한데 실행 거부: {result}"
        )

        # [ENV] 헤더가 기록되는지도 확인 (실제 psutil 사용)
        all_written = _mock_log.getvalue()
        assert "[ENV]" in all_written, f"[ENV] 헤더 없음:\n{all_written[:400]}"
        assert "available_memory=" in all_written, (
            f"[ENV] 헤더에 available_memory 없음:\n{all_written[:400]}"
        )
