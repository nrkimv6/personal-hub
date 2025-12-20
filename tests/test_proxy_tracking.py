"""
프록시 추적 기능 테스트 (RIGHT-BICEP)

RIGHT:
- Right: 정상 케이스에서 올바른 결과가 반환되는지
- Inverse: 역연산이 올바른지 (해당 없음)
- Cross-check: 다른 방법으로 검증 (해당 없음)
- Boundary: 경계값 조건 (NULL, 빈 문자열)
- Error: 에러 조건에서 적절히 처리되는지
- Performance: 성능 요구사항 (해당 없음)

BICEP:
- Boundary: 경계 조건
- Inverse: 역관계
- Cross-check: 다른 수단으로 교차 검증
- Error: 에러 조건
- Performance: 성능 특성

테스트 대상:
- NaverGraphQLClient._last_used_proxy 추적
- ScheduleInfo.proxy_url 필드
- AvailabilityResult.proxy_url 필드
- EventLogger.log_monitoring_event() proxy_url 파라미터

Note: 이 테스트는 프로젝트의 가상환경에서 실행해야 합니다.
      pydantic_settings 모듈이 필요합니다.
"""
import sys
import os

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import asdict, dataclass, field
from typing import List, Dict, Any, Optional, Tuple

# Skip all tests if pydantic_settings is not available
try:
    import pydantic_settings
    HAS_DEPENDENCIES = True
except ImportError:
    HAS_DEPENDENCIES = False

pytestmark = pytest.mark.skipif(
    not HAS_DEPENDENCIES,
    reason="pydantic_settings not installed"
)


# Lazy import helpers to avoid import errors during collection
def get_schedule_info():
    from app.modules.naver_booking.services.graphql_client import ScheduleInfo
    return ScheduleInfo


def get_naver_graphql_client():
    from app.modules.naver_booking.services.graphql_client import NaverGraphQLClient
    return NaverGraphQLClient


def get_availability_result():
    from app.modules.naver_booking.services.anonymous_monitor import AvailabilityResult
    return AvailabilityResult


def get_anonymous_monitor():
    from app.modules.naver_booking.services.anonymous_monitor import AnonymousMonitor
    return AnonymousMonitor


def get_event_logger():
    # Import all models first to resolve relationships
    import app.models  # noqa: F401
    from app.services.event_logger import EventLogger
    return EventLogger


def get_monitoring_event_model():
    # Import all models first to resolve relationships
    import app.models  # noqa: F401
    from app.models.monitoring_event import MonitoringEvent
    return MonitoringEvent


def get_monitoring_event_schema():
    from app.schemas.monitoring_event import MonitoringEventBase
    return MonitoringEventBase


class TestScheduleInfoProxyUrl:
    """ScheduleInfo.proxy_url 필드 테스트"""

    # RIGHT: 정상 케이스
    def test_schedule_info_has_proxy_url_field(self):
        """ScheduleInfo에 proxy_url 필드가 존재해야 함"""
        ScheduleInfo = get_schedule_info()
        info = ScheduleInfo(
            business_id="123",
            biz_item_id="456",
            available_dates=[],
            slots=[],
            slots_by_date={},
            proxy_url="http://proxy.example.com:8080"
        )
        assert info.proxy_url == "http://proxy.example.com:8080"

    def test_schedule_info_proxy_url_default_none(self):
        """proxy_url 기본값은 None이어야 함"""
        ScheduleInfo = get_schedule_info()
        info = ScheduleInfo(
            business_id="123",
            biz_item_id="456",
            available_dates=[],
            slots=[]
        )
        assert info.proxy_url is None

    # BOUNDARY: 경계 조건
    def test_schedule_info_proxy_url_empty_string(self):
        """빈 문자열도 허용되어야 함"""
        ScheduleInfo = get_schedule_info()
        info = ScheduleInfo(
            business_id="123",
            biz_item_id="456",
            available_dates=[],
            slots=[],
            proxy_url=""
        )
        assert info.proxy_url == ""


class TestAvailabilityResultProxyUrl:
    """AvailabilityResult.proxy_url 필드 테스트"""

    # RIGHT: 정상 케이스
    def test_availability_result_has_proxy_url_field(self):
        """AvailabilityResult에 proxy_url 필드가 존재해야 함"""
        AvailabilityResult = get_availability_result()
        result = AvailabilityResult(
            available=True,
            slots=[],
            proxy_url="http://1.2.3.4:8080"
        )
        assert result.proxy_url == "http://1.2.3.4:8080"

    def test_availability_result_proxy_url_default_none(self):
        """proxy_url 기본값은 None이어야 함"""
        AvailabilityResult = get_availability_result()
        result = AvailabilityResult(
            available=False,
            slots=[]
        )
        assert result.proxy_url is None

    # BOUNDARY: 경계 조건
    def test_availability_result_with_error_no_proxy(self):
        """에러 상황에서도 proxy_url이 None으로 설정될 수 있어야 함"""
        AvailabilityResult = get_availability_result()
        result = AvailabilityResult(
            available=False,
            slots=[],
            error="connection timeout",
            proxy_url=None
        )
        assert result.error == "connection timeout"
        assert result.proxy_url is None


