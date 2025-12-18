"""
프록시 사용 이력 기능 테스트

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
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import uuid

# 상위 디렉토리를 모듈 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.models.proxy_usage import ProxyUsageLog
from app.schemas.proxy_usage import (
    ProxyUsageLogCreate,
    ProxyUsageLogResponse,
    ProxyUsageStatItem,
    ProxyUsageStatsResponse,
    RetryHistoryResponse,
    RetryAttemptInfo,
)


# ============== Model Tests ==============

class TestProxyUsageLogModelRight:
    """RIGHT: 모델 올바른 결과 검증"""

    def test_right_model_has_required_columns(self):
        """모델에 필수 컬럼이 존재하는지 검증"""
        columns = [c.name for c in ProxyUsageLog.__table__.columns]

        # 필수 컬럼 검증
        assert "id" in columns
        assert "schedule_id" in columns
        assert "proxy_url" in columns
        assert "attempt_number" in columns
        assert "success" in columns
        assert "request_id" in columns
        assert "timestamp" in columns

    def test_right_model_has_optional_columns(self):
        """모델에 선택적 컬럼이 존재하는지 검증"""
        columns = [c.name for c in ProxyUsageLog.__table__.columns]

        # 선택적 컬럼 검증
        assert "monitoring_event_id" in columns
        assert "proxy_host" in columns
        assert "http_status" in columns
        assert "error_type" in columns
        assert "error_message" in columns
        assert "response_time_ms" in columns
        assert "target_url" in columns
        assert "fetch_method" in columns

    def test_right_extract_host_simple(self):
        """단순 프록시 URL에서 호스트 추출"""
        result = ProxyUsageLog.extract_host("http://192.168.1.1:8080")
        assert result == "192.168.1.1"

    def test_right_extract_host_with_auth(self):
        """인증 정보가 있는 프록시 URL에서 호스트 추출"""
        result = ProxyUsageLog.extract_host("http://user:pass@192.168.1.1:8080")
        assert result == "192.168.1.1"

    def test_right_extract_host_https(self):
        """HTTPS 프록시 URL에서 호스트 추출"""
        result = ProxyUsageLog.extract_host("https://proxy.example.com:443")
        assert result == "proxy.example.com"


class TestProxyUsageLogModelBoundary:
    """BOUNDARY: 경계 조건 테스트"""

    def test_boundary_nullable_monitoring_event_id(self):
        """monitoring_event_id가 nullable인지 검증"""
        col = ProxyUsageLog.__table__.columns["monitoring_event_id"]
        assert col.nullable is True

    def test_boundary_not_null_schedule_id(self):
        """schedule_id가 NOT NULL인지 검증"""
        col = ProxyUsageLog.__table__.columns["schedule_id"]
        assert col.nullable is False

    def test_boundary_not_null_proxy_url(self):
        """proxy_url이 NOT NULL인지 검증"""
        col = ProxyUsageLog.__table__.columns["proxy_url"]
        assert col.nullable is False


class TestProxyUsageLogModelReference:
    """REFERENCE: 외래키 참조 검증"""

    def test_reference_schedule_id_fk(self):
        """schedule_id가 monitor_schedules를 참조하는지 검증"""
        col = ProxyUsageLog.__table__.columns["schedule_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert "monitor_schedules.id" in str(fks[0])

    def test_reference_monitoring_event_id_fk(self):
        """monitoring_event_id가 monitoring_events를 참조하는지 검증"""
        col = ProxyUsageLog.__table__.columns["monitoring_event_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert "monitoring_events.id" in str(fks[0])


# ============== Schema Tests ==============

class TestProxyUsageSchemaRight:
    """RIGHT: 스키마 올바른 결과 검증"""

    def test_right_create_schema_valid(self):
        """유효한 생성 스키마 검증"""
        data = ProxyUsageLogCreate(
            schedule_id=1,
            proxy_url="http://192.168.1.1:8080",
            attempt_number=1,
            request_id=str(uuid.uuid4()),
            success=True,
            http_status=200,
            response_time_ms=500,
        )

        assert data.schedule_id == 1
        assert data.success is True
        assert data.http_status == 200

    def test_right_create_schema_defaults(self):
        """생성 스키마 기본값 검증"""
        data = ProxyUsageLogCreate(
            schedule_id=1,
            proxy_url="http://192.168.1.1:8080",
            attempt_number=1,
            request_id=str(uuid.uuid4()),
        )

        assert data.success is False
        assert data.http_status is None
        assert data.error_type is None

    def test_right_response_schema_valid(self):
        """유효한 응답 스키마 검증"""
        data = ProxyUsageLogResponse(
            id=1,
            schedule_id=1,
            proxy_url="http://192.168.1.1:8080",
            proxy_host="192.168.1.1",
            attempt_number=1,
            success=True,
            http_status=200,
            response_time_ms=500,
            timestamp=datetime.now(),
        )

        assert data.id == 1
        assert data.proxy_host == "192.168.1.1"


class TestProxyUsageStatItemRight:
    """RIGHT: 통계 스키마 검증"""

    def test_right_stat_item_valid(self):
        """유효한 통계 항목 검증"""
        data = ProxyUsageStatItem(
            proxy_host="192.168.1.1",
            total_attempts=100,
            success_count=80,
            fail_count=20,
            success_rate=80.0,
            avg_response_time_ms=500.5,
            last_used_at=datetime.now(),
            error_types={"timeout": 10, "http_403": 5, "connection_error": 5},
        )

        assert data.total_attempts == 100
        assert data.success_rate == 80.0
        assert len(data.error_types) == 3

    def test_right_stats_response_valid(self):
        """유효한 통계 응답 검증"""
        data = ProxyUsageStatsResponse(
            total_proxies_used=10,
            total_attempts=1000,
            overall_success_rate=85.5,
            by_proxy=[],
            by_error_type={"timeout": 100, "http_403": 50},
        )

        assert data.total_proxies_used == 10
        assert data.overall_success_rate == 85.5


class TestRetryHistorySchemaRight:
    """RIGHT: 재시도 이력 스키마 검증"""

    def test_right_retry_attempt_info_valid(self):
        """유효한 재시도 시도 정보 검증"""
        data = RetryAttemptInfo(
            attempt_number=1,
            proxy_url="http://192.168.1.1:8080",
            proxy_host="192.168.1.1",
            success=False,
            http_status=403,
            error_type="http_403",
            error_message="Forbidden",
            response_time_ms=1500,
            timestamp=datetime.now(),
        )

        assert data.attempt_number == 1
        assert data.success is False
        assert data.error_type == "http_403"

    def test_right_retry_history_response_valid(self):
        """유효한 재시도 이력 응답 검증"""
        now = datetime.now()
        attempts = [
            RetryAttemptInfo(
                attempt_number=1,
                proxy_url="http://192.168.1.1:8080",
                success=False,
                error_type="timeout",
                timestamp=now,
            ),
            RetryAttemptInfo(
                attempt_number=2,
                proxy_url="http://192.168.1.2:8080",
                success=True,
                http_status=200,
                response_time_ms=500,
                timestamp=now + timedelta(seconds=5),
            ),
        ]

        data = RetryHistoryResponse(
            request_id=str(uuid.uuid4()),
            schedule_id=1,
            business_name="테스트 업체",
            biz_item_name="테스트 상품",
            total_attempts=2,
            final_success=True,
            attempts=attempts,
            started_at=now,
            completed_at=now + timedelta(seconds=5),
            total_duration_ms=5000,
        )

        assert data.total_attempts == 2
        assert data.final_success is True
        assert len(data.attempts) == 2


# ============== Conformance Tests ==============

class TestProxyUsageConformance:
    """CONFORMANCE: 형식 준수 검증"""

    def test_conformance_proxy_url_format(self):
        """프록시 URL 형식 검증"""
        # 유효한 프록시 URL 형식들
        valid_urls = [
            "http://192.168.1.1:8080",
            "http://user:pass@192.168.1.1:8080",
            "https://proxy.example.com:443",
            "socks5://192.168.1.1:1080",
        ]

        for url in valid_urls:
            data = ProxyUsageLogCreate(
                schedule_id=1,
                proxy_url=url,
                attempt_number=1,
                request_id=str(uuid.uuid4()),
            )
            assert data.proxy_url == url

    def test_conformance_error_types(self):
        """에러 유형 형식 검증"""
        valid_error_types = [
            "timeout",
            "connection_error",
            "http_403",
            "http_429",
            "http_500",
            "unknown",
        ]

        for error_type in valid_error_types:
            data = ProxyUsageLogCreate(
                schedule_id=1,
                proxy_url="http://192.168.1.1:8080",
                attempt_number=1,
                request_id=str(uuid.uuid4()),
                success=False,
                error_type=error_type,
            )
            assert data.error_type == error_type


# ============== Range Tests ==============

class TestProxyUsageRange:
    """RANGE: 범위 검증"""

    def test_range_attempt_number_positive(self):
        """attempt_number가 양수인지 검증"""
        data = ProxyUsageLogCreate(
            schedule_id=1,
            proxy_url="http://192.168.1.1:8080",
            attempt_number=1,
            request_id=str(uuid.uuid4()),
        )
        assert data.attempt_number >= 1

    def test_range_success_rate_0_to_100(self):
        """success_rate가 0-100 범위인지 검증"""
        data = ProxyUsageStatItem(
            proxy_host="192.168.1.1",
            total_attempts=100,
            success_count=80,
            fail_count=20,
            success_rate=80.0,
            last_used_at=datetime.now(),
        )
        assert 0 <= data.success_rate <= 100

    def test_range_response_time_positive(self):
        """response_time_ms가 양수인지 검증"""
        data = ProxyUsageLogCreate(
            schedule_id=1,
            proxy_url="http://192.168.1.1:8080",
            attempt_number=1,
            request_id=str(uuid.uuid4()),
            success=True,
            response_time_ms=500,
        )
        assert data.response_time_ms > 0


# ============== Cardinality Tests ==============

class TestProxyUsageCardinality:
    """CARDINALITY: 수량 검증"""

    def test_cardinality_retry_attempts_count(self):
        """재시도 시도 횟수와 목록 일치 검증"""
        now = datetime.now()
        attempts = [
            RetryAttemptInfo(
                attempt_number=i,
                proxy_url=f"http://192.168.1.{i}:8080",
                success=(i == 3),
                timestamp=now + timedelta(seconds=i),
            )
            for i in range(1, 4)
        ]

        data = RetryHistoryResponse(
            request_id=str(uuid.uuid4()),
            schedule_id=1,
            total_attempts=3,
            final_success=True,
            attempts=attempts,
            started_at=now,
            completed_at=now + timedelta(seconds=3),
            total_duration_ms=3000,
        )

        assert data.total_attempts == len(data.attempts)


# ============== Integration-like Tests ==============

class TestProxyUsageScenarios:
    """통합 시나리오 테스트"""

    def test_scenario_single_success(self):
        """단일 성공 시나리오"""
        request_id = str(uuid.uuid4())

        log = ProxyUsageLogCreate(
            schedule_id=1,
            proxy_url="http://192.168.1.1:8080",
            attempt_number=1,
            request_id=request_id,
            success=True,
            http_status=200,
            response_time_ms=500,
            fetch_method="graphql_api",
        )

        assert log.success is True
        assert log.attempt_number == 1

    def test_scenario_retry_then_success(self):
        """재시도 후 성공 시나리오"""
        request_id = str(uuid.uuid4())

        # 1차 시도: 실패 (timeout)
        attempt1 = ProxyUsageLogCreate(
            schedule_id=1,
            proxy_url="http://192.168.1.1:8080",
            attempt_number=1,
            request_id=request_id,
            success=False,
            error_type="timeout",
            response_time_ms=5000,
        )

        # 2차 시도: 실패 (http_403)
        attempt2 = ProxyUsageLogCreate(
            schedule_id=1,
            proxy_url="http://192.168.1.2:8080",
            attempt_number=2,
            request_id=request_id,
            success=False,
            http_status=403,
            error_type="http_403",
            response_time_ms=1500,
        )

        # 3차 시도: 성공
        attempt3 = ProxyUsageLogCreate(
            schedule_id=1,
            proxy_url="http://192.168.1.3:8080",
            attempt_number=3,
            request_id=request_id,
            success=True,
            http_status=200,
            response_time_ms=800,
        )

        attempts = [attempt1, attempt2, attempt3]

        assert attempts[0].success is False
        assert attempts[1].success is False
        assert attempts[2].success is True
        assert all(a.request_id == request_id for a in attempts)

    def test_scenario_all_retries_failed(self):
        """모든 재시도 실패 시나리오"""
        request_id = str(uuid.uuid4())

        attempts = [
            ProxyUsageLogCreate(
                schedule_id=1,
                proxy_url=f"http://192.168.1.{i}:8080",
                attempt_number=i,
                request_id=request_id,
                success=False,
                error_type="timeout",
            )
            for i in range(1, 4)
        ]

        assert all(a.success is False for a in attempts)
        assert len(attempts) == 3


# ============== Run Tests ==============

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
