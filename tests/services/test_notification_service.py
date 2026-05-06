"""
NotificationService 테스트

경로: app/shared/notification/notification_service.py

RIGHT-BICEP 패턴:
- Right: 정상 동작 테스트
- Boundary: 경계값 테스트
- Inverse: 역관계 테스트
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 특성 테스트
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta


class TestNotificationServiceInit:
    """NotificationService 초기화 테스트"""

    def test_right_init_with_default_settings(self):
        """기본 설정으로 초기화"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '["available"]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            service = NotificationService()

            assert service.enable_telegram is True
            assert service.enable_desktop is True
            assert "available" in service.notify_states

    def test_right_init_creates_default_when_no_settings(self):
        """설정이 없을 때 기본값 생성"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = None
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            service = NotificationService()

            assert service.enable_telegram is True
            assert service.enable_desktop is True

    def test_right_init_filters_stale_notification_states(self):
        """startup/shutdown 같은 stale 상태는 로드 시 제거된다."""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '["available", "startup", "popup_new", "shutdown"]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            service = NotificationService()

            assert service.notify_states == ["available", "popup_new"]

    def test_right_init_closes_db_generator_after_loading_settings(self):
        """초기 설정 로드 후 DB 제너레이터를 즉시 닫아 세션 누수를 막는다."""
        with patch('app.shared.notification.notification_service.settings') as mock_settings:
            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '["available"]')
            closed = {"value": False}

            def fake_get_db():
                try:
                    yield mock_db
                finally:
                    closed["value"] = True

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            with patch('app.shared.notification.notification_service.get_db', side_effect=fake_get_db):
                from app.shared.notification.notification_service import NotificationService
                NotificationService()

            assert closed["value"] is True


class TestShouldNotify:
    """should_notify 메서드 테스트"""

    @pytest.fixture
    def notification_service(self):
        """테스트용 NotificationService 인스턴스"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '["available", "error"]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            return NotificationService()

    def test_right_should_notify_for_configured_state(self, notification_service):
        """설정된 상태에 대해 알림 허용"""
        assert notification_service.should_notify("available") is True
        assert notification_service.should_notify("error") is True

    def test_right_should_not_notify_for_unconfigured_state(self, notification_service):
        """설정되지 않은 상태에 대해 알림 거부"""
        assert notification_service.should_notify("startup") is False
        assert notification_service.should_notify("shutdown") is False


class TestDuplicateMessage:
    """중복 메시지 필터링 테스트"""

    @pytest.fixture
    def notification_service(self):
        """테스트용 NotificationService 인스턴스"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '[]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100
            mock_settings.MESSAGE_DEDUPLICATION = True
            mock_settings.MESSAGE_EXPIRY_SECONDS = 60

            from app.shared.notification.notification_service import NotificationService
            return NotificationService()

    def test_right_first_message_not_duplicate(self, notification_service):
        """첫 번째 메시지는 중복이 아님"""
        result = notification_service._is_duplicate_message("테스트 메시지")
        assert result is False

    def test_right_same_message_is_duplicate(self, notification_service):
        """동일한 메시지는 중복"""
        notification_service._is_duplicate_message("테스트 메시지")
        result = notification_service._is_duplicate_message("테스트 메시지")
        assert result is True

    def test_right_different_message_not_duplicate(self, notification_service):
        """다른 메시지는 중복이 아님"""
        notification_service._is_duplicate_message("테스트 메시지 1")
        result = notification_service._is_duplicate_message("테스트 메시지 2")
        assert result is False


class TestHashMessage:
    """메시지 해시 테스트"""

    @pytest.fixture
    def notification_service(self):
        """테스트용 NotificationService 인스턴스"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '[]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            return NotificationService()

    def test_right_hash_is_consistent(self, notification_service):
        """동일한 메시지는 동일한 해시"""
        hash1 = notification_service._hash_message("테스트")
        hash2 = notification_service._hash_message("테스트")
        assert hash1 == hash2

    def test_right_different_messages_different_hash(self, notification_service):
        """다른 메시지는 다른 해시"""
        hash1 = notification_service._hash_message("테스트1")
        hash2 = notification_service._hash_message("테스트2")
        assert hash1 != hash2

    def test_boundary_empty_message(self, notification_service):
        """빈 메시지 해시"""
        hash_result = notification_service._hash_message("")
        assert hash_result is not None
        assert len(hash_result) == 32  # MD5 해시 길이


