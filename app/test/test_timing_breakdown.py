"""
타이밍 분석 기능 테스트 (REQ-MON-011)

RIGHT-BICEP 테스트 패턴 적용:
- Right: 올바른 결과 검증
- Boundary: 경계 조건
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건
- Performance: 성능

CORRECT 테스트:
- Conformance: 형식 준수
- Ordering: 순서
- Range: 범위
- Reference: 참조
- Existence: 존재
- Cardinality: 수량
- Time: 시간
"""

import sys
import os
import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

# 상위 디렉토리를 모듈 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.models.monitoring_event import MonitoringEvent as MonitoringEventModel
from app.schemas.monitoring_event import MonitoringEvent as MonitoringEventSchema
from app.schemas.monitoring_event import MonitoringEventBase
from app.services.event_logger import EventLogger, AsyncEventLogger


class TestTimingFieldsRight:
    """RIGHT: 올바른 결과 검증"""

    def test_right_schema_accepts_timing_fields(self):
        """Pydantic 스키마가 타이밍 필드를 올바르게 받는지 검증"""
        # Given: 타이밍 필드가 포함된 데이터
        data = {
            "event_type": "check",
            "status": "success",
            "graphql_time_ms": 1500.5,
            "proxy_retry_count": 2,
            "booking_time_ms": 3000.0,
            "booking_attempt_count": 3
        }

        # When: 스키마 생성
        schema = MonitoringEventBase(**data)

        # Then: 모든 필드가 올바르게 설정됨
        assert schema.graphql_time_ms == 1500.5
        assert schema.proxy_retry_count == 2
        assert schema.booking_time_ms == 3000.0
        assert schema.booking_attempt_count == 3

    def test_right_schema_defaults_to_none(self):
        """타이밍 필드가 없을 때 기본값이 None인지 검증"""
        # Given: 기본 필드만 있는 데이터
        data = {
            "event_type": "check",
            "status": "success"
        }

        # When: 스키마 생성
        schema = MonitoringEventBase(**data)

        # Then: 타이밍 필드가 None
        assert schema.graphql_time_ms is None
        assert schema.proxy_retry_count is None
        assert schema.booking_time_ms is None
        assert schema.booking_attempt_count is None

    def test_right_model_has_timing_columns(self):
        """SQLAlchemy 모델에 타이밍 컬럼이 존재하는지 검증"""
        # Given/When: 모델 컬럼 확인
        columns = [c.name for c in MonitoringEventModel.__table__.columns]

        # Then: 타이밍 컬럼이 존재
        assert "graphql_time_ms" in columns
        assert "proxy_retry_count" in columns
        assert "booking_time_ms" in columns
        assert "booking_attempt_count" in columns

    def test_right_model_timing_columns_nullable(self):
        """타이밍 컬럼이 nullable인지 검증"""
        # Given/When: 컬럼 속성 확인
        graphql_col = MonitoringEventModel.__table__.columns["graphql_time_ms"]
        retry_col = MonitoringEventModel.__table__.columns["proxy_retry_count"]
        booking_col = MonitoringEventModel.__table__.columns["booking_time_ms"]
        attempt_col = MonitoringEventModel.__table__.columns["booking_attempt_count"]

        # Then: 모두 nullable
        assert graphql_col.nullable is True
        assert retry_col.nullable is True
        assert booking_col.nullable is True
        assert attempt_col.nullable is True


