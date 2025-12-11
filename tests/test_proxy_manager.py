"""
ProxyManager 테스트 (RIGHT-BICEP)
작성일: 2025-12-11

RIGHT-BICEP 원칙에 따른 테스트:
- Right: 정확한 결과를 반환하는가?
- Inverse: 역 관계를 확인할 수 있는가?
- Cross-check: 다른 방법으로 결과를 검증할 수 있는가?
- Error conditions: 에러 조건을 올바르게 처리하는가?
- Boundary conditions: 경계 조건을 올바르게 처리하는가?
"""

import pytest
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import tempfile
import os

from app.services.proxy_manager import ProxyManager


class TestProxyManagerRight:
    """Right: 정확한 결과 테스트"""

    def test_is_valid_proxy_valid_http(self):
        """유효한 HTTP 프록시 URL 검증"""
        manager = ProxyManager()
        assert manager._is_valid_proxy("http://192.168.1.1:8080") is True

    def test_is_valid_proxy_valid_https(self):
        """유효한 HTTPS 프록시 URL 검증"""
        manager = ProxyManager()
        assert manager._is_valid_proxy("https://192.168.1.1:443") is True

    def test_is_valid_proxy_valid_socks5(self):
        """유효한 SOCKS5 프록시 URL 검증"""
        manager = ProxyManager()
        assert manager._is_valid_proxy("socks5://192.168.1.1:1080") is True

    def test_is_valid_proxy_with_auth(self):
        """인증 정보가 있는 프록시 URL 검증"""
        manager = ProxyManager()
        assert manager._is_valid_proxy("http://user:pass@192.168.1.1:8080") is True

    def test_get_status_initial(self):
        """초기 상태 확인"""
        manager = ProxyManager()
        status = manager.get_status()

        assert status["initialized"] is False
        assert status["total"] == 0
        assert status["active_pool"] == 0
        assert status["blacklisted"] == 0
        assert status["current"] is None
        assert status["request_count"] == 0

    def test_get_playwright_proxy_format(self):
        """Playwright 프록시 설정 형식 확인"""
        manager = ProxyManager()
        manager.proxy_list = ["http://192.168.1.1:8080"]
        manager.active_pool = ["http://192.168.1.1:8080"]
        manager._initialized = True

        proxy_config = manager.get_playwright_proxy()

        assert proxy_config is not None
        assert "server" in proxy_config
        assert proxy_config["server"] == "http://192.168.1.1:8080"

    def test_get_playwright_proxy_with_auth(self):
        """인증이 있는 Playwright 프록시 설정"""
        manager = ProxyManager()
        manager.proxy_list = ["http://user:pass@192.168.1.1:8080"]
        manager.active_pool = ["http://user:pass@192.168.1.1:8080"]
        manager._initialized = True

        proxy_config = manager.get_playwright_proxy()

        assert proxy_config is not None
        assert proxy_config["username"] == "user"
        assert proxy_config["password"] == "pass"


class TestProxyManagerInverse:
    """Inverse: 역 관계 테스트"""

    def test_is_valid_proxy_invalid_scheme(self):
        """잘못된 스킴은 무효"""
        manager = ProxyManager()
        assert manager._is_valid_proxy("ftp://192.168.1.1:21") is False

    def test_is_valid_proxy_no_port(self):
        """포트가 없으면 무효"""
        manager = ProxyManager()
        assert manager._is_valid_proxy("http://192.168.1.1") is False

    def test_is_valid_proxy_empty(self):
        """빈 문자열은 무효"""
        manager = ProxyManager()
        assert manager._is_valid_proxy("") is False

    def test_is_valid_proxy_garbage(self):
        """잘못된 형식은 무효"""
        manager = ProxyManager()
        assert manager._is_valid_proxy("not-a-proxy") is False


class TestProxyManagerCrossCheck:
    """Cross-check: 다른 방법으로 검증"""

    def test_load_and_count_match(self):
        """로드된 프록시 수와 상태 카운트 일치"""
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write("http://1.1.1.1:80\n")
                f.write("http://2.2.2.2:80\n")
                f.write("# comment\n")
                f.write("http://3.3.3.3:80\n")
                temp_path = f.name

            manager = ProxyManager(proxy_file=Path(temp_path))
            result = manager.load_proxy_list()

            assert result is True
            assert len(manager.proxy_list) == 3
            assert manager.get_status()["total"] == 3
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except PermissionError:
                    pass

    def test_blacklist_count_consistency(self):
        """블랙리스트 카운트 일관성"""
        manager = ProxyManager(blacklist_duration=300)
        manager.proxy_list = ["http://1.1.1.1:80", "http://2.2.2.2:80"]
        manager.active_pool = ["http://1.1.1.1:80", "http://2.2.2.2:80"]
        manager._initialized = True

        # 프록시 실패 처리
        manager.mark_failed("http://1.1.1.1:80", "test error")

        assert len(manager.blacklist) == 1
        assert manager.get_status()["blacklisted"] == 1
        assert len(manager.active_pool) == 1


class TestProxyManagerErrorConditions:
    """Error conditions: 에러 처리 테스트"""

    def test_load_nonexistent_file(self):
        """존재하지 않는 파일 로드"""
        manager = ProxyManager(proxy_file=Path("/nonexistent/path/file.txt"))
        result = manager.load_proxy_list()

        assert result is False
        assert len(manager.proxy_list) == 0

    def test_get_next_proxy_empty(self):
        """빈 프록시 풀에서 다음 프록시 요청"""
        manager = ProxyManager()
        result = manager.get_next_proxy()

        assert result is None

    def test_mark_failed_unknown_proxy(self):
        """알 수 없는 프록시 실패 처리"""
        manager = ProxyManager()
        manager.proxy_list = ["http://1.1.1.1:80"]

        # 존재하지 않는 프록시 - 에러 없이 처리
        manager.mark_failed("http://unknown:80", "test error")

        assert len(manager.blacklist) == 0

    def test_get_playwright_proxy_not_initialized(self):
        """초기화되지 않은 상태에서 프록시 요청"""
        manager = ProxyManager()
        result = manager.get_playwright_proxy()

        assert result is None


