"""
GraphQL 응답 로깅 기능 테스트
작성일: 2025-12-16
요구사항: 실행내역 페이지에서 GraphQL 응답 확인 기능

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
- Reference: 참조 검증
- Existence: 존재 여부
- Cardinality: 개수 검증
- Time: 시간 관련 테스트
"""

import pytest
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.naver_booking.services.graphql_client import (
    NaverGraphQLClient,
    ScheduleInfo,
    ScheduleSlot,
)
from app.modules.naver_booking.services.anonymous_monitor import (
    AnonymousMonitor,
    AvailabilityResult,
)
from app.services.event_logger import EventLogger, AsyncEventLogger
from app.schemas.monitoring_event import MonitoringEvent as MonitoringEventSchema


# ============================================================
# 테스트 픽스처
# ============================================================

@pytest.fixture
def sample_graphql_response():
    """샘플 GraphQL 응답 데이터"""
    return {
        "schedule": {
            "bizItemSchedule": {
                "hourly": [
                    {
                        "slotId": "slot_001",
                        "unitStartTime": "2025-12-20 10:00:00",
                        "isBusinessDay": True,
                        "isSaleDay": True,
                        "stock": 10,
                        "unitStock": 5,
                        "unitBookingCount": 2,
                        "duration": 60,
                        "minBookingCount": 1,
                        "maxBookingCount": 4,
                        "prices": [{"name": "성인", "price": 30000}]
                    },
                    {
                        "slotId": "slot_002",
                        "unitStartTime": "2025-12-20 11:00:00",
                        "isBusinessDay": True,
                        "isSaleDay": True,
                        "stock": 10,
                        "unitStock": 5,
                        "unitBookingCount": 5,
                        "duration": 60,
                        "minBookingCount": 1,
                        "maxBookingCount": 4,
                        "prices": [{"name": "성인", "price": 30000}]
                    }
                ]
            }
        }
    }


@pytest.fixture
def sample_empty_response():
    """빈 슬롯 응답"""
    return {
        "schedule": {
            "bizItemSchedule": {
                "hourly": []
            }
        }
    }