class TestNaverGraphQLClientProxyTracking:
    """NaverGraphQLClient 프록시 추적 테스트"""

    # RIGHT: 정상 케이스
    def test_client_has_last_used_proxy_attribute(self):
        """클라이언트에 _last_used_proxy 속성이 있어야 함"""
        NaverGraphQLClient = get_naver_graphql_client()
        client = NaverGraphQLClient()
        assert hasattr(client, '_last_used_proxy')
        assert client._last_used_proxy is None

    @pytest.mark.asyncio
    async def test_last_used_proxy_set_when_proxy_manager_available(self):
        """프록시 매니저가 있을 때 _last_used_proxy가 설정되어야 함"""
        NaverGraphQLClient = get_naver_graphql_client()

        # Mock proxy manager - 현재 구현은 get_fresh_proxy() 사용
        mock_proxy_manager = MagicMock()
        mock_proxy_manager.is_available = True
        mock_proxy_manager.get_fresh_proxy.return_value = "http://proxy:8080"

        client = NaverGraphQLClient(proxy_manager=mock_proxy_manager)

        # Mock session
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"data": {"schedule": None}})

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        client._session = mock_session

        # Execute query
        with patch.object(client, '_ensure_session', return_value=mock_session):
            await client._do_execute_query("query", {}, "test")

        assert client._last_used_proxy == "http://proxy:8080"

    @pytest.mark.asyncio
    async def test_last_used_proxy_none_when_no_proxy_manager(self):
        """프록시 매니저가 없을 때 _last_used_proxy는 None이어야 함"""
        NaverGraphQLClient = get_naver_graphql_client()
        client = NaverGraphQLClient(proxy_manager=None)

        # Mock session
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"data": {"schedule": None}})

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        client._session = mock_session

        with patch.object(client, '_ensure_session', return_value=mock_session):
            await client._do_execute_query("query", {}, "test")

        assert client._last_used_proxy is None


def get_dual_check_result():
    from app.modules.naver_booking.services.graphql_client import DualCheckResult
    return DualCheckResult


class TestAnonymousMonitorProxyPropagation:
    """AnonymousMonitor 프록시 정보 전파 테스트"""

    @pytest.mark.asyncio
    async def test_check_availability_propagates_proxy_url(self):
        """check_availability가 proxy_url을 전파해야 함"""
        ScheduleInfo = get_schedule_info()
        DualCheckResult = get_dual_check_result()
        AnonymousMonitor = get_anonymous_monitor()

        mock_client = MagicMock()
        mock_client._last_used_proxy = "http://proxy:8080"

        # Mock schedule info with proxy_url
        mock_schedule = ScheduleInfo(
            business_id="123",
            biz_item_id="456",
            available_dates=["2025-12-11"],
            slots=[],
            slots_by_date={"2025-12-11": []},
            proxy_url="http://proxy:8080"
        )

        # Mock DualCheckResult
        mock_dual_result = DualCheckResult(
            can_book=False,
            schedule=mock_schedule,
            has_slots=False,
            http_ok=True,
            http_checked=True,
            error_reason=None
        )
        mock_client.fetch_schedule_dual = AsyncMock(return_value=mock_dual_result)

        monitor = AnonymousMonitor(client=mock_client)
        result = await monitor._do_check(
            business_type_id=1,
            business_id="123",
            biz_item_id="456",
            target_date="2025-12-11"
        )

        assert result.proxy_url == "http://proxy:8080"

    @pytest.mark.asyncio
    async def test_check_availability_none_when_no_schedule(self):
        """schedule이 None일 때 proxy_url도 None이어야 함"""
        DualCheckResult = get_dual_check_result()
        AnonymousMonitor = get_anonymous_monitor()

        mock_client = MagicMock()
        mock_client._last_used_proxy = None

        # Mock DualCheckResult with no schedule
        mock_dual_result = DualCheckResult(
            can_book=False,
            schedule=None,
            has_slots=False,
            http_ok=False,
            http_checked=True,
            error_reason="graphql_failed"
        )
        mock_client.fetch_schedule_dual = AsyncMock(return_value=mock_dual_result)

        monitor = AnonymousMonitor(client=mock_client)
        result = await monitor._do_check(
            business_type_id=1,
            business_id="123",
            biz_item_id="456",
            target_date="2025-12-11"
        )

        assert result.proxy_url is None
        assert result.available is False