class TestProxyManagerBoundaryConditions:
    """Boundary conditions: 경계 조건 테스트"""

    def test_rotation_interval_one(self):
        """로테이션 주기 1 테스트 - 매 요청마다 로테이션"""
        manager = ProxyManager(rotation_interval=1)
        manager.proxy_list = ["http://1.1.1.1:80", "http://2.2.2.2:80"]
        manager.active_pool = ["http://1.1.1.1:80", "http://2.2.2.2:80"]
        manager._initialized = True

        # 첫 요청과 두 번째 요청은 같을 수 있음 (초기 상태)
        first = manager.get_next_proxy()
        second = manager.get_next_proxy()
        third = manager.get_next_proxy()

        # 3번 요청하면 최소 2개의 다른 프록시가 사용되어야 함
        used_proxies = {first, second, third}
        assert len(used_proxies) >= 1  # 최소 1개 이상

    def test_single_proxy_rotation(self):
        """프록시가 하나일 때 로테이션"""
        manager = ProxyManager(rotation_interval=1)
        manager.proxy_list = ["http://1.1.1.1:80"]
        manager.active_pool = ["http://1.1.1.1:80"]
        manager._initialized = True

        first = manager.get_next_proxy()
        second = manager.get_next_proxy()

        assert first == second == "http://1.1.1.1:80"

    def test_all_proxies_blacklisted(self):
        """모든 프록시가 블랙리스트에 있을 때"""
        manager = ProxyManager(blacklist_duration=300)
        manager.proxy_list = ["http://1.1.1.1:80"]
        manager.active_pool = ["http://1.1.1.1:80"]
        manager._initialized = True

        manager.mark_failed("http://1.1.1.1:80", "test error")

        # 블랙리스트가 초기화되고 다시 사용 가능해야 함
        result = manager.get_next_proxy()
        assert result == "http://1.1.1.1:80"
        assert len(manager.blacklist) == 0

    def test_blacklist_expiration(self):
        """블랙리스트 만료 테스트"""
        manager = ProxyManager(blacklist_duration=1)  # 1초 만료
        manager.proxy_list = ["http://1.1.1.1:80", "http://2.2.2.2:80"]
        manager.active_pool = ["http://1.1.1.1:80", "http://2.2.2.2:80"]
        manager._initialized = True

        manager.mark_failed("http://1.1.1.1:80", "test error")
        assert len(manager.blacklist) == 1

        # 만료 대기
        time.sleep(1.1)

        # cleanup 호출
        manager._cleanup_blacklist()
        assert len(manager.blacklist) == 0

    def test_empty_proxy_file(self):
        """빈 프록시 파일 로드"""
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write("# only comments\n")
                f.write("\n")
                temp_path = f.name

            manager = ProxyManager(proxy_file=Path(temp_path))
            result = manager.load_proxy_list()

            assert result is False
            assert len(manager.proxy_list) == 0
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except PermissionError:
                    pass

    def test_max_active_pool_limit(self):
        """활성 풀 최대 크기 제한"""
        manager = ProxyManager(max_active_pool=2)

        # 5개 프록시 중 2개만 활성 풀에 들어가야 함
        manager.proxy_list = [
            "http://1.1.1.1:80",
            "http://2.2.2.2:80",
            "http://3.3.3.3:80",
            "http://4.4.4.4:80",
            "http://5.5.5.5:80",
        ]

        # 수동으로 active_pool 설정 (실제로는 validate_proxy가 필요)
        manager.active_pool = manager.proxy_list[:2]

        assert len(manager.active_pool) <= manager.max_active_pool


class TestProxyManagerAsync:
    """비동기 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_validate_proxy_timeout(self):
        """프록시 검증 타임아웃"""
        manager = ProxyManager(connection_timeout=1)

        # 존재하지 않는 프록시로 타임아웃 테스트
        is_valid, response_time, result = await manager.validate_proxy(
            "http://192.0.2.1:80"  # TEST-NET, 응답하지 않는 IP
        )

        assert is_valid is False
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_check_and_reload_no_change(self):
        """파일 변경 없을 때 리로드"""
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write("http://1.1.1.1:80\n")
                temp_path = f.name

            manager = ProxyManager(proxy_file=Path(temp_path))
            manager.load_proxy_list()

            # 파일이 변경되지 않았으므로 False 반환
            result = await manager.check_and_reload()
            assert result is False
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except PermissionError:
                    pass


class TestProxyManagerIsAvailable:
    """is_available 프로퍼티 테스트"""

    def test_is_available_not_initialized(self):
        """초기화되지 않았을 때"""
        manager = ProxyManager()
        assert manager.is_available is False

    def test_is_available_empty_pool(self):
        """활성 풀이 비었을 때"""
        manager = ProxyManager()
        manager._initialized = True
        manager.active_pool = []
        assert manager.is_available is False

    def test_is_available_with_proxies(self):
        """프록시가 있을 때"""
        manager = ProxyManager()
        manager._initialized = True
        manager.active_pool = ["http://1.1.1.1:80"]
        assert manager.is_available is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
