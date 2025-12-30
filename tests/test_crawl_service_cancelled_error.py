"""
CrawlService CancelledError 처리 테스트

RIGHT-BICEP 원칙 적용:
- Right: asyncio.CancelledError 발생 시 finished_at이 업데이트되는가?
- Boundary: 다양한 예외 상황에서 동작
- Error: CancelledError가 제대로 캐치되는가?

CORRECT 조건 적용:
- Time: finished_at이 올바르게 설정되는가?
- Existence: 에러 발생 시에도 crawl_run 레코드가 업데이트되는가?
"""

import asyncio
import pytest
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 테스트 픽스처
# ============================================================

@pytest.fixture
def mock_db():
    """Mock 데이터베이스 세션"""
    db = MagicMock()
    db.query.return_value.get.return_value = MagicMock(
        id=1,
        success=False,
        error_message=None,
        total_collected=0,
        new_saved=0,
        finished_at=None,
    )
    return db


@pytest.fixture
def mock_crawler():
    """Mock InstagramCrawler"""
    crawler = MagicMock()
    return crawler


@pytest.fixture
def mock_crawl_run():
    """Mock InstagramCrawlRun"""
    run = MagicMock()
    run.id = 1
    run.success = False
    run.error_message = None
    run.total_collected = 0
    run.new_saved = 0
    run.finished_at = None
    return run


# ============================================================
# CancelledError 처리 테스트
# ============================================================

class TestCrawlServiceCancelledError:
    """CrawlService의 CancelledError 처리 테스트"""

    def test_cancelled_error_is_caught(self, mock_db, mock_crawl_run):
        """[Right] asyncio.CancelledError가 캐치되는지 확인"""
        from app.modules.instagram.services.crawl_service import CrawlService

        # CrawlService 생성
        service = CrawlService(mock_db)

        # CancelledError 발생하도록 설정
        mock_crawler = AsyncMock()
        mock_crawler.crawl_feed = AsyncMock(side_effect=asyncio.CancelledError())

        # run_crawl 메서드에서 crawl_run을 생성하는 부분 모킹
        with patch.object(service, 'get_schedule_config', return_value=MagicMock(
            max_posts=20, scroll_count=3, duplicate_stop_count=5
        )):
            with patch.object(service.db, 'add'):
                mock_db.query.return_value.get.return_value = mock_crawl_run

                # 테스트 실행 - CancelledError가 캐치되어 crawl_run이 반환되어야 함
                try:
                    result = asyncio.run(service.run_crawl(
                        crawler=mock_crawler,
                        service_account_id=1
                    ))
                    # CancelledError가 캐치되면 crawl_run이 반환됨
                    assert result is not None
                except asyncio.CancelledError:
                    # CancelledError가 캐치되지 않으면 테스트 실패
                    pytest.fail("CancelledError should be caught by CrawlService")

    def test_finished_at_set_on_cancelled_error(self, mock_db, mock_crawl_run):
        """[Time] CancelledError 발생 시 finished_at이 설정되는지 확인"""
        from app.modules.instagram.services.crawl_service import CrawlService

        service = CrawlService(mock_db)

        mock_crawler = AsyncMock()
        mock_crawler.crawl_feed = AsyncMock(side_effect=asyncio.CancelledError())

        with patch.object(service, 'get_schedule_config', return_value=MagicMock(
            max_posts=20, scroll_count=3, duplicate_stop_count=5
        )):
            with patch.object(service.db, 'add'):
                mock_db.query.return_value.get.return_value = mock_crawl_run

                before_time = datetime.now()
                asyncio.run(service.run_crawl(
                    crawler=mock_crawler,
                    service_account_id=1
                ))

                # finished_at이 설정되었는지 확인
                assert mock_crawl_run.finished_at is not None
                assert mock_crawl_run.finished_at >= before_time

    def test_success_false_on_cancelled_error(self, mock_db, mock_crawl_run):
        """[Right] CancelledError 발생 시 success=False로 설정되는지 확인"""
        from app.modules.instagram.services.crawl_service import CrawlService

        service = CrawlService(mock_db)

        mock_crawler = AsyncMock()
        mock_crawler.crawl_feed = AsyncMock(side_effect=asyncio.CancelledError())

        with patch.object(service, 'get_schedule_config', return_value=MagicMock(
            max_posts=20, scroll_count=3, duplicate_stop_count=5
        )):
            with patch.object(service.db, 'add'):
                mock_db.query.return_value.get.return_value = mock_crawl_run

                asyncio.run(service.run_crawl(
                    crawler=mock_crawler,
                    service_account_id=1
                ))

                # success가 False로 설정되었는지 확인
                assert mock_crawl_run.success == False

    def test_error_message_set_on_cancelled_error(self, mock_db, mock_crawl_run):
        """[Existence] CancelledError 발생 시 error_message가 설정되는지 확인"""
        from app.modules.instagram.services.crawl_service import CrawlService

        service = CrawlService(mock_db)

        mock_crawler = AsyncMock()
        mock_crawler.crawl_feed = AsyncMock(side_effect=asyncio.CancelledError("Task cancelled"))

        with patch.object(service, 'get_schedule_config', return_value=MagicMock(
            max_posts=20, scroll_count=3, duplicate_stop_count=5
        )):
            with patch.object(service.db, 'add'):
                mock_db.query.return_value.get.return_value = mock_crawl_run

                asyncio.run(service.run_crawl(
                    crawler=mock_crawler,
                    service_account_id=1
                ))

                # error_message가 설정되었는지 확인
                assert mock_crawl_run.error_message is not None


