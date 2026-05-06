"""test_stream_output_pump.py — _dr_stream_output._stream_output 단위 테스트

검증 범위:
- readline 루프: stdout 라인이 log_handle에 기록되고 Redis에 publish되는지
- 노이즈 필터: is_noise_line=True인 라인이 publish 억제되는지
- rate-limiter: 동일 라인 BURST_LIMIT 초과 시 억제되는지
- 모듈 분리 검증: _stream_output이 _dr_stream_output에서 import 가능한지
"""
from __future__ import annotations

import io
import subprocess
import sys
import threading
import types
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import fakeredis
import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


class _NoCloseBuf(io.StringIO):
    """_stream_output의 close() 호출 후에도 getvalue()를 유지하는 버퍼."""
    def close(self):
        pass  # 실제 close 방지 — getvalue() 계속 사용 가능
    def tell(self):
        try:
            return super().tell()
        except Exception:
            return 0
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# noise 필터 모킹 — 테스트 코드에서 직접 제어하기 위해 sys.modules에 등록
_noise_mod = types.ModuleType("listener_noise_filter")
_noise_mod.NOISE_BLOCK_MARKERS = []
_noise_mod.is_noise_line = lambda line: False
sys.modules.setdefault("listener_noise_filter", _noise_mod)


# ---------------------------------------------------------------------------
# 모듈 분리 import 검증
# ---------------------------------------------------------------------------

class TestModuleSeparation:
    def test_R_stream_output_importable_from_dr_stream_output(self):
        """_dr_stream_output에서 _stream_output 직접 import 가능해야 한다."""
        from _dr_stream_output import _stream_output
        assert callable(_stream_output)

    def test_R_stream_output_importable_from_dr_plan_runner(self):
        """하위 호환: _dr_plan_runner 파사드에서도 import 가능해야 한다."""
        from _dr_plan_runner import _stream_output
        assert callable(_stream_output)

    def test_B_runner_control_importable(self):
        """lifecycle 함수가 _dr_runner_control에서 import 가능해야 한다."""
        from _dr_runner_control import (
            start_plan_runner, stop_plan_runner, get_status,
            force_stop_plan_runner, force_kill_plan_runner,
        )
        for fn in (start_plan_runner, stop_plan_runner, get_status,
                   force_stop_plan_runner, force_kill_plan_runner):
            assert callable(fn)

    def test_B_do_inline_merge_importable_from_stream_cleanup(self):
        """_do_inline_merge의 정의 위치가 _dr_stream_cleanup이어야 한다."""
        from _dr_stream_cleanup import _do_inline_merge
        assert callable(_do_inline_merge)


# ---------------------------------------------------------------------------
# _stream_output 행동 테스트
# ---------------------------------------------------------------------------

def _make_fake_process(lines: list[str], exit_code: int = 0):
    """지정된 라인을 출력하는 가짜 subprocess.Popen 객체 생성."""
    content = "".join(f"{line}\n" for line in lines)
    proc = MagicMock(spec=subprocess.Popen)
    proc.stdout = io.StringIO(content)
    proc.stderr = None
    proc.returncode = exit_code
    proc.poll.return_value = None  # 초기 poll은 None (실행 중)
    proc.wait.return_value = exit_code
    proc.pid = 12345
    return proc


class TestStreamOutputReadlineLoop:
    def test_R_lines_written_to_log_handle(self):
        """stdout 라인이 log_handle에 기록되어야 한다."""
        from _dr_stream_output import _stream_output

        lines = ["hello world", "second line"]
        proc = _make_fake_process(lines)
        log_buf = _NoCloseBuf()
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        with patch("_dr_stream_output._resolve_exit_status"), \
             patch("_dr_stream_output._drain_stdout_log", return_value=[]), \
             patch("_dr_stream_output._process_error_details"), \
             patch("_dr_stream_output._determine_merge_requested", return_value=False), \
             patch("_dr_stream_output._update_workflow_and_execute_cleanup"):
            _stream_output(proc, log_buf, redis_client, runner_id="test-r1")

        log_content = log_buf.getvalue()
        assert "hello world" in log_content
        assert "second line" in log_content

    def test_R_lines_published_to_redis(self):
        """stdout 라인이 Redis log 채널에 publish되어야 한다."""
        from _dr_stream_output import _stream_output

        lines = ["published line"]
        proc = _make_fake_process(lines)
        log_buf = _NoCloseBuf()
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        published = []

        original_publish = redis_client.publish
        def capture_publish(channel, message):
            published.append((channel, message))
            return original_publish(channel, message)

        redis_client.publish = capture_publish

        with patch("_dr_stream_output._resolve_exit_status"), \
             patch("_dr_stream_output._drain_stdout_log", return_value=[]), \
             patch("_dr_stream_output._process_error_details"), \
             patch("_dr_stream_output._determine_merge_requested", return_value=False), \
             patch("_dr_stream_output._update_workflow_and_execute_cleanup"):
            _stream_output(proc, log_buf, redis_client, runner_id="test-r2")

        channels = [ch for ch, _ in published]
        assert any("test-r2" in ch for ch in channels), f"runner_id not in channels: {channels}"

    def test_B_empty_stdout_completes_without_error(self):
        """빈 stdout에서도 정상 종료되어야 한다."""
        from _dr_stream_output import _stream_output

        proc = _make_fake_process([])
        log_buf = _NoCloseBuf()
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        with patch("_dr_stream_output._resolve_exit_status"), \
             patch("_dr_stream_output._drain_stdout_log", return_value=[]), \
             patch("_dr_stream_output._process_error_details"), \
             patch("_dr_stream_output._determine_merge_requested", return_value=False), \
             patch("_dr_stream_output._update_workflow_and_execute_cleanup"):
            _stream_output(proc, log_buf, redis_client)  # runner_id 없이도 동작


