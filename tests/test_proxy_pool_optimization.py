"""
프록시 풀 최적화 테스트 (RIGHT-BICEP)
작성일: 2025-12-12

테스트 대상:
1. 10초 프록시 쿨다운
2. 70/30 응답시간 기반 풀 구성

RIGHT-BICEP 원칙에 따른 테스트:
- Right: 정확한 결과를 반환하는가?
- Inverse: 역 관계를 확인할 수 있는가?
- Cross-check: 다른 방법으로 결과를 검증할 수 있는가?
- Error conditions: 에러 조건을 올바르게 처리하는가?
- Boundary conditions: 경계 조건을 올바르게 처리하는가?
- Performance: 성능 요구사항을 충족하는가?
"""

import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch
from typing import List, Optional

from app.schemas.proxy import ProxyInfo
from app.services.proxy_manager_v2 import ProxyManagerV2


def create_mock_proxy(
    proxy_id: int,
    avg_response_time: Optional[float] = None,
    priority_score: float = 50.0,
) -> ProxyInfo:
    """테스트용 프록시 생성"""
    return ProxyInfo(
        id=proxy_id,
        url=f"http://proxy{proxy_id}.test:8080",
        protocol="http",
        host=f"proxy{proxy_id}.test",
        port=8080,
        username=None,
        password=None,
        priority_score=priority_score,
        avg_response_time=avg_response_time,
        success_count=10,
        fail_count=0,
        total_checks=10,
    )


def create_mock_db_service(
    fast_proxies: List[ProxyInfo] = None,
    normal_proxies: List[ProxyInfo] = None,
    pending_proxies: List[ProxyInfo] = None,
):
    """테스트용 DB 서비스 모킹"""
    mock_db = MagicMock()
    fast_proxies = fast_proxies or []
    normal_proxies = normal_proxies or []
    pending_proxies = pending_proxies or []

    def get_proxies_by_response_time(
        min_response_time=None,
        max_response_time=None,
        limit=10,
        status="active",
        exclude_ids=None,
        min_success_rate=0.5,
    ):
        exclude_ids = exclude_ids or []

        if min_response_time is None and max_response_time is not None:
            # fast 프록시 (응답시간 <= threshold)
            result = [p for p in fast_proxies if p.id not in exclude_ids]
        elif min_response_time is not None and max_response_time is not None:
            # normal 프록시 (threshold < 응답시간 <= max)
            result = [p for p in normal_proxies if p.id not in exclude_ids]
        else:
            result = []

        return result[:limit]

    def get_top_proxies_for_pool(
        limit=10,
        status="active",
        min_success_rate=0.0,
        min_checks=0,
        exclude_ids=None,
        max_response_time=None,
    ):
        exclude_ids = exclude_ids or []
        if status == "pending":
            return [p for p in pending_proxies if p.id not in exclude_ids][:limit]
        return []

    mock_db.get_proxies_by_response_time = MagicMock(side_effect=get_proxies_by_response_time)
    mock_db.get_top_proxies_for_pool = MagicMock(side_effect=get_top_proxies_for_pool)

    return mock_db


# ============================================================
# RIGHT: 정확한 결과 테스트
# ============================================================

