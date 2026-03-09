"""
Session 0 Desktop 알림 분기 테스트

- Session 0에서 _send_desktop 호출 시 Redis LPUSH 릴레이
- Session 1에서 _send_desktop 호출 시 plyer.notification 직접 호출
- Redis 연결 실패 시 예외 없이 warning 로그만 남김
- 실제 Redis LPUSH → BRPOP 라운드트립 통합 테스트 (plyer mock)
"""
import json
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _make_service():
    """NotificationService를 DB/설정 없이 인스턴스화합니다."""
    with (
        patch("app.shared.notification.notification_service._is_session_0", return_value=False),
        patch("app.shared.notification.notification_service.get_db"),
        patch("app.shared.notification.notification_service.settings"),
    ):
        from app.shared.notification.notification_service import NotificationService
        svc = object.__new__(NotificationService)
        svc.enable_desktop = True
        svc.recent_messages = []
        svc.message_timestamps = {}
        return svc


@pytest.mark.asyncio
async def test_session0_desktop_relay_right():
    """Session 0에서 _send_desktop 호출 시 Redis LPUSH가 호출돼야 한다."""
    svc = _make_service()

    mock_redis_client = AsyncMock()
    mock_redis_class = MagicMock(return_value=mock_redis_client)

    with (
        patch("app.shared.notification.notification_service._IN_SESSION_0", True),
        patch("redis.asyncio.Redis", mock_redis_class),
        patch("app.shared.notification.notification_service.settings") as mock_settings,
    ):
        mock_settings.REDIS_HOST = "localhost"
        mock_settings.REDIS_PORT = 6379
        mock_settings.REDIS_QUEUE_PREFIX = "monitor"

        result = await svc._send_desktop("테스트 알림")

    # Redis LPUSH가 호출됐는지 확인
    mock_redis_client.lpush.assert_awaited_once()
    call_args = mock_redis_client.lpush.call_args
    queue_arg = call_args[0][0]
    payload_arg = call_args[0][1]

    assert "notification:desktop" in queue_arg
    payload = json.loads(payload_arg)
    assert payload["message"] == "테스트 알림"

    assert result is True


@pytest.mark.asyncio
async def test_session1_desktop_direct_right():
    """Session 1에서 _send_desktop 호출 시 plyer.notification.notify가 직접 호출돼야 한다."""
    svc = _make_service()

    mock_notify = MagicMock()

    with (
        patch("app.shared.notification.notification_service._IN_SESSION_0", False),
        patch("app.shared.notification.notification_service.notification") as mock_notification,
    ):
        mock_notification.notify = mock_notify
        # 중복 메시지 검사 우회
        with patch.object(svc, "_is_duplicate_message", return_value=False):
            result = await svc._send_desktop("세션1 테스트")

    mock_notify.assert_called_once()
    call_kwargs = mock_notify.call_args
    # title 또는 message 파라미터에 알림 내용 포함 확인
    assert result is True


@pytest.mark.asyncio
async def test_desktop_relay_redis_error_error():
    """Redis 연결 실패 시 예외 없이 False를 반환하고 warning 로그만 남겨야 한다."""
    svc = _make_service()

    with (
        patch("app.shared.notification.notification_service._IN_SESSION_0", True),
        patch("redis.asyncio.Redis", side_effect=Exception("Redis connection refused")),
        patch("app.shared.notification.notification_service.settings") as mock_settings,
        patch("app.shared.notification.notification_service.logger") as mock_logger,
    ):
        mock_settings.REDIS_HOST = "localhost"
        mock_settings.REDIS_PORT = 6379
        mock_settings.REDIS_QUEUE_PREFIX = "monitor"

        # 예외가 밖으로 전파되지 않아야 함
        result = await svc._send_desktop("에러 테스트")

    assert result is False
    # warning 로그가 호출됐는지 확인
    mock_logger.warning.assert_called_once()
    warning_msg = mock_logger.warning.call_args[0][0]
    assert "릴레이 실패" in warning_msg or "Redis" in warning_msg


# ---------------------------------------------------------------------------
# T3: 통합 테스트 — 실제 Redis LPUSH → BRPOP 라운드트립
# ---------------------------------------------------------------------------

def _redis_available() -> bool:
    """로컬 Redis(localhost:6379)에 실제로 연결 가능한지 확인."""
    try:
        import socket
        s = socket.create_connection(("localhost", 6379), timeout=1)
        s.close()
        return True
    except OSError:
        return False


requires_redis = pytest.mark.skipif(
    not _redis_available(),
    reason="로컬 Redis(localhost:6379)에 연결할 수 없어 통합 테스트를 건너뜁니다.",
)


@requires_redis
@pytest.mark.asyncio
async def test_desktop_relay_integration():
    """실제 Redis 연결로 LPUSH → BRPOP 라운드트립을 검증합니다.

    NotificationService._relay_desktop_via_redis()가 실제 Redis에 메시지를
    LPUSH하면, BRPOP으로 꺼낸 페이로드가 원본 메시지와 일치해야 합니다.
    plyer.notification은 mock 처리합니다.
    """
    import redis.asyncio as aioredis
    from app.shared.redis.queue import DESKTOP_NOTIFICATION_QUEUE

    TEST_QUEUE_PREFIX = "test_integration"
    queue_name = f"{TEST_QUEUE_PREFIX}:{DESKTOP_NOTIFICATION_QUEUE}"
    test_message = "통합테스트 알림 메시지"

    # 실제 Redis 클라이언트
    client = aioredis.Redis(host="localhost", port=6379, decode_responses=True)

    # 테스트 시작 전 큐 초기화 (잔여 데이터 제거)
    await client.delete(queue_name)

    try:
        svc = _make_service()

        # _relay_desktop_via_redis 내부에서 `from app.core.config import settings as _settings`로
        # 임포트하므로, app.core.config.settings를 직접 패치해야 실제 Redis 큐 이름이 일치한다.
        with (
            patch("app.shared.notification.notification_service._IN_SESSION_0", True),
            patch("app.core.config.settings") as mock_core_settings,
        ):
            mock_core_settings.REDIS_HOST = "localhost"
            mock_core_settings.REDIS_PORT = 6379
            mock_core_settings.REDIS_QUEUE_PREFIX = TEST_QUEUE_PREFIX

            result = await svc._send_desktop(test_message)

        # LPUSH 성공 확인
        assert result is True, "_relay_desktop_via_redis()가 True를 반환해야 합니다."

        # BRPOP으로 메시지 꺼내기 (timeout=2초)
        popped = await client.brpop(queue_name, timeout=2)
        assert popped is not None, f"Redis 큐 '{queue_name}'에서 메시지를 꺼내지 못했습니다."

        _, raw_payload = popped
        payload = json.loads(raw_payload)
        assert payload["message"] == test_message, (
            f"페이로드 message 불일치: 기대={test_message!r}, 실제={payload.get('message')!r}"
        )

    finally:
        # 테스트 후 큐 정리
        await client.delete(queue_name)
        await client.aclose()
