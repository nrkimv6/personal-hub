"""
프록시 타임아웃 및 재시도 테스트
작성일: 2025-12-15

RIGHT-BICEP 및 CORRECT 원칙을 따른 테스트케이스

RIGHT:
- Right: 정상 결과 확인
- Boundary: 경계 조건
- Inverse: 역관계
- Cross-check: 교차 검증
- Error: 에러 조건
- Performance: 성능

CORRECT:
- Conformance: 적합성
- Ordering: 순서
- Range: 범위
- Reference: 참조
- Existence: 존재성
- Cardinality: 기수
- Time: 시간
"""

import pytest
import asyncio
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from datetime import datetime

# 테스트 대상
from app.services.proxy_manager import ProxyManager
from app.services.proxy_manager_v2 import ProxyManagerV2
from app.modules.naver_booking.services.graphql_client import (
    PROXY_REQUEST_TIMEOUT,
    DIRECT_REQUEST_TIMEOUT,
)


# ============================================================================
# ProxyManager mark_slow() 테스트
# ============================================================================

class TestProxyManagerMarkSlow:
    """ProxyManager.mark_slow() 4단계 점진적 페널티 테스트"""

    @pytest.fixture
    def proxy_manager(self):
        """테스트용 ProxyManager 인스턴스"""
        pm = ProxyManager(proxy_file=None)
        pm.proxy_list = [
            "http://proxy1.test:8080",
            "http://proxy2.test:8080",
            "http://proxy3.test:8080",
        ]
        pm.active_pool = pm.proxy_list.copy()
        pm._initialized = True
        return pm

    # ---- RIGHT: 정상 결과 확인 ----

    def test_right_mark_slow_stage1_moves_to_back(self, proxy_manager):
        """RIGHT: 1단계 - 풀 맨 뒤로 이동"""
        proxy = "http://proxy1.test:8080"
        initial_pool = proxy_manager.active_pool.copy()

        stage = proxy_manager.mark_slow(proxy, 1.5)

        assert stage == 1
        assert proxy_manager.active_pool[-1] == proxy  # 맨 뒤로 이동
        assert proxy_manager.slow_count[proxy] == 1

    def test_right_mark_slow_stage2_removes_from_pool(self, proxy_manager):
        """RIGHT: 2단계 - 풀에서 제거"""
        proxy = "http://proxy1.test:8080"

        proxy_manager.mark_slow(proxy, 1.5)  # 1단계
        stage = proxy_manager.mark_slow(proxy, 1.5)  # 2단계

        assert stage == 2
        assert proxy not in proxy_manager.active_pool
        assert proxy in proxy_manager.blacklist  # 임시 블랙리스트
        assert proxy_manager.slow_count[proxy] == 2

    def test_right_mark_slow_stage3_session_blacklist(self, proxy_manager):
        """RIGHT: 3단계 - 세션 블랙리스트 등록"""
        proxy = "http://proxy1.test:8080"

        for _ in range(2):
            proxy_manager.mark_slow(proxy, 1.5)  # 1, 2단계
        stage = proxy_manager.mark_slow(proxy, 1.5)  # 3단계

        assert stage == 3
        assert proxy not in proxy_manager.active_pool
        assert proxy in proxy_manager.session_blacklist
        assert proxy_manager.slow_count[proxy] == 3

    def test_right_mark_slow_stage4_db_candidate(self, proxy_manager):
        """RIGHT: 4단계 - DB 기록 대상"""
        proxy = "http://proxy1.test:8080"

        for _ in range(3):
            proxy_manager.mark_slow(proxy, 1.5)  # 1, 2, 3단계
        stage = proxy_manager.mark_slow(proxy, 1.5)  # 4단계

        assert stage == 4
        assert proxy in proxy_manager.session_blacklist
        assert "DB 기록 대상" in proxy_manager.session_blacklist[proxy]
        assert proxy_manager.slow_count[proxy] == 4

    # ---- BICEP-B: 경계값 테스트 ----

    def test_boundary_unknown_proxy_returns_zero(self, proxy_manager):
        """BICEP-B: 알 수 없는 프록시는 0 반환"""
        stage = proxy_manager.mark_slow("http://unknown.test:8080", 1.5)
        assert stage == 0

    def test_boundary_partial_url_match(self, proxy_manager):
        """BICEP-B: 부분 URL 매칭 지원"""
        stage = proxy_manager.mark_slow("proxy1.test:8080", 1.5)
        assert stage == 1  # 부분 매칭으로 찾아야 함

    # ---- BICEP-I: 역관계 테스트 ----

    def test_inverse_stage_progression(self, proxy_manager):
        """BICEP-I: 단계가 항상 증가"""
        proxy = "http://proxy1.test:8080"
        stages = []

        for _ in range(5):
            stage = proxy_manager.mark_slow(proxy, 1.5)
            stages.append(stage)

        assert stages == [1, 2, 3, 4, 4]  # 4단계 이상은 4 유지

    # ---- BICEP-C: 교차검증 테스트 ----

    def test_crosscheck_slow_count_matches_status(self, proxy_manager):
        """BICEP-C: slow_count와 status의 일관성"""
        proxy = "http://proxy1.test:8080"

        proxy_manager.mark_slow(proxy, 1.5)
        proxy_manager.mark_slow(proxy, 1.5)

        status = proxy_manager.get_status()
        assert status["slow_count"] == 1  # 프록시 1개
        assert status["slow_details"][proxy] == 2  # 횟수 2회

    # ---- BICEP-E: 에러 조건 테스트 ----

    def test_error_empty_pool_handles_gracefully(self, proxy_manager):
        """BICEP-E: 빈 풀에서도 정상 동작"""
        proxy_manager.active_pool = []
        proxy = "http://proxy1.test:8080"

        # 예외 없이 실행되어야 함
        stage = proxy_manager.mark_slow(proxy, 1.5)
        assert stage == 1  # proxy_list에는 있으므로

    def test_error_none_proxy_url(self, proxy_manager):
        """BICEP-E: 완전히 다른 URL 처리"""
        # 존재하지 않는 URL은 0 반환
        stage = proxy_manager.mark_slow("http://completely.different.url:9999", 1.5)
        assert stage == 0

    # ---- BICEP-P: 성능 테스트 ----

    def test_performance_multiple_proxies(self, proxy_manager):
        """BICEP-P: 여러 프록시 동시 처리"""
        proxies = proxy_manager.proxy_list.copy()

        for proxy in proxies:
            for _ in range(4):
                proxy_manager.mark_slow(proxy, 1.5)

        # 모든 프록시가 세션 블랙리스트에 있어야 함
        assert len(proxy_manager.session_blacklist) == 3

    # ---- CORRECT-C: 적합성 테스트 ----

    def test_conformance_return_type(self, proxy_manager):
        """CORRECT-C: 반환 타입 확인"""
        stage = proxy_manager.mark_slow("http://proxy1.test:8080", 1.5)
        assert isinstance(stage, int)

    # ---- CORRECT-O: 순서 테스트 ----

    def test_ordering_penalty_stages(self, proxy_manager):
        """CORRECT-O: 페널티 단계 순서 확인"""
        proxy = "http://proxy1.test:8080"

        stage1 = proxy_manager.mark_slow(proxy, 1.5)
        in_pool_after_1 = proxy in proxy_manager.active_pool
        in_blacklist_after_1 = proxy in proxy_manager.blacklist
        in_session_blacklist_after_1 = proxy in proxy_manager.session_blacklist

        stage2 = proxy_manager.mark_slow(proxy, 1.5)
        in_pool_after_2 = proxy in proxy_manager.active_pool
        in_blacklist_after_2 = proxy in proxy_manager.blacklist

        stage3 = proxy_manager.mark_slow(proxy, 1.5)
        in_session_blacklist_after_3 = proxy in proxy_manager.session_blacklist

        # 순서 검증
        assert stage1 < stage2 < stage3
        assert in_pool_after_1 is True  # 1단계: 풀에 있음 (맨 뒤)
        assert in_pool_after_2 is False  # 2단계: 풀에서 제거
        assert in_blacklist_after_2 is True  # 2단계: 임시 블랙리스트
        assert in_session_blacklist_after_3 is True  # 3단계: 세션 블랙리스트

    # ---- CORRECT-R: 범위 테스트 ----

    def test_range_slow_count_positive(self, proxy_manager):
        """CORRECT-R: slow_count는 항상 양수"""
        proxy = "http://proxy1.test:8080"

        for i in range(10):
            proxy_manager.mark_slow(proxy, 1.5)
            assert proxy_manager.slow_count[proxy] == i + 1
            assert proxy_manager.slow_count[proxy] > 0

    # ---- CORRECT-E: 존재성 테스트 ----

    def test_existence_slow_count_initialized(self, proxy_manager):
        """CORRECT-E: slow_count 초기화 확인"""
        assert hasattr(proxy_manager, 'slow_count')
        assert isinstance(proxy_manager.slow_count, dict)
        assert len(proxy_manager.slow_count) == 0

    # ---- CORRECT-C: 기수 테스트 ----

    def test_cardinality_pool_size_after_removals(self, proxy_manager):
        """CORRECT-C: 제거 후 풀 크기 확인"""
        initial_size = len(proxy_manager.active_pool)

        # 모든 프록시를 2단계까지 (풀에서 제거)
        for proxy in proxy_manager.proxy_list.copy():
            proxy_manager.mark_slow(proxy, 1.5)  # 1단계
            proxy_manager.mark_slow(proxy, 1.5)  # 2단계

        assert len(proxy_manager.active_pool) == 0
        assert len(proxy_manager.blacklist) == initial_size

    # ---- CORRECT-T: 시간 테스트 ----

    def test_time_blacklist_duration(self, proxy_manager):
        """CORRECT-T: 블랙리스트 지속 시간 확인"""
        import time

        proxy = "http://proxy1.test:8080"
        proxy_manager.blacklist_duration = 1  # 1초로 설정

        proxy_manager.mark_slow(proxy, 1.5)
        proxy_manager.mark_slow(proxy, 1.5)  # 2단계: 블랙리스트 등록

        assert proxy in proxy_manager.blacklist
        expiry_time = proxy_manager.blacklist[proxy]

        # 만료 시간이 현재 시간 + duration 이내
        assert expiry_time > time.time()
        assert expiry_time < time.time() + 2


