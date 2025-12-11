"""
Anonymous 모드 Rate Limiting 테스트
작성일: 2025-12-11

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

테스트 대상:
1. Anonymous 태스크 수 추적
2. Anonymous 모드 동시 실행 제한
3. 태스크 등록/해제
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings


# ============================================================
# Mock 클래스 정의
# ============================================================

class MockTabPoolManager:
    """모의 TabPoolManager"""
    def __init__(self):
        self.tab_in_use = {}


class MockMonitoringExecutor:
    """모의 MonitoringExecutor"""
    pass


class MockScheduleService:
    """모의 ScheduleService"""
    def __init__(self):
        self.schedules = {}

    def get_schedule(self, schedule_id):
        return self.schedules.get(schedule_id, {
            "id": schedule_id,
            "url": "https://booking.naver.com/test",
            "label": f"테스트 스케줄 {schedule_id}",
            "monitoring_mode": "anonymous",
            "is_enabled": True
        })

    def update_schedule(self, schedule_id, data):
        if schedule_id not in self.schedules:
            self.schedules[schedule_id] = {}
        self.schedules[schedule_id].update(data)


# ============================================================
# 테스트 픽스처
# ============================================================

@pytest.fixture
def monitoring_queue():
    """MonitoringQueue 인스턴스 생성"""
    from app.shared.browser.monitoring_queue import MonitoringQueue

    tab_pool = MockTabPoolManager()
    executor = MockMonitoringExecutor()
    schedule_service = MockScheduleService()

    queue = MonitoringQueue(tab_pool, executor, schedule_service)
    # PriorityQueue 초기화
    queue.monitoring_queue = asyncio.PriorityQueue()

    return queue


# ============================================================
# 1. Anonymous 태스크 추적 테스트
# ============================================================

class TestAnonymousTaskTracking:
    """Anonymous 태스크 추적 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_initial_anonymous_count_zero(self, monitoring_queue):
        """
        [Right] 초기 Anonymous 태스크 수가 0인지
        """
        count = monitoring_queue._get_active_anonymous_count()
        assert count == 0

    def test_right_register_anonymous_task(self, monitoring_queue):
        """
        [Right] Anonymous 태스크 등록이 동작하는지
        """
        monitoring_queue._register_anonymous_task(1)
        monitoring_queue._register_anonymous_task(2)
        monitoring_queue._register_anonymous_task(3)

        assert 1 in monitoring_queue.anonymous_task_ids
        assert 2 in monitoring_queue.anonymous_task_ids
        assert 3 in monitoring_queue.anonymous_task_ids
        assert len(monitoring_queue.anonymous_task_ids) == 3

    def test_right_unregister_anonymous_task(self, monitoring_queue):
        """
        [Right] Anonymous 태스크 해제가 동작하는지
        """
        monitoring_queue._register_anonymous_task(1)
        monitoring_queue._register_anonymous_task(2)

        monitoring_queue._unregister_anonymous_task(1)

        assert 1 not in monitoring_queue.anonymous_task_ids
        assert 2 in monitoring_queue.anonymous_task_ids

    def test_right_get_active_count_with_tasks(self, monitoring_queue):
        """
        [Right] 활성 태스크 수가 올바르게 계산되는지
        """
        # 완료되지 않은 태스크 모의
        task1 = MagicMock()
        task1.done.return_value = False
        task2 = MagicMock()
        task2.done.return_value = False

        monitoring_queue.monitoring_tasks[1] = task1
        monitoring_queue.monitoring_tasks[2] = task2

        monitoring_queue._register_anonymous_task(1)
        monitoring_queue._register_anonymous_task(2)

        count = monitoring_queue._get_active_anonymous_count()
        assert count == 2

    # --- Boundary: 경계값 테스트 ---

    def test_boundary_completed_tasks_excluded(self, monitoring_queue):
        """
        [Boundary] 완료된 태스크가 카운트에서 제외되는지
        """
        # 완료된 태스크
        completed_task = MagicMock()
        completed_task.done.return_value = True

        # 활성 태스크
        active_task = MagicMock()
        active_task.done.return_value = False

        monitoring_queue.monitoring_tasks[1] = completed_task
        monitoring_queue.monitoring_tasks[2] = active_task

        monitoring_queue._register_anonymous_task(1)
        monitoring_queue._register_anonymous_task(2)

        count = monitoring_queue._get_active_anonymous_count()

        assert count == 1  # 완료된 태스크 제외
        assert 1 not in monitoring_queue.anonymous_task_ids  # 정리됨
        assert 2 in monitoring_queue.anonymous_task_ids

    def test_boundary_missing_task_cleaned_up(self, monitoring_queue):
        """
        [Boundary] monitoring_tasks에 없는 태스크 ID가 정리되는지
        """
        monitoring_queue._register_anonymous_task(1)
        monitoring_queue._register_anonymous_task(2)

        # task 2만 존재
        task2 = MagicMock()
        task2.done.return_value = False
        monitoring_queue.monitoring_tasks[2] = task2

        count = monitoring_queue._get_active_anonymous_count()

        assert count == 1  # 1은 없으므로 제외
        assert 1 not in monitoring_queue.anonymous_task_ids  # 정리됨

    # --- Error: 에러 조건 테스트 ---

    def test_error_unregister_nonexistent_task(self, monitoring_queue):
        """
        [Error] 존재하지 않는 태스크 해제 시 오류 없이 처리되는지
        """
        monitoring_queue._unregister_anonymous_task(999)
        # 예외 없이 통과해야 함
        assert 999 not in monitoring_queue.anonymous_task_ids

    def test_error_duplicate_register(self, monitoring_queue):
        """
        [Error] 중복 등록 시 오류 없이 처리되는지 (set이므로)
        """
        monitoring_queue._register_anonymous_task(1)
        monitoring_queue._register_anonymous_task(1)
        monitoring_queue._register_anonymous_task(1)

        assert len(monitoring_queue.anonymous_task_ids) == 1


