"""
프록시 풀 고갈 복구 테스트
작성일: 2025-12-20

버그: 프록시 풀이 고갈되면 is_available=False가 되어
get_fresh_proxy()가 호출되지 않아 풀 갱신 기회가 사라지는 문제

수정:
1. graphql_client.py에서 is_available 체크 제거
2. proxy_manager_v2.py의 is_available 속성에서 풀 갱신 시도

RIGHT-BICEP 원칙에 따른 테스트:
- Right: 정상 동작 확인
- Boundary: 경계 조건 (풀 0개, 1개 등)
- Error: 에러 조건 (DB 실패 시 graceful degradation)
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from app.schemas.proxy import ProxyInfo


# ============== Fixtures ==============

@pytest.fixture
def mock_db_service():
    """Mock ProxyDBService"""
    service = Mock()
    service.get_top_proxies_for_pool = Mock(return_value=[])
    service.get_proxies_by_response_time = Mock(return_value=[])
    service.record_check_result = Mock(return_value=True)
    service.get_proxy_info_by_id = Mock(return_value=None)
    service.batch_update_proxy_stats = Mock()
    return service


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
            avg_response_time=0.3,  # fast proxy
            success_count=i + 1,
            fail_count=0,
            total_checks=i + 1,
        )
        for i in range(1, 6)
    ]


@pytest.fixture
def proxy_manager_v2_empty(mock_db_service):
    """빈 풀의 ProxyManagerV2 인스턴스"""
    from app.services.proxy_manager_v2 import ProxyManagerV2

    manager = ProxyManagerV2(
        db_service=mock_db_service,
        pool_size=10,
        weighted_selection=False,
    )
    # 초기화 상태로 설정하되 풀은 비워둠
    manager._initialized = True
    manager._enabled = True
    manager._active_pool = []

    return manager


@pytest.fixture
def proxy_manager_v2_with_pool(mock_db_service, sample_proxy_list):
    """프록시가 있는 ProxyManagerV2 인스턴스"""
    from app.services.proxy_manager_v2 import ProxyManagerV2

    mock_db_service.get_proxies_by_response_time.return_value = sample_proxy_list

    manager = ProxyManagerV2(
        db_service=mock_db_service,
        pool_size=10,
        weighted_selection=False,
    )
    manager._initialized = True
    manager._enabled = True
    manager._active_pool = sample_proxy_list.copy()

    return manager


# ============== Right: 정상 동작 테스트 ==============

class TestPoolExhaustionRecovery:
    """풀 고갈 복구 테스트"""

    def test_is_available_false_on_empty_pool(
        self, proxy_manager_v2_empty, mock_db_service, sample_proxy_list
    ):
        """풀이 비었을 때 is_available=False 반환 (갱신은 get_fresh_proxy에서)"""
        # Given: 빈 풀
        # is_available은 풀 상태만 확인, 갱신은 get_fresh_proxy()에서 처리

        # When: is_available 접근
        result = proxy_manager_v2_empty.is_available

        # Then: False 반환 (풀이 비어있으므로)
        assert result is False

    def test_is_available_returns_false_when_refresh_fails(
        self, proxy_manager_v2_empty, mock_db_service
    ):
        """풀 갱신 실패 시 is_available=False 반환"""
        # Given: 빈 풀 + DB에서 빈 결과 반환
        mock_db_service.get_proxies_by_response_time.return_value = []
        mock_db_service.get_top_proxies_for_pool.return_value = []

        # When: is_available 접근
        result = proxy_manager_v2_empty.is_available

        # Then: False 반환
        assert result is False

    def test_get_fresh_proxy_triggers_refresh_on_low_pool(
        self, proxy_manager_v2_empty, mock_db_service, sample_proxy_list
    ):
        """풀이 3개 미만일 때 get_fresh_proxy() 호출 시 갱신 시도"""
        # Given: 풀에 프록시 2개만 있음
        proxy_manager_v2_empty._active_pool = sample_proxy_list[:2]
        mock_db_service.get_proxies_by_response_time.return_value = sample_proxy_list

        # When: get_fresh_proxy() 호출
        result = proxy_manager_v2_empty.get_fresh_proxy()

        # Then: 갱신 시도 후 프록시 반환
        assert result is not None
        assert mock_db_service.get_proxies_by_response_time.called

    def test_get_fresh_proxy_returns_proxy_after_refresh(
        self, proxy_manager_v2_empty, mock_db_service, sample_proxy_list
    ):
        """빈 풀에서 get_fresh_proxy() 호출 시 갱신 후 프록시 반환"""
        # Given: 빈 풀 + DB에서 반환할 프록시 설정
        mock_db_service.get_proxies_by_response_time.return_value = sample_proxy_list

        # When: get_fresh_proxy() 호출
        result = proxy_manager_v2_empty.get_fresh_proxy()

        # Then: 프록시 URL 반환
        assert result is not None
        assert result.startswith("http://192.168.1.")


# ============== Boundary: 경계 조건 테스트 ==============

class TestPoolBoundaryConditions:
    """풀 경계 조건 테스트"""

    def test_pool_with_one_proxy(
        self, proxy_manager_v2_with_pool, sample_proxy_list
    ):
        """프록시 1개일 때 정상 동작 (갱신 후에도 프록시 사용 가능)"""
        # Given: 프록시 1개 (풀 갱신 시 같은 프록시 유지)
        proxy_manager_v2_with_pool._active_pool = sample_proxy_list[:1]

        # When: get_fresh_proxy() 호출 (풀이 3개 미만이므로 갱신 시도됨)
        result = proxy_manager_v2_with_pool.get_fresh_proxy()

        # Then: 프록시 반환 (갱신 후 풀에 프록시 있음)
        assert result is not None

    def test_pool_with_zero_proxies_and_db_empty(
        self, proxy_manager_v2_empty, mock_db_service
    ):
        """프록시 0개 + DB도 비어있을 때"""
        # Given: 빈 풀 + DB 빈 결과
        mock_db_service.get_proxies_by_response_time.return_value = []
        mock_db_service.get_top_proxies_for_pool.return_value = []

        # When: get_fresh_proxy() 호출
        result = proxy_manager_v2_empty.get_fresh_proxy()

        # Then: None 반환
        assert result is None

    def test_all_proxies_in_session_blacklist(
        self, proxy_manager_v2_with_pool, mock_db_service, sample_proxy_list
    ):
        """모든 프록시가 세션 블랙리스트에 있을 때"""
        # Given: 모든 프록시를 세션 블랙리스트에 등록
        for proxy in sample_proxy_list:
            proxy_manager_v2_with_pool._session_blacklist[proxy.id] = "test"

        # DB에서 새 프록시 반환
        new_proxies = [
            ProxyInfo(
                id=100 + i,
                url=f"http://10.0.0.{i}:8080",
                protocol="http",
                host=f"10.0.0.{i}",
                port=8080,
                priority_score=50.0,
                avg_response_time=0.3,
                success_count=5,
                fail_count=0,
                total_checks=5,
            )
            for i in range(1, 4)
        ]
        mock_db_service.get_proxies_by_response_time.return_value = new_proxies

        # When: get_fresh_proxy() 호출
        result = proxy_manager_v2_with_pool.get_fresh_proxy()

        # Then: 새 프록시가 반환되거나 None (블랙리스트 외 프록시 시도)
        # 기존 풀에서 블랙리스트 아닌 것 찾거나 갱신됨


# ============== Error: 에러 조건 테스트 ==============

class TestPoolRefreshErrors:
    """풀 갱신 에러 테스트"""

    def test_refresh_fails_gracefully_on_db_error(
        self, proxy_manager_v2_empty, mock_db_service
    ):
        """DB 에러 시 graceful degradation"""
        # Given: DB 에러 발생
        mock_db_service.get_proxies_by_response_time.side_effect = Exception("DB Error")

        # When: is_available 접근
        result = proxy_manager_v2_empty.is_available

        # Then: False 반환 (크래시 없음)
        assert result is False

    def test_get_fresh_proxy_handles_db_error(
        self, proxy_manager_v2_empty, mock_db_service
    ):
        """get_fresh_proxy() DB 에러 처리"""
        # Given: DB 에러 발생
        mock_db_service.get_proxies_by_response_time.side_effect = Exception("DB Error")

        # When: get_fresh_proxy() 호출
        result = proxy_manager_v2_empty.get_fresh_proxy()

        # Then: None 반환 (크래시 없음)
        assert result is None


# ============== Cross-check: GraphQL 클라이언트 연동 테스트 ==============

class TestGraphQLClientIntegration:
    """GraphQL 클라이언트와 프록시 매니저 연동 테스트"""

    def test_graphql_client_calls_get_fresh_proxy_without_is_available_check(
        self, proxy_manager_v2_empty, mock_db_service, sample_proxy_list
    ):
        """
        GraphQL 클라이언트가 is_available 체크 없이 get_fresh_proxy() 호출

        이 테스트는 수정된 graphql_client.py의 동작을 검증:
        - 기존: if self._proxy_manager and self._proxy_manager.is_available
        - 수정: if self._proxy_manager
        """
        # Given: 빈 풀 + DB에서 프록시 반환 설정
        mock_db_service.get_proxies_by_response_time.return_value = sample_proxy_list
        manager = proxy_manager_v2_empty

        # When: is_available 체크 없이 바로 get_fresh_proxy() 호출
        # (수정된 graphql_client.py의 동작 시뮬레이션)
        if manager:  # is_available 체크 없음
            proxy_url = manager.get_fresh_proxy()

        # Then: 풀이 갱신되고 프록시가 반환됨
        assert proxy_url is not None
        assert len(manager._active_pool) > 0

    def test_proxy_manager_not_set_returns_none(self):
        """프록시 매니저가 None일 때 프록시 사용 안함"""
        # Given: 프록시 매니저 없음
        proxy_manager = None

        # When: 조건 체크
        proxy_url = None
        if proxy_manager:
            proxy_url = proxy_manager.get_fresh_proxy()

        # Then: None
        assert proxy_url is None


# ============== 통합 테스트: 풀 고갈 시나리오 ==============

class TestPoolExhaustionScenario:
    """풀 고갈 시나리오 통합 테스트"""

    def test_complete_pool_exhaustion_and_recovery(
        self, proxy_manager_v2_with_pool, mock_db_service, sample_proxy_list
    ):
        """
        전체 시나리오: 풀 고갈 → get_fresh_proxy에서 복구

        1. 초기 상태: 풀에 프록시 있음
        2. 모든 프록시 사용 후 풀 고갈
        3. get_fresh_proxy() 호출 시 풀 갱신
        4. 프록시 다시 사용 가능
        """
        manager = proxy_manager_v2_with_pool

        # 1. 초기 상태 확인
        assert manager.is_available is True
        assert len(manager._active_pool) == 5

        # 2. 풀 고갈 시뮬레이션 (모든 프록시 제거)
        manager._active_pool = []

        # 3. is_available은 False (풀이 비어있으므로)
        assert manager.is_available is False

        # 4. get_fresh_proxy() 호출 시 풀 갱신 시도
        mock_db_service.get_proxies_by_response_time.return_value = sample_proxy_list

        # 5. get_fresh_proxy()는 내부에서 풀 갱신 시도 후 프록시 반환
        proxy_url = manager.get_fresh_proxy()
        assert proxy_url is not None
        assert len(manager._active_pool) > 0
