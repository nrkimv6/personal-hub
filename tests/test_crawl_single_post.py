"""
crawl_single_post 메서드 테스트

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

테스트 대상:
- InstagramCrawler.crawl_single_post()
- InstagramCrawler._extract_single_post_data()
- InstagramCrawler._click_more_button_on_page()
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import asdict


# ============================================================
# Right - 올바른 결과 검증
# ============================================================

class TestCrawlSinglePostRight:
    """crawl_single_post 올바른 결과 테스트"""

    def test_method_exists(self):
        """crawl_single_post 메서드 존재 확인"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        assert hasattr(crawler, 'crawl_single_post')
        assert callable(crawler.crawl_single_post)

    def test_extract_single_post_data_method_exists(self):
        """_extract_single_post_data 메서드 존재 확인"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        assert hasattr(crawler, '_extract_single_post_data')
        assert callable(crawler._extract_single_post_data)

    def test_click_more_button_on_page_method_exists(self):
        """_click_more_button_on_page 메서드 존재 확인"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        assert hasattr(crawler, '_click_more_button_on_page')
        assert callable(crawler._click_more_button_on_page)

    @pytest.mark.asyncio
    async def test_crawl_single_post_returns_post_data(self):
        """정상 케이스: PostData 객체 반환"""
        from app.modules.instagram.services.crawler import InstagramCrawler, PostData

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)  # 동기 메서드
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Test content without login")
        mock_page.evaluate = AsyncMock(return_value={
            "account": "testuser",
            "datetime": "2025-12-23T10:00:00.000Z",
            "display_time": "1일",
            "likes": 100,
            "comments": 10,
            "caption": "This is a test caption that is long enough to be captured by the crawler",
            "images": [{"src": "https://cdn.instagram.com/img.jpg", "alt": "Test"}],
            "hashtags": ["#test", "#demo"],
            "hasVideo": False,
        })

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/ABC123/")

        assert result is not None
        assert isinstance(result, PostData)
        assert result.account == "testuser"
        assert result.likes == 100
        assert result.comments == 10
        # URL is normalized (trailing slash removed)
        assert result.url == "https://www.instagram.com/p/ABC123"

    @pytest.mark.asyncio
    async def test_crawl_single_post_likes_int_type(self):
        """좋아요 수가 정수 타입으로 반환"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)  # 동기 메서드
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Normal content")
        mock_page.evaluate = AsyncMock(return_value={
            "account": "testuser",
            "likes": 1234,
            "comments": 56,
            "images": [],
        })

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/ABC123/")

        assert result is not None
        assert isinstance(result.likes, int)
        assert result.likes == 1234


# ============================================================
# Boundary - 경계 조건 테스트
# ============================================================

class TestCrawlSinglePostBoundary:
    """crawl_single_post 경계 조건 테스트"""

    @pytest.mark.asyncio
    async def test_crawl_post_with_zero_likes(self):
        """좋아요 0개인 게시물"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)  # 동기 메서드
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Normal content")
        mock_page.evaluate = AsyncMock(return_value={
            "account": "testuser",
            "likes": 0,
            "comments": 5,
            "images": [],
        })

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/ABC123/")

        assert result is not None
        assert result.likes == 0

    @pytest.mark.asyncio
    async def test_crawl_post_with_no_comments(self):
        """댓글 없는 게시물"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)  # 동기 메서드
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Normal content")
        mock_page.evaluate = AsyncMock(return_value={
            "account": "testuser",
            "likes": 50,
            "comments": 0,
            "images": [],
        })

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/ABC123/")

        assert result is not None
        assert result.comments == 0

    @pytest.mark.asyncio
    async def test_crawl_post_with_short_caption(self):
        """본문이 짧은(50자 미만) 게시물 - caption이 None일 수 있음"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)  # 동기 메서드
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Normal content")
        mock_page.evaluate = AsyncMock(return_value={
            "account": "testuser",
            "likes": 10,
            "comments": 2,
            "caption": None,  # 50자 미만이라 추출 안됨
            "images": [],
        })

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/ABC123/")

        assert result is not None
        # 짧은 본문은 None일 수 있음
        assert result.caption is None

    @pytest.mark.asyncio
    async def test_crawl_post_with_no_images_video_only(self):
        """이미지 없고 비디오만 있는 게시물"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)  # 동기 메서드
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Normal content")
        mock_page.evaluate = AsyncMock(return_value={
            "account": "testuser",
            "likes": 200,
            "comments": 15,
            "images": [],
            "hasVideo": True,
            "videoUrls": ["https://cdn.instagram.com/video.mp4"],
        })

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/ABC123/")

        assert result is not None
        assert len(result.images) == 0

    @pytest.mark.asyncio
    async def test_crawl_post_with_missing_likes(self):
        """좋아요 수가 없는 게시물 (likes=None)"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)  # 동기 메서드
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Normal content")
        mock_page.evaluate = AsyncMock(return_value={
            "account": "testuser",
            "images": [],
        })

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/ABC123/")

        assert result is not None
        assert result.likes is None


