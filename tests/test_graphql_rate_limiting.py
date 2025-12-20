"""
NaverGraphQLClient Rate Limiting 테스트
작성일: 2025-12-11

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

테스트 대상:
1. Semaphore 동시 요청 제한
2. TTL 캐시 기능
3. 캐시 만료 및 정리
"""

import pytest
import asyncio
import time
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.naver_booking.services.graphql_client import (
    NaverGraphQLClient,
    CacheEntry,
)
from app.core.config import settings


# ============================================================
# 테스트 전 설정
# ============================================================

@pytest.fixture(autouse=True)
def reset_client_state():
    """각 테스트 전에 클라이언트 상태 초기화"""
    # 캐시 및 Semaphore 초기화
    NaverGraphQLClient._cache.clear()
    NaverGraphQLClient._semaphore = None
    NaverGraphQLClient._last_cleanup = 0
    yield
    # 테스트 후 정리
    NaverGraphQLClient._cache.clear()
    NaverGraphQLClient._semaphore = None


@pytest.fixture
def mock_api_response():
    """모의 API 응답"""
    return {
        "business": {
            "businessId": "123",
            "name": "테스트 업체"
        }
    }


# ============================================================
# 1. Semaphore 동시 요청 제한 테스트
# ============================================================

class TestSemaphoreRateLimiting:
    """Semaphore 기반 동시 요청 제한 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_semaphore_initialization(self):
        """
        [Right] Semaphore가 설정값으로 초기화되는지
        """
        semaphore = NaverGraphQLClient._get_semaphore()

        assert semaphore is not None
        assert isinstance(semaphore, asyncio.Semaphore)
        # Semaphore의 내부 값 확인 (Python 3.10+)
        assert semaphore._value == settings.MAX_CONCURRENT_GRAPHQL_REQUESTS

    def test_right_semaphore_singleton(self):
        """
        [Right] Semaphore가 싱글톤으로 유지되는지
        """
        sem1 = NaverGraphQLClient._get_semaphore()
        sem2 = NaverGraphQLClient._get_semaphore()

        assert sem1 is sem2

    @pytest.mark.asyncio
    async def test_right_concurrent_requests_limited(self, mock_api_response):
        """
        [Right] 동시 요청이 MAX_CONCURRENT_GRAPHQL_REQUESTS로 제한되는지
        """
        max_concurrent = settings.MAX_CONCURRENT_GRAPHQL_REQUESTS
        concurrent_count = 0
        max_observed = 0

        async def mock_execute(*args, **kwargs):
            nonlocal concurrent_count, max_observed
            concurrent_count += 1
            max_observed = max(max_observed, concurrent_count)
            await asyncio.sleep(0.1)  # API 지연 시뮬레이션
            concurrent_count -= 1
            return mock_api_response

        client = NaverGraphQLClient()

        with patch.object(client, '_do_execute_query', side_effect=mock_execute):
            # MAX + 2개의 동시 요청 생성
            tasks = [
                client._execute_query("query", {"id": str(i)}, f"op{i}", use_cache=False)
                for i in range(max_concurrent + 2)
            ]
            await asyncio.gather(*tasks)

        # 최대 동시 실행 수가 제한값을 초과하지 않아야 함
        assert max_observed <= max_concurrent

        await client.close()

    # --- Boundary: 경계값 테스트 ---

    @pytest.mark.asyncio
    async def test_boundary_exactly_max_concurrent(self, mock_api_response):
        """
        [Boundary] 정확히 MAX_CONCURRENT_GRAPHQL_REQUESTS개의 요청이 동시 실행될 수 있는지
        """
        max_concurrent = settings.MAX_CONCURRENT_GRAPHQL_REQUESTS
        concurrent_at_start = 0

        async def mock_execute(*args, **kwargs):
            nonlocal concurrent_at_start
            concurrent_at_start += 1
            await asyncio.sleep(0.05)
            return mock_api_response

        client = NaverGraphQLClient()

        with patch.object(client, '_do_execute_query', side_effect=mock_execute):
            tasks = [
                client._execute_query("query", {"id": str(i)}, f"op{i}", use_cache=False)
                for i in range(max_concurrent)
            ]
            # 모든 태스크 시작 전 잠시 대기
            await asyncio.sleep(0.01)
            await asyncio.gather(*tasks)

        # 정확히 max_concurrent개가 실행되어야 함
        assert concurrent_at_start == max_concurrent

        await client.close()


# ============================================================
# 2. TTL 캐시 기능 테스트
# ============================================================

class TestTTLCache:
    """TTL 캐시 기능 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_cache_key_generation(self):
        """
        [Right] 캐시 키가 올바르게 생성되는지
        """
        key1 = NaverGraphQLClient._get_cache_key("schedule", {"businessId": "123"})
        key2 = NaverGraphQLClient._get_cache_key("schedule", {"businessId": "123"})
        key3 = NaverGraphQLClient._get_cache_key("schedule", {"businessId": "456"})

        assert key1 == key2  # 동일한 입력 → 동일한 키
        assert key1 != key3  # 다른 입력 → 다른 키
        assert len(key1) == 32  # MD5 해시 길이

    def test_right_cache_set_and_get(self):
        """
        [Right] 캐시에 데이터 저장 및 조회가 동작하는지
        """
        test_data = {"result": "test"}
        cache_key = "test_key"

        NaverGraphQLClient._set_cache(cache_key, test_data)
        retrieved = NaverGraphQLClient._get_from_cache(cache_key)

        assert retrieved == test_data

    @pytest.mark.asyncio
    async def test_right_cache_hit_prevents_api_call(self, mock_api_response):
        """
        [Right] 캐시 히트 시 API 호출이 방지되는지
        """
        client = NaverGraphQLClient()
        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_api_response

        with patch.object(client, '_do_execute_query', side_effect=mock_execute):
            # 첫 번째 호출 - API 호출됨
            await client._execute_query("query", {"id": "1"}, "test_op")
            # 두 번째 호출 - 캐시 히트
            await client._execute_query("query", {"id": "1"}, "test_op")
            # 세 번째 호출 - 캐시 히트
            await client._execute_query("query", {"id": "1"}, "test_op")

        assert call_count == 1  # API는 1번만 호출되어야 함

        await client.close()

    @pytest.mark.asyncio
    async def test_right_different_params_different_cache(self, mock_api_response):
        """
        [Right] 다른 파라미터는 다른 캐시 엔트리를 사용하는지
        """
        client = NaverGraphQLClient()
        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_api_response

        with patch.object(client, '_do_execute_query', side_effect=mock_execute):
            await client._execute_query("query", {"id": "1"}, "test_op")
            await client._execute_query("query", {"id": "2"}, "test_op")
            await client._execute_query("query", {"id": "3"}, "test_op")

        assert call_count == 3  # 각각 다른 캐시

        await client.close()

    # --- Boundary: 경계값 테스트 ---

    def test_boundary_cache_ttl_expiration(self):
        """
        [Boundary] 캐시가 TTL 후에 만료되는지
        """
        test_data = {"result": "test"}
        cache_key = "expiry_test"

        # 캐시 저장 (이미 만료된 시간으로 설정)
        NaverGraphQLClient._cache[cache_key] = CacheEntry(
            data=test_data,
            expires_at=time.time() - 1  # 1초 전에 만료
        )

        # 조회 시 None 반환
        retrieved = NaverGraphQLClient._get_from_cache(cache_key)

        assert retrieved is None
        assert cache_key not in NaverGraphQLClient._cache  # 만료된 엔트리 삭제됨

    def test_boundary_cache_just_before_expiry(self):
        """
        [Boundary] 만료 직전의 캐시가 유효한지
        """
        test_data = {"result": "test"}
        cache_key = "almost_expired"

        # 1초 후 만료 설정
        NaverGraphQLClient._cache[cache_key] = CacheEntry(
            data=test_data,
            expires_at=time.time() + 1
        )

        retrieved = NaverGraphQLClient._get_from_cache(cache_key)

        assert retrieved == test_data

    # --- Error: 에러 조건 테스트 ---

    def test_error_cache_miss(self):
        """
        [Error] 존재하지 않는 키 조회 시 None 반환
        """
        result = NaverGraphQLClient._get_from_cache("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_error_api_failure_not_cached(self):
        """
        [Error] API 실패 시 결과가 캐시되지 않는지
        """
        client = NaverGraphQLClient()

        async def mock_execute(*args, **kwargs):
            return None  # API 실패

        with patch.object(client, '_do_execute_query', side_effect=mock_execute):
            await client._execute_query("query", {"id": "1"}, "test_op")

        # 캐시가 비어있어야 함
        assert len(NaverGraphQLClient._cache) == 0

        await client.close()

    # --- Cross-check: 교차 검증 ---

    @pytest.mark.asyncio
    async def test_crosscheck_cache_after_semaphore_wait(self, mock_api_response):
        """
        [Cross-check] Semaphore 대기 후에도 캐시를 재확인하는지
        """
        client = NaverGraphQLClient()
        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)  # Semaphore 대기 시뮬레이션
            return mock_api_response

        # Semaphore를 1로 제한
        NaverGraphQLClient._semaphore = asyncio.Semaphore(1)

        with patch.object(client, '_do_execute_query', side_effect=mock_execute):
            # 동일한 요청 동시 실행
            tasks = [
                client._execute_query("query", {"id": "same"}, "test_op")
                for _ in range(3)
            ]
            await asyncio.gather(*tasks)

        # 첫 번째 요청만 API 호출, 나머지는 캐시 히트
        assert call_count == 1

        await client.close()


