"""
Session 0 Desktop 알림 분기 테스트

- Session 0에서 _send_desktop 호출 시 Redis LPUSH 릴레이
- Session 1에서 _send_desktop 호출 시 plyer.notification 직접 호출
- Redis 연결 실패 시 예외 없이 warning 로그만 남김
"""
import json
import pytest
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
