"""
ProxyUsageLogger 테스트

RIGHT-BICEP 테스트 패턴 적용:
- Right: 올바른 결과 검증
- Boundary: 경계 조건
- Cross-check: 교차 검증
- Error: 에러 조건
"""

import sys
import os
import pytest
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

# 상위 디렉토리를 모듈 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.proxy_usage_logger import (
    ProxyUsageLogger,
    ProxyAttempt,
    get_proxy_usage_logger,
)


class TestProxyAttemptRight:
    """RIGHT: ProxyAttempt 올바른 결과 검증"""

    def test_right_proxy_attempt_creation(self):
        """ProxyAttempt 생성 검증"""
        attempt = ProxyAttempt(
            proxy_url="http://192.168.1.1:8080",
            proxy_host="192.168.1.1",
            attempt_number=1,
            success=True,
            http_status=200,
            response_time_ms=500,
        )

        assert attempt.proxy_url == "http://192.168.1.1:8080"
        assert attempt.proxy_host == "192.168.1.1"
        assert attempt.attempt_number == 1
        assert attempt.success is True
        assert attempt.http_status == 200

    def test_right_proxy_attempt_defaults(self):
        """ProxyAttempt 기본값 검증"""
        attempt = ProxyAttempt(
            proxy_url="http://192.168.1.1:8080",
            proxy_host="192.168.1.1",
            attempt_number=1,
        )

        assert attempt.success is False
        assert attempt.http_status is None
        assert attempt.error_type is None
        assert attempt.timestamp is not None


class TestProxyUsageLoggerRight:
    """RIGHT: ProxyUsageLogger 올바른 결과 검증"""

    def test_right_extract_host_simple(self):
        """단순 URL 호스트 추출"""
        result = ProxyUsageLogger._extract_host("http://192.168.1.1:8080")
        assert result == "192.168.1.1"

    def test_right_extract_host_with_auth(self):
        """인증 정보 포함 URL 호스트 추출"""
        result = ProxyUsageLogger._extract_host("http://user:pass@192.168.1.1:8080")
        assert result == "192.168.1.1"

    def test_right_extract_host_socks5(self):
        """SOCKS5 URL 호스트 추출"""
        result = ProxyUsageLogger._extract_host("socks5://192.168.1.1:1080")
        assert result == "192.168.1.1"

    def test_right_extract_host_domain(self):
        """도메인 URL 호스트 추출"""
        result = ProxyUsageLogger._extract_host("http://proxy.example.com:8080")
        assert result == "proxy.example.com"

    def test_right_start_request(self):
        """요청 시작 검증"""
        logger = ProxyUsageLogger()

        request_id = logger.start_request(
            schedule_id=1,
            target_url="https://booking.naver.com/test",
            fetch_method="graphql_api",
            http_method="post",
        )

        assert request_id is not None
        assert len(request_id) == 36  # UUID 길이
        assert request_id in logger._pending_requests
        assert logger._pending_requests[request_id]["http_method"] == "post"

    def test_right_log_attempt_success(self):
        """성공 시도 로깅 검증"""
        logger = ProxyUsageLogger()

        request_id = logger.start_request(
            schedule_id=1,
            target_url="https://example.com",
            fetch_method="graphql_api",
        )

        logger.log_attempt(
            request_id=request_id,
            proxy_url="http://192.168.1.1:8080",
            success=True,
            http_status=200,
            response_time_ms=500,
        )

        # 성공 시 자동으로 finalize되어 버퍼로 이동
        assert request_id not in logger._pending_requests
        assert len(logger._buffer) == 1
        assert logger._buffer[0]["success"] is True

    def test_right_log_attempt_failure(self):
        """실패 시도 로깅 검증"""
        logger = ProxyUsageLogger()

        request_id = logger.start_request(
            schedule_id=1,
            target_url="https://example.com",
            fetch_method="graphql_api",
        )

        logger.log_attempt(
            request_id=request_id,
            proxy_url="http://192.168.1.1:8080",
            success=False,
            error_type="timeout",
            error_message="Connection timed out",
            response_time_ms=5000,
        )

        # 실패는 pending에 유지
        assert request_id in logger._pending_requests
        assert len(logger._pending_requests[request_id]["attempts"]) == 1

    def test_right_complete_request(self):
        """요청 완료 검증"""
        logger = ProxyUsageLogger()

        request_id = logger.start_request(
            schedule_id=1,
            target_url="https://example.com",
            fetch_method="graphql_api",
        )

        # 실패 시도 추가
        logger.log_attempt(
            request_id=request_id,
            proxy_url="http://192.168.1.1:8080",
            success=False,
            error_type="timeout",
        )

        # 수동으로 완료 처리
        logger.complete_request(request_id, monitoring_event_id=123)

        # pending에서 제거되고 버퍼로 이동
        assert request_id not in logger._pending_requests
        assert len(logger._buffer) == 1
        assert logger._buffer[0]["monitoring_event_id"] == 123


