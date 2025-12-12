"""
ProxyManagerV2 테스트
작성일: 2025-12-11

RIGHT-BICEP 원칙에 따른 테스트:
- Right: 정상 동작 확인
- Boundary: 경계 조건 확인
- Inverse: 역관계 확인
- Cross-check: 교차 검증
- Error: 에러 조건 확인
- Performance: 성능 특성 확인
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.schemas.proxy import ProxyInfo, ValidationResult


# ============== Fixtures ==============

@pytest.fixture
def mock_db_service():
    """Mock ProxyDBService"""
    service = Mock()
    service.get_top_proxies_for_pool = Mock(return_value=[])
    service.record_check_result = Mock(return_value=True)
    service.get_proxy_info_by_id = Mock(return_value=None)
    return service


@pytest.fixture
def sample_proxy_info():
    """샘플 ProxyInfo"""
    return ProxyInfo(
        id=1,
        url="http://192.168.1.1:8080",
        protocol="http",
        host="192.168.1.1",
        port=8080,
        priority_score=50.0,
        avg_response_time=1.5,
        success_count=10,
        fail_count=0,
        total_checks=10,
    )


@pytest.fixture
def sample_proxy_list():
    """샘플 프록시 목록"""
    return [
        ProxyInfo(
            id=i,
            url=f"http://192.168.1.{i}:8080",
            protocol="http",
            host=f"192.168.1.{i}",
            port=8080,
            priority_score=i * 10.0,
            avg_response_time=0.5 + i * 0.1,
            success_count=i + 1,
            fail_count=0,
            total_checks=i + 1,
        )
        for i in range(1, 6)
    ]


@pytest.fixture
def proxy_manager_v2(mock_db_service, sample_proxy_list):
    """ProxyManagerV2 인스턴스"""
    from app.services.proxy_manager_v2 import ProxyManagerV2

    mock_db_service.get_top_proxies_for_pool.return_value = sample_proxy_list

    manager = ProxyManagerV2(
        db_service=mock_db_service,
        pool_size=10,
        min_success_rate=0.5,
        pool_refresh_interval=300,
        adaptive_timeout_enabled=True,
        adaptive_timeout_multiplier=2.0,
        adaptive_timeout_min=3.0,
        adaptive_timeout_max=10.0,
        weighted_selection=True,
    )
    return manager


# ============== ProxyInfo Tests ==============

class TestProxyInfo:
    """ProxyInfo 데이터 클래스 테스트"""

    def test_right_to_aiohttp_proxy(self, sample_proxy_info):
        """[Right] aiohttp 프록시 URL 생성"""
        result = sample_proxy_info.to_aiohttp_proxy()
        assert result == "http://192.168.1.1:8080"

    def test_right_to_aiohttp_proxy_with_auth(self):
        """[Right] 인증 정보가 있는 aiohttp 프록시 URL"""
        proxy = ProxyInfo(
            id=1,
            url="http://user:pass@192.168.1.1:8080",
            protocol="http",
            host="192.168.1.1",
            port=8080,
            username="user",
            password="pass",
        )
        result = proxy.to_aiohttp_proxy()
        assert result == "http://user:pass@192.168.1.1:8080"

    def test_right_to_playwright_proxy(self, sample_proxy_info):
        """[Right] Playwright 프록시 설정 생성"""
        result = sample_proxy_info.to_playwright_proxy()
        assert result == {"server": "http://192.168.1.1:8080"}

    def test_right_to_playwright_proxy_with_auth(self):
        """[Right] 인증 정보가 있는 Playwright 프록시 설정"""
        proxy = ProxyInfo(
            id=1,
            url="http://user:pass@192.168.1.1:8080",
            protocol="http",
            host="192.168.1.1",
            port=8080,
            username="user",
            password="pass",
        )
        result = proxy.to_playwright_proxy()
        assert result == {
            "server": "http://192.168.1.1:8080",
            "username": "user",
            "password": "pass",
        }

    def test_right_success_rate(self, sample_proxy_info):
        """[Right] 성공률 계산"""
        assert sample_proxy_info.success_rate == 1.0  # 10/10

    def test_boundary_success_rate_no_checks(self):
        """[Boundary] 검증 없는 경우 성공률"""
        proxy = ProxyInfo(
            id=1,
            url="http://192.168.1.1:8080",
            protocol="http",
            host="192.168.1.1",
            port=8080,
            total_checks=0,
        )
        assert proxy.success_rate is None


# ============== ProxyManagerV2 Tests ==============

class TestProxyManagerV2Init:
    """ProxyManagerV2 초기화 테스트"""

    def test_right_init(self, mock_db_service):
        """[Right] 초기화 정상 동작"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        manager = ProxyManagerV2(
            db_service=mock_db_service,
            pool_size=10,
        )

        assert manager._pool_size == 10
        assert manager._initialized is False
        assert manager.is_available is False

    @pytest.mark.asyncio
    async def test_right_initialize(self, proxy_manager_v2, sample_proxy_list):
        """[Right] 초기화 및 풀 로드"""
        result = await proxy_manager_v2.initialize()

        assert result is True
        assert proxy_manager_v2.is_initialized is True
        assert proxy_manager_v2.is_available is True
        assert proxy_manager_v2.pool_size == len(sample_proxy_list)

    @pytest.mark.asyncio
    async def test_error_initialize_empty_pool(self, mock_db_service):
        """[Error] 빈 풀로 초기화 (에러는 아니지만 풀이 비어있음)"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        mock_db_service.get_top_proxies_for_pool.return_value = []

        manager = ProxyManagerV2(db_service=mock_db_service)
        result = await manager.initialize()

        # 초기화 자체는 성공하지만 풀이 비어있음
        assert result is True
        assert manager.is_initialized is True
        assert manager.pool_size == 0
        assert manager.is_available is False  # 풀이 비어있으므로 사용 불가


class TestProxySelection:
    """프록시 선택 테스트"""

    @pytest.mark.asyncio
    async def test_right_get_next_proxy(self, proxy_manager_v2):
        """[Right] 프록시 선택"""
        await proxy_manager_v2.initialize()

        proxy = proxy_manager_v2.get_next_proxy()

        assert proxy is not None
        assert isinstance(proxy, ProxyInfo)

    @pytest.mark.asyncio
    async def test_right_weighted_selection(self, proxy_manager_v2):
        """[Right] 가중치 기반 선택 (높은 점수 프록시가 더 자주 선택됨)"""
        await proxy_manager_v2.initialize()

        selection_counts = {}
        for _ in range(1000):
            proxy = proxy_manager_v2.get_next_proxy()
            selection_counts[proxy.id] = selection_counts.get(proxy.id, 0) + 1

        # 높은 점수 프록시(id=5, score=50)가 낮은 점수 프록시(id=1, score=10)보다 더 자주 선택
        # 통계적으로 대략 5배 차이가 나야 함
        assert selection_counts.get(5, 0) > selection_counts.get(1, 0)

    @pytest.mark.asyncio
    async def test_right_round_robin_selection(self, mock_db_service, sample_proxy_list):
        """[Right] 라운드 로빈 선택"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        mock_db_service.get_top_proxies_for_pool.return_value = sample_proxy_list

        manager = ProxyManagerV2(
            db_service=mock_db_service,
            weighted_selection=False,
        )
        await manager.initialize()

        # 순서대로 선택되어야 함
        first = manager.get_next_proxy()
        second = manager.get_next_proxy()
        third = manager.get_next_proxy()

        assert first.id != second.id
        assert second.id != third.id

    def test_boundary_get_next_proxy_empty_pool(self, mock_db_service):
        """[Boundary] 빈 풀에서 선택"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        mock_db_service.get_top_proxies_for_pool.return_value = []

        manager = ProxyManagerV2(db_service=mock_db_service)

        proxy = manager.get_next_proxy()
        assert proxy is None


class TestAdaptiveTimeout:
    """적응형 타임아웃 테스트"""

    @pytest.mark.asyncio
    async def test_right_get_timeout_for_proxy(self, proxy_manager_v2, sample_proxy_info):
        """[Right] 프록시별 타임아웃 계산"""
        await proxy_manager_v2.initialize()

        # avg_response_time=1.5, multiplier=2.0 -> 3.0
        timeout = proxy_manager_v2.get_timeout_for_proxy(sample_proxy_info)

        assert timeout == 3.0  # 1.5 * 2 = 3.0, min은 3.0

    def test_boundary_timeout_min(self, mock_db_service):
        """[Boundary] 최소 타임아웃"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        manager = ProxyManagerV2(
            db_service=mock_db_service,
            adaptive_timeout_min=3.0,
            adaptive_timeout_multiplier=2.0,
        )

        proxy = ProxyInfo(
            id=1, url="http://test:8080", protocol="http",
            host="test", port=8080, avg_response_time=0.5,  # 0.5 * 2 = 1.0 < 3.0
        )

        timeout = manager.get_timeout_for_proxy(proxy)
        assert timeout == 3.0  # 최소값 적용

    def test_boundary_timeout_max(self, mock_db_service):
        """[Boundary] 최대 타임아웃"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        manager = ProxyManagerV2(
            db_service=mock_db_service,
            adaptive_timeout_max=10.0,
            adaptive_timeout_multiplier=2.0,
        )

        proxy = ProxyInfo(
            id=1, url="http://test:8080", protocol="http",
            host="test", port=8080, avg_response_time=8.0,  # 8.0 * 2 = 16.0 > 10.0
        )

        timeout = manager.get_timeout_for_proxy(proxy)
        assert timeout == 10.0  # 최대값 적용

    def test_boundary_timeout_no_avg(self, mock_db_service):
        """[Boundary] 평균 응답시간 없는 경우"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        manager = ProxyManagerV2(
            db_service=mock_db_service,
            adaptive_timeout_max=10.0,
        )

        proxy = ProxyInfo(
            id=1, url="http://test:8080", protocol="http",
            host="test", port=8080, avg_response_time=None,
        )

        timeout = manager.get_timeout_for_proxy(proxy)
        assert timeout == 5.0  # 기본값 (max / 2)

    def test_right_disabled_adaptive_timeout(self, mock_db_service):
        """[Right] 적응형 타임아웃 비활성화"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        manager = ProxyManagerV2(
            db_service=mock_db_service,
            adaptive_timeout_enabled=False,
            adaptive_timeout_max=10.0,
        )

        proxy = ProxyInfo(
            id=1, url="http://test:8080", protocol="http",
            host="test", port=8080, avg_response_time=1.0,
        )

        timeout = manager.get_timeout_for_proxy(proxy)
        assert timeout == 5.0  # max / 2 반환


class TestReportResults:
    """결과 보고 테스트"""

    @pytest.mark.asyncio
    async def test_right_report_success(self, proxy_manager_v2, sample_proxy_info):
        """[Right] 성공 보고"""
        await proxy_manager_v2.initialize()
        proxy_manager_v2._active_pool = [sample_proxy_info]

        await proxy_manager_v2.report_success(
            proxy=sample_proxy_info,
            response_time=1.0,
            detected_ip="1.2.3.4",
        )

        # DB 서비스 호출 확인
        proxy_manager_v2._db_service.record_check_result.assert_called_once_with(
            proxy_id=sample_proxy_info.id,
            is_valid=True,
            response_time=1.0,
            detected_ip="1.2.3.4",
            is_anonymous=None,
        )

        # 로컬 캐시 업데이트 확인
        assert sample_proxy_info.success_count == 11  # 10 + 1
        assert sample_proxy_info.fail_count == 0

    @pytest.mark.asyncio
    async def test_right_report_failure(self, proxy_manager_v2, sample_proxy_info):
        """[Right] 실패 보고"""
        await proxy_manager_v2.initialize()
        proxy_manager_v2._active_pool = [sample_proxy_info]

        await proxy_manager_v2.report_failure(
            proxy=sample_proxy_info,
            error_type="timeout",
            error_message="Connection timed out",
        )

        # DB 서비스 호출 확인
        proxy_manager_v2._db_service.record_check_result.assert_called_once_with(
            proxy_id=sample_proxy_info.id,
            is_valid=False,
            error_type="timeout",
            error_message="Connection timed out",
            http_status=None,
        )

        # 로컬 캐시 업데이트 확인
        assert sample_proxy_info.fail_count == 1

    @pytest.mark.asyncio
    async def test_right_consecutive_failures_remove_from_pool(self, proxy_manager_v2, sample_proxy_info):
        """[Right] 연속 실패 시 풀에서 제거"""
        await proxy_manager_v2.initialize()
        proxy_manager_v2._active_pool = [sample_proxy_info]

        # 3번 연속 실패
        for _ in range(3):
            await proxy_manager_v2.report_failure(
                proxy=sample_proxy_info,
                error_type="timeout",
                error_message="Timed out",
            )

        # 풀에서 제거됨
        assert sample_proxy_info not in proxy_manager_v2._active_pool


class TestProxyUrls:
    """프록시 URL 반환 테스트"""

    @pytest.mark.asyncio
    async def test_right_get_aiohttp_proxy(self, proxy_manager_v2):
        """[Right] aiohttp 프록시 URL 반환"""
        await proxy_manager_v2.initialize()

        url = proxy_manager_v2.get_aiohttp_proxy()

        assert url is not None
        assert url.startswith("http://")

    @pytest.mark.asyncio
    async def test_right_get_playwright_proxy(self, proxy_manager_v2):
        """[Right] Playwright 프록시 설정 반환"""
        await proxy_manager_v2.initialize()

        config = proxy_manager_v2.get_playwright_proxy()

        assert config is not None
        assert "server" in config

    def test_boundary_get_aiohttp_proxy_empty(self, mock_db_service):
        """[Boundary] 빈 풀에서 aiohttp 프록시 URL"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        mock_db_service.get_top_proxies_for_pool.return_value = []
        manager = ProxyManagerV2(db_service=mock_db_service)

        url = manager.get_aiohttp_proxy()
        assert url is None