class TestTimingFieldsBoundary:
    """BOUNDARY: 경계 조건"""

    def test_boundary_zero_values(self):
        """타이밍 값이 0인 경우 검증"""
        # Given: 0값 데이터
        data = {
            "event_type": "check",
            "status": "success",
            "graphql_time_ms": 0.0,
            "proxy_retry_count": 0,
            "booking_time_ms": 0.0,
            "booking_attempt_count": 0
        }

        # When: 스키마 생성
        schema = MonitoringEventBase(**data)

        # Then: 0값이 유지됨 (None이 아님)
        assert schema.graphql_time_ms == 0.0
        assert schema.proxy_retry_count == 0
        assert schema.booking_time_ms == 0.0
        assert schema.booking_attempt_count == 0

    def test_boundary_large_values(self):
        """큰 타이밍 값 검증 (예: 60초 = 60000ms)"""
        # Given: 큰 값
        data = {
            "event_type": "check",
            "status": "error",
            "graphql_time_ms": 60000.0,  # 60초
            "proxy_retry_count": 10,
            "booking_time_ms": 30000.0,  # 30초
            "booking_attempt_count": 100
        }

        # When: 스키마 생성
        schema = MonitoringEventBase(**data)

        # Then: 큰 값도 허용
        assert schema.graphql_time_ms == 60000.0
        assert schema.proxy_retry_count == 10
        assert schema.booking_time_ms == 30000.0
        assert schema.booking_attempt_count == 100

    def test_boundary_partial_timing_data(self):
        """일부 타이밍 필드만 있는 경우"""
        # Given: graphql_time만 있고 booking_time은 없는 경우
        data = {
            "event_type": "check",
            "status": "success",
            "graphql_time_ms": 1500.0,
            "proxy_retry_count": 1
            # booking_time_ms, booking_attempt_count 없음
        }

        # When: 스키마 생성
        schema = MonitoringEventBase(**data)

        # Then: 설정된 값은 유지, 나머지는 None
        assert schema.graphql_time_ms == 1500.0
        assert schema.proxy_retry_count == 1
        assert schema.booking_time_ms is None
        assert schema.booking_attempt_count is None

    def test_boundary_float_precision(self):
        """밀리초 소수점 정밀도 검증"""
        # Given: 소수점이 있는 값
        data = {
            "event_type": "check",
            "status": "success",
            "graphql_time_ms": 1234.56789,
            "booking_time_ms": 0.001
        }

        # When: 스키마 생성
        schema = MonitoringEventBase(**data)

        # Then: 정밀도 유지
        assert abs(schema.graphql_time_ms - 1234.56789) < 0.0001
        assert abs(schema.booking_time_ms - 0.001) < 0.0001


class TestTimingFieldsInverse:
    """INVERSE: 역관계 검증"""

    def test_inverse_schema_to_dict_and_back(self):
        """스키마 → dict → 스키마 변환이 동일한지 검증"""
        # Given: 원본 스키마
        original = MonitoringEventBase(
            event_type="check",
            status="success",
            graphql_time_ms=1500.0,
            proxy_retry_count=2,
            booking_time_ms=3000.0,
            booking_attempt_count=3
        )

        # When: dict로 변환 후 다시 스키마로
        data_dict = original.model_dump()
        restored = MonitoringEventBase(**data_dict)

        # Then: 동일한 값
        assert restored.graphql_time_ms == original.graphql_time_ms
        assert restored.proxy_retry_count == original.proxy_retry_count
        assert restored.booking_time_ms == original.booking_time_ms
        assert restored.booking_attempt_count == original.booking_attempt_count


class TestTimingFieldsCrossCheck:
    """CROSS-CHECK: 교차 검증"""

    def test_crosscheck_timing_sum_approximation(self):
        """
        total_time ≈ graphql_time + booking_time + other_time

        실제로는 other_time = total - graphql - booking 이므로
        total >= graphql + booking 인지 검증
        """
        # Given: 총 응답시간과 세부 시간
        total_response_time_ms = 5000.0  # 5초
        graphql_time_ms = 2000.0  # 2초
        booking_time_ms = 1500.0  # 1.5초
        # other_time = 5000 - 2000 - 1500 = 1500ms (기타 오버헤드)

        # When: 합계 계산
        detailed_sum = graphql_time_ms + booking_time_ms

        # Then: total >= detailed_sum (기타 시간이 있을 수 있으므로)
        assert total_response_time_ms >= detailed_sum

    def test_crosscheck_retry_count_matches_expected_pattern(self):
        """
        proxy_retry_count가 0이면 첫 시도에 성공
        proxy_retry_count > 0이면 재시도 발생
        """
        # Case 1: 재시도 없음
        schema1 = MonitoringEventBase(
            event_type="check",
            status="success",
            proxy_retry_count=0
        )
        assert schema1.proxy_retry_count == 0

        # Case 2: 2번 재시도 후 성공
        schema2 = MonitoringEventBase(
            event_type="check",
            status="success",
            proxy_retry_count=2
        )
        assert schema2.proxy_retry_count == 2

    def test_crosscheck_booking_fields_together(self):
        """
        booking_time_ms와 booking_attempt_count가 함께 설정되는지 검증
        예약이 실행되면 둘 다 값이 있어야 함
        """
        # Given: 예약 실행된 경우
        schema = MonitoringEventBase(
            event_type="slot_booked",
            status="available",
            booking_triggered=True,
            booking_time_ms=2500.0,
            booking_attempt_count=5
        )

        # Then: 둘 다 값이 있음
        assert schema.booking_time_ms is not None
        assert schema.booking_attempt_count is not None
        assert schema.booking_attempt_count > 0


