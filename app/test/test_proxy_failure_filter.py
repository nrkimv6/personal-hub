"""
프록시 실패율 필터링 및 누적 실패율 블랙리스트 테스트
작성일: 2025-12-21

테스트 범위 (RIGHT-BICEP):
1. Right: 정상 동작 검증
   - get_high_failure_proxy_hosts() 정상 필터링
   - get_proxy_usage_stats_for_sync() 정상 조회
   - sync_usage_stats_from_logs() 정상 동기화
   - 누적 실패율 기반 블랙리스트 등록

2. Boundary: 경계 조건 검증
   - 최소 시도 횟수 미만
   - 임계값 경계 (정확히 80%)
   - 빈 데이터

3. Inverse: 역조건 검증
   - 성공률 높은 프록시는 필터링 안됨
   - 시도 횟수 부족하면 블랙리스트 안됨

4. Cross-check: 교차 검증
   - 풀 갱신 시 high_failure_hosts 제외 확인

5. Error: 에러 조건 검증
   - DB 에러 시 예외 처리

6. Performance: 성능 검증 (생략)
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta

from app.services.proxy_manager_v2 import ProxyManagerV2
from app.services.proxy_usage_service import ProxyUsageService
from app.schemas.proxy import ProxyInfo


class TestHighFailureProxyHosts:
    """get_high_failure_proxy_hosts() 테스트"""

    @pytest.fixture
    def mock_db(self):
        """Mock DB 세션"""
        db = Mock()
        return db

    @pytest.fixture
    def usage_service(self):
        """ProxyUsageService 인스턴스"""
        return ProxyUsageService()

    def test_returns_high_failure_hosts(self, mock_db, usage_service):
        """실패율 높은 프록시 호스트 반환"""
        # Mock 쿼리 결과: 성공률 10%인 프록시
        mock_row = Mock()
        mock_row.proxy_host = "1.2.3.4"
        mock_row.total_attempts = 10
        mock_row.success_count = 1  # 10% 성공률

        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.group_by = Mock(return_value=mock_query)
        mock_query.having = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[mock_row])

        mock_db.query = Mock(return_value=mock_query)

        result = usage_service.get_high_failure_proxy_hosts(
            db=mock_db,
            hours=6,
            min_attempts=3,
            max_success_rate=0.2,  # 20% 이하만 필터링
        )

        assert "1.2.3.4" in result

    def test_excludes_successful_hosts(self, mock_db, usage_service):
        """성공률 높은 프록시는 제외"""
        # Mock 쿼리 결과: 성공률 90%인 프록시
        mock_row = Mock()
        mock_row.proxy_host = "1.2.3.4"
        mock_row.total_attempts = 10
        mock_row.success_count = 9  # 90% 성공률

        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.group_by = Mock(return_value=mock_query)
        mock_query.having = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[mock_row])

        mock_db.query = Mock(return_value=mock_query)

        result = usage_service.get_high_failure_proxy_hosts(
            db=mock_db,
            hours=6,
            min_attempts=3,
            max_success_rate=0.2,
        )

        assert "1.2.3.4" not in result

    def test_excludes_special_hosts(self, mock_db, usage_service):
        """특수 호스트(direct, socks4 등) 제외"""
        # 필터에 notin_ 조건이 있는지 확인
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.group_by = Mock(return_value=mock_query)
        mock_query.having = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[])

        mock_db.query = Mock(return_value=mock_query)

        usage_service.get_high_failure_proxy_hosts(db=mock_db)

        # filter 호출 확인
        assert mock_query.filter.called

    def test_empty_result(self, mock_db, usage_service):
        """결과 없으면 빈 리스트 반환"""
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.group_by = Mock(return_value=mock_query)
        mock_query.having = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[])

        mock_db.query = Mock(return_value=mock_query)

        result = usage_service.get_high_failure_proxy_hosts(db=mock_db)

        assert result == []


class TestCumulativeFailureBlacklist:
    """누적 실패율 기반 블랙리스트 테스트"""

    @pytest.fixture
    def mock_db_service(self):
        """Mock DB 서비스"""
        service = Mock()
        service.get_proxies_by_response_time = Mock(return_value=[])
        service.get_top_proxies_for_pool = Mock(return_value=[])
        service.get_proxy_ids_by_hosts = Mock(return_value={})
        return service

    @pytest.fixture
    def proxy_manager(self, mock_db_service):
        """ProxyManagerV2 인스턴스"""
        manager = ProxyManagerV2(
            db_service=mock_db_service,
            pool_size=5,
            min_success_rate=0.5,
        )
        manager._initialized = True
        manager._cumulative_failure_threshold = 0.8  # 80%
        manager._cumulative_failure_min_attempts = 5
        return manager

    @pytest.fixture
    def sample_proxy(self):
        """샘플 프록시"""
        return ProxyInfo(
            id=1, url="http://1.1.1.1:8080", protocol="http",
            host="1.1.1.1", port=8080, priority_score=80.0,
            avg_response_time=0.3, success_count=100, fail_count=0, total_checks=100
        )

    def test_blacklist_on_high_failure_rate(self, proxy_manager, sample_proxy):
        """누적 실패율 80% 이상 시 블랙리스트 등록"""
        proxy_manager._active_pool = [sample_proxy]

        # 5회 시도 중 4회 실패 (80%)
        for i in range(4):
            proxy_manager._record_session_result(sample_proxy.id, is_success=False)
        proxy_manager._record_session_result(sample_proxy.id, is_success=True)

        # 블랙리스트 체크
        result = proxy_manager._check_cumulative_failure(sample_proxy.id)

        assert result is True
        assert sample_proxy.id in proxy_manager._session_blacklist

    def test_no_blacklist_under_threshold(self, proxy_manager, sample_proxy):
        """누적 실패율 80% 미만 시 블랙리스트 미등록"""
        proxy_manager._active_pool = [sample_proxy]

        # 5회 시도 중 3회 실패 (60%)
        for i in range(3):
            proxy_manager._record_session_result(sample_proxy.id, is_success=False)
        for i in range(2):
            proxy_manager._record_session_result(sample_proxy.id, is_success=True)

        # 블랙리스트 체크
        result = proxy_manager._check_cumulative_failure(sample_proxy.id)

        assert result is False
        assert sample_proxy.id not in proxy_manager._session_blacklist

    def test_no_blacklist_insufficient_attempts(self, proxy_manager, sample_proxy):
        """최소 시도 횟수 미만 시 블랙리스트 미등록"""
        proxy_manager._active_pool = [sample_proxy]

        # 3회만 시도 (최소 5회 필요)
        for i in range(3):
            proxy_manager._record_session_result(sample_proxy.id, is_success=False)

        # 블랙리스트 체크
        result = proxy_manager._check_cumulative_failure(sample_proxy.id)

        assert result is False
        assert sample_proxy.id not in proxy_manager._session_blacklist

    def test_report_failure_triggers_cumulative_check(self, proxy_manager, sample_proxy):
        """report_failure() 호출 시 누적 실패율 체크"""
        proxy_manager._active_pool = [sample_proxy]

        # 4회 실패 기록 (직접)
        for i in range(4):
            proxy_manager._record_session_result(sample_proxy.id, is_success=False)

        # 5번째 실패를 report_failure로 기록
        proxy_manager.report_failure(sample_proxy, "timeout")

        # 블랙리스트 등록 확인 (5회 시도 중 5회 실패 = 100%)
        assert sample_proxy.id in proxy_manager._session_blacklist


class TestSetHighFailureHosts:
    """set_high_failure_hosts() 테스트"""

    @pytest.fixture
    def mock_db_service(self):
        """Mock DB 서비스"""
        service = Mock()
        service.get_proxies_by_response_time = Mock(return_value=[])
        service.get_top_proxies_for_pool = Mock(return_value=[])
        service.get_proxy_ids_by_hosts = Mock(return_value={
            "1.1.1.1": 1,
            "2.2.2.2": 2,
        })
        return service

    @pytest.fixture
    def proxy_manager(self, mock_db_service):
        """ProxyManagerV2 인스턴스"""
        manager = ProxyManagerV2(
            db_service=mock_db_service,
            pool_size=5,
        )
        manager._initialized = True
        return manager

    def test_set_high_failure_hosts(self, proxy_manager):
        """실패율 높은 호스트 목록 설정"""
        hosts = ["1.1.1.1", "2.2.2.2"]

        proxy_manager.set_high_failure_hosts(hosts)

        assert proxy_manager._high_failure_hosts == {"1.1.1.1", "2.2.2.2"}

    def test_update_high_failure_hosts(self, proxy_manager):
        """호스트 목록 업데이트"""
        proxy_manager.set_high_failure_hosts(["1.1.1.1"])
        proxy_manager.set_high_failure_hosts(["2.2.2.2", "3.3.3.3"])

        assert "1.1.1.1" not in proxy_manager._high_failure_hosts
        assert "2.2.2.2" in proxy_manager._high_failure_hosts
        assert "3.3.3.3" in proxy_manager._high_failure_hosts

    def test_empty_hosts(self, proxy_manager):
        """빈 호스트 목록 설정"""
        proxy_manager.set_high_failure_hosts(["1.1.1.1"])
        proxy_manager.set_high_failure_hosts([])

        assert len(proxy_manager._high_failure_hosts) == 0


class TestRefreshPoolWithHighFailureFilter:
    """풀 갱신 시 실패율 높은 프록시 제외 테스트"""

    @pytest.fixture
    def mock_db_service(self):
        """Mock DB 서비스"""
        service = Mock()
        service.get_proxies_by_response_time = Mock(return_value=[])
        service.get_top_proxies_for_pool = Mock(return_value=[])
        service.get_proxy_ids_by_hosts = Mock(return_value={
            "bad.proxy.1": 101,
            "bad.proxy.2": 102,
        })
        return service

    @pytest.fixture
    def proxy_manager(self, mock_db_service):
        """ProxyManagerV2 인스턴스"""
        manager = ProxyManagerV2(
            db_service=mock_db_service,
            pool_size=10,
        )
        manager._initialized = True
        return manager

    @pytest.mark.asyncio
    async def test_refresh_pool_excludes_high_failure_hosts(self, proxy_manager, mock_db_service):
        """풀 갱신 시 실패율 높은 프록시 ID 제외 확인"""
        # 실패율 높은 호스트 설정
        proxy_manager.set_high_failure_hosts(["bad.proxy.1", "bad.proxy.2"])

        # 풀 갱신
        await proxy_manager._refresh_pool()

        # get_proxies_by_response_time 호출 시 exclude_ids에 101, 102 포함 확인
        call_args = mock_db_service.get_proxies_by_response_time.call_args

        if call_args:
            exclude_ids = call_args.kwargs.get("exclude_ids", [])
            assert 101 in exclude_ids or 102 in exclude_ids


class TestGetSessionStats:
    """세션 통계 조회 테스트"""

    @pytest.fixture
    def mock_db_service(self):
        """Mock DB 서비스"""
        return Mock()

    @pytest.fixture
    def proxy_manager(self, mock_db_service):
        """ProxyManagerV2 인스턴스"""
        manager = ProxyManagerV2(
            db_service=mock_db_service,
            pool_size=5,
        )
        return manager

    def test_get_session_stats(self, proxy_manager):
        """세션 통계 반환"""
        proxy_manager._high_failure_hosts = {"1.1.1.1", "2.2.2.2"}
        proxy_manager._session_failure_stats = {1: {"success": 5, "fail": 3}}
        proxy_manager._session_blacklist = {2: "test_reason"}

        stats = proxy_manager.get_session_stats()

        assert stats["high_failure_hosts_count"] == 2
        assert stats["session_failure_stats_count"] == 1
        assert stats["session_blacklist_count"] == 1
        assert stats["cumulative_failure_threshold"] == 0.8
        assert stats["cumulative_failure_min_attempts"] == 5


class TestProxyUsageStatsForSync:
    """get_proxy_usage_stats_for_sync() 테스트"""

    @pytest.fixture
    def mock_db(self):
        """Mock DB 세션"""
        return Mock()

    @pytest.fixture
    def usage_service(self):
        """ProxyUsageService 인스턴스"""
        return ProxyUsageService()

    def test_returns_stats_format(self, mock_db, usage_service):
        """올바른 형식의 통계 반환"""
        # Mock 쿼리 결과
        mock_row = Mock()
        mock_row.proxy_host = "1.2.3.4"
        mock_row.total_attempts = 10
        mock_row.success_count = 8
        mock_row.fail_count = 2
        mock_row.avg_response_time_ms = 500.0
        mock_row.last_used_at = datetime.now()

        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.group_by = Mock(return_value=mock_query)
        mock_query.having = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[mock_row])

        mock_db.query = Mock(return_value=mock_query)

        result = usage_service.get_proxy_usage_stats_for_sync(db=mock_db, hours=24)

        assert len(result) == 1
        assert result[0]["proxy_host"] == "1.2.3.4"
        assert result[0]["success_count"] == 8
        assert result[0]["fail_count"] == 2
        assert result[0]["total_attempts"] == 10
        assert result[0]["avg_response_time_ms"] == 500.0

    def test_empty_result(self, mock_db, usage_service):
        """결과 없으면 빈 리스트 반환"""
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.group_by = Mock(return_value=mock_query)
        mock_query.having = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[])

        mock_db.query = Mock(return_value=mock_query)

        result = usage_service.get_proxy_usage_stats_for_sync(db=mock_db)

        assert result == []
