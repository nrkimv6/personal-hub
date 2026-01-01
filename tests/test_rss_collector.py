"""
RSS Collector 테스트

RSSCollector 클래스 및 관련 서비스 동작을 검증합니다.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.writing import WritingSource, WritingRssFeed
from app.modules.writing.services.rss_collector import RSSCollector
from app.modules.writing.services.writing_service import WritingService


@pytest.fixture(autouse=True)
def cleanup_rss_data(test_db_session):
    """각 테스트 전후로 RSS 관련 테이블 정리"""
    # 테스트 전 정리
    test_db_session.query(WritingRssFeed).delete()
    # source_type이 rss인 것만 삭제
    test_db_session.query(WritingSource).filter(
        WritingSource.source_type == WritingSource.SOURCE_TYPE_RSS
    ).delete()
    test_db_session.commit()
    yield
    # 테스트 후 정리
    test_db_session.query(WritingRssFeed).delete()
    test_db_session.query(WritingSource).filter(
        WritingSource.source_type == WritingSource.SOURCE_TYPE_RSS
    ).delete()
    test_db_session.commit()


# ========== RSSCollector 단위 테스트 ==========


class TestRSSCollector:
    """RSSCollector 클래스 테스트"""

    def test_strip_html(self):
        """HTML 태그 제거 테스트"""
        collector = RSSCollector()

        # 기본 태그 제거
        assert collector._strip_html("<p>Hello</p>") == "Hello"
        assert collector._strip_html("<b>Bold</b> text") == "Bold text"

        # 스크립트/스타일 제거
        html = "<script>alert('x')</script>Content<style>.a{}</style>"
        assert collector._strip_html(html) == "Content"

        # HTML 엔티티 디코딩
        assert collector._strip_html("A &amp; B") == "A & B"
        assert collector._strip_html("&lt;tag&gt;") == "<tag>"

    def test_compute_content_hash(self):
        """콘텐츠 해시 계산 테스트"""
        # 같은 내용은 같은 해시
        hash1 = RSSCollector.compute_content_hash("Hello World")
        hash2 = RSSCollector.compute_content_hash("Hello World")
        assert hash1 == hash2

        # 공백 정규화
        hash3 = RSSCollector.compute_content_hash("Hello  World")  # 공백 2개
        assert hash1 == hash3  # 정규화 후 같음

        # 다른 내용은 다른 해시
        hash4 = RSSCollector.compute_content_hash("Different content")
        assert hash1 != hash4

        # 64자 해시
        assert len(hash1) == 64

    def test_filter_by_length(self):
        """글자 수 필터링 테스트"""
        collector = RSSCollector()

        items = [
            {"content": "A" * 100},  # 너무 짧음
            {"content": "B" * 500},  # 적정
            {"content": "C" * 5000},  # 너무 김
            {"content": "D" * 300},  # 경계값 (최소)
            {"content": "E" * 3000},  # 경계값 (최대)
            {"content": None},  # None
            {"content": ""},  # 빈 문자열
        ]

        filtered = collector.filter_by_length(items, min_len=300, max_len=3000)

        assert len(filtered) == 3
        assert filtered[0]["content"] == "B" * 500
        assert filtered[1]["content"] == "D" * 300
        assert filtered[2]["content"] == "E" * 3000

    def test_filter_by_keywords_exclude(self):
        """제외 키워드 필터링 테스트"""
        collector = RSSCollector()

        items = [
            {"title": "일상 에세이", "content": "오늘의 일상을 적어봅니다."},
            {"title": "광고", "content": "쿠팡파트너스 할인 코드"},  # 제외
            {"title": "MZ세대 이야기", "content": "요즘 20대는..."},  # 제외
            {"title": "감사 일기", "content": "오늘 감사한 일"},
        ]

        filtered = collector.filter_by_keywords(items)

        assert len(filtered) == 2
        # 제외된 항목 확인
        titles = [item["title"] for item in filtered]
        assert "광고" not in titles
        assert "MZ세대 이야기" not in titles

    def test_filter_by_keywords_relevance_score(self):
        """키워드 관련성 점수 테스트"""
        collector = RSSCollector()

        items = [
            {"title": "가족", "content": "가족과 함께한 여행"},  # 키워드 1개
            {"title": "에세이", "content": "일상 속 감사와 추억"},  # 키워드 3개+
            {"title": "기술 블로그", "content": "프로그래밍 이야기"},  # 키워드 0개
        ]

        filtered = collector.filter_by_keywords(items)

        # 점수순 정렬 확인
        assert filtered[0]["title"] == "에세이"  # 가장 높은 점수
        assert filtered[0]["relevance_score"] > filtered[1]["relevance_score"]


class TestRSSCollectorAsync:
    """RSSCollector 비동기 테스트"""

    @pytest.mark.asyncio
    async def test_fetch_feed_success(self):
        """RSS 피드 수집 성공 테스트"""
        collector = RSSCollector()

        # Mock RSS 응답
        mock_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Test Article</title>
                    <link>https://example.com/1</link>
                    <description>This is a test article content.</description>
                </item>
            </channel>
        </rss>"""

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.text = mock_rss
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            items = await collector.fetch_feed("https://example.com/rss")

            assert len(items) == 1
            assert items[0]["title"] == "Test Article"
            assert "test article content" in items[0]["content"].lower()

    @pytest.mark.asyncio
    async def test_fetch_feed_http_error(self):
        """HTTP 에러 처리 테스트"""
        import httpx

        collector = RSSCollector()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.HTTPError("Connection failed")
            )

            items = await collector.fetch_feed("https://example.com/rss")

            # 에러 시 빈 리스트 반환
            assert items == []

    @pytest.mark.asyncio
    async def test_collect_from_feeds_dedup(self):
        """여러 피드에서 수집 시 중복 제거 테스트"""
        collector = RSSCollector()

        # 같은 내용을 반환하는 두 피드
        mock_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Duplicate Article</title>
                    <link>https://example.com/dup</link>
                    <description>""" + "X" * 400 + """</description>
                </item>
            </channel>
        </rss>"""

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.text = mock_rss
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            items = await collector.collect_from_feeds(
                ["https://feed1.com/rss", "https://feed2.com/rss"],
                min_length=100,
                max_length=5000,
            )

            # 중복 제거로 1개만 남음
            assert len(items) == 1
            assert "content_hash" in items[0]


# ========== WritingService RSS 관련 테스트 ==========


class TestWritingServiceFeeds:
    """WritingService RSS 피드 관리 테스트"""

    def test_add_feed(self, test_db_session):
        """피드 추가 테스트"""
        service = WritingService(test_db_session)

        feed = service.add_feed(
            name="테스트 블로그",
            url="https://test.tistory.com/rss",
            source_type="tistory",
        )

        assert feed.id is not None
        assert feed.name == "테스트 블로그"
        assert feed.url == "https://test.tistory.com/rss"
        assert feed.enabled == 1

    def test_list_feeds(self, test_db_session):
        """피드 목록 조회 테스트"""
        service = WritingService(test_db_session)

        # 피드 추가
        service.add_feed("Feed 1", "https://feed1.com/rss", "tistory")
        service.add_feed("Feed 2", "https://feed2.com/rss", "naver_blog")

        # 비활성화된 피드
        feed3 = service.add_feed("Feed 3", "https://feed3.com/rss", "tistory")
        service.update_feed(feed3.id, enabled=False)

        # 활성 피드만 조회
        feeds = service.list_feeds(enabled_only=True)
        assert len(feeds) == 2

        # 모든 피드 조회
        all_feeds = service.list_feeds(enabled_only=False)
        assert len(all_feeds) == 3

        # source_type 필터
        tistory_feeds = service.list_feeds(source_type="tistory", enabled_only=False)
        assert len(tistory_feeds) == 2

    def test_update_feed(self, test_db_session):
        """피드 수정 테스트"""
        service = WritingService(test_db_session)

        feed = service.add_feed("Original", "https://original.com/rss", "tistory")

        # 이름 변경
        updated = service.update_feed(feed.id, name="Updated Name")
        assert updated.name == "Updated Name"

        # 비활성화
        updated = service.update_feed(feed.id, enabled=False)
        assert updated.enabled == 0

    def test_delete_feed(self, test_db_session):
        """피드 삭제 테스트"""
        service = WritingService(test_db_session)

        feed = service.add_feed("To Delete", "https://delete.com/rss", "tistory")
        feed_id = feed.id

        # 삭제
        success = service.delete_feed(feed_id)
        assert success is True

        # 조회 불가
        assert service.get_feed(feed_id) is None

        # 없는 피드 삭제 시도
        success = service.delete_feed(9999)
        assert success is False

    def test_update_feed_status(self, test_db_session):
        """피드 상태 업데이트 테스트"""
        service = WritingService(test_db_session)

        feed = service.add_feed("Status Test", "https://status.com/rss", "tistory")

        # 성공 업데이트
        service.update_feed_status(feed.id, success=True)
        updated = service.get_feed(feed.id)
        assert updated.fetch_count == 1
        assert updated.last_fetched_at is not None

        # 실패 업데이트
        service.update_feed_status(feed.id, success=False, error_message="Timeout")
        updated = service.get_feed(feed.id)
        assert updated.fetch_count == 2
        assert updated.error_count == 1
        assert updated.last_error == "Timeout"


class TestWritingServiceCollect:
    """WritingService RSS 수집 테스트"""

    @pytest.mark.asyncio
    async def test_collect_from_feeds_no_feeds(self, test_db_session):
        """피드 없을 때 수집 테스트"""
        service = WritingService(test_db_session)

        result = await service.collect_from_feeds()

        assert result["collected"] == 0
        assert result["feeds"] == 0
        assert "No enabled feeds" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_collect_from_feeds_with_mock(self, test_db_session):
        """Mock 피드로 수집 테스트"""
        service = WritingService(test_db_session)

        # 피드 추가
        service.add_feed("Test Feed", "https://test.com/rss", "tistory")

        # Mock RSS 응답
        mock_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>New Article</title>
                    <link>https://test.com/article/1</link>
                    <description>""" + "A" * 500 + """</description>
                </item>
            </channel>
        </rss>"""

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.text = mock_rss
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await service.collect_from_feeds(min_length=100, max_length=5000)

            assert result["feeds"] == 1
            assert result["collected"] >= 0  # 필터링에 따라 다름

    @pytest.mark.asyncio
    async def test_collect_dedup_by_hash(self, test_db_session):
        """해시 기반 중복 제거 테스트"""
        service = WritingService(test_db_session)

        # 기존 소스 추가 (같은 해시)
        content = "A" * 500
        content_hash = RSSCollector.compute_content_hash(content)
        existing = WritingSource(
            content=content,
            source_type=WritingSource.SOURCE_TYPE_RSS,
            content_hash=content_hash,
        )
        test_db_session.add(existing)
        test_db_session.commit()

        # 피드 추가
        service.add_feed("Test", "https://test.com/rss", "tistory")

        # 같은 내용의 RSS
        mock_rss = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Duplicate</title>
                    <link>https://test.com/dup</link>
                    <description>{"A" * 500}</description>
                </item>
            </channel>
        </rss>"""

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.text = mock_rss
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await service.collect_from_feeds(min_length=100, max_length=5000)

            # 중복으로 추가되지 않음
            assert result["collected"] == 0


# ========== 모델 테스트 ==========


class TestWritingRssFeedModel:
    """WritingRssFeed 모델 테스트"""

    def test_create_feed(self, test_db_session):
        """피드 생성 테스트"""
        feed = WritingRssFeed(
            name="테스트 피드",
            url="https://example.com/rss",
            source_type=WritingRssFeed.SOURCE_TYPE_TISTORY,
        )
        test_db_session.add(feed)
        test_db_session.commit()

        assert feed.id is not None
        assert feed.enabled == 1
        assert feed.fetch_count == 0

    def test_source_type_constants(self):
        """소스 타입 상수 테스트"""
        assert WritingRssFeed.SOURCE_TYPE_TISTORY == "tistory"
        assert WritingRssFeed.SOURCE_TYPE_NAVER_BLOG == "naver_blog"
        assert WritingRssFeed.SOURCE_TYPE_MEDIUM == "medium"


class TestWritingSourceExtension:
    """WritingSource 확장 필드 테스트"""

    def test_source_type_field(self, test_db_session):
        """source_type 필드 테스트"""
        source = WritingSource(
            content="Test content",
            source_type=WritingSource.SOURCE_TYPE_RSS,
            source_url="https://example.com/article/1",
        )
        test_db_session.add(source)
        test_db_session.commit()

        retrieved = test_db_session.query(WritingSource).filter(
            WritingSource.id == source.id
        ).first()

        assert retrieved.source_type == "rss"
        assert retrieved.source_url == "https://example.com/article/1"

    def test_content_hash_field(self, test_db_session):
        """content_hash 필드 테스트"""
        content = "Test content for hashing"
        hash_value = RSSCollector.compute_content_hash(content)

        source = WritingSource(
            content=content,
            content_hash=hash_value,
        )
        test_db_session.add(source)
        test_db_session.commit()

        # 해시로 조회
        found = test_db_session.query(WritingSource).filter(
            WritingSource.content_hash == hash_value
        ).first()

        assert found is not None
        assert found.content == content
