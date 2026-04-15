"""Kakao notification queue tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_enqueue_kakao_notification_pushes_payload():
    with patch("app.shared.notification.kakao_queue.settings") as mock_settings, \
         patch("app.shared.notification.kakao_queue.RedisQueue") as mock_queue_cls:
        mock_settings.REDIS_QUEUE_PREFIX = "monitor"
        mock_settings.MEGABEAUTY_KAKAO_ALERT_ENABLED = True
        mock_settings.MEGABEAUTY_KAKAO_ALERT_ROOM_NAME = "소나무봇"
        mock_settings.MEGABEAUTY_KAKAO_ALERT_EXPIRES_SECONDS = 900
        mock_settings.MEGABEAUTY_KAKAO_ALERT_DEDUP_TTL_SECONDS = 300

        mock_queue = MagicMock()
        mock_queue.queue_name = "monitor:notification:kakao"
        mock_queue.push = AsyncMock(return_value=True)
        mock_queue.length = AsyncMock(return_value=3)
        mock_queue_cls.return_value = mock_queue

        from app.shared.notification.kakao_queue import KakaoNotificationQueue

        client = AsyncMock()
        client.set = AsyncMock(return_value=True)
        queue = KakaoNotificationQueue(client)

        result = await queue.enqueue(
            "테스트 메시지",
            source="coupang-megabeautyshow",
            metadata={"date": "2026-04-17"},
        )

        assert result["enqueued"] is True
        assert result["duplicate"] is False
        assert result["queue_length"] == 3
        mock_queue.push.assert_awaited_once()
        client.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_kakao_notification_duplicate_skips_push():
    with patch("app.shared.notification.kakao_queue.settings") as mock_settings, \
         patch("app.shared.notification.kakao_queue.RedisQueue") as mock_queue_cls:
        mock_settings.REDIS_QUEUE_PREFIX = "monitor"
        mock_settings.MEGABEAUTY_KAKAO_ALERT_ENABLED = True
        mock_settings.MEGABEAUTY_KAKAO_ALERT_ROOM_NAME = "소나무봇"
        mock_settings.MEGABEAUTY_KAKAO_ALERT_EXPIRES_SECONDS = 900
        mock_settings.MEGABEAUTY_KAKAO_ALERT_DEDUP_TTL_SECONDS = 300

        mock_queue = MagicMock()
        mock_queue.queue_name = "monitor:notification:kakao"
        mock_queue.push = AsyncMock(return_value=True)
        mock_queue.length = AsyncMock(return_value=5)
        mock_queue_cls.return_value = mock_queue

        from app.shared.notification.kakao_queue import KakaoNotificationQueue

        client = AsyncMock()
        client.set = AsyncMock(return_value=False)
        queue = KakaoNotificationQueue(client)

        result = await queue.enqueue("테스트 메시지", source="coupang-megabeautyshow")

        assert result["enqueued"] is False
        assert result["duplicate"] is True
        mock_queue.push.assert_not_called()