# ============================================================================
# ProxyManagerV2 mark_slow() 테스트
# ============================================================================

class TestProxyManagerV2MarkSlow:
    """ProxyManagerV2.mark_slow() 4단계 점진적 페널티 테스트"""

    @pytest.fixture
    def mock_db_service(self):
        """Mock DB 서비스"""
        return Mock()

    @pytest.fixture
    def mock_proxy_info(self):
        """Mock ProxyInfo 객체 생성 함수"""
        def _create(proxy_id, url="http://test:8080"):
            proxy = Mock()
            proxy.id = proxy_id
            proxy.url = url
            proxy.protocol = "http"
            proxy.host = url.split("://")[1].split(":")[0] if "://" in url else "test"
            proxy.port = 8080
            proxy.priority_score = 50.0
            proxy.avg_response_time = 0.5
            proxy.success_rate = 0.9
            proxy.fail_count = 0
            proxy.to_aiohttp_proxy = Mock(return_value=url)
            return proxy
        return _create

    @pytest.fixture
    def proxy_manager_v2(self, mock_db_service, mock_proxy_info):
        """테스트용 ProxyManagerV2 인스턴스"""
        pm = ProxyManagerV2(db_service=mock_db_service, pool_size=10)
        pm._active_pool = [
            mock_proxy_info(1, "http://proxy1.test:8080"),
            mock_proxy_info(2, "http://proxy2.test:8080"),
            mock_proxy_info(3, "http://proxy3.test:8080"),
        ]
        pm._initialized = True
        return pm

    # ---- RIGHT: 정상 결과 확인 ----

    def test_right_mark_slow_stage1_moves_to_back(self, proxy_manager_v2):
        """RIGHT: 1단계 - 풀 맨 뒤로 이동"""
        proxy_url = "http://proxy1.test:8080"
        proxy_id = proxy_manager_v2._active_pool[0].id

        stage = proxy_manager_v2.mark_slow(proxy_url, 1.5)

        assert stage == 1
        assert proxy_manager_v2._active_pool[-1].id == proxy_id
        assert proxy_manager_v2._slow_count[proxy_id] == 1

    def test_right_mark_slow_stage2_removes_from_pool(self, proxy_manager_v2):
        """RIGHT: 2단계 - 풀에서 제거"""
        proxy_url = "http://proxy1.test:8080"
        proxy_id = proxy_manager_v2._active_pool[0].id

        proxy_manager_v2.mark_slow(proxy_url, 1.5)  # 1단계
        stage = proxy_manager_v2.mark_slow(proxy_url, 1.5)  # 2단계

        assert stage == 2
        assert all(p.id != proxy_id for p in proxy_manager_v2._active_pool)
        assert proxy_manager_v2._slow_count[proxy_id] == 2

    def test_right_mark_slow_stage3_excludes_from_next_pool(self, proxy_manager_v2):
        """RIGHT: 3단계 - 다음 풀에서 제외"""
        proxy_url = "http://proxy1.test:8080"
        proxy_id = proxy_manager_v2._active_pool[0].id

        for _ in range(2):
            proxy_manager_v2.mark_slow(proxy_url, 1.5)
        stage = proxy_manager_v2.mark_slow(proxy_url, 1.5)  # 3단계

        assert stage == 3
        assert proxy_id in proxy_manager_v2._slow_proxies
        assert proxy_manager_v2._slow_count[proxy_id] == 3

    def test_right_mark_slow_stage4_db_candidate(self, proxy_manager_v2):
        """RIGHT: 4단계 - DB 기록 대상"""
        proxy_url = "http://proxy1.test:8080"
        proxy_id = proxy_manager_v2._active_pool[0].id

        for _ in range(3):
            proxy_manager_v2.mark_slow(proxy_url, 1.5)
        stage = proxy_manager_v2.mark_slow(proxy_url, 1.5)  # 4단계

        assert stage == 4
        assert proxy_id in proxy_manager_v2._slow_proxies
        assert proxy_manager_v2._slow_count[proxy_id] == 4

    # ---- BICEP-B: 경계값 테스트 ----

    def test_boundary_unknown_proxy_returns_zero(self, proxy_manager_v2):
        """BICEP-B: 알 수 없는 프록시는 0 반환"""
        stage = proxy_manager_v2.mark_slow("http://unknown.test:8080", 1.5)
        assert stage == 0

    # ---- BICEP-C: 교차검증 테스트 ----

    def test_crosscheck_slow_count_matches_status(self, proxy_manager_v2):
        """BICEP-C: slow_count와 status의 일관성"""
        proxy_url = "http://proxy1.test:8080"
        proxy_id = proxy_manager_v2._active_pool[0].id

        proxy_manager_v2.mark_slow(proxy_url, 1.5)
        proxy_manager_v2.mark_slow(proxy_url, 1.5)

        status = proxy_manager_v2.get_status()
        assert status["slow_count_details"][proxy_id] == 2

    # ---- CORRECT-O: 순서 테스트 ----

    def test_ordering_penalty_stages(self, proxy_manager_v2):
        """CORRECT-O: 페널티 단계 순서 확인"""
        proxy_url = "http://proxy1.test:8080"
        stages = []

        for _ in range(5):
            stage = proxy_manager_v2.mark_slow(proxy_url, 1.5)
            stages.append(stage)

        assert stages == [1, 2, 3, 4, 4]


