"""
LLM 성능 분석 API 테스트

성능 분석 엔드포인트와 관련 서비스 메서드를 테스트합니다.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.models.llm_request import LLMRequest


@pytest.fixture(autouse=True)
def cleanup_llm_requests(test_db_session: Session):
    """각 테스트 전후로 LLM 요청 정리"""
    # 테스트 전 정리
    test_db_session.query(LLMRequest).delete()
    test_db_session.commit()
    yield
    # 테스트 후 정리
    test_db_session.query(LLMRequest).delete()
    test_db_session.commit()


class TestLLMPerformanceService:
    """LLMService.get_performance_stats() 테스트"""

    def test_empty_stats(self, test_db_session: Session):
        """요청이 없을 때 빈 통계 반환"""
        service = LLMService(test_db_session)
        stats = service.get_performance_stats(hours=24)

        assert stats["period_hours"] == 24
        assert stats["llm_stats"]["total_requests"] == 0
        assert stats["llm_stats"]["avg_processing_time"] == 0
        assert stats["by_hour"] == [] or all(h["count"] == 0 for h in stats["by_hour"])
        assert stats["slow_requests"] == []

    def test_stats_with_completed_requests(self, test_db_session: Session):
        """완료된 요청이 있을 때 통계 계산"""
        # 테스트 데이터 생성
        now = datetime.now()
        requests = [
            LLMRequest(
                caller_type="instagram",
                caller_id=f"post_{i}",
                prompt="test prompt",
                status="completed",
                requested_at=now - timedelta(hours=1),
                processed_at=now - timedelta(hours=1) + timedelta(seconds=30 + i * 10),
            )
            for i in range(5)
        ]

        for req in requests:
            test_db_session.add(req)
        test_db_session.commit()

        service = LLMService(test_db_session)
        stats = service.get_performance_stats(hours=24)

        assert stats["llm_stats"]["total_requests"] == 5
        assert stats["llm_stats"]["avg_processing_time"] > 0
        assert stats["llm_stats"]["min_time"] == 30.0
        assert stats["llm_stats"]["max_time"] == 70.0
        assert len(stats["slow_requests"]) <= 10

    def test_stats_excludes_old_requests(self, test_db_session: Session):
        """기간 외 요청은 통계에서 제외"""
        now = datetime.now()

        # 기간 내 요청
        recent = LLMRequest(
            caller_type="instagram",
            caller_id="recent",
            prompt="test",
            status="completed",
            requested_at=now - timedelta(hours=1),
            processed_at=now - timedelta(minutes=30),
        )

        # 기간 외 요청 (48시간 전)
        old = LLMRequest(
            caller_type="instagram",
            caller_id="old",
            prompt="test",
            status="completed",
            requested_at=now - timedelta(hours=48),
            processed_at=now - timedelta(hours=47),
        )

        test_db_session.add(recent)
        test_db_session.add(old)
        test_db_session.commit()

        service = LLMService(test_db_session)
        stats = service.get_performance_stats(hours=24)

        # 24시간 내 요청만 포함
        assert stats["llm_stats"]["total_requests"] == 1

    def test_stats_with_failed_requests(self, test_db_session: Session):
        """실패한 요청 수 집계"""
        now = datetime.now()

        # 완료 요청
        completed = LLMRequest(
            caller_type="instagram",
            caller_id="completed",
            prompt="test",
            status="completed",
            requested_at=now - timedelta(hours=1),
            processed_at=now - timedelta(minutes=30),
        )

        # 실패 요청
        failed = LLMRequest(
            caller_type="instagram",
            caller_id="failed",
            prompt="test",
            status="failed",
            requested_at=now - timedelta(hours=1),
            error_message="Test error",
        )

        test_db_session.add(completed)
        test_db_session.add(failed)
        test_db_session.commit()

        service = LLMService(test_db_session)
        stats = service.get_performance_stats(hours=24)

        assert stats["llm_stats"]["total_requests"] == 1  # 완료된 것만
        assert stats["llm_stats"]["failed_count"] == 1

    def test_slow_requests_sorted_by_time(self, test_db_session: Session):
        """느린 요청이 처리 시간 순으로 정렬"""
        now = datetime.now()

        # 다양한 처리 시간의 요청 생성
        times = [10, 50, 30, 70, 20]
        for i, t in enumerate(times):
            req = LLMRequest(
                caller_type="instagram",
                caller_id=f"post_{i}",
                prompt="test",
                status="completed",
                requested_at=now - timedelta(hours=1),
                processed_at=now - timedelta(hours=1) + timedelta(seconds=t),
            )
            test_db_session.add(req)
        test_db_session.commit()

        service = LLMService(test_db_session)
        stats = service.get_performance_stats(hours=24)

        slow = stats["slow_requests"]
        assert len(slow) == 5

        # 내림차순 정렬 확인
        for i in range(len(slow) - 1):
            assert slow[i]["processing_time"] >= slow[i + 1]["processing_time"]

    def test_by_hour_distribution(self, test_db_session: Session):
        """시간대별 분포 계산"""
        now = datetime.now()
        current_hour = now.replace(minute=0, second=0, microsecond=0)

        # 현재 시간대에 요청 추가
        req = LLMRequest(
            caller_type="instagram",
            caller_id="test",
            prompt="test",
            status="completed",
            requested_at=current_hour + timedelta(minutes=10),
            processed_at=current_hour + timedelta(minutes=11),
        )
        test_db_session.add(req)
        test_db_session.commit()

        service = LLMService(test_db_session)
        stats = service.get_performance_stats(hours=24)

        # by_hour에 데이터가 있어야 함
        assert len(stats["by_hour"]) > 0


class TestImageDownloadTiming:
    """이미지 다운로드 시간 측정 테스트"""

    def test_download_image_returns_tuple(self):
        """download_image 함수가 (경로, 시간) 튜플 반환"""
        from app.modules.instagram.services.llm_classifier_service import download_image

        # 존재하지 않는 URL로 테스트 (실패해도 시간은 반환)
        path, elapsed = download_image("http://invalid.url/test.jpg", "test_post")

        assert path is None  # 실패
        assert isinstance(elapsed, float)
        assert elapsed >= 0

    def test_download_post_images_returns_tuple(self):
        """download_post_images 함수가 (경로 목록, 총 시간) 튜플 반환"""
        from app.modules.instagram.services.llm_classifier_service import download_post_images
        from unittest.mock import MagicMock

        # Mock 게시물 생성
        mock_post = MagicMock()
        mock_post.id = 999
        mock_post.images = []

        paths, total_time = download_post_images(mock_post)

        assert isinstance(paths, list)
        assert isinstance(total_time, float)
        assert len(paths) == 0
        assert total_time == 0.0