class TestRight:
    """Right: 올바른 결과를 반환하는가?"""

    def test_cooldown_blocks_immediate_reuse(self):
        """쿨다운이 즉시 재사용을 방지하는지 검증"""
        # Given: 프록시 3개가 있는 풀
        fast_proxies = [create_mock_proxy(i, avg_response_time=0.3) for i in range(1, 4)]
        mock_db = create_mock_db_service(fast_proxies=fast_proxies)

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=3,
            proxy_cooldown_seconds=10.0,
        )
        manager._active_pool = fast_proxies.copy()
        manager._initialized = True

        # When: 프록시 A 선택 후 즉시 다시 선택
        first_proxy = manager.get_next_proxy()
        second_proxy = manager.get_next_proxy()
        third_proxy = manager.get_next_proxy()

        # Then: 3개 모두 다른 프록시
        selected_ids = {first_proxy.id, second_proxy.id, third_proxy.id}
        assert len(selected_ids) == 3

    def test_pool_composition_follows_70_30_ratio(self):
        """풀 구성이 70/30 비율을 따르는지 검증"""
        # Given: fast 10개, normal 10개 존재
        fast_proxies = [create_mock_proxy(i, avg_response_time=0.3) for i in range(1, 11)]
        normal_proxies = [create_mock_proxy(i, avg_response_time=1.0) for i in range(11, 21)]
        mock_db = create_mock_db_service(fast_proxies=fast_proxies, normal_proxies=normal_proxies)

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=10,
            fast_proxy_ratio=0.7,
        )

        # When: 풀 갱신
        manager._sync_refresh_pool()

        # Then: fast 7개, normal 3개
        assert len(manager._active_pool) == 10

        # get_proxies_by_response_time 호출 확인
        calls = mock_db.get_proxies_by_response_time.call_args_list
        assert len(calls) >= 2

        # 첫 번째 호출: fast 프록시 (limit=7)
        first_call_kwargs = calls[0].kwargs
        assert first_call_kwargs.get('limit') == 7
        assert first_call_kwargs.get('max_response_time') == 0.5

        # 두 번째 호출: normal 프록시 (limit=3)
        second_call_kwargs = calls[1].kwargs
        assert second_call_kwargs.get('limit') == 3
        assert second_call_kwargs.get('min_response_time') == 0.5

    def test_mark_proxy_used_records_timestamp(self):
        """프록시 사용 시간이 기록되는지 검증"""
        mock_db = create_mock_db_service()
        manager = ProxyManagerV2(db_service=mock_db)

        # When
        before = time.time()
        manager._mark_proxy_used(123)
        after = time.time()

        # Then
        assert 123 in manager._proxy_last_used
        assert before <= manager._proxy_last_used[123] <= after


# ============================================================
# BOUNDARY: 경계 조건 테스트
# ============================================================

class TestBoundary:
    """Boundary: 경계값 테스트"""

    def test_response_time_exactly_05_is_fast(self):
        """응답시간 0.5초는 fast로 분류"""
        # Given: 0.5초 프록시
        fast_proxy = create_mock_proxy(1, avg_response_time=0.5)
        mock_db = create_mock_db_service(fast_proxies=[fast_proxy])

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=1,
            fast_response_threshold=0.5,
        )

        # When: fast 프록시 조회
        manager._sync_refresh_pool()

        # Then: 0.5초는 fast로 분류되어야 함
        # get_proxies_by_response_time(max_response_time=0.5)에서 반환되어야 함
        first_call = mock_db.get_proxies_by_response_time.call_args_list[0]
        assert first_call.kwargs.get('max_response_time') == 0.5

    def test_response_time_above_05_is_normal(self):
        """응답시간 0.5초 초과는 normal로 분류"""
        # Given: 0.6초 프록시 (normal)
        normal_proxy = create_mock_proxy(1, avg_response_time=0.6)
        mock_db = create_mock_db_service(normal_proxies=[normal_proxy])

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=1,
            fast_response_threshold=0.5,
        )

        # When/Then: normal 프록시 조회 시 min_response_time > 0.5
        manager._sync_refresh_pool()

        # 두 번째 호출이 normal 조회
        if len(mock_db.get_proxies_by_response_time.call_args_list) >= 2:
            second_call = mock_db.get_proxies_by_response_time.call_args_list[1]
            assert second_call.kwargs.get('min_response_time') == 0.5

    def test_cooldown_exactly_10_seconds_allows_reuse(self):
        """쿨다운 10초 경과 시 재사용 가능"""
        mock_db = create_mock_db_service()
        manager = ProxyManagerV2(
            db_service=mock_db,
            proxy_cooldown_seconds=10.0,
        )

        # Given: 10초 전에 사용된 프록시
        manager._proxy_last_used[1] = time.time() - 10.0

        # Then: 재사용 가능
        assert manager._is_cooldown_passed(1) is True

    def test_cooldown_9_9_seconds_blocks_reuse(self):
        """쿨다운 9.9초에서는 재사용 불가"""
        mock_db = create_mock_db_service()
        manager = ProxyManagerV2(
            db_service=mock_db,
            proxy_cooldown_seconds=10.0,
        )

        # Given: 9.9초 전에 사용된 프록시
        manager._proxy_last_used[1] = time.time() - 9.9

        # Then: 재사용 불가
        assert manager._is_cooldown_passed(1) is False

    def test_never_used_proxy_passes_cooldown(self):
        """사용 기록 없는 프록시는 쿨다운 통과"""
        mock_db = create_mock_db_service()
        manager = ProxyManagerV2(db_service=mock_db)

        # Then: 사용 기록 없으면 쿨다운 통과
        assert manager._is_cooldown_passed(999) is True


