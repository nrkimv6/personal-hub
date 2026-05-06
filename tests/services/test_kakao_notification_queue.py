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


def test_build_kakao_payload_adds_guard_metadata_defaults():
    from app.shared.notification.kakao_queue import build_kakao_payload

    payload = build_kakao_payload(
        "테스트 메시지",
        "소나무봇",
        source="unit-test",
        metadata={"date": "2026-04-17"},
    )

    assert payload["metadata"]["date"] == "2026-04-17"
    assert payload["metadata"]["retry_count"] == 0
    assert payload["metadata"]["last_error"] is None
    assert payload["metadata"]["guard_required"] is True


@pytest.mark.asyncio
async def test_requeue_and_dead_letter_update_retry_metadata():
    with patch("app.shared.notification.kakao_queue.RedisQueue") as mock_queue_cls:
        main_queue = MagicMock()
        main_queue.queue_name = "monitor:notification:kakao"
        main_queue.push = AsyncMock(return_value=True)
        main_queue.length = AsyncMock(return_value=0)

        dead_letter_queue = MagicMock()
        dead_letter_queue.queue_name = "monitor:notification:kakao:dead-letter"
        dead_letter_queue.push = AsyncMock(return_value=True)
        dead_letter_queue.length = AsyncMock(return_value=1)
        mock_queue_cls.side_effect = [main_queue, dead_letter_queue]

        from app.shared.notification.kakao_queue import KakaoNotificationQueue

        queue = KakaoNotificationQueue(AsyncMock())
        payload = {
            "id": "payload-1",
            "message": "메시지",
            "room_name": "소나무봇",
            "metadata": {"retry_count": 1, "guard_required": True},
        }

        assert await queue.requeue(payload, last_error="guard failed") is True
        requeued = main_queue.push.await_args.args[0]
        assert requeued["metadata"]["retry_count"] == 2
        assert requeued["metadata"]["last_error"] == "guard failed"

        assert await queue.dead_letter(payload, last_error="retry exceeded") is True
        dead_lettered = dead_letter_queue.push.await_args.args[0]
        assert dead_lettered["metadata"]["retry_count"] == 1
        assert dead_lettered["metadata"]["last_error"] == "retry exceeded"
        assert "dead_lettered_at" in dead_lettered["metadata"]