class TestEnableDisable:
    """활성화/비활성화 테스트"""

    @pytest.mark.asyncio
    async def test_right_enable_disable(self, proxy_manager_v2):
        """[Right] 활성화/비활성화"""
        await proxy_manager_v2.initialize()

        assert proxy_manager_v2._enabled is True

        proxy_manager_v2.disable()
        assert proxy_manager_v2._enabled is False
        assert proxy_manager_v2.is_available is False

        proxy_manager_v2.enable()
        assert proxy_manager_v2._enabled is True
        assert proxy_manager_v2.is_available is True


class TestGetStatus:
    """상태 조회 테스트"""

    @pytest.mark.asyncio
    async def test_right_get_status(self, proxy_manager_v2):
        """[Right] 상태 정보 반환"""
        await proxy_manager_v2.initialize()

        status = proxy_manager_v2.get_status()

        assert "enabled" in status
        assert "initialized" in status
        assert "pool_size" in status
        assert "proxies" in status
        assert status["enabled"] is True
        assert status["initialized"] is True
        # pool_size는 실제 로드된 프록시 수
        assert status["pool_size"] == proxy_manager_v2.pool_size


class TestMarkFailed:
    """레거시 인터페이스 테스트"""

    @pytest.mark.asyncio
    async def test_right_mark_failed(self, mock_db_service):
        """[Right] mark_failed 레거시 인터페이스"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        # 테스트용 프록시 하나만 생성
        test_proxy = ProxyInfo(
            id=100,
            url="http://test.proxy:8080",
            protocol="http",
            host="test.proxy",
            port=8080,
            priority_score=50.0,
        )
        mock_db_service.get_top_proxies_for_pool.return_value = [test_proxy]

        manager = ProxyManagerV2(db_service=mock_db_service)
        await manager.initialize()

        proxy_url = test_proxy.to_aiohttp_proxy()
        initial_pool_size = manager.pool_size

        # 3번 실패
        for _ in range(3):
            manager.mark_failed(proxy_url, "Connection refused")

        # 풀에서 제거됨
        assert manager.pool_size == initial_pool_size - 1


# ============== ValidationResult Tests ==============

class TestValidationResult:
    """ValidationResult 테스트"""

    def test_right_success_result(self):
        """[Right] 성공 검증 결과"""
        result = ValidationResult(
            is_valid=True,
            response_time=0.5,
            detected_ip="1.2.3.4",
            is_anonymous=True,
        )

        assert result.is_valid is True
        assert result.response_time == 0.5
        assert result.error_type is None

    def test_right_failure_result(self):
        """[Right] 실패 검증 결과"""
        result = ValidationResult(
            is_valid=False,
            error_type="timeout",
            error_message="Connection timed out",
        )

        assert result.is_valid is False
        assert result.error_type == "timeout"
        assert result.response_time is None


# ============== Cross-check Tests ==============

class TestCrossCheck:
    """교차 검증 테스트"""

    @pytest.mark.asyncio
    async def test_cross_check_pool_and_status(self, proxy_manager_v2):
        """[Cross-check] 풀 크기와 상태 일치"""
        await proxy_manager_v2.initialize()

        status = proxy_manager_v2.get_status()

        assert status["pool_size"] == len(proxy_manager_v2._active_pool)
        assert status["pool_size"] == len(status["proxies"])

    @pytest.mark.asyncio
    async def test_inverse_success_increases_count(self, proxy_manager_v2, sample_proxy_info):
        """[Inverse] 성공 시 카운트 증가"""
        await proxy_manager_v2.initialize()
        proxy_manager_v2._active_pool = [sample_proxy_info]

        initial_success = sample_proxy_info.success_count
        initial_total = sample_proxy_info.total_checks

        await proxy_manager_v2.report_success(sample_proxy_info, 1.0)

        assert sample_proxy_info.success_count == initial_success + 1
        assert sample_proxy_info.total_checks == initial_total + 1


class TestProxyRotation:
    """프록시 로테이션 테스트"""

    @pytest.mark.asyncio
    async def test_right_move_to_back_after_selection(self, proxy_manager_v2):
        """[Right] 선택된 프록시가 풀 뒤로 이동"""
        await proxy_manager_v2.initialize()

        # 라운드 로빈 모드로 변경하여 예측 가능하게
        proxy_manager_v2._weighted_selection = False
        proxy_manager_v2._current_index = 0

        first_proxy = proxy_manager_v2._active_pool[0]
        first_id = first_proxy.id

        # 선택
        selected = proxy_manager_v2.get_next_proxy()
        assert selected.id == first_id

        # 선택된 프록시는 맨 뒤로 이동해야 함
        assert proxy_manager_v2._active_pool[-1].id == first_id
        # 맨 앞은 이제 다른 프록시
        assert proxy_manager_v2._active_pool[0].id != first_id

    @pytest.mark.asyncio
    async def test_right_no_repeat_until_full_rotation(self, mock_db_service):
        """[Right] 전체 로테이션 전까지 동일 프록시 재사용 없음"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        # 5개 프록시 생성
        proxies = [
            ProxyInfo(
                id=i,
                url=f"http://192.168.1.{i}:8080",
                protocol="http",
                host=f"192.168.1.{i}",
                port=8080,
                priority_score=50.0,  # 모두 동일한 점수
            )
            for i in range(1, 6)
        ]
        mock_db_service.get_top_proxies_for_pool.return_value = proxies

        manager = ProxyManagerV2(
            db_service=mock_db_service,
            weighted_selection=False,  # 라운드 로빈으로 예측 가능하게
        )
        await manager.initialize()

        # 5개 프록시를 순서대로 선택
        selected_ids = []
        for _ in range(5):
            proxy = manager.get_next_proxy()
            selected_ids.append(proxy.id)

        # 모두 다른 프록시여야 함
        assert len(set(selected_ids)) == 5

    @pytest.mark.asyncio
    async def test_right_rotation_after_full_cycle(self, mock_db_service):
        """[Right] 전체 순환 후 처음 프록시 재사용"""
        from app.services.proxy_manager_v2 import ProxyManagerV2

        # 3개 프록시 생성
        proxies = [
            ProxyInfo(
                id=i,
                url=f"http://192.168.1.{i}:8080",
                protocol="http",
                host=f"192.168.1.{i}",
                port=8080,
                priority_score=50.0,
            )
            for i in range(1, 4)
        ]
        mock_db_service.get_top_proxies_for_pool.return_value = proxies

        manager = ProxyManagerV2(
            db_service=mock_db_service,
            weighted_selection=False,
        )
        await manager.initialize()

        first_proxy = manager.get_next_proxy()
        first_id = first_proxy.id

        # 나머지 2개 선택
        manager.get_next_proxy()
        manager.get_next_proxy()

        # 4번째 선택은 다시 첫 번째 프록시
        fourth_proxy = manager.get_next_proxy()
        assert fourth_proxy.id == first_id
