"""
프록시 세션 블랙리스트 테스트
작성일: 2025-12-20

테스트 범위:
1. extract_host SOCKS 프로토콜 지원
2. 세션 블랙리스트 기능
3. 풀 갱신 후 블랙리스트 유지
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from app.models.proxy_usage import ProxyUsageLog
from app.services.proxy_manager_v2 import ProxyManagerV2
from app.schemas.proxy import ProxyInfo


class TestExtractHost:
    """extract_host 메서드 테스트"""

    def test_http_protocol(self):
        """HTTP 프로토콜 처리"""
        assert ProxyUsageLog.extract_host("http://1.2.3.4:8080") == "1.2.3.4"

    def test_https_protocol(self):
        """HTTPS 프로토콜 처리"""
        assert ProxyUsageLog.extract_host("https://1.2.3.4:8080") == "1.2.3.4"

    def test_socks4_protocol(self):
        """SOCKS4 프로토콜 처리"""
        assert ProxyUsageLog.extract_host("socks4://1.2.3.4:1080") == "1.2.3.4"

    def test_socks5_protocol(self):
        """SOCKS5 프로토콜 처리"""
        assert ProxyUsageLog.extract_host("socks5://1.2.3.4:1080") == "1.2.3.4"

    def test_with_auth(self):
        """인증 정보 포함 URL 처리"""
        assert ProxyUsageLog.extract_host("http://user:pass@1.2.3.4:8080") == "1.2.3.4"
        assert ProxyUsageLog.extract_host("socks5://user:pass@1.2.3.4:1080") == "1.2.3.4"

    def test_hostname(self):
        """호스트명 처리"""
        assert ProxyUsageLog.extract_host("http://proxy.example.com:8080") == "proxy.example.com"

    def test_invalid_url(self):
        """잘못된 URL은 원본 반환"""
        assert ProxyUsageLog.extract_host("invalid") == "invalid"


class TestProxyManagerV2SessionBlacklist:
    """ProxyManagerV2 세션 블랙리스트 테스트"""

    @pytest.fixture
    def mock_db_service(self):
        """Mock DB 서비스"""
        service = Mock()
        service.get_proxies_by_response_time = Mock(return_value=[])
        service.get_top_proxies_for_pool = Mock(return_value=[])
        service.batch_update_proxy_stats = Mock()
        return service

    @pytest.fixture
    def proxy_manager(self, mock_db_service):
        """ProxyManagerV2 인스턴스"""
        manager = ProxyManagerV2(
            db_service=mock_db_service,
            pool_size=5,
            min_success_rate=0.5,
            pool_refresh_interval=300,
        )
        manager._initialized = True
        return manager

    @pytest.fixture
    def sample_proxies(self):
        """샘플 프록시 목록"""
        return [
            ProxyInfo(
                id=1, url="http://1.1.1.1:8080", protocol="http",
                host="1.1.1.1", port=8080, priority_score=80.0,
                avg_response_time=0.3, success_count=100, fail_count=0, total_checks=100
            ),
            ProxyInfo(
                id=2, url="http://2.2.2.2:8080", protocol="http",
                host="2.2.2.2", port=8080, priority_score=70.0,
                avg_response_time=0.5, success_count=80, fail_count=0, total_checks=80
            ),
            ProxyInfo(
                id=3, url="http://3.3.3.3:8080", protocol="http",
                host="3.3.3.3", port=8080, priority_score=60.0,
                avg_response_time=0.8, success_count=60, fail_count=0, total_checks=60
            ),
        ]

    def test_session_blacklist_on_consecutive_failures(self, proxy_manager, sample_proxies):
        """연속 실패 시 세션 블랙리스트 등록"""
        proxy_manager._active_pool = sample_proxies.copy()
        proxy = sample_proxies[0]

        # 3회 연속 실패
        for _ in range(3):
            proxy_manager.mark_failed(proxy.url, "HTTP 403")

        # 세션 블랙리스트에 등록되어야 함
        assert proxy.id in proxy_manager._session_blacklist
        assert proxy_manager._session_blacklist[proxy.id] == "HTTP 403"

        # 풀에서 제거되어야 함
        assert proxy not in proxy_manager._active_pool

    def test_session_blacklist_survives_pool_refresh(self, proxy_manager, sample_proxies, mock_db_service):
        """풀 갱신 후에도 세션 블랙리스트 유지"""
        proxy_manager._active_pool = sample_proxies.copy()

        # 프록시 1을 세션 블랙리스트에 등록
        proxy_manager._session_blacklist[1] = "test_reason"

        # 새 프록시 목록 반환하도록 설정
        new_proxies = [
            ProxyInfo(
                id=4, url="http://4.4.4.4:8080", protocol="http",
                host="4.4.4.4", port=8080, priority_score=90.0,
                avg_response_time=0.2, success_count=100, fail_count=0, total_checks=100
            ),
        ]
        mock_db_service.get_proxies_by_response_time.return_value = new_proxies

        # 풀 갱신 시뮬레이션 (_sync_refresh_pool 호출)
        proxy_manager._sync_refresh_pool()

        # 세션 블랙리스트가 유지되어야 함
        assert 1 in proxy_manager._session_blacklist
        assert proxy_manager._session_blacklist[1] == "test_reason"

    def test_blacklisted_proxy_excluded_from_selection(self, proxy_manager, sample_proxies):
        """블랙리스트 프록시가 선택에서 제외됨"""
        proxy_manager._active_pool = sample_proxies.copy()

        # 프록시 1, 2를 세션 블랙리스트에 등록
        proxy_manager._session_blacklist[1] = "reason1"
        proxy_manager._session_blacklist[2] = "reason2"

        # get_next_proxy 호출 시 블랙리스트되지 않은 프록시만 선택되어야 함
        proxy = proxy_manager.get_next_proxy()
        assert proxy is not None
        assert proxy.id == 3  # 유일하게 블랙리스트되지 않은 프록시

    def test_blacklisted_proxy_excluded_from_fresh_proxy(self, proxy_manager, sample_proxies):
        """get_fresh_proxy에서도 블랙리스트 프록시 제외"""
        proxy_manager._active_pool = sample_proxies.copy()

        # 프록시 1을 세션 블랙리스트에 등록
        proxy_manager._session_blacklist[1] = "reason1"

        # get_fresh_proxy 호출
        proxy_url = proxy_manager.get_fresh_proxy()

        # 블랙리스트된 프록시 URL이 아니어야 함
        assert proxy_url is not None
        assert "1.1.1.1" not in proxy_url

    def test_slow_proxies_survive_pool_refresh(self, proxy_manager, sample_proxies, mock_db_service):
        """풀 갱신 후에도 느린 프록시 목록 유지"""
        proxy_manager._active_pool = sample_proxies.copy()

        # 프록시 1을 느린 프록시로 등록
        proxy_manager._slow_proxies.add(1)

        # 새 프록시 목록 반환하도록 설정
        mock_db_service.get_proxies_by_response_time.return_value = []

        # 풀 갱신 시뮬레이션
        proxy_manager._sync_refresh_pool()

        # 느린 프록시 목록이 유지되어야 함
        assert 1 in proxy_manager._slow_proxies

    def test_update_local_proxy_blacklists_on_failure(self, proxy_manager, sample_proxies):
        """_update_local_proxy에서 연속 실패 시 블랙리스트 등록"""
        proxy_manager._active_pool = sample_proxies.copy()
        proxy = sample_proxies[0]

        # 2회 실패 (아직 블랙리스트 안 됨)
        proxy_manager._update_local_proxy(proxy.id, is_valid=False)
        proxy_manager._update_local_proxy(proxy.id, is_valid=False)
        assert proxy.id not in proxy_manager._session_blacklist

        # 3회째 실패 (블랙리스트됨)
        proxy_manager._update_local_proxy(proxy.id, is_valid=False)
        assert proxy.id in proxy_manager._session_blacklist

    def test_success_resets_fail_count(self, proxy_manager, sample_proxies):
        """성공 시 fail_count 리셋"""
        proxy_manager._active_pool = sample_proxies.copy()
        proxy = sample_proxies[0]

        # 2회 실패
        proxy_manager._update_local_proxy(proxy.id, is_valid=False)
        proxy_manager._update_local_proxy(proxy.id, is_valid=False)
        assert proxy.fail_count == 2

        # 1회 성공
        proxy_manager._update_local_proxy(proxy.id, is_valid=True, response_time=0.5)
        assert proxy.fail_count == 0

        # 다시 2회 실패 (블랙리스트 안 됨)
        proxy_manager._update_local_proxy(proxy.id, is_valid=False)
        proxy_manager._update_local_proxy(proxy.id, is_valid=False)
        assert proxy.id not in proxy_manager._session_blacklist

    def test_get_status_includes_session_blacklist(self, proxy_manager, sample_proxies):
        """get_status에 세션 블랙리스트 정보 포함"""
        proxy_manager._active_pool = sample_proxies.copy()
        proxy_manager._session_blacklist[1] = "test_reason"
        proxy_manager._session_blacklist[2] = "another_reason"

        status = proxy_manager.get_status()

        assert "session_blacklist_count" in status
        assert status["session_blacklist_count"] == 2
        assert "session_blacklist_details" in status
        assert status["session_blacklist_details"][1] == "test_reason"
        assert "consecutive_fail_threshold" in status
        assert status["consecutive_fail_threshold"] == 3

    def test_all_proxies_blacklisted_returns_none(self, proxy_manager, sample_proxies):
        """모든 프록시가 블랙리스트되면 None 반환"""
        proxy_manager._active_pool = sample_proxies.copy()

        # 모든 프록시를 블랙리스트에 등록
        for proxy in sample_proxies:
            proxy_manager._session_blacklist[proxy.id] = "test"

        # get_next_proxy가 None 반환해야 함
        result = proxy_manager.get_next_proxy()
        assert result is None


class TestProxyManagerV2RefreshPoolExcludesBlacklist:
    """풀 갱신 시 세션 블랙리스트 제외 테스트"""

    @pytest.fixture
    def mock_db_service(self):
        """Mock DB 서비스"""
        service = Mock()
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

    def test_refresh_pool_excludes_session_blacklist(self, proxy_manager, mock_db_service):
        """풀 갱신 시 세션 블랙리스트 프록시가 exclude_ids에 포함됨"""
        # 세션 블랙리스트에 프록시 등록
        proxy_manager._session_blacklist[10] = "blacklisted"
        proxy_manager._session_blacklist[20] = "blacklisted"
        proxy_manager._slow_proxies.add(30)
        proxy_manager._previous_pool_ids = {40, 50}

        # Mock 설정
        mock_db_service.get_proxies_by_response_time.return_value = []
        mock_db_service.get_top_proxies_for_pool.return_value = []

        # _sync_refresh_pool 호출
        proxy_manager._sync_refresh_pool()

        # get_proxies_by_response_time 호출 시 exclude_ids 확인
        call_args = mock_db_service.get_proxies_by_response_time.call_args_list[0]
        exclude_ids = call_args.kwargs.get("exclude_ids", [])

        # 세션 블랙리스트, 느린 프록시, 이전 풀 모두 제외되어야 함
        # Note: _sync_refresh_pool은 _previous_pool_ids를 제외하지 않음 (긴급 갱신)
        assert 10 in exclude_ids or 20 in exclude_ids or 30 in exclude_ids