class TestSendTelegram:
    """텔레그램 전송 테스트"""

    @pytest.fixture
    def notification_service(self):
        """테스트용 NotificationService 인스턴스"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '[]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            return NotificationService()

    @pytest.mark.asyncio
    async def test_right_send_telegram_success(self, notification_service):
        """텔레그램 전송 성공"""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value='{"ok": true}')

            mock_session = MagicMock()
            mock_session.post = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock())
            )
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await notification_service._send_telegram("테스트 메시지")
            assert result is True

    @pytest.mark.asyncio
    async def test_error_send_telegram_no_token(self):
        """토큰 없이 텔레그램 전송 시도"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings, \
             patch('aiohttp.ClientSession') as mock_session_class:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '[]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = ""
            mock_settings.TELEGRAM_CHAT_ID = ""
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            service = NotificationService()

            result = await service._send_telegram("테스트 메시지")
            assert result is None  # 토큰 없으면 None 반환
            mock_session_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_public_send_telegram_no_token_skips_network(self):
        """공개 send_telegram도 빈 설정이면 네트워크 호출 없이 skip"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings, \
             patch('aiohttp.ClientSession') as mock_session_class:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '[]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = ""
            mock_settings.TELEGRAM_CHAT_ID = ""
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            service = NotificationService()

            result = await service.send_telegram("테스트 메시지")
            assert result is None
            mock_session_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_send_telegram_api_failure(self, notification_service):
        """텔레그램 API 실패"""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 400
            mock_response.text = AsyncMock(return_value='{"ok": false, "error": "Bad Request"}')

            mock_session = MagicMock()
            mock_session.post = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock())
            )
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await notification_service._send_telegram("테스트 메시지")
            assert result is False


class TestSendDesktop:
    """데스크톱 알림 테스트"""

    @pytest.fixture
    def notification_service(self):
        """테스트용 NotificationService 인스턴스"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '[]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100
            mock_settings.MESSAGE_DEDUPLICATION = False

            from app.shared.notification.notification_service import NotificationService
            return NotificationService()

    @pytest.mark.asyncio
    async def test_right_send_desktop_success(self, notification_service):
        """데스크톱 알림 전송 성공"""
        with patch('app.shared.notification.notification_service.notification') as mock_notification:
            mock_notification.notify = MagicMock()

            result = await notification_service._send_desktop("테스트 메시지")

            mock_notification.notify.assert_called_once()
            assert result is True

    @pytest.mark.asyncio
    async def test_boundary_long_message_truncated(self, notification_service):
        """256자 초과 메시지 잘림"""
        with patch('app.shared.notification.notification_service.notification') as mock_notification:
            mock_notification.notify = MagicMock()

            long_message = "가" * 300
            await notification_service._send_desktop(long_message)

            # notify 호출 시 메시지가 256자 이하로 잘렸는지 확인
            call_args = mock_notification.notify.call_args
            actual_message = call_args[1]['message']
            assert len(actual_message) <= 256

    @pytest.mark.asyncio
    async def test_right_skip_when_disabled(self):
        """데스크톱 알림 비활성화 시 스킵"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings, \
             patch('app.shared.notification.notification_service.notification') as mock_notification:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 0, '[]')  # enable_desktop = False
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = False
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            service = NotificationService()
            service.enable_desktop = False

            await service._send_desktop("테스트 메시지")
            mock_notification.notify.assert_not_called()


class TestNotificationEmoji:
    """알림 이모지 테스트"""

    @pytest.fixture
    def notification_service(self):
        """테스트용 NotificationService 인스턴스"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '[]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            return NotificationService()

    def test_right_emoji_for_available(self, notification_service):
        """예약 가능 상태 이모지"""
        emoji = notification_service._get_notification_emoji("예약가능", "매진→예약가능")
        assert emoji == "✅"

    def test_right_emoji_for_sold_out(self, notification_service):
        """매진 상태 이모지"""
        emoji = notification_service._get_notification_emoji("매진", "예약가능→매진")
        assert emoji == "❌"

    def test_right_emoji_for_error(self, notification_service):
        """에러 상태 이모지"""
        emoji = notification_service._get_notification_emoji("에러", "에러발생")
        assert emoji == "⚠️"

    def test_right_emoji_for_error_resolved(self, notification_service):
        """에러 해결 상태 이모지"""
        emoji = notification_service._get_notification_emoji("정상", "에러해결")
        assert emoji == "🔄"


