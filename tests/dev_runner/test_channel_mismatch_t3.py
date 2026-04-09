"""Phase T3: 채널 불일치 재현 TC (fakeredis 사용)

검증 목적:
1. per-runner 채널(`plan-runner:logs:{runner_id}`)로 publish → stream_log_file 수신 확인
2. bare 채널(`plan-runner:logs`)로 publish → stream_log_file 미수신 확인 (회귀 방지)
3. fallback 재현 TC: Redis publish 없이 파일 폴링 fallback 발동 + [SSE][FALLBACK] 로그

관련 plan: docs/plan/2026-04-08_fix-logviewer-realtime-channel-mismatch_todo-2.md
Phase T3 체크박스 검증 전용 테스트.
"""
import asyncio
import logging
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch as _patch, AsyncMock

import pytest
import fakeredis
import fakeredis.aioredis


# ─── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _make_log_service_fakeredis(fake_server=None):
    """LogService + fakeredis 인스턴스 (실제 pub/sub 동작 검증용)"""
    from app.modules.dev_runner.services.log_service import LogService
    from app.modules.dev_runner.services.log_file_resolver import LogFileResolver

    if fake_server is None:
        fake_server = fakeredis.FakeServer()

    svc = LogService.__new__(LogService)
    svc.redis_client = fakeredis.FakeRedis(server=fake_server, decode_responses=True)
    svc.async_redis = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)

    # resolver: find_current_log = None (파일시스템 fallback 무시)
    svc.resolver = MagicMock(spec=LogFileResolver)
    svc.resolver.find_current_log.return_value = None
    svc._sync_resolver = MagicMock()

    return svc, fake_server


async def _instant_sleep(*args, **kwargs):
    """asyncio.sleep 즉시 반환 (hang 방지)"""
    pass


# ─── Phase T3: 채널 불일치 재현 TC ──────────────────────────────────────────────

class TestChannelMismatchReproduction:
    """T3-1: per-runner 채널 구독 vs bare 채널 publish — 수신 여부 검증"""

    def test_per_runner_channel_publish_received(self):
        """per-runner 채널 publish → stream_log_file 수신 확인 (정상 경로)"""
        fake_server = fakeredis.FakeServer()
        svc, _ = _make_log_service_fakeredis(fake_server)

        runner_id = "runner1"
        expected_channel = f"plan-runner:logs:{runner_id}"
        test_message = "Hello from per-runner channel"

        received = []
        stream_started = threading.Event()

        async def stream_and_collect():
            """stream_log_file 시작 후 메시지 수집"""
            svc._find_current_log = MagicMock(return_value=None)

            async def gen():
                async for chunk in svc.stream_log_file(runner_id, since_line=0):
                    yield chunk

            async def collect():
                async for chunk in gen():
                    received.append(chunk)
                    if "data:" in chunk and test_message in chunk:
                        break
                    if "event: connected" in chunk:
                        stream_started.set()
                    if len(received) > 20:
                        break

            with _patch.object(asyncio, "sleep", _instant_sleep):
                await asyncio.wait_for(collect(), timeout=5.0)

        def publisher():
            """stream 시작 후 메시지 publish"""
            stream_started.wait(timeout=3.0)
            time.sleep(0.1)
            fr = fakeredis.FakeRedis(server=fake_server, decode_responses=True)
            fr.publish(expected_channel, test_message)
            # COMPLETED sentinel 보내서 스트림 종료
            time.sleep(0.1)
            fr.publish(expected_channel, "__COMPLETED__")

        pub_thread = threading.Thread(target=publisher, daemon=True)
        pub_thread.start()

        asyncio.run(stream_and_collect())
        pub_thread.join(timeout=5.0)

        # per-runner 채널 메시지가 수신됨
        data_chunks = [c for c in received if test_message in c]
        assert len(data_chunks) >= 1, (
            f"per-runner 채널 메시지 미수신. received chunks: {received}"
        )

    def test_bare_channel_publish_not_received(self):
        """bare 'plan-runner:logs' 채널 publish → stream_log_file 미수신 (채널 불일치 회귀 방지)"""
        fake_server = fakeredis.FakeServer()
        svc, _ = _make_log_service_fakeredis(fake_server)

        runner_id = "runner1"
        bare_channel = "plan-runner:logs"  # 잘못된 채널 (old behavior)
        test_message = "Should NOT be received"

        received = []
        stream_started = threading.Event()

        # pubsub가 구독된 후 바로 COMPLETED 보내서 스트림 종료
        async def stream_and_collect():
            svc._find_current_log = MagicMock(return_value=None)

            async def collect():
                call_count = [0]
                async for chunk in svc.stream_log_file(runner_id, since_line=0):
                    received.append(chunk)
                    if "event: connected" in chunk:
                        stream_started.set()
                    call_count[0] += 1
                    if call_count[0] >= 15:
                        break

            with _patch.object(asyncio, "sleep", _instant_sleep):
                await asyncio.wait_for(collect(), timeout=5.0)

        def publisher():
            stream_started.wait(timeout=3.0)
            time.sleep(0.1)
            fr = fakeredis.FakeRedis(server=fake_server, decode_responses=True)
            # bare 채널로 publish (잘못된 채널)
            fr.publish(bare_channel, test_message)
            time.sleep(0.1)
            # per-runner 채널로 COMPLETED 전송 (스트림 종료)
            fr.publish(f"plan-runner:logs:{runner_id}", "__COMPLETED__")

        pub_thread = threading.Thread(target=publisher, daemon=True)
        pub_thread.start()

        asyncio.run(stream_and_collect())
        pub_thread.join(timeout=5.0)

        # bare 채널 메시지는 수신 안 됨
        bad_chunks = [c for c in received if test_message in c]
        assert len(bad_chunks) == 0, (
            f"bare 'plan-runner:logs' 채널 메시지가 수신됨 — 채널 불일치 버그 재발: {bad_chunks}"
        )