# ============================================================
# 3. 캐시 정리 테스트
# ============================================================

class TestCacheCleanup:
    """캐시 정리 기능 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_cleanup_removes_expired_entries(self):
        """
        [Right] 정리 시 만료된 엔트리가 제거되는지
        """
        current_time = time.time()

        # 만료된 엔트리 추가
        NaverGraphQLClient._cache["expired1"] = CacheEntry(
            data="old", expires_at=current_time - 10
        )
        NaverGraphQLClient._cache["expired2"] = CacheEntry(
            data="old", expires_at=current_time - 5
        )
        # 유효한 엔트리 추가
        NaverGraphQLClient._cache["valid"] = CacheEntry(
            data="new", expires_at=current_time + 100
        )

        # 정리 강제 실행
        NaverGraphQLClient._last_cleanup = 0
        NaverGraphQLClient._cleanup_interval = 0
        NaverGraphQLClient._cleanup_expired_cache()

        assert "expired1" not in NaverGraphQLClient._cache
        assert "expired2" not in NaverGraphQLClient._cache
        assert "valid" in NaverGraphQLClient._cache

    def test_right_cleanup_interval_respected(self):
        """
        [Right] 정리 간격이 존중되는지
        """
        NaverGraphQLClient._cache["test"] = CacheEntry(
            data="data", expires_at=time.time() - 10
        )
        NaverGraphQLClient._last_cleanup = time.time()
        NaverGraphQLClient._cleanup_interval = 60

        # 정리 시도 - 간격 미달로 실행되지 않아야 함
        NaverGraphQLClient._cleanup_expired_cache()

        assert "test" in NaverGraphQLClient._cache  # 삭제되지 않음

    # --- Existence: 존재 여부 ---

    def test_existence_cache_stats(self):
        """
        [Existence] 캐시 통계가 올바르게 반환되는지
        """
        current_time = time.time()

        NaverGraphQLClient._cache["valid1"] = CacheEntry(
            data="data", expires_at=current_time + 100
        )
        NaverGraphQLClient._cache["valid2"] = CacheEntry(
            data="data", expires_at=current_time + 100
        )
        NaverGraphQLClient._cache["expired"] = CacheEntry(
            data="data", expires_at=current_time - 10
        )

        stats = NaverGraphQLClient.get_cache_stats()

        assert stats["total_entries"] == 3
        assert stats["valid_entries"] == 2
        assert stats["expired_entries"] == 1
        assert stats["cache_ttl"] == settings.GRAPHQL_CACHE_TTL

    def test_existence_clear_cache(self):
        """
        [Existence] 캐시 전체 삭제가 동작하는지
        """
        NaverGraphQLClient._cache["key1"] = CacheEntry(
            data="data", expires_at=time.time() + 100
        )
        NaverGraphQLClient._cache["key2"] = CacheEntry(
            data="data", expires_at=time.time() + 100
        )

        NaverGraphQLClient.clear_cache()

        assert len(NaverGraphQLClient._cache) == 0


# ============================================================
# 4. 통합 테스트
# ============================================================

class TestRateLimitingIntegration:
    """Rate Limiting 통합 테스트"""

    @pytest.mark.asyncio
    async def test_integration_full_flow(self, mock_api_response):
        """
        [Integration] 캐시 + Semaphore가 함께 동작하는지
        """
        client = NaverGraphQLClient()
        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return mock_api_response

        with patch.object(client, '_do_execute_query', side_effect=mock_execute):
            # 동일 요청 3회 + 다른 요청 2회
            await client._execute_query("query", {"id": "1"}, "op1")
            await client._execute_query("query", {"id": "1"}, "op1")  # 캐시 히트
            await client._execute_query("query", {"id": "1"}, "op1")  # 캐시 히트
            await client._execute_query("query", {"id": "2"}, "op2")
            await client._execute_query("query", {"id": "3"}, "op3")

        # 3개의 고유 요청만 API 호출
        assert call_count == 3

        await client.close()

    @pytest.mark.asyncio
    async def test_integration_use_cache_false(self, mock_api_response):
        """
        [Integration] use_cache=False 시 캐시 우회하는지
        """
        client = NaverGraphQLClient()
        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_api_response

        with patch.object(client, '_do_execute_query', side_effect=mock_execute):
            await client._execute_query("query", {"id": "1"}, "op1", use_cache=False)
            await client._execute_query("query", {"id": "1"}, "op1", use_cache=False)
            await client._execute_query("query", {"id": "1"}, "op1", use_cache=False)

        # 캐시 우회로 3번 모두 API 호출
        assert call_count == 3

        await client.close()


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