# ============================================================
# Error - 에러 조건 테스트
# ============================================================

class TestCrawlSinglePostError:
    """crawl_single_post 에러 조건 테스트"""

    @pytest.mark.asyncio
    async def test_crawl_post_login_required(self):
        """로그인 필요 페이지 접근 시 None 반환"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Log in to see this content")

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/ABC123/")

        assert result is None

    @pytest.mark.asyncio
    async def test_crawl_post_login_required_korean(self):
        """로그인 필요 페이지 (한국어) 접근 시 None 반환"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="로그인하여 계속하세요")

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/ABC123/")

        assert result is None

    @pytest.mark.asyncio
    async def test_crawl_post_unavailable(self):
        """삭제된 게시물 접근 시 None 반환"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Sorry, this page isn't available.")

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/DELETED123/")

        assert result is None

    @pytest.mark.asyncio
    async def test_crawl_post_unavailable_korean(self):
        """삭제된 게시물 (한국어) 접근 시 None 반환"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="죄송합니다. 이 페이지를 사용할 수 없습니다.")

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/DELETED123/")

        assert result is None

    @pytest.mark.asyncio
    async def test_crawl_post_private_account(self):
        """비공개 계정 게시물 접근 시 None 반환"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="This Account is Private")

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/PRIVATE123/")

        assert result is None

    @pytest.mark.asyncio
    async def test_crawl_post_exception_handling(self):
        """예외 발생 시 None 반환"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Network error"))

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/ABC123/")

        assert result is None


# ============================================================
# Inverse - 역관계 검증
# ============================================================

class TestCrawlSinglePostInverse:
    """crawl_single_post 역관계 테스트"""

    @pytest.mark.asyncio
    async def test_post_data_fields_match_extracted_data(self):
        """추출된 데이터가 PostData 필드에 올바르게 매핑됨"""
        from app.modules.instagram.services.crawler import InstagramCrawler, PostData

        extracted_data = {
            "account": "testaccount",
            "datetime": "2025-12-23T12:00:00.000Z",
            "display_time": "2시간",
            "likes": 500,
            "comments": 25,
            "caption": "This is a very long caption that exceeds fifty characters for testing purposes",
            "images": [{"src": "https://cdn.instagram.com/1.jpg", "alt": "Image 1"}],
            "hashtags": ["#test"],
            "hasVideo": False,
        }

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)  # 동기 메서드
        mock_page.goto = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Normal content")
        mock_page.evaluate = AsyncMock(return_value=extracted_data)

        crawler = InstagramCrawler(mock_page)
        result = await crawler.crawl_single_post("https://www.instagram.com/p/TEST123/")

        assert result.account == extracted_data["account"]
        assert result.datetime_str == extracted_data["datetime"]
        assert result.display_time == extracted_data["display_time"]
        assert result.likes == extracted_data["likes"]
        assert result.comments == extracted_data["comments"]
        assert result.caption == extracted_data["caption"]
        assert result.images == extracted_data["images"]


# ============================================================
# Cross-check - 교차 검증
# ============================================================

class TestCrawlSinglePostCrossCheck:
    """crawl_single_post 교차 검증 테스트"""

    def test_more_button_texts_consistency(self):
        """더보기 버튼 텍스트 목록 일관성 확인"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        # 기존 MORE_BUTTON_TEXTS와 _click_more_button_on_page의 텍스트가 일치해야 함
        assert hasattr(crawler, 'MORE_BUTTON_TEXTS')
        assert '더 보기' in crawler.MORE_BUTTON_TEXTS
        assert 'more' in crawler.MORE_BUTTON_TEXTS


# ============================================================
# Click More Button 테스트
# ============================================================

class TestClickMoreButtonOnPage:
    """_click_more_button_on_page 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_click_more_button_success(self):
        """더보기 버튼 클릭 성공"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=True)

        crawler = InstagramCrawler(mock_page)
        result = await crawler._click_more_button_on_page()

        assert result is True

    @pytest.mark.asyncio
    async def test_click_more_button_not_found(self):
        """더보기 버튼이 없는 경우"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=False)

        crawler = InstagramCrawler(mock_page)
        result = await crawler._click_more_button_on_page()

        assert result is False

    @pytest.mark.asyncio
    async def test_click_more_button_exception(self):
        """더보기 버튼 클릭 중 예외 발생"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("JS error"))

        crawler = InstagramCrawler(mock_page)
        result = await crawler._click_more_button_on_page()

        assert result is False


# ============================================================
# Extract Single Post Data 테스트
# ============================================================

class TestExtractSinglePostData:
    """_extract_single_post_data 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_extract_returns_dict(self):
        """딕셔너리 반환 확인"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value={
            "account": "test",
            "likes": 100,
        })

        crawler = InstagramCrawler(mock_page)
        result = await crawler._extract_single_post_data()

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_extract_calls_page_evaluate(self):
        """page.evaluate 호출 확인"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value={})

        crawler = InstagramCrawler(mock_page)
        await crawler._extract_single_post_data()

        mock_page.evaluate.assert_called_once()