# ============================================================================
# 타임아웃 상수 테스트
# ============================================================================

class TestTimeoutConstants:
    """타임아웃 상수 테스트"""

    def test_proxy_request_timeout_value(self):
        """CORRECT-T: 프록시 요청 타임아웃 값 확인"""
        assert PROXY_REQUEST_TIMEOUT == 1.0

    def test_direct_request_timeout_value(self):
        """CORRECT-T: 직접 연결 타임아웃 값 확인"""
        assert DIRECT_REQUEST_TIMEOUT == 30.0

    def test_proxy_timeout_less_than_direct(self):
        """CORRECT-R: 프록시 타임아웃 < 직접 연결 타임아웃"""
        assert PROXY_REQUEST_TIMEOUT < DIRECT_REQUEST_TIMEOUT


# ============================================================================
# 통합 테스트 (Mock 기반)
# ============================================================================

class TestIntegrationMocked:
    """통합 테스트 (Mock 기반)"""

    def test_mark_slow_called_on_timeout_simulation(self):
        """
        타임아웃 시나리오 시뮬레이션:
        mark_slow가 타임아웃 상황에서 올바르게 동작하는지 확인
        (실제 네트워크 요청 없이 ProxyManager 동작만 테스트)
        """
        # ProxyManager 설정
        pm = ProxyManager(proxy_file=None)
        pm.proxy_list = ["http://slow.proxy:8080"]
        pm.active_pool = pm.proxy_list.copy()
        pm._initialized = True

        # 타임아웃 상황 시뮬레이션 - mark_slow 호출
        proxy = "http://slow.proxy:8080"
        response_time = 1.5  # 타임아웃 시간

        stage = pm.mark_slow(proxy, response_time)

        # 검증
        assert stage == 1  # 첫 번째 호출은 1단계
        assert proxy in pm.slow_count
        assert pm.slow_count[proxy] == 1

    def test_timeout_constants_applied(self):
        """타임아웃 상수가 올바르게 설정되었는지 확인"""
        from app.modules.naver_booking.services.graphql_client import (
            PROXY_REQUEST_TIMEOUT,
            DIRECT_REQUEST_TIMEOUT,
        )

        # 프록시 타임아웃은 1초
        assert PROXY_REQUEST_TIMEOUT == 1.0

        # 직접 연결 타임아웃은 30초
        assert DIRECT_REQUEST_TIMEOUT == 30.0

        # 프록시 타임아웃이 더 짧아야 함
        assert PROXY_REQUEST_TIMEOUT < DIRECT_REQUEST_TIMEOUT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