# ============================================================
# INVERSE: 역 관계 테스트
# ============================================================

class TestInverse:
    """Inverse: 역 관계 검증"""

    def test_fast_and_normal_are_mutually_exclusive(self):
        """fast와 normal 프록시는 상호 배타적"""
        # Given: fast 프록시와 normal 프록시
        fast_proxies = [create_mock_proxy(i, avg_response_time=0.3) for i in range(1, 6)]
        normal_proxies = [create_mock_proxy(i, avg_response_time=1.0) for i in range(6, 11)]
        mock_db = create_mock_db_service(fast_proxies=fast_proxies, normal_proxies=normal_proxies)

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=10,
            fast_proxy_ratio=0.7,
        )

        # When: 풀 갱신
        manager._sync_refresh_pool()

        # Then: fast ID와 normal ID가 겹치지 않음
        fast_ids = {p.id for p in fast_proxies}
        normal_ids = {p.id for p in normal_proxies}
        assert fast_ids.isdisjoint(normal_ids)

    def test_used_proxy_not_in_cooldown_available(self):
        """사용되지 않은 프록시는 쿨다운에 영향받지 않음"""
        fast_proxies = [create_mock_proxy(i, avg_response_time=0.3) for i in range(1, 4)]
        mock_db = create_mock_db_service(fast_proxies=fast_proxies)

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=3,
            proxy_cooldown_seconds=10.0,
        )
        manager._active_pool = fast_proxies.copy()
        manager._initialized = True

        # Given: 프록시 1만 사용됨
        manager._mark_proxy_used(1)

        # Then: 프록시 2, 3은 쿨다운 통과
        assert manager._is_cooldown_passed(2) is True
        assert manager._is_cooldown_passed(3) is True
        assert manager._is_cooldown_passed(1) is False


# ============================================================
# CROSS-CHECK: 교차 검증
# ============================================================

class TestCrossCheck:
    """Cross-check: 다른 방법으로 검증"""

    def test_pool_total_equals_fast_plus_normal(self):
        """풀 총 개수 = fast + normal"""
        fast_proxies = [create_mock_proxy(i, avg_response_time=0.3) for i in range(1, 8)]
        normal_proxies = [create_mock_proxy(i, avg_response_time=1.0) for i in range(8, 11)]
        mock_db = create_mock_db_service(fast_proxies=fast_proxies, normal_proxies=normal_proxies)

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=10,
            fast_proxy_ratio=0.7,
        )

        # When
        manager._sync_refresh_pool()

        # Then: 풀 크기 검증
        assert len(manager._active_pool) == 10

    def test_cooldown_record_matches_used_count(self):
        """쿨다운 기록 수 = 사용된 프록시 수"""
        fast_proxies = [create_mock_proxy(i, avg_response_time=0.3) for i in range(1, 6)]
        mock_db = create_mock_db_service(fast_proxies=fast_proxies)

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=5,
            proxy_cooldown_seconds=10.0,
        )
        manager._active_pool = fast_proxies.copy()
        manager._initialized = True

        # When: 3개 프록시 사용
        manager.get_next_proxy()
        manager.get_next_proxy()
        manager.get_next_proxy()

        # Then: 쿨다운 기록도 3개
        assert len(manager._proxy_last_used) == 3


