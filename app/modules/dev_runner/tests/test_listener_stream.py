"""dev-runner-command-listener의 _stream_output 테스트"""

import threading
from io import StringIO
from unittest.mock import MagicMock

import pytest


def _stream_output_fn(process, log_handle, redis_client):
    """테스트용 _stream_output 복제 (listener.py에서 추출)"""
    LOG_CHANNEL = "plan-runner:logs"
    try:
        for line in process.stdout:
            stripped = line.rstrip('\n')
            log_handle.write(line)
            log_handle.flush()
            try:
                redis_client.publish(LOG_CHANNEL, stripped)
            except Exception:
                pass
    except Exception:
        pass


class FakeProcess:
    """stdout을 시뮬레이션하는 가짜 프로세스"""

    def __init__(self, lines: list[str]):
        self.stdout = iter(lines)


class TestStreamOutput:
    def test_publishes_parsed_log_lines(self):
        """[TAG] msg 형태 라인이 Redis에 publish되는지 확인"""
        lines = [
            "[10:30:00] [AI] 구현을 시작합니다\n",
            "[10:30:01] [TOOL] Edit\n",
            "[10:30:05] [DONE] claude-opus-4-6 | out:3879 in:11 | 122s\n",
        ]
        process = FakeProcess(lines)
        log_handle = StringIO()
        redis_client = MagicMock()

        _stream_output_fn(process, log_handle, redis_client)

        assert redis_client.publish.call_count == 3
        calls = [c.args[1] for c in redis_client.publish.call_args_list]
        assert "[AI] 구현을 시작합니다" in calls[0]
        assert "[TOOL] Edit" in calls[1]
        assert "[DONE]" in calls[2]
        assert "out:3879" in calls[2]

    def test_writes_to_log_file(self):
        """로그 파일에도 기록되는지 확인"""
        lines = ["[10:30:00] [AI] test\n"]
        process = FakeProcess(lines)
        log_handle = StringIO()
        redis_client = MagicMock()

        _stream_output_fn(process, log_handle, redis_client)

        log_handle.seek(0)
        content = log_handle.read()
        assert "[AI] test" in content

    def test_continues_on_redis_error(self):
        """Redis 에러 시에도 로그 파일 기록 계속"""
        lines = [
            "[10:30:00] [AI] line1\n",
            "[10:30:01] [AI] line2\n",
        ]
        process = FakeProcess(lines)
        log_handle = StringIO()
        redis_client = MagicMock()
        redis_client.publish.side_effect = ConnectionError("Redis down")

        _stream_output_fn(process, log_handle, redis_client)

        log_handle.seek(0)
        content = log_handle.read()
        assert "line1" in content
        assert "line2" in content

    def test_stderr_tag_published(self):
        """[STDERR] 태그 라인도 정상 publish"""
        lines = ["[10:30:00] [STDERR] API key invalid\n"]
        process = FakeProcess(lines)
        log_handle = StringIO()
        redis_client = MagicMock()

        _stream_output_fn(process, log_handle, redis_client)

        assert redis_client.publish.call_count == 1
        assert "[STDERR]" in redis_client.publish.call_args.args[1]

    def test_warn_tag_published(self):
        """[WARN] 태그 라인도 정상 publish"""
        lines = ["[10:30:00] [WARN] out:0 in:0 감지\n"]
        process = FakeProcess(lines)
        log_handle = StringIO()
        redis_client = MagicMock()

        _stream_output_fn(process, log_handle, redis_client)

        assert redis_client.publish.call_count == 1
        assert "[WARN]" in redis_client.publish.call_args.args[1]


# ── drain 위치 추적 TC (Phase 3 fix) ─────────────────────────────────────────

import io
import re as _re

_ANSI_ESCAPE = _re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

LOG_CHANNEL = "plan-runner:logs:runner-1"


def _run_drain_logic(log_file_path: str, last_flushed_pos: int, redis_client) -> None:
    """_stream_output finally의 stdout drain 로직 복제 (Phase 3 fix)"""
    runner_id = "runner-1"
    log_channel = LOG_CHANNEL
    try:
        with open(log_file_path, "r", encoding="utf-8", errors="replace") as _drain_f:
            _drain_f.seek(0, 2)
            end_pos = _drain_f.tell()
            if last_flushed_pos >= end_pos:
                pass  # 이미 모두 발행됨 → skip
            else:
                start_pos = max(last_flushed_pos, end_pos - 8192)
                _drain_f.seek(start_pos)
                tail_lines = _drain_f.readlines()
                for _tail_line in tail_lines[-50:]:
                    _stripped = _tail_line.rstrip('\n')
                    if _stripped:
                        try:
                            redis_client.publish(log_channel, _ANSI_ESCAPE.sub('', _stripped))
                        except Exception:
                            pass
    except Exception:
        pass