class TestProxyUsageLoggerBoundary:
    """BOUNDARY: 경계 조건 테스트"""

    def test_boundary_log_unknown_request(self):
        """존재하지 않는 요청에 대한 로깅"""
        logger = ProxyUsageLogger()

        # 존재하지 않는 request_id로 로깅 시도
        logger.log_attempt(
            request_id="non-existent-id",
            proxy_url="http://192.168.1.1:8080",
            success=True,
        )

        # 에러 없이 무시됨
        assert len(logger._buffer) == 0

    def test_boundary_complete_unknown_request(self):
        """존재하지 않는 요청 완료 처리"""
        logger = ProxyUsageLogger()

        # 존재하지 않는 request_id로 완료 시도
        logger.complete_request("non-existent-id", monitoring_event_id=123)

        # 에러 없이 무시됨
        assert len(logger._buffer) == 0

    def test_boundary_long_error_message_truncated(self):
        """긴 에러 메시지 자르기"""
        logger = ProxyUsageLogger()

        request_id = logger.start_request(
            schedule_id=1,
            target_url="https://example.com",
            fetch_method="graphql_api",
        )

        # 500자 초과 에러 메시지
        long_message = "x" * 1000

        logger.log_attempt(
            request_id=request_id,
            proxy_url="http://192.168.1.1:8080",
            success=False,
            error_type="unknown",
            error_message=long_message,
        )

        # 500자로 잘림
        assert len(logger._pending_requests[request_id]["attempts"][0].error_message) == 500


class TestProxyUsageLoggerRetryScenario:
    """재시도 시나리오 테스트"""

    def test_scenario_multiple_retries_then_success(self):
        """여러 번 재시도 후 성공"""
        logger = ProxyUsageLogger()

        request_id = logger.start_request(
            schedule_id=1,
            target_url="https://example.com",
            fetch_method="graphql_api",
        )

        # 1차 시도: 실패
        logger.log_attempt(
            request_id=request_id,
            proxy_url="http://192.168.1.1:8080",
            success=False,
            error_type="timeout",
        )

        # 2차 시도: 실패
        logger.log_attempt(
            request_id=request_id,
            proxy_url="http://192.168.1.2:8080",
            success=False,
            error_type="http_403",
            http_status=403,
        )

        # 3차 시도: 성공
        logger.log_attempt(
            request_id=request_id,
            proxy_url="http://192.168.1.3:8080",
            success=True,
            http_status=200,
            response_time_ms=800,
        )

        # 성공 시 자동 finalize
        assert request_id not in logger._pending_requests
        assert len(logger._buffer) == 3

        # 시도 순서 검증
        assert logger._buffer[0]["attempt_number"] == 1
        assert logger._buffer[0]["success"] is False
        assert logger._buffer[1]["attempt_number"] == 2
        assert logger._buffer[1]["success"] is False
        assert logger._buffer[2]["attempt_number"] == 3
        assert logger._buffer[2]["success"] is True

    def test_scenario_all_retries_failed(self):
        """모든 재시도 실패"""
        logger = ProxyUsageLogger()

        request_id = logger.start_request(
            schedule_id=1,
            target_url="https://example.com",
            fetch_method="graphql_api",
        )

        # 3번 모두 실패
        for i in range(1, 4):
            logger.log_attempt(
                request_id=request_id,
                proxy_url=f"http://192.168.1.{i}:8080",
                success=False,
                error_type="timeout",
            )

        # 아직 pending에 있음
        assert request_id in logger._pending_requests

        # 수동으로 완료 처리
        logger.complete_request(request_id)

        # 버퍼로 이동
        assert request_id not in logger._pending_requests
        assert len(logger._buffer) == 3
        assert all(entry["success"] is False for entry in logger._buffer)


class TestProxyUsageLoggerAsync:
    """비동기 기능 테스트"""

    @pytest.mark.asyncio
    async def test_async_start_stop(self):
        """시작/종료 테스트"""
        logger = ProxyUsageLogger()

        await logger.start()
        assert logger._running is True
        assert logger._flush_task is not None

        await logger.stop()
        assert logger._running is False

    @pytest.mark.asyncio
    async def test_async_flush_on_stop(self):
        """종료 시 플러시 테스트"""
        logger = ProxyUsageLogger()
        await logger.start()

        # 요청 생성 및 시도 추가
        request_id = logger.start_request(
            schedule_id=1,
            target_url="https://example.com",
            fetch_method="graphql_api",
        )
        logger.log_attempt(
            request_id=request_id,
            proxy_url="http://192.168.1.1:8080",
            success=False,
            error_type="timeout",
        )

        # pending에 있음
        assert request_id in logger._pending_requests

        # Mock DB 쓰기
        with patch.object(logger, '_batch_insert_logs') as mock_insert:
            await logger.stop()

            # pending이 finalize되고 버퍼에서 플러시됨
            assert request_id not in logger._pending_requests


class TestProxyUsageLoggerHelpers:
    """헬퍼 메서드 테스트"""

    def test_get_pending_count(self):
        """진행 중 요청 수 조회"""
        logger = ProxyUsageLogger()

        # 3개의 요청 생성
        for _ in range(3):
            logger.start_request(
                schedule_id=1,
                target_url="https://example.com",
                fetch_method="graphql_api",
            )

        assert logger.get_pending_count() == 3

    def test_get_buffer_count(self):
        """버퍼 대기 로그 수 조회"""
        logger = ProxyUsageLogger()

        # 3개의 요청 생성 및 성공 처리
        for i in range(3):
            request_id = logger.start_request(
                schedule_id=1,
                target_url="https://example.com",
                fetch_method="graphql_api",
            )
            logger.log_attempt(
                request_id=request_id,
                proxy_url=f"http://192.168.1.{i}:8080",
                success=True,
            )

        assert logger.get_buffer_count() == 3


# ============== Run Tests ==============

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