def _make_mock_pubsub_with_counter(pubsub_call, complete_after=8):
    """pubsub mock: complete_after 회 호출 후 __COMPLETED__ 반환"""
    mock_ps = MagicMock()

    async def patched_get_message(**kwargs):
        pubsub_call[0] += 1
        if pubsub_call[0] > complete_after:
            return {"type": "message", "data": "__COMPLETED__"}
        return None

    async def mock_subscribe(*args, **kwargs): pass
    async def mock_aclose(): pass
    mock_ps.get_message = patched_get_message
    mock_ps.subscribe = mock_subscribe
    mock_ps.aclose = mock_aclose
    return mock_ps


class TestFallbackModeReproduction:
    """T3-2: Redis publish 없이 파일 폴링 fallback 발동 검증"""

    def test_fallback_mode_warning_logged(self, tmp_path):
        """5초 pub/sub 무수신 → [SSE][FALLBACK] WARNING 로그 발생 확인 (patch.object 사용)

        핵심: asyncio.run()이 내부적으로 time.monotonic()을 다수 호출하므로,
        FILE_POLL_TIMEOUT=0으로 패치해 fallback을 즉시 발동시킨다.
        """
        import app.modules.dev_runner.services.log_service as _ls_mod

        fake_server = fakeredis.FakeServer()
        svc, _ = _make_log_service_fakeredis(fake_server)

        runner_id = "fallback-test"
        log_file = tmp_path / f"plan-runner-stream-{runner_id}-20260408.log"
        log_file.write_text("existing line\n", encoding="utf-8")

        svc._find_current_log = MagicMock(return_value=log_file)

        pubsub_call = [0]
        mock_ps = _make_mock_pubsub_with_counter(pubsub_call, complete_after=8)
        svc.async_redis.pubsub = MagicMock(return_value=mock_ps)

        # FILE_POLL_TIMEOUT=0으로 패치: asyncio 내부 monotonic 호출 횟수 무관하게 즉시 발동
        with _patch.object(_ls_mod.logger, "warning", wraps=_ls_mod.logger.warning) as mock_warn:
            with _patch("app.modules.dev_runner.services.log_service.FILE_POLL_TIMEOUT", 0.0):
                with _patch.object(asyncio, "sleep", _instant_sleep):
                    asyncio.run(
                        asyncio.wait_for(
                            _collect_stream(svc, runner_id),
                            timeout=5.0,
                        )
                    )

        # [SSE][FALLBACK] 경고가 최소 1회 호출되었는지 확인
        fallback_calls = [
            c for c in mock_warn.call_args_list
            if "[SSE][FALLBACK]" in str(c)
        ]
        assert len(fallback_calls) >= 1, (
            f"[SSE][FALLBACK] WARNING 미발생. 실제 호출: {mock_warn.call_args_list}"
        )
        # 구조화 메시지 확인
        fallback_args = str(fallback_calls[0])
        assert "fallback_mode" in fallback_args, (
            f"fallback_mode 구조화 메시지 없음: {fallback_args}"
        )

    def test_fallback_does_not_resend_existing_lines(self, tmp_path):
        """fallback 발동 후 기존 파일 내용 재전송 안 함 (EOF 초기화 검증)"""
        import app.modules.dev_runner.services.log_service as _ls_mod

        fake_server = fakeredis.FakeServer()
        svc, _ = _make_log_service_fakeredis(fake_server)

        runner_id = "eof-test"
        log_file = tmp_path / f"plan-runner-stream-{runner_id}-20260408.log"
        log_file.write_text("old line 1\nold line 2\n", encoding="utf-8")

        svc._find_current_log = MagicMock(return_value=log_file)

        pubsub_call = [0]
        mock_ps = _make_mock_pubsub_with_counter(pubsub_call, complete_after=8)
        svc.async_redis.pubsub = MagicMock(return_value=mock_ps)

        # FILE_POLL_TIMEOUT=0: 즉시 fallback 발동
        with _patch("app.modules.dev_runner.services.log_service.FILE_POLL_TIMEOUT", 0.0):
            with _patch.object(asyncio, "sleep", _instant_sleep):
                chunks = asyncio.run(
                    asyncio.wait_for(
                        _collect_stream(svc, runner_id),
                        timeout=5.0,
                    )
                )

        # 기존 파일 내용 재전송 없음
        resent = [c for c in chunks if "old line" in c]
        assert len(resent) == 0, (
            f"기존 내용 재전송됨 (EOF 초기화 미동작): {resent}"
        )

    def test_fallback_receives_new_lines(self, tmp_path):
        """fallback 발동 후 파일에 추가된 신규 줄 수신 확인 (plan item 15: 신규 로그 줄 수신)

        시나리오:
        1. 파일에 기존 내용("old content\\n") 존재 → 첫 fallback에서 EOF seek으로 skip
        2. 첫 fallback 이후 파일에 신규 줄 append (complete_after=2로 두 번째 None 후)
        3. 두 번째 폴링에서 신규 줄을 읽어 SSE chunk 생성 확인

        핵심: FILE_POLL_TIMEOUT=0으로 패치해 즉시 fallback 발동.
        """
        import app.modules.dev_runner.services.log_service as _ls_mod

        fake_server = fakeredis.FakeServer()
        svc, _ = _make_log_service_fakeredis(fake_server)

        runner_id = "newline-test"
        log_file = tmp_path / f"plan-runner-stream-{runner_id}-20260408.log"
        # 기존 내용: 첫 fallback에서 EOF seek 후 skip
        log_file.write_text("old content\n", encoding="utf-8")

        new_line_written = [False]
        call_count = [0]

        def find_log_and_maybe_write(_runner_id):
            """_find_current_log 첫 호출(=첫 fallback) 후 두 번째 호출 시 신규 줄 추가"""
            call_count[0] += 1
            if call_count[0] >= 2 and not new_line_written[0]:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write("new log line\n")
                new_line_written[0] = True
            return log_file

        svc._find_current_log = find_log_and_maybe_write

        pubsub_call = [0]
        # complete_after=10: 10번 None → 11번째에 COMPLETED (신규 줄 수신 후 종료)
        mock_ps = _make_mock_pubsub_with_counter(pubsub_call, complete_after=10)
        svc.async_redis.pubsub = MagicMock(return_value=mock_ps)

        # FILE_POLL_TIMEOUT=0: asyncio 내부 monotonic 호출 횟수 무관, 즉시 fallback 발동
        with _patch("app.modules.dev_runner.services.log_service.FILE_POLL_TIMEOUT", 0.0):
            with _patch.object(asyncio, "sleep", _instant_sleep):
                chunks = asyncio.run(
                    asyncio.wait_for(
                        _collect_stream(svc, runner_id),
                        timeout=5.0,
                    )
                )

        # fallback 파일 폴링으로 신규 줄이 수신되었는지 확인
        new_line_chunks = [c for c in chunks if "new log line" in c]
        assert len(new_line_chunks) >= 1, (
            f"fallback 후 신규 로그 줄 미수신. chunks: {chunks}"
        )


async def _collect_stream(svc, runner_id: str) -> list[str]:
    """stream_log_file 결과를 리스트로 수집 (완료 시 또는 최대 50개 청크까지)"""
    chunks = []
    async for chunk in svc.stream_log_file(runner_id, since_line=0):
        chunks.append(chunk)
        if len(chunks) >= 50:
            break
    return chunks