class TestDrainPositionTracking:
    """Phase 3 fix: stdout drain 중복 발행 방지 (_last_flushed_pos 기반) TC"""

    def _make_log_file(self, tmp_path, lines: list[str]) -> str:
        """임시 로그 파일 생성 후 경로 반환"""
        p = tmp_path / "test.log"
        p.write_text("".join(lines), encoding="utf-8")
        return str(p)

    def test_drain_skips_when_last_pos_at_end(self, tmp_path):
        """R: _last_flushed_pos == end_pos → publish 0건 (전체 skip)"""
        content = "line1\nline2\nline3\n"
        log_path = self._make_log_file(tmp_path, [content])
        # 실제 파일 크기를 end_pos로 사용 (Windows \r\n 대응)
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            end_pos = f.tell()

        redis_client = MagicMock()
        _run_drain_logic(log_path, last_flushed_pos=end_pos, redis_client=redis_client)

        redis_client.publish.assert_not_called()

    def test_drain_publishes_only_after_last_flushed(self, tmp_path):
        """R: _last_flushed_pos가 파일 중간이면 그 이후 라인만 publish됨"""
        line1 = "already-published\n"
        line2 = "new-line\n"
        content = line1 + line2
        log_path = self._make_log_file(tmp_path, [content])
        # line1까지는 이미 발행됨
        pos_after_line1 = len(line1.encode("utf-8"))

        redis_client = MagicMock()
        _run_drain_logic(log_path, last_flushed_pos=pos_after_line1, redis_client=redis_client)

        assert redis_client.publish.call_count == 1
        published_msg = redis_client.publish.call_args.args[1]
        assert "new-line" in published_msg
        assert "already-published" not in published_msg

    def test_drain_publishes_all_when_pos_zero(self, tmp_path):
        """B: _last_flushed_pos=0 → 기존 start_pos 기준으로 전체 발행"""
        lines = ["line1\n", "line2\n", "line3\n"]
        content = "".join(lines)
        log_path = self._make_log_file(tmp_path, [content])

        redis_client = MagicMock()
        _run_drain_logic(log_path, last_flushed_pos=0, redis_client=redis_client)

        assert redis_client.publish.call_count == 3

    def test_last_flushed_pos_updates_per_line(self):
        """R: 파이프 루프에서 3줄 쓰면 _last_flushed_pos가 3번 갱신됨 (tell() mock 검증)"""
        lines = [
            "[10:00:01] line1\n",
            "[10:00:02] line2\n",
            "[10:00:03] line3\n",
        ]
        process = FakeProcess(lines)
        log_handle = MagicMock()
        log_handle.__iter__ = MagicMock(return_value=iter([]))
        redis_client = MagicMock()

        # tell()은 호출될 때마다 다른 값 반환
        tell_values = [10, 20, 30]
        log_handle.tell.side_effect = tell_values

        last_flushed_pos = 0
        for line in process.stdout:
            stripped = line.rstrip('\n')
            log_handle.write(line)
            log_handle.flush()
            try:
                last_flushed_pos = log_handle.tell()
            except Exception:
                pass
            try:
                redis_client.publish(LOG_CHANNEL, stripped)
            except Exception:
                pass

        assert log_handle.tell.call_count == 3
        assert last_flushed_pos == 30


# ── _publish_with_retry TC (Phase 1 fix) ─────────────────────────────────────

import redis as _redis_module


def _publish_with_retry(redis_client, channel: str, msg: str) -> bool:
    """테스트용 _publish_with_retry 복제 (_dr_plan_runner.py에서 동일 로직)"""
    try:
        redis_client.publish(channel, msg)
        return True
    except _redis_module.ConnectionError:
        pass
    try:
        redis_client.ping()
        redis_client.publish(channel, msg)
        return True
    except (_redis_module.ConnectionError, Exception):
        return False


class TestPublishWithRetry:
    """_publish_with_retry 헬퍼 TC"""

    def test_stream_output_readline_publishes(self):
        """R(Right): readline 기반 stdout 읽기 + Redis publish 3회 검증"""
        class FakeStdout:
            def __init__(self, lines):
                self._iter = iter(lines)
            def readline(self):
                return next(self._iter, "")

        lines = ["line1\n", "line2\n", "line3\n"]
        stdout = FakeStdout(lines)
        redis_client = MagicMock()

        published = []
        while True:
            line = stdout.readline()
            if not line:
                break
            stripped = line.rstrip('\n')
            _publish_with_retry(redis_client, "plan-runner:logs:test", stripped)

        assert redis_client.publish.call_count == 3
        args_list = [c.args[1] for c in redis_client.publish.call_args_list]
        assert "line1" in args_list[0]
        assert "line2" in args_list[1]
        assert "line3" in args_list[2]

    def test_stream_output_publish_retry_on_error(self):
        """E(Error): ConnectionError 시 재시도 후 publish 성공"""
        redis_client = MagicMock()
        redis_client.publish.side_effect = [_redis_module.ConnectionError("Redis down"), None]

        result = _publish_with_retry(redis_client, "plan-runner:logs:test", "hello")

        assert result is True
        assert redis_client.ping.call_count == 1
        assert redis_client.publish.call_count == 2

    def test_stream_output_publish_retry_both_fail(self):
        """E(Error): 재시도도 실패 시 False 반환 + 예외 없음"""
        redis_client = MagicMock()
        redis_client.publish.side_effect = _redis_module.ConnectionError("Redis down")
        redis_client.ping.side_effect = _redis_module.ConnectionError("still down")

        result = _publish_with_retry(redis_client, "plan-runner:logs:test", "hello")

        assert result is False

    def test_stream_output_line_counter_log(self, caplog):
        """B(Boundary): 10줄 도달 시 로그 출력 확인"""
        import logging

        class FakeStdout:
            def __init__(self, count):
                self._count = count
                self._i = 0
            def readline(self):
                if self._i < self._count:
                    self._i += 1
                    return f"line-{self._i}\n"
                return ""

        stdout = FakeStdout(15)
        redis_client = MagicMock()
        _logger = logging.getLogger("test_counter")
        _line_count = 0

        with caplog.at_level(logging.INFO, logger="test_counter"):
            while True:
                line = stdout.readline()
                if not line:
                    break
                _line_count += 1
                if _line_count in (10, 100, 1000) or (_line_count > 1000 and _line_count % 1000 == 0):
                    _logger.info(f"[_stream_output] {_line_count}줄 처리됨 runner_id='test'")
                _publish_with_retry(redis_client, "plan-runner:logs:test", line.rstrip())

        assert any("10줄 처리됨" in r.message for r in caplog.records)
        assert not any("100줄 처리됨" in r.message for r in caplog.records)
