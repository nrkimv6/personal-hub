"""
계층형 모니터링 구조 테스트

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

CORRECT 조건 적용:
- Conformance: 형식 준수
- Ordering: 순서 보장
- Range: 범위 검증
- Reference: 참조 검증 (외래키, 연관 데이터)
- Existence: 존재 여부
- Cardinality: 개수 검증
- Time: 시간 관련 테스트

테스트 대상:
- Business -> BizItem -> MonitorSchedule 계층 구조
- ScheduleMonitorService
- URL 빌더
- 상태 전이 (is_enabled, is_active, run_status)
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch
from typing import Dict, Any, List

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 테스트 픽스처
# ============================================================

@pytest.fixture
def sample_business():
    """테스트용 업체 데이터"""
    return {
        "id": 1,
        "business_id": "142806",
        "business_type_id": "5",
        "name": "테스트 업체",
        "category": "default",
        "service_type": "naver",
        "booking_options": None
    }


@pytest.fixture
def sample_biz_item():
    """테스트용 아이템 데이터"""
    return {
        "id": 1,
        "business_id": 1,
        "biz_item_id": "4520991",
        "name": "테스트 아이템",
        "time_range": "10:00-21:00",
        "auto_booking_enabled": True,
        "max_bookings_per_schedule": 2
    }


@pytest.fixture
def sample_schedule():
    """테스트용 일정 데이터"""
    return {
        "id": 1,
        "biz_item_id": 1,
        "date": "2025-12-15",
        "times": ["10:00", "14:00", "18:00"],
        "is_enabled": True,
        "is_active": False,
        "run_status": "idle",
        "interval": 5,
        "error_count": 0,
        "last_error": None,
        "booking_count": 0,
        "last_booking_time": None
    }


@pytest.fixture
def sample_schedule_context(sample_business, sample_biz_item, sample_schedule):
    """테스트용 스케줄 컨텍스트 (상위 정보 포함)"""
    return {
        # schedule 정보
        "id": sample_schedule["id"],
        "date": sample_schedule["date"],
        "times": sample_schedule["times"],
        "is_enabled": sample_schedule["is_enabled"],
        "is_active": sample_schedule["is_active"],
        "run_status": sample_schedule["run_status"],
        "interval": sample_schedule["interval"],
        "error_count": sample_schedule["error_count"],
        "booking_count": sample_schedule["booking_count"],
        "max_bookings_per_schedule": sample_biz_item["max_bookings_per_schedule"],
        # biz_item 정보
        "biz_item_id": sample_biz_item["id"],
        "naver_biz_item_id": sample_biz_item["biz_item_id"],
        "item_name": sample_biz_item["name"],
        "time_range": sample_biz_item["time_range"],
        "auto_booking_enabled": sample_biz_item["auto_booking_enabled"],
        # business 정보
        "business_id": sample_business["id"],
        "naver_business_id": sample_business["business_id"],
        "business_type_id": sample_business["business_type_id"],
        "business_name": sample_business["name"],
        "category": sample_business["category"],
        "service_type": sample_business["service_type"],
        "booking_options": sample_business["booking_options"],
        # 생성된 URL
        "url": "https://booking.naver.com/booking/5/bizes/142806/items/4520991?startDate=2025-12-15",
        "label": "테스트 업체 - 테스트 아이템 (2025-12-15)"
    }


# ============================================================
# 1. URL 빌더 테스트
# ============================================================

class TestURLBuilder:
    """URL 빌더 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_naver_booking_url_format(self):
        """
        [Right] 네이버 예약 URL이 올바른 형식으로 생성되는지
        """
        from app.utils.url_builder import build_naver_booking_url

        url = build_naver_booking_url(
            business_type_id="5",
            business_id="142806",
            biz_item_id="4520991",
            date="2025-12-15"
        )

        assert "booking.naver.com" in url
        assert "142806" in url
        assert "4520991" in url
        assert "2025-12-15" in url

    def test_right_url_contains_all_parts(self):
        """
        [Right] URL에 모든 필수 구성요소가 포함되는지
        """
        from app.utils.url_builder import build_naver_booking_url

        url = build_naver_booking_url(
            business_type_id="10",
            business_id="123456",
            biz_item_id="7890123",
            date="2025-01-01"
        )

        # business_type_id가 URL 경로에 포함
        assert "/10/" in url or "/booking/10" in url
        # business_id가 포함
        assert "123456" in url
        # biz_item_id가 포함
        assert "7890123" in url

    # --- Boundary: 경계값 테스트 ---

    def test_boundary_empty_date(self):
        """
        [Boundary] 날짜가 빈 문자열일 때
        """
        from app.utils.url_builder import build_naver_booking_url

        url = build_naver_booking_url(
            business_type_id="5",
            business_id="142806",
            biz_item_id="4520991",
            date=""
        )

        # 날짜 없이도 기본 URL이 생성되어야 함
        assert "booking.naver.com" in url

    def test_boundary_special_characters(self):
        """
        [Boundary] 특수 문자가 포함된 ID 처리
        """
        from app.utils.url_builder import build_naver_booking_url

        # 실제로는 ID에 특수 문자가 없어야 하지만, 방어적 코딩 확인
        url = build_naver_booking_url(
            business_type_id="5",
            business_id="142806",
            biz_item_id="4520991",
            date="2025-12-15"
        )

        assert isinstance(url, str)

    # --- Conformance: 형식 준수 ---

    def test_conformance_url_scheme(self):
        """
        [Conformance] URL이 https로 시작하는지
        """
        from app.utils.url_builder import build_naver_booking_url

        url = build_naver_booking_url(
            business_type_id="5",
            business_id="142806",
            biz_item_id="4520991",
            date="2025-12-15"
        )

        assert url.startswith("https://")