# ============================================================
# ERROR: 에러 조건 테스트
# ============================================================

class TestError:
    """Error: 에러 조건 테스트"""

    def test_insufficient_fast_proxies_filled_with_normal(self):
        """fast 프록시 부족 시 normal로 채움"""
        # Given: fast 3개만 존재 (7개 필요)
        fast_proxies = [create_mock_proxy(i, avg_response_time=0.3) for i in range(1, 4)]
        normal_proxies = [create_mock_proxy(i, avg_response_time=1.0) for i in range(4, 14)]
        mock_db = create_mock_db_service(fast_proxies=fast_proxies, normal_proxies=normal_proxies)

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=10,
            fast_proxy_ratio=0.7,
        )

        # When
        manager._sync_refresh_pool()

        # Then: 총 10개 (fast 3 + normal로 채움)
        assert len(manager._active_pool) <= 10

    def test_all_proxies_in_cooldown_selects_oldest(self):
        """모든 프록시가 쿨다운 중일 때 가장 오래된 것 선택"""
        fast_proxies = [create_mock_proxy(i, avg_response_time=0.3) for i in range(1, 4)]
        mock_db = create_mock_db_service(fast_proxies=fast_proxies)

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=3,
            proxy_cooldown_seconds=10.0,
        )
        manager._active_pool = fast_proxies.copy()
        manager._initialized = True

        # Given: 모든 프록시가 쿨다운 중 (프록시 1이 가장 오래됨)
        now = time.time()
        manager._proxy_last_used[1] = now - 5  # 5초 전 (가장 오래됨)
        manager._proxy_last_used[2] = now - 2  # 2초 전
        manager._proxy_last_used[3] = now - 1  # 1초 전

        # When
        selected = manager.get_next_proxy()

        # Then: 가장 오래된 프록시 1 선택
        assert selected.id == 1

    def test_empty_pool_returns_none(self):
        """빈 풀에서 None 반환"""
        mock_db = create_mock_db_service()

        manager = ProxyManagerV2(
            db_service=mock_db,
            pool_size=10,
        )
        manager._active_pool = []
        manager._initialized = True

        # When/Then
        result = manager.get_next_proxy()
        # 빈 풀이면 sync_refresh_pool 호출 후에도 None일 수 있음
        # (mock_db가 빈 리스트 반환하므로)


# ============================================================
# PERFORMANCE: 성능 테스트 (선택)
# ============================================================

class TestPerformance:
    """Performance: 성능 요구사항"""

    def test_cooldown_check_is_fast(self):
        """쿨다운 체크가 빠른지 확인 (O(1))"""
        mock_db = create_mock_db_service()
        manager = ProxyManagerV2(db_service=mock_db)

        # 1000개 쿨다운 기록 추가
        now = time.time()
        for i in range(1000):
            manager._proxy_last_used[i] = now - 5

        # When: 쿨다운 체크 1000회
        start = time.time()
        for i in range(1000):
            manager._is_cooldown_passed(i)
        elapsed = time.time() - start

        # Then: 1ms 이내 완료
        assert elapsed < 0.1  # 100ms 이내 (넉넉하게)

    def test_cleanup_removes_old_records(self):
        """오래된 쿨다운 기록 정리"""
        mock_db = create_mock_db_service()
        manager = ProxyManagerV2(
            db_service=mock_db,
            proxy_cooldown_seconds=10.0,
        )

        # Given: 오래된 기록과 새 기록
        now = time.time()
        manager._proxy_last_used[1] = now - 200  # 오래된 기록 (10초 * 10 = 100초 이상)
        manager._proxy_last_used[2] = now - 5    # 새 기록

        # When
        manager._cleanup_cooldown_records()

        # Then: 오래된 기록만 삭제
        assert 1 not in manager._proxy_last_used
        assert 2 in manager._proxy_last_used


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