class TestTimingFieldsError:
    """ERROR: 에러 조건"""

    def test_error_negative_time_still_accepted(self):
        """
        음수 시간값은 Pydantic에서 기본적으로 허용됨
        (실제로는 발생하지 않아야 하지만 DB 저장은 가능)
        """
        # Given: 음수 값 (비정상)
        data = {
            "event_type": "check",
            "status": "success",
            "graphql_time_ms": -100.0  # 비정상이지만 스키마는 허용
        }

        # When/Then: 스키마 생성 가능 (검증은 비즈니스 로직에서)
        schema = MonitoringEventBase(**data)
        assert schema.graphql_time_ms == -100.0

    def test_error_invalid_type_raises_validation_error(self):
        """잘못된 타입이 들어오면 ValidationError 발생"""
        # Given: 문자열을 숫자 필드에 넣음
        data = {
            "event_type": "check",
            "status": "success",
            "graphql_time_ms": "not a number"
        }

        # When/Then: ValidationError 발생
        with pytest.raises(Exception):  # Pydantic ValidationError
            MonitoringEventBase(**data)

    def test_error_none_is_valid(self):
        """None 값은 유효함"""
        # Given: 명시적 None
        data = {
            "event_type": "check",
            "status": "success",
            "graphql_time_ms": None,
            "proxy_retry_count": None
        }

        # When: 스키마 생성
        schema = MonitoringEventBase(**data)

        # Then: None 유지
        assert schema.graphql_time_ms is None
        assert schema.proxy_retry_count is None