@pytest.fixture
def sample_large_response():
    """대용량 슬롯 응답 (100개 슬롯)"""
    hourly = []
    for i in range(100):
        hour = 10 + (i // 6)
        minute = (i % 6) * 10
        hourly.append({
            "slotId": f"slot_{i:03d}",
            "unitStartTime": f"2025-12-20 {hour:02d}:{minute:02d}:00",
            "isBusinessDay": True,
            "isSaleDay": True,
            "stock": 10,
            "unitStock": 5,
            "unitBookingCount": i % 5,
            "duration": 60,
            "minBookingCount": 1,
            "maxBookingCount": 4,
            "prices": [{"name": "성인", "price": 30000}]
        })
    return {
        "schedule": {
            "bizItemSchedule": {
                "hourly": hourly
            }
        }
    }


# ============================================================
# RIGHT: 올바른 결과 테스트
# ============================================================

class TestRightResults:
    """RIGHT: 올바른 결과가 반환되는가?"""

    def test_schedule_info_includes_raw_response(self, sample_graphql_response):
        """ScheduleInfo에 raw_response가 포함되는지 확인"""
        schedule = ScheduleInfo(
            business_id="12345",
            biz_item_id="67890",
            available_dates=["2025-12-20"],
            slots=[],
            slots_by_date={},
            proxy_url=None,
            raw_response=sample_graphql_response
        )

        assert schedule.raw_response is not None
        assert schedule.raw_response == sample_graphql_response
        assert "schedule" in schedule.raw_response
        assert "bizItemSchedule" in schedule.raw_response["schedule"]

    def test_availability_result_includes_raw_response(self, sample_graphql_response):
        """AvailabilityResult에 raw_response가 포함되는지 확인"""
        result = AvailabilityResult(
            available=True,
            slots=[],
            all_active_slots=[],
            estimated_hours=("10:00", "11:00"),
            proxy_url=None,
            http_ok=True,
            raw_response=sample_graphql_response
        )

        assert result.raw_response is not None
        assert result.raw_response == sample_graphql_response

    def test_schema_parses_json_string(self, sample_graphql_response):
        """스키마가 JSON 문자열을 파싱하는지 확인"""
        json_str = json.dumps(sample_graphql_response)

        schema = MonitoringEventSchema(
            id=1,
            schedule_id=1,
            timestamp=datetime.now(),
            event_type="check",
            status="success",
            graphql_response=json_str  # JSON 문자열로 전달
        )

        # validator가 JSON 문자열을 파싱해야 함
        assert schema.graphql_response is not None
        assert isinstance(schema.graphql_response, dict)
        assert "schedule" in schema.graphql_response


# ============================================================
# BOUNDARY: 경계값 테스트
# ============================================================

class TestBoundaryConditions:
    """BOUNDARY: 경계 조건 테스트"""

    def test_null_graphql_response(self):
        """null 응답 처리"""
        result = AvailabilityResult(
            available=False,
            slots=[],
            raw_response=None
        )

        assert result.raw_response is None

    def test_empty_graphql_response(self, sample_empty_response):
        """빈 슬롯 응답 처리"""
        schedule = ScheduleInfo(
            business_id="12345",
            biz_item_id="67890",
            available_dates=[],
            slots=[],
            slots_by_date={},
            raw_response=sample_empty_response
        )

        assert schedule.raw_response is not None
        assert schedule.raw_response["schedule"]["bizItemSchedule"]["hourly"] == []

    def test_large_graphql_response(self, sample_large_response):
        """대용량 응답 처리 (100개 슬롯)"""
        schedule = ScheduleInfo(
            business_id="12345",
            biz_item_id="67890",
            available_dates=["2025-12-20"],
            slots=[],
            slots_by_date={},
            raw_response=sample_large_response
        )

        assert schedule.raw_response is not None
        hourly = schedule.raw_response["schedule"]["bizItemSchedule"]["hourly"]
        assert len(hourly) == 100

    def test_schema_handles_invalid_json_string(self):
        """잘못된 JSON 문자열 처리"""
        schema = MonitoringEventSchema(
            id=1,
            schedule_id=1,
            timestamp=datetime.now(),
            event_type="check",
            status="success",
            graphql_response="invalid json {"  # 잘못된 JSON
        )

        # validator가 None을 반환해야 함
        assert schema.graphql_response is None

    def test_schema_handles_dict_directly(self, sample_graphql_response):
        """딕셔너리가 직접 전달될 때 처리"""
        schema = MonitoringEventSchema(
            id=1,
            schedule_id=1,
            timestamp=datetime.now(),
            event_type="check",
            status="success",
            graphql_response=sample_graphql_response  # 딕셔너리로 전달
        )

        assert schema.graphql_response is not None
        assert schema.graphql_response == sample_graphql_response


# ============================================================
# INVERSE: 역관계 검증
# ============================================================

class TestInverseRelations:
    """INVERSE: 저장 후 불러오면 동일한 결과"""

    def test_json_serialize_deserialize(self, sample_graphql_response):
        """JSON 직렬화/역직렬화 검증"""
        # 직렬화
        json_str = json.dumps(sample_graphql_response)

        # 역직렬화
        parsed = json.loads(json_str)

        assert parsed == sample_graphql_response

    def test_schema_roundtrip(self, sample_graphql_response):
        """스키마를 통한 왕복 변환 검증"""
        json_str = json.dumps(sample_graphql_response)

        schema = MonitoringEventSchema(
            id=1,
            schedule_id=1,
            timestamp=datetime.now(),
            event_type="check",
            status="success",
            graphql_response=json_str
        )

        # 스키마에서 다시 JSON 문자열로
        output = json.dumps(schema.graphql_response)
        re_parsed = json.loads(output)

        assert re_parsed == sample_graphql_response


# ============================================================
# CROSS-CHECK: 교차 검증
# ============================================================

class TestCrossCheck:
    """CROSS-CHECK: 다른 방법으로 검증"""

    def test_slot_count_matches_response(self, sample_graphql_response):
        """슬롯 개수가 응답과 일치하는지 검증"""
        hourly = sample_graphql_response["schedule"]["bizItemSchedule"]["hourly"]
        expected_count = len(hourly)

        schedule = ScheduleInfo(
            business_id="12345",
            biz_item_id="67890",
            available_dates=["2025-12-20"],
            slots=[],
            slots_by_date={},
            raw_response=sample_graphql_response
        )

        actual_count = len(schedule.raw_response["schedule"]["bizItemSchedule"]["hourly"])
        assert actual_count == expected_count

    def test_available_slots_calculation(self, sample_graphql_response):
        """예약 가능 슬롯 계산 검증"""
        hourly = sample_graphql_response["schedule"]["bizItemSchedule"]["hourly"]

        # 직접 계산
        available_count = 0
        for slot in hourly:
            remaining = slot["unitStock"] - slot["unitBookingCount"]
            if slot["isSaleDay"] and remaining > 0:
                available_count += 1

        # slot_001: 5-2=3 > 0 → 가능
        # slot_002: 5-5=0 → 불가능
        assert available_count == 1


# ============================================================
# ERROR: 에러 조건 테스트
# ============================================================

class TestErrorConditions:
    """ERROR: 에러 상황 처리"""

    def test_malformed_response_structure(self):
        """잘못된 응답 구조 처리"""
        malformed = {
            "data": {
                "wrong_key": {}
            }
        }

        schedule = ScheduleInfo(
            business_id="12345",
            biz_item_id="67890",
            available_dates=[],
            slots=[],
            slots_by_date={},
            raw_response=malformed
        )

        # 저장은 되지만 hourly 키가 없음
        assert schedule.raw_response is not None
        assert "hourly" not in schedule.raw_response.get("schedule", {}).get("bizItemSchedule", {})

    def test_graphql_error_response(self):
        """GraphQL 에러 응답 처리"""
        error_response = {
            "errors": [
                {"message": "Invalid business ID", "path": ["schedule"]}
            ],
            "data": None
        }

        result = AvailabilityResult(
            available=False,
            slots=[],
            error="graphql_failed",
            raw_response=error_response
        )

        assert result.raw_response is not None
        assert "errors" in result.raw_response


# ============================================================
# CONFORMANCE: 형식 준수 테스트
# ============================================================

class TestConformance:
    """CONFORMANCE: 형식 준수"""

    def test_response_structure_conforms_to_schema(self, sample_graphql_response):
        """응답 구조가 예상 스키마를 따르는지 확인"""
        assert "schedule" in sample_graphql_response
        assert "bizItemSchedule" in sample_graphql_response["schedule"]
        assert "hourly" in sample_graphql_response["schedule"]["bizItemSchedule"]

        for slot in sample_graphql_response["schedule"]["bizItemSchedule"]["hourly"]:
            assert "slotId" in slot
            assert "unitStartTime" in slot
            assert "isSaleDay" in slot
            assert "unitStock" in slot
            assert "unitBookingCount" in slot


# ============================================================
# EXISTENCE: 존재 여부 테스트
# ============================================================

class TestExistence:
    """EXISTENCE: 존재 여부 확인"""

    def test_raw_response_field_exists_in_schedule_info(self):
        """ScheduleInfo에 raw_response 필드가 존재하는지 확인"""
        schedule = ScheduleInfo(
            business_id="12345",
            biz_item_id="67890",
            available_dates=[],
            slots=[],
            slots_by_date={}
        )

        # raw_response는 Optional이므로 기본값 None
        assert hasattr(schedule, "raw_response")

    def test_raw_response_field_exists_in_availability_result(self):
        """AvailabilityResult에 raw_response 필드가 존재하는지 확인"""
        result = AvailabilityResult(
            available=False,
            slots=[]
        )

        assert hasattr(result, "raw_response")

    def test_graphql_response_field_exists_in_schema(self):
        """MonitoringEventSchema에 graphql_response 필드가 존재하는지 확인"""
        schema = MonitoringEventSchema(
            id=1,
            schedule_id=1,
            timestamp=datetime.now(),
            event_type="check",
            status="success"
        )

        assert hasattr(schema, "graphql_response")


# ============================================================
# CARDINALITY: 개수 검증
# ============================================================

class TestCardinality:
    """CARDINALITY: 개수 검증"""

    def test_single_response_per_event(self, sample_graphql_response):
        """이벤트당 하나의 응답만 저장되는지 확인"""
        schema = MonitoringEventSchema(
            id=1,
            schedule_id=1,
            timestamp=datetime.now(),
            event_type="check",
            status="success",
            graphql_response=sample_graphql_response
        )

        # graphql_response는 단일 객체
        assert isinstance(schema.graphql_response, (dict, type(None)))


# ============================================================
# PERFORMANCE: 성능 테스트 (간단한 벤치마크)
# ============================================================

class TestPerformance:
    """PERFORMANCE: 성능 관련 테스트"""

    def test_large_response_json_operations(self, sample_large_response):
        """대용량 응답의 JSON 작업 성능"""
        import time

        # 직렬화 시간 측정
        start = time.time()
        json_str = json.dumps(sample_large_response)
        serialize_time = time.time() - start

        # 역직렬화 시간 측정
        start = time.time()
        parsed = json.loads(json_str)
        deserialize_time = time.time() - start

        # 100개 슬롯 기준 1초 이내 완료되어야 함
        assert serialize_time < 1.0, f"직렬화 시간 초과: {serialize_time}s"
        assert deserialize_time < 1.0, f"역직렬화 시간 초과: {deserialize_time}s"


# ============================================================
# 통합 테스트
# ============================================================

class TestIntegration:
    """통합 테스트"""

    def test_full_flow_with_graphql_response(self, sample_graphql_response):
        """전체 흐름 테스트: GraphQL 응답 → ScheduleInfo → AvailabilityResult"""
        # 1. ScheduleInfo 생성
        schedule = ScheduleInfo(
            business_id="12345",
            biz_item_id="67890",
            available_dates=["2025-12-20"],
            slots=[],
            slots_by_date={},
            proxy_url="http://proxy:8080",
            raw_response=sample_graphql_response
        )

        # 2. AvailabilityResult 생성
        result = AvailabilityResult(
            available=True,
            slots=[],
            all_active_slots=[],
            estimated_hours=("10:00", "11:00"),
            proxy_url=schedule.proxy_url,
            http_ok=True,
            raw_response=schedule.raw_response
        )

        # 3. 검증
        assert result.raw_response == sample_graphql_response
        assert result.proxy_url == "http://proxy:8080"

        # 4. JSON 직렬화 가능 확인
        json_str = json.dumps(result.raw_response)
        assert len(json_str) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