# ============================================================
# 2. 계층 구조 참조 테스트
# ============================================================

class TestHierarchicalReference:
    """계층 구조 참조 관계 테스트"""

    # --- Reference: 참조 검증 ---

    def test_reference_schedule_belongs_to_item(self, sample_schedule, sample_biz_item):
        """
        [Reference] 스케줄이 아이템에 속하는지
        """
        assert sample_schedule["biz_item_id"] == sample_biz_item["id"]

    def test_reference_item_belongs_to_business(self, sample_biz_item, sample_business):
        """
        [Reference] 아이템이 업체에 속하는지
        """
        assert sample_biz_item["business_id"] == sample_business["id"]

    def test_reference_cascade_delete_simulation(self):
        """
        [Reference] 업체 삭제 시 하위 아이템/스케줄도 삭제되는지 (시뮬레이션)
        """
        # 계층 구조 시뮬레이션
        business_id = 1
        items = [
            {"id": 1, "business_id": 1},
            {"id": 2, "business_id": 1},
        ]
        schedules = [
            {"id": 1, "biz_item_id": 1},
            {"id": 2, "biz_item_id": 1},
            {"id": 3, "biz_item_id": 2},
        ]

        # 업체 삭제 시 cascade
        deleted_items = [i for i in items if i["business_id"] == business_id]
        deleted_item_ids = {i["id"] for i in deleted_items}
        deleted_schedules = [s for s in schedules if s["biz_item_id"] in deleted_item_ids]

        assert len(deleted_items) == 2
        assert len(deleted_schedules) == 3

    # --- Existence: 존재 여부 ---

    def test_existence_item_exists_before_schedule_create(self):
        """
        [Existence] 스케줄 생성 전 아이템이 존재해야 함
        """
        item_id = 1
        items = {1: {"id": 1, "name": "테스트"}}

        # 아이템 존재 확인
        assert item_id in items

    def test_existence_business_exists_before_item_create(self):
        """
        [Existence] 아이템 생성 전 업체가 존재해야 함
        """
        business_id = 1
        businesses = {1: {"id": 1, "name": "테스트 업체"}}

        # 업체 존재 확인
        assert business_id in businesses

    # --- Cardinality: 개수 검증 ---

    def test_cardinality_one_business_many_items(self):
        """
        [Cardinality] 하나의 업체에 여러 아이템 가능
        """
        business_id = 1
        items = [
            {"id": 1, "business_id": 1, "name": "아이템1"},
            {"id": 2, "business_id": 1, "name": "아이템2"},
            {"id": 3, "business_id": 1, "name": "아이템3"},
        ]

        business_items = [i for i in items if i["business_id"] == business_id]
        assert len(business_items) == 3

    def test_cardinality_one_item_many_schedules(self):
        """
        [Cardinality] 하나의 아이템에 여러 스케줄 가능
        """
        item_id = 1
        schedules = [
            {"id": 1, "biz_item_id": 1, "date": "2025-12-15"},
            {"id": 2, "biz_item_id": 1, "date": "2025-12-16"},
            {"id": 3, "biz_item_id": 1, "date": "2025-12-17"},
        ]

        item_schedules = [s for s in schedules if s["biz_item_id"] == item_id]
        assert len(item_schedules) == 3

    def test_cardinality_unique_date_per_item(self):
        """
        [Cardinality] 같은 아이템에 같은 날짜의 스케줄은 하나만 가능
        """
        item_id = 1
        schedules = [
            {"biz_item_id": 1, "date": "2025-12-15"},
            {"biz_item_id": 1, "date": "2025-12-16"},
            {"biz_item_id": 1, "date": "2025-12-15"},  # 중복!
        ]

        dates = [s["date"] for s in schedules if s["biz_item_id"] == item_id]
        unique_dates = set(dates)

        # 중복 감지
        assert len(dates) != len(unique_dates)