class TestTimingFieldsCorrectScenarios:
    """CORRECT: 실제 사용 시나리오 기반 테스트"""

    def test_correct_fast_response_no_retry(self):
        """
        시나리오: 빠른 응답 (프록시 재시도 없음)
        - GraphQL 호출 500ms
        - 프록시 재시도 0회
        - 예약 실행 안 함
        """
        schema = MonitoringEventBase(
            event_type="check",
            status="no_slots",
            response_time_ms=600.0,
            graphql_time_ms=500.0,
            proxy_retry_count=0,
            booking_triggered=False
        )

        assert schema.graphql_time_ms < schema.response_time_ms
        assert schema.proxy_retry_count == 0
        assert schema.booking_time_ms is None

    def test_correct_slow_response_with_retry(self):
        """
        시나리오: 느린 응답 (프록시 재시도 발생)
        - 총 응답 17초 (문제 상황)
        - GraphQL 15초 (프록시 3번 재시도)
        - 예약 실행 안 함
        """
        schema = MonitoringEventBase(
            event_type="check",
            status="success",
            response_time_ms=17000.0,
            graphql_time_ms=15000.0,
            proxy_retry_count=3,
            booking_triggered=False
        )

        assert schema.response_time_ms >= schema.graphql_time_ms
        assert schema.proxy_retry_count > 0
        # 재시도가 많으면 시간이 오래 걸림
        assert schema.graphql_time_ms > 10000  # 10초 이상

    def test_correct_booking_executed(self):
        """
        시나리오: 슬롯 발견 후 자동 예약 실행
        - GraphQL 호출 1초
        - 프록시 재시도 1회
        - 예약 실행 3초 (5개 슬롯)
        """
        schema = MonitoringEventBase(
            event_type="slot_booked",
            status="available",
            response_time_ms=5000.0,
            graphql_time_ms=1000.0,
            proxy_retry_count=1,
            booking_triggered=True,
            booking_success=True,
            booking_time_ms=3000.0,
            booking_attempt_count=5
        )

        assert schema.booking_triggered is True
        assert schema.booking_time_ms is not None
        assert schema.booking_attempt_count == 5
        # 총 시간 ≈ graphql + booking + other
        expected_minimum = schema.graphql_time_ms + schema.booking_time_ms
        assert schema.response_time_ms >= expected_minimum

    def test_correct_anonymous_monitoring_with_proxy(self):
        """
        시나리오: 익명 모니터링 (프록시 사용)
        - 프록시 URL 있음
        - 프록시 재시도 2회
        - fetch_method: anonymous_api
        """
        schema = MonitoringEventBase(
            event_type="check",
            status="success",
            fetch_method="anonymous_api",
            proxy_url="http://proxy.example.com:8080",
            response_time_ms=8000.0,
            graphql_time_ms=7500.0,
            proxy_retry_count=2
        )

        assert schema.fetch_method == "anonymous_api"
        assert schema.proxy_url is not None
        assert schema.proxy_retry_count > 0

    def test_correct_error_case_with_timing(self):
        """
        시나리오: 에러 발생 시에도 타이밍 기록
        - GraphQL 호출 시도 후 타임아웃
        """
        schema = MonitoringEventBase(
            event_type="error",
            status="error",
            error_message="Proxy timeout after 3 retries",
            response_time_ms=30000.0,
            graphql_time_ms=30000.0,
            proxy_retry_count=3
        )

        assert schema.status == "error"
        assert schema.graphql_time_ms is not None
        assert schema.proxy_retry_count == 3
        assert "timeout" in schema.error_message.lower()


class TestEventLoggerTimingIntegration:
    """EventLogger 타이밍 필드 통합 테스트"""

    def test_event_logger_accepts_timing_params(self):
        """EventLogger.log_monitoring_event가 타이밍 파라미터를 받는지 검증"""
        import inspect

        # Given: EventLogger.log_monitoring_event 시그니처
        sig = inspect.signature(EventLogger.log_monitoring_event)
        params = sig.parameters

        # Then: 타이밍 파라미터 존재
        assert "graphql_time_ms" in params
        assert "proxy_retry_count" in params
        assert "booking_time_ms" in params
        assert "booking_attempt_count" in params

    def test_async_event_logger_accepts_timing_params(self):
        """AsyncEventLogger.log_monitoring_event가 타이밍 파라미터를 받는지 검증"""
        import inspect

        # Given: AsyncEventLogger.log_monitoring_event 시그니처
        sig = inspect.signature(AsyncEventLogger.log_monitoring_event)
        params = sig.parameters

        # Then: 타이밍 파라미터 존재
        assert "graphql_time_ms" in params
        assert "proxy_retry_count" in params
        assert "booking_time_ms" in params
        assert "booking_attempt_count" in params


class TestDatabaseMigrationCompatibility:
    """DB 마이그레이션 호환성 테스트"""

    def test_migration_file_exists(self):
        """마이그레이션 파일이 존재하는지 검증"""
        migration_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "migrations",
            "027_add_timing_breakdown.sql"
        )
        assert os.path.exists(migration_path), f"Migration file not found: {migration_path}"

    def test_migration_contains_required_columns(self):
        """마이그레이션 파일에 필요한 컬럼이 포함되어 있는지 검증"""
        migration_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "migrations",
            "027_add_timing_breakdown.sql"
        )

        with open(migration_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Then: 필요한 컬럼 추가 구문 포함
        assert "graphql_time_ms" in content
        assert "proxy_retry_count" in content
        assert "booking_time_ms" in content
        assert "booking_attempt_count" in content
        assert "ALTER TABLE" in content or "ADD COLUMN" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