class TestStreamOutputNoiseFilter:
    def test_R_noise_line_not_published(self):
        """is_noise_line=True 라인은 publish 억제되어야 한다."""
        from _dr_stream_output import _stream_output
        import _dr_stream_output as smod

        lines = ["normal line", "xterm.js: Parsing error"]
        proc = _make_fake_process(lines)
        log_buf = _NoCloseBuf()
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        published_msgs = []
        original_publish = redis_client.publish
        def capture(ch, msg):
            published_msgs.append(msg)
            return original_publish(ch, msg)
        redis_client.publish = capture

        # noise 필터: "Parsing error" 포함 시 억제
        def _noise(line): return "Parsing error" in line

        with patch.object(smod, "_is_noise_line", _noise), \
             patch("_dr_stream_output._resolve_exit_status"), \
             patch("_dr_stream_output._drain_stdout_log", return_value=[]), \
             patch("_dr_stream_output._process_error_details"), \
             patch("_dr_stream_output._determine_merge_requested", return_value=False), \
             patch("_dr_stream_output._update_workflow_and_execute_cleanup"):
            _stream_output(proc, log_buf, redis_client, runner_id="noise-test")

        # "Parsing error" 포함 메시지가 publish되면 안 됨
        assert not any("Parsing error" in m for m in published_msgs), \
            f"Noise line was published: {published_msgs}"

    def test_B_noise_line_still_written_to_log(self):
        """억제된 노이즈 라인은 log_handle에는 기록되어야 한다."""
        from _dr_stream_output import _stream_output
        import _dr_stream_output as smod

        lines = ["xterm.js: Parsing error block"]
        proc = _make_fake_process(lines)
        log_buf = _NoCloseBuf()
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        def _noise(line): return "Parsing error" in line

        with patch.object(smod, "_is_noise_line", _noise), \
             patch("_dr_stream_output._resolve_exit_status"), \
             patch("_dr_stream_output._drain_stdout_log", return_value=[]), \
             patch("_dr_stream_output._process_error_details"), \
             patch("_dr_stream_output._determine_merge_requested", return_value=False), \
             patch("_dr_stream_output._update_workflow_and_execute_cleanup"):
            _stream_output(proc, log_buf, redis_client, runner_id="noise-log-test")

        assert "Parsing error" in log_buf.getvalue()


class TestStreamOutputRateLimiter:
    def test_R_burst_limit_suppresses_repeated_lines(self):
        """동일 라인이 BURST_LIMIT(10)초과 반복 시 publish 억제되어야 한다."""
        from _dr_stream_output import _stream_output

        # 동일 라인을 15번 반복
        repeated_line = "same line repeated"
        lines = [repeated_line] * 15
        proc = _make_fake_process(lines)
        log_buf = _NoCloseBuf()
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        published_msgs = []
        original_publish = redis_client.publish
        def capture(ch, msg):
            published_msgs.append(msg)
            return original_publish(ch, msg)
        redis_client.publish = capture

        with patch("_dr_stream_output._resolve_exit_status"), \
             patch("_dr_stream_output._drain_stdout_log", return_value=[]), \
             patch("_dr_stream_output._process_error_details"), \
             patch("_dr_stream_output._determine_merge_requested", return_value=False), \
             patch("_dr_stream_output._update_workflow_and_execute_cleanup"):
            _stream_output(proc, log_buf, redis_client, runner_id="rate-test")

        # 15번 중 최대 10번만 publish (BURST_LIMIT 초과분 억제)
        same_line_count = sum(1 for m in published_msgs if repeated_line in m)
        assert same_line_count <= 10, \
            f"Rate limiter 미작동: {same_line_count}번 publish (기대: ≤10)"