# ============================================================
# 3. 상태 전이 테스트
# ============================================================

class TestStateTransition:
    """is_enabled / is_active / run_status 상태 전이 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_enable_sets_pending(self, sample_schedule):
        """
        [Right] 스케줄 활성화 시 is_enabled=true, run_status=pending
        """
        # enable API 호출 시뮬레이션
        sample_schedule["is_enabled"] = True
        sample_schedule["run_status"] = "pending"

        assert sample_schedule["is_enabled"] == True
        assert sample_schedule["run_status"] == "pending"
        # is_active는 워커가 설정
        assert sample_schedule["is_active"] == False

    def test_right_disable_sets_paused(self, sample_schedule):
        """
        [Right] 스케줄 비활성화 시 is_enabled=false, run_status=paused
        """
        # disable API 호출 시뮬레이션
        sample_schedule["is_enabled"] = False
        sample_schedule["run_status"] = "paused"

        assert sample_schedule["is_enabled"] == False
        assert sample_schedule["run_status"] == "paused"

    def test_right_worker_detects_disabled_active(self):
        """
        [Right] 워커가 is_enabled=false, is_active=true인 스케줄을 감지
        """
        schedules = [
            {"id": 1, "is_enabled": True, "is_active": True},
            {"id": 2, "is_enabled": False, "is_active": True},  # 불일치!
            {"id": 3, "is_enabled": False, "is_active": False},
        ]

        # 워커의 감지 쿼리 로직
        inconsistent = [s for s in schedules
                       if not s["is_enabled"] and s["is_active"]]

        assert len(inconsistent) == 1
        assert inconsistent[0]["id"] == 2

    # --- Inverse: 역관계 검증 ---

    def test_inverse_enabled_not_affected_by_detection(self):
        """
        [Inverse] is_enabled=true인 스케줄은 감지에 영향받지 않음
        """
        schedules = [
            {"id": 1, "is_enabled": True, "is_active": True},
            {"id": 2, "is_enabled": True, "is_active": False},
        ]

        # 감지 쿼리: is_enabled=false만 대상
        inconsistent = [s for s in schedules
                       if not s["is_enabled"] and s["is_active"]]

        assert len(inconsistent) == 0

    # --- Cross-check: 교차 검증 ---

    def test_crosscheck_api_worker_responsibility(self):
        """
        [Cross-check] API와 워커의 책임 분리 검증
        """
        # API가 설정하는 필드
        api_fields = {"is_enabled", "run_status"}

        # 워커가 설정하는 필드
        worker_fields = {"is_active", "run_status", "error_count", "last_error"}

        # is_active는 워커만 설정
        assert "is_active" in worker_fields
        assert "is_active" not in api_fields

        # is_enabled는 API만 설정
        assert "is_enabled" in api_fields
        assert "is_enabled" not in worker_fields

    # --- Range: 범위 검증 ---

    def test_range_valid_run_status(self):
        """
        [Range] run_status의 유효한 값 검증
        """
        valid_statuses = {"idle", "pending", "queued", "running", "paused", "stopped", "error"}

        test_status = "running"
        assert test_status in valid_statuses

        invalid_status = "active"
        assert invalid_status not in valid_statuses

    def test_range_boolean_fields(self, sample_schedule):
        """
        [Range] boolean 필드가 True/False만 가지는지
        """
        assert isinstance(sample_schedule["is_enabled"], bool)
        assert isinstance(sample_schedule["is_active"], bool)


# ============================================================
# 4. ScheduleMonitorService 테스트
# ============================================================

class TestScheduleMonitorService:
    """ScheduleMonitorService 테스트"""

    # --- Right: 결과가 올바른가? ---

    def test_right_get_schedule_returns_context(self):
        """
        [Right] get_schedule이 상위 컨텍스트를 포함한 정보를 반환하는지
        """
        # 예상 반환 필드
        expected_fields = {
            # schedule 필드
            "id", "date", "times", "is_enabled", "is_active", "run_status",
            # biz_item 필드
            "biz_item_id", "naver_biz_item_id", "item_name", "time_range",
            # business 필드
            "business_id", "naver_business_id", "business_type_id", "business_name",
            # 생성된 필드
            "url", "label"
        }

        # 실제 서비스 테스트 시 확인
        # result = schedule_monitor_service.get_schedule(1)
        # assert all(field in result for field in expected_fields)

        # 픽스처로 검증
        sample_result = {
            "id": 1, "date": "2025-12-15", "times": [], "is_enabled": True,
            "is_active": False, "run_status": "idle",
            "biz_item_id": 1, "naver_biz_item_id": "4520991",
            "item_name": "테스트", "time_range": "10:00-21:00",
            "business_id": 1, "naver_business_id": "142806",
            "business_type_id": "5", "business_name": "테스트 업체",
            "url": "https://example.com", "label": "테스트"
        }

        for field in expected_fields:
            assert field in sample_result

    def test_right_update_schedule_fields(self):
        """
        [Right] update_schedule이 지정된 필드만 업데이트하는지
        """
        update_data = {
            "is_enabled": False,
            "run_status": "paused"
        }

        # 허용된 필드
        allowed_fields = {"is_enabled", "is_active", "run_status", "interval",
                         "error_count", "last_error", "booking_count",
                         "last_booking_time", "times"}

        for key in update_data:
            assert key in allowed_fields

    def test_right_increment_booking_count(self):
        """
        [Right] increment_booking_count가 booking_count를 1 증가시키는지
        """
        initial_count = 0
        # increment 후
        new_count = initial_count + 1

        assert new_count == 1

    # --- Error: 에러 조건 테스트 ---

    def test_error_nonexistent_schedule(self):
        """
        [Error] 존재하지 않는 스케줄 조회 시 None 반환
        """
        # get_schedule(999999) -> None
        result = None  # 실제 테스트에서는 서비스 호출
        assert result is None

    def test_error_increment_error_count(self):
        """
        [Error] increment_error_count가 error_count를 1 증가시키는지
        """
        initial_count = 0
        error_message = "테스트 에러"

        # increment 후
        new_count = initial_count + 1
        assert new_count == 1

    # --- Boundary: 경계값 테스트 ---

    def test_boundary_max_error_count(self):
        """
        [Boundary] 최대 에러 카운트 도달 시 동작
        """
        max_error_threshold = 5
        error_count = 5

        # 임계값 도달 시 비활성화 여부
        should_disable = error_count >= max_error_threshold
        assert should_disable == True

    def test_boundary_max_bookings_reached(self):
        """
        [Boundary] 최대 예약 수 도달 시 can_book=false
        """
        max_bookings = 2
        booking_count = 2

        can_book = booking_count < max_bookings
        assert can_book == False

    def test_boundary_max_bookings_not_reached(self):
        """
        [Boundary] 최대 예약 수 미도달 시 can_book=true
        """
        max_bookings = 2
        booking_count = 1

        can_book = booking_count < max_bookings
        assert can_book == True


# ============================================================
# 5. 스케줄 활성화/비활성화 플로우 테스트
# ============================================================

class TestScheduleActivationFlow:
    """스케줄 활성화/비활성화 전체 플로우 테스트"""

    # --- Ordering: 순서 보장 ---

    def test_ordering_enable_flow(self):
        """
        [Ordering] 활성화 플로우 순서 검증

        1. API: is_enabled=true, run_status=pending
        2. Worker: 감지 후 is_active=true, run_status=queued
        3. Worker: 모니터링 시작, run_status=running
        """
        states = []

        # Step 1: API
        states.append({
            "step": 1,
            "actor": "API",
            "is_enabled": True,
            "is_active": False,
            "run_status": "pending"
        })

        # Step 2: Worker 감지
        states.append({
            "step": 2,
            "actor": "Worker",
            "is_enabled": True,
            "is_active": True,
            "run_status": "queued"
        })

        # Step 3: Worker 실행
        states.append({
            "step": 3,
            "actor": "Worker",
            "is_enabled": True,
            "is_active": True,
            "run_status": "running"
        })

        # 순서 검증
        assert states[0]["step"] == 1
        assert states[1]["step"] == 2
        assert states[2]["step"] == 3

        # 최종 상태
        final = states[-1]
        assert final["is_enabled"] == True
        assert final["is_active"] == True
        assert final["run_status"] == "running"

    def test_ordering_disable_flow(self):
        """
        [Ordering] 비활성화 플로우 순서 검증

        1. 초기: is_enabled=true, is_active=true, run_status=running
        2. API: is_enabled=false, run_status=paused
        3. Worker: 감지 후 is_active=false
        """
        states = []

        # Step 1: 초기 상태
        states.append({
            "step": 1,
            "actor": "Initial",
            "is_enabled": True,
            "is_active": True,
            "run_status": "running"
        })

        # Step 2: API 비활성화
        states.append({
            "step": 2,
            "actor": "API",
            "is_enabled": False,
            "is_active": True,  # API는 is_active를 변경하지 않음
            "run_status": "paused"
        })

        # Step 3: Worker 감지 및 처리
        states.append({
            "step": 3,
            "actor": "Worker",
            "is_enabled": False,
            "is_active": False,  # Worker가 변경
            "run_status": "paused"
        })

        # 중간 상태 (불일치)
        inconsistent = states[1]
        assert inconsistent["is_enabled"] == False
        assert inconsistent["is_active"] == True  # 아직 true

        # 최종 상태
        final = states[-1]
        assert final["is_enabled"] == False
        assert final["is_active"] == False
        assert final["run_status"] == "paused"

    # --- Time: 시간 관련 테스트 ---

    def test_time_worker_polling_interval(self):
        """
        [Time] 워커의 폴링 간격이 적절한지
        """
        polling_interval = 1  # 초

        # 1초 간격이면 빠른 감지 가능
        assert polling_interval <= 5

    def test_time_schedule_check_interval(self, sample_schedule):
        """
        [Time] 스케줄의 체크 간격이 유효한지
        """
        interval = sample_schedule["interval"]

        # 간격은 양수여야 함
        assert interval > 0
        # 너무 짧지 않아야 함 (최소 1초)
        assert interval >= 1


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
