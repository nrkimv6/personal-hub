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