class TestEventLoggerProxyParameter:
    """EventLogger.log_monitoring_event proxy_url 파라미터 테스트"""

    # RIGHT: 정상 케이스
    @patch('app.services.event_logger.SessionLocal')
    def test_log_monitoring_event_accepts_proxy_url(self, mock_session_local):
        """log_monitoring_event가 proxy_url 파라미터를 받아야 함"""
        EventLogger = get_event_logger()

        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        # Should not raise
        EventLogger.log_monitoring_event(
            schedule_id=1,
            event_type="check",
            status="no_slots",
            proxy_url="http://proxy:8080"
        )

        # Verify MonitoringEvent was created with proxy_url
        mock_db.add.assert_called_once()
        event = mock_db.add.call_args[0][0]
        assert event.proxy_url == "http://proxy:8080"

    @patch('app.services.event_logger.SessionLocal')
    def test_log_monitoring_event_proxy_url_default_none(self, mock_session_local):
        """proxy_url 기본값은 None이어야 함"""
        EventLogger = get_event_logger()

        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        EventLogger.log_monitoring_event(
            schedule_id=1,
            event_type="check",
            status="no_slots"
        )

        event = mock_db.add.call_args[0][0]
        assert event.proxy_url is None


class TestMonitoringEventModel:
    """MonitoringEvent 모델 테스트"""

    # RIGHT: 정상 케이스
    def test_monitoring_event_has_proxy_url_column(self):
        """MonitoringEvent 모델에 proxy_url 컬럼이 있어야 함"""
        MonitoringEvent = get_monitoring_event_model()
        event = MonitoringEvent(
            schedule_id=1,
            event_type="check",
            status="no_slots",
            proxy_url="http://proxy:8080"
        )
        assert event.proxy_url == "http://proxy:8080"

    def test_monitoring_event_proxy_url_nullable(self):
        """proxy_url은 nullable이어야 함"""
        MonitoringEvent = get_monitoring_event_model()
        event = MonitoringEvent(
            schedule_id=1,
            event_type="check",
            status="no_slots"
        )
        assert event.proxy_url is None


class TestMonitoringEventSchema:
    """MonitoringEvent Pydantic 스키마 테스트"""

    # RIGHT: 정상 케이스
    def test_schema_has_proxy_url_field(self):
        """스키마에 proxy_url 필드가 있어야 함"""
        MonitoringEventBase = get_monitoring_event_schema()
        schema = MonitoringEventBase(
            event_type="check",
            status="no_slots",
            proxy_url="http://proxy:8080"
        )
        assert schema.proxy_url == "http://proxy:8080"

    def test_schema_proxy_url_default_none(self):
        """proxy_url 기본값은 None이어야 함"""
        MonitoringEventBase = get_monitoring_event_schema()
        schema = MonitoringEventBase(
            event_type="check",
            status="no_slots"
        )
        assert schema.proxy_url is None

    # BOUNDARY: 경계 조건
    def test_schema_accepts_various_proxy_formats(self):
        """다양한 프록시 URL 형식을 허용해야 함"""
        MonitoringEventBase = get_monitoring_event_schema()
        formats = [
            "http://1.2.3.4:8080",
            "https://proxy.example.com:443",
            "socks5://user:pass@proxy:1080",
            "",  # 빈 문자열
            None,  # None
        ]
        for proxy_url in formats:
            schema = MonitoringEventBase(
                event_type="check",
                status="no_slots",
                proxy_url=proxy_url
            )
            assert schema.proxy_url == proxy_url


class TestCrossCheck:
    """교차 검증 테스트 (CROSS-CHECK)"""

    def test_all_layers_have_consistent_proxy_url_field(self):
        """모든 레이어에서 proxy_url 필드가 일관되게 존재해야 함"""
        MonitoringEvent = get_monitoring_event_model()
        MonitoringEventBase = get_monitoring_event_schema()
        ScheduleInfo = get_schedule_info()
        AvailabilityResult = get_availability_result()

        # Model
        assert hasattr(MonitoringEvent, 'proxy_url')

        # Schema
        schema = MonitoringEventBase(event_type="check", status="no_slots")
        assert hasattr(schema, 'proxy_url')

        # ScheduleInfo dataclass
        info = ScheduleInfo(business_id="1", biz_item_id="2", available_dates=[], slots=[])
        assert hasattr(info, 'proxy_url')

        # AvailabilityResult dataclass
        result = AvailabilityResult(available=False, slots=[])
        assert hasattr(result, 'proxy_url')


class TestErrorConditions:
    """에러 조건 테스트 (ERROR)"""

    @pytest.mark.asyncio
    async def test_proxy_url_none_on_api_error(self):
        """API 에러 시에도 proxy_url이 처리되어야 함"""
        AnonymousMonitor = get_anonymous_monitor()

        mock_client = AsyncMock()
        mock_client.fetch_schedule = AsyncMock(side_effect=Exception("API Error"))

        monitor = AnonymousMonitor(client=mock_client)

        # Should handle error gracefully
        result = await monitor.check_availability(
            business_type_id=1,
            business_id="123",
            biz_item_id="456",
            target_date="2025-12-11",
            use_cache=False
        )

        assert result.available is False
        assert result.error is not None
        # proxy_url은 기본값 None
        assert result.proxy_url is None