# ============================================================
# 2. Anonymous 모드 동시 실행 제한 테스트
# ============================================================

class TestAnonymousConcurrencyLimit:
    """Anonymous 모드 동시 실행 제한 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_max_concurrent_setting_loaded(self, monitoring_queue):
        """
        [Right] MAX_CONCURRENT_ANONYMOUS 설정이 로드되는지
        """
        assert monitoring_queue.MAX_CONCURRENT_ANONYMOUS == settings.MAX_CONCURRENT_ANONYMOUS
        assert monitoring_queue.MAX_CONCURRENT_ANONYMOUS > 0

    def test_right_under_limit_allowed(self, monitoring_queue):
        """
        [Right] 제한 미만일 때 추가가 허용되는지
        """
        # 제한 -1 개의 태스크 등록
        for i in range(monitoring_queue.MAX_CONCURRENT_ANONYMOUS - 1):
            task = MagicMock()
            task.done.return_value = False
            monitoring_queue.monitoring_tasks[i] = task
            monitoring_queue._register_anonymous_task(i)

        count = monitoring_queue._get_active_anonymous_count()

        assert count < monitoring_queue.MAX_CONCURRENT_ANONYMOUS

    # --- Boundary: 경계값 테스트 ---

    def test_boundary_exactly_at_limit(self, monitoring_queue):
        """
        [Boundary] 정확히 제한에 도달했을 때
        """
        # 정확히 제한 개수만큼 등록
        for i in range(monitoring_queue.MAX_CONCURRENT_ANONYMOUS):
            task = MagicMock()
            task.done.return_value = False
            monitoring_queue.monitoring_tasks[i] = task
            monitoring_queue._register_anonymous_task(i)

        count = monitoring_queue._get_active_anonymous_count()

        assert count == monitoring_queue.MAX_CONCURRENT_ANONYMOUS

    # --- Cross-check: 교차 검증 ---

    def test_crosscheck_limit_respected_after_completion(self, monitoring_queue):
        """
        [Cross-check] 태스크 완료 후 제한이 다시 적용되는지
        """
        # 제한까지 등록
        for i in range(monitoring_queue.MAX_CONCURRENT_ANONYMOUS):
            task = MagicMock()
            task.done.return_value = False
            monitoring_queue.monitoring_tasks[i] = task
            monitoring_queue._register_anonymous_task(i)

        initial_count = monitoring_queue._get_active_anonymous_count()

        # 2개 완료 처리
        monitoring_queue.monitoring_tasks[0].done.return_value = True
        monitoring_queue.monitoring_tasks[1].done.return_value = True

        new_count = monitoring_queue._get_active_anonymous_count()

        assert initial_count == monitoring_queue.MAX_CONCURRENT_ANONYMOUS
        assert new_count == monitoring_queue.MAX_CONCURRENT_ANONYMOUS - 2


# ============================================================
# 3. 통합 테스트
# ============================================================

class TestAnonymousRateLimitingIntegration:
    """Anonymous Rate Limiting 통합 테스트"""

    def test_integration_task_lifecycle(self, monitoring_queue):
        """
        [Integration] 태스크 전체 라이프사이클이 올바르게 동작하는지
        """
        # 1. 초기 상태
        assert monitoring_queue._get_active_anonymous_count() == 0

        # 2. 태스크 등록
        task = MagicMock()
        task.done.return_value = False
        monitoring_queue.monitoring_tasks[1] = task
        monitoring_queue._register_anonymous_task(1)

        assert monitoring_queue._get_active_anonymous_count() == 1

        # 3. 태스크 완료
        task.done.return_value = True
        count_after_complete = monitoring_queue._get_active_anonymous_count()

        assert count_after_complete == 0
        assert 1 not in monitoring_queue.anonymous_task_ids

        # 4. 명시적 해제 (이미 정리됨)
        monitoring_queue._unregister_anonymous_task(1)

        assert monitoring_queue._get_active_anonymous_count() == 0

    def test_integration_mixed_mode_tasks(self, monitoring_queue):
        """
        [Integration] Anonymous와 Tab 모드 태스크가 혼합될 때
        """
        # Anonymous 태스크
        anon_task = MagicMock()
        anon_task.done.return_value = False
        monitoring_queue.monitoring_tasks[1] = anon_task
        monitoring_queue._register_anonymous_task(1)

        # Tab 모드 태스크 (anonymous_task_ids에 등록하지 않음)
        tab_task = MagicMock()
        tab_task.done.return_value = False
        monitoring_queue.monitoring_tasks[2] = tab_task

        # 전체 태스크 수
        total_tasks = len([t for t in monitoring_queue.monitoring_tasks.values()
                          if not t.done()])
        # Anonymous 태스크 수
        anon_count = monitoring_queue._get_active_anonymous_count()

        assert total_tasks == 2
        assert anon_count == 1


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