class TestCrawlServiceOtherExceptions:
    """CrawlService의 일반 예외 처리 테스트"""

    def test_general_exception_is_caught(self, mock_db, mock_crawl_run):
        """[Error] 일반 Exception도 여전히 캐치되는지 확인"""
        from app.modules.instagram.services.crawl_service import CrawlService

        service = CrawlService(mock_db)

        mock_crawler = AsyncMock()
        mock_crawler.crawl_feed = AsyncMock(side_effect=ValueError("Test error"))

        with patch.object(service, 'get_schedule_config', return_value=MagicMock(
            max_posts=20, scroll_count=3, duplicate_stop_count=5
        )):
            with patch.object(service.db, 'add'):
                mock_db.query.return_value.get.return_value = mock_crawl_run

                # Exception이 캐치되어 crawl_run이 반환되어야 함
                result = asyncio.run(service.run_crawl(
                    crawler=mock_crawler,
                    service_account_id=1
                ))

                assert result is not None
                assert mock_crawl_run.success == False
                assert mock_crawl_run.finished_at is not None

    def test_timeout_error_is_caught(self, mock_db, mock_crawl_run):
        """[Error] TimeoutError도 캐치되는지 확인"""
        from app.modules.instagram.services.crawl_service import CrawlService

        service = CrawlService(mock_db)

        mock_crawler = AsyncMock()
        mock_crawler.crawl_feed = AsyncMock(side_effect=TimeoutError("Operation timed out"))

        with patch.object(service, 'get_schedule_config', return_value=MagicMock(
            max_posts=20, scroll_count=3, duplicate_stop_count=5
        )):
            with patch.object(service.db, 'add'):
                mock_db.query.return_value.get.return_value = mock_crawl_run

                result = asyncio.run(service.run_crawl(
                    crawler=mock_crawler,
                    service_account_id=1
                ))

                assert result is not None
                assert mock_crawl_run.success == False
                assert mock_crawl_run.finished_at is not None


# ============================================================
# Python 3.8+ CancelledError 특성 테스트
# ============================================================

class TestCancelledErrorInheritance:
    """asyncio.CancelledError 상속 관계 테스트"""

    def test_cancelled_error_is_base_exception(self):
        """[Right] CancelledError가 BaseException 서브클래스인지 확인"""
        assert issubclass(asyncio.CancelledError, BaseException)

    def test_cancelled_error_is_not_exception_subclass(self):
        """[Right] CancelledError가 Exception 서브클래스가 아닌지 확인 (Python 3.8+)"""
        # Python 3.8+에서 CancelledError는 Exception을 상속하지 않음
        assert not issubclass(asyncio.CancelledError, Exception)

    def test_tuple_exception_catches_cancelled_error(self):
        """[Right] (Exception, CancelledError) 튜플로 캐치할 수 있는지 확인"""
        caught = False
        try:
            raise asyncio.CancelledError("test")
        except (Exception, asyncio.CancelledError):
            caught = True

        assert caught, "CancelledError should be caught with (Exception, CancelledError)"
