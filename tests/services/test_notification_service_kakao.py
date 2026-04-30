"""NotificationService Kakao queue tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def notification_service():
    with patch("app.shared.notification.notification_service.get_db") as mock_get_db, \
         patch("app.shared.notification.notification_service.settings") as mock_settings:
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = (1, 1, "[]")
        mock_get_db.return_value = iter([mock_db])

        mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
        mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
        mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
        mock_settings.RECENT_MESSAGES_MAX = 100
        mock_settings.MEGABEAUTY_KAKAO_ALERT_ENABLED = True
        mock_settings.MEGABEAUTY_KAKAO_ALERT_ROOM_NAME = "소나무봇"
        mock_settings.MEGABEAUTY_KAKAO_ALERT_EXPIRES_SECONDS = 900
        mock_settings.MEGABEAUTY_KAKAO_ALERT_DEDUP_TTL_SECONDS = 300
        mock_settings.MEGABEAUTY_KAKAO_ALERT_BACKLOG_THRESHOLD = 10
        mock_settings.MEGABEAUTY_KAKAO_ALERT_BACKLOG_COOLDOWN_SECONDS = 600
        mock_settings.REDIS_HOST = "localhost"
        mock_settings.REDIS_PORT = 6379

        from app.shared.notification.notification_service import NotificationService
        yield NotificationService()


@pytest.mark.asyncio
async def test_enqueue_kakao_notification_triggers_backlog_telegram(notification_service):
    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock(return_value={
        "enqueued": True,
        "duplicate": False,
        "disabled": False,
        "queue_length": 12,
        "payload": {"id": "abc"},
    })
    fake_queue.queue_name = "monitor:notification:kakao"

    cooldown_client = AsyncMock()
    cooldown_client.set = AsyncMock(return_value=True)
    cooldown_client.aclose = AsyncMock()

    with patch("app.shared.notification.notification_service.KakaoNotificationQueue", return_value=fake_queue), \
         patch("redis.asyncio.Redis", return_value=cooldown_client), \
         patch.object(notification_service, "send_telegram", AsyncMock()) as mock_send_telegram:
        result = await notification_service._enqueue_kakao_notification(
            "메가뷰티쇼 공석 알림",
            metadata={"date": "2026-04-17"},
        )

    assert result is True
    mock_send_telegram.assert_awaited_once()
    assert mock_send_telegram.call_args.kwargs["force_send"] is True
    cooldown_client.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_kakao_enqueue_guard_failure_stays_kakao_scoped(notification_service):
    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock(return_value={
        "enqueued": False,
        "duplicate": False,
        "disabled": False,
        "queue_length": 0,
        "payload": {"id": "abc", "metadata": {"guard_required": True}},
        "error": "guard failed",
    })
    fake_queue.queue_name = "monitor:notification:kakao"

    redis_client = AsyncMock()
    redis_client.aclose = AsyncMock()

    with patch("app.shared.notification.notification_service.KakaoNotificationQueue", return_value=fake_queue), \
         patch("redis.asyncio.Redis", return_value=redis_client), \
         patch.object(notification_service, "send_telegram", AsyncMock()) as mock_send_telegram:
        result = await notification_service._enqueue_kakao_notification(
            "메가뷰티쇼 공석 알림",
            metadata={"guard_required": True},
        )

    assert result is False
    fake_queue.enqueue.assert_awaited_once()
    mock_send_telegram.assert_not_called()
    redis_client.aclose.assert_awaited_once()