class TestUrlStatusCache:
    """URL 상태 캐시 테스트"""

    @pytest.fixture
    def notification_service(self):
        """테스트용 NotificationService 인스턴스"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '[]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            return NotificationService()

    def test_right_get_url_status_creates_default(self, notification_service):
        """새 URL에 대해 기본 상태 생성"""
        url = "https://example.com/test"
        status = notification_service._get_url_status(url)

        assert status["status"] == "미확인"
        assert "last_update" in status
        assert status["change_count"] == 0

    def test_right_update_url_status(self, notification_service):
        """URL 상태 업데이트"""
        url = "https://example.com/test"
        notification_service._get_url_status(url)

        change_type = notification_service._update_url_status(url, "예약가능")
        assert change_type == "초기화"

        # 상태가 업데이트 되었는지 확인
        status = notification_service._get_url_status(url)
        assert status["status"] == "예약가능"

    def test_right_detect_status_change(self, notification_service):
        """상태 변경 감지"""
        url = "https://example.com/test"

        # 초기화
        notification_service._update_url_status(url, "매진")

        # 매진 → 예약가능
        change_type = notification_service._update_url_status(url, "예약가능")
        assert change_type == "매진→예약가능"

        # 예약가능 → 매진
        change_type = notification_service._update_url_status(url, "매진")
        assert change_type == "예약가능→매진"

    def test_right_no_change_when_same_status(self, notification_service):
        """동일한 상태는 변화 없음"""
        url = "https://example.com/test"

        notification_service._update_url_status(url, "예약가능")
        change_type = notification_service._update_url_status(url, "예약가능")

        assert change_type == "변화없음"


class TestFormatTimeInfo:
    """시간 정보 포맷팅 테스트"""

    @pytest.fixture
    def notification_service(self):
        """테스트용 NotificationService 인스턴스"""
        with patch('app.shared.notification.notification_service.get_db') as mock_get_db, \
             patch('app.shared.notification.notification_service.settings') as mock_settings:

            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = (1, 1, '[]')
            mock_get_db.return_value = iter([mock_db])

            mock_settings.TELEGRAM_BOT_TOKEN = "test_token"
            mock_settings.TELEGRAM_CHAT_ID = "test_chat_id"
            mock_settings.ENABLE_DESKTOP_NOTIFICATION = True
            mock_settings.RECENT_MESSAGES_MAX = 100

            from app.shared.notification.notification_service import NotificationService
            return NotificationService()

    def test_right_format_time_info(self, notification_service):
        """시간 정보 포맷팅"""
        times = ["오후 2:00", "오전 10:00", "오전 11:00"]
        result = notification_service._format_time_info(times)

        # 오전이 먼저 오도록 정렬됨
        assert "오전 10:00" in result
        assert result.index("오전") < result.index("오후")

    def test_boundary_empty_time_list(self, notification_service):
        """빈 시간 목록"""
        result = notification_service._format_time_info([])
        assert result == ""

    def test_boundary_single_time(self, notification_service):
        """단일 시간"""
        result = notification_service._format_time_info(["오전 10:00"])
        assert result == "오전 10:00"
