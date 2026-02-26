"""7.2: 스트림 에러 무한 반복 방지 검증 테스트

asyncio.sleep을 전역 패치하면 asyncio.wait_for 내부 타이머가 고장나므로,
대신 log_service 모듈의 asyncio 객체만 부분 패치하는 방식을 사용.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class _FakePubSub:
    """aclose/close 둘 다 있는 기본 PubSub stub"""
    def __init__(self, side_effect=None):
        self._side_effect = side_effect
        self._call_count = 0

    async def subscribe(self, channel):
        pass

    async def unsubscribe(self, channel):
        pass

    async def aclose(self):
        pass

    async def get_message(self, **kwargs):
        self._call_count += 1
        if callable(self._side_effect):
            result = self._side_effect(self._call_count)
            if asyncio.iscoroutine(result):
                return await result
            return result
        raise self._side_effect




async def _drive_gen(gen, max_events=20, max_iterations=200):
    """sleep 없이 generator를 직접 소비. 짧은 sleep(0) yield로 이벤트 루프 양보."""
    events = []
    iterations = 0
    try:
        async for event in gen:
            events.append(event)
            if len(events) >= max_events:
                break
            iterations += 1
            if iterations >= max_iterations:
                break
            await asyncio.sleep(0)  # 이벤트 루프 양보 (0초 sleep은 타이머 영향 없음)
    except Exception:
        pass
    return events


@pytest.mark.asyncio
async def test_stream_stops_after_5_errors():
    """연속 에러 5회 → stream_error 이벤트 후 generator 종료"""
    import app.modules.dev_runner.services.log_service as ls_module
    from app.modules.dev_runner.services.log_service import LogService

    svc = LogService()
    pub = _FakePubSub(side_effect=RuntimeError("mock error"))

    # log_service 내부의 asyncio.sleep만 패치 (wait_for용 전역 sleep은 유지)
    orig_sleep = ls_module.asyncio.sleep
    ls_module.asyncio.sleep = AsyncMock(return_value=None)

    try:
        with patch.object(svc.async_redis, "pubsub", return_value=pub):
            events = await asyncio.wait_for(
                _drive_gen(svc.stream_log_file("test_runner")), timeout=10.0
            )
    finally:
        ls_module.asyncio.sleep = orig_sleep

    stream_errors = [e for e in events if "event: stream_error" in e]
    assert len(stream_errors) == 1, f"stream_error 1개 필요:\n" + "\n".join(events)

    data_errors = [e for e in events if "[Stream error #" in e]
    assert len(data_errors) <= 5

    assert "event: stream_error" in events[-1], "stream_error는 마지막 이벤트"


@pytest.mark.asyncio
async def test_consecutive_errors_reset_on_success():
    """에러 3회 후 정상 수신 → 카운터 리셋 → stream_error 없음"""
    import app.modules.dev_runner.services.log_service as ls_module
    from app.modules.dev_runner.services.log_service import LogService

    svc = LogService()

    def mixed_effect(call_count):
        # 1~3: 에러 (counter=3)
        if call_count <= 3:
            raise RuntimeError("before-reset error")
        # 4: 정상 수신 → counter 리셋
        if call_count == 4:
            return {"type": "message", "data": "recovery-ok"}
        # 5~9: 에러 → 리셋 후 counter=1,2,3,4,5 → stream_error
        raise RuntimeError("after-reset error")

    pub = _FakePubSub(side_effect=mixed_effect)

    orig_sleep = ls_module.asyncio.sleep
    ls_module.asyncio.sleep = AsyncMock(return_value=None)

    try:
        with patch.object(svc.async_redis, "pubsub", return_value=pub):
            events = await asyncio.wait_for(
                _drive_gen(svc.stream_log_file("test_runner"), max_events=20), timeout=10.0
            )
    finally:
        ls_module.asyncio.sleep = orig_sleep

    # recovery-ok 메시지 수신
    assert any("recovery-ok" in e for e in events), f"정상 메시지 수신 필요:\n" + "\n".join(events)

    # 최종 stream_error 발생 (리셋 후 5회 더 필요)
    assert any("event: stream_error" in e for e in events), "최종 stream_error 필요"

    # 리셋 전 에러 3개, 리셋 후 에러 4개 (5번째에 stream_error)
    recovery_idx = next(i for i, e in enumerate(events) if "recovery-ok" in e)
    errors_before = [e for e in events[:recovery_idx] if "[Stream error #" in e]
    errors_after = [e for e in events[recovery_idx:] if "[Stream error #" in e]
    assert len(errors_before) == 3, f"리셋 전 에러 3개: {errors_before}"
    assert len(errors_after) == 4, f"리셋 후 에러 4개: {errors_after}"


@pytest.mark.asyncio
async def test_pubsub_close_fallback_when_no_aclose():
    """aclose 없는 pubsub → _close_pubsub이 AttributeError 없이 처리"""
    import app.modules.dev_runner.services.log_service as ls_module
    from app.modules.dev_runner.services.log_service import LogService

    svc = LogService()

    class NoAclosePubSub:
        async def subscribe(self, ch): pass
        async def unsubscribe(self, ch): pass
        async def close(self): pass
        async def get_message(self, **kw): raise RuntimeError("no aclose test")

    pub = NoAclosePubSub()

    orig_sleep = ls_module.asyncio.sleep
    ls_module.asyncio.sleep = AsyncMock(return_value=None)

    try:
        with patch.object(svc.async_redis, "pubsub", return_value=pub):
            try:
                events = await asyncio.wait_for(
                    _drive_gen(svc.stream_log_file("test_runner")), timeout=10.0
                )
            except AttributeError as e:
                pytest.fail(f"aclose 없는 pubsub에서 AttributeError 발생: {e}")
    finally:
        ls_module.asyncio.sleep = orig_sleep

    stream_errors = [e for e in events if "event: stream_error" in e]
    assert len(stream_errors) == 1, f"stream_error로 정상 종료 필요:\n" + "\n".join(events)


@pytest.mark.asyncio
async def test_connection_error_no_counter_increment():
    """ConnectionError → consecutive_errors 증가 없이 redis_disconnected 이벤트"""
    import redis as sync_redis
    import app.modules.dev_runner.services.log_service as ls_module
    from app.modules.dev_runner.services.log_service import LogService

    svc = LogService()

    def conn_effect(call_count):
        if call_count <= 8:
            raise sync_redis.ConnectionError("lost")
        return {"type": "message", "data": "after-reconnect"}

    pub = _FakePubSub(side_effect=conn_effect)

    orig_sleep = ls_module.asyncio.sleep
    ls_module.asyncio.sleep = AsyncMock(return_value=None)

    try:
        with patch.object(svc.async_redis, "pubsub", return_value=pub):
            events = await asyncio.wait_for(
                _drive_gen(svc.stream_log_file("test_runner"), max_events=20), timeout=10.0
            )
    finally:
        ls_module.asyncio.sleep = orig_sleep

    assert not any("event: stream_error" in e for e in events), \
        "ConnectionError는 stream_error 유발 금지"
    assert any("event: redis_disconnected" in e for e in events), \
        "ConnectionError 시 redis_disconnected 필요"
    assert any("after-reconnect" in e for e in events), \
        "재연결 후 정상 메시지 필요"
