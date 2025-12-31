"""Public Data Collector 테스트."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.modules.writing.services.public_data_collector import (
    WikisourceCollector,
    PublicDataCollector,
)


# ========== WikisourceCollector 테스트 ==========


class TestWikisourceCollector:
    """위키문헌 수집기 테스트."""

    def test_default_categories(self):
        """기본 카테고리 확인."""
        collector = WikisourceCollector()
        assert len(collector.DEFAULT_CATEGORIES) > 0
        assert "수필" in collector.DEFAULT_CATEGORIES

    def test_compute_hash(self):
        """해시 계산 테스트."""
        content = "테스트 콘텐츠"
        hash1 = WikisourceCollector._compute_hash(content)
        hash2 = WikisourceCollector._compute_hash(content)
        assert hash1 == hash2
        assert len(hash1) == 64

    @pytest.mark.asyncio
    async def test_list_category_pages_with_mock(self):
        """카테고리 페이지 목록 조회 모킹."""
        collector = WikisourceCollector()

        mock_response = {
            "query": {
                "categorymembers": [
                    {"title": "수필1", "pageid": 1},
                    {"title": "수필2", "pageid": 2},
                ]
            }
        }

        with patch(
            "app.modules.writing.services.public_data_collector.httpx.AsyncClient"
        ) as mock_client:
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response_obj)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await collector.list_category_pages("수필")

            assert len(result) == 2
            assert result[0]["title"] == "수필1"

    @pytest.mark.asyncio
    async def test_get_page_content_with_mock(self):
        """페이지 콘텐츠 조회 모킹."""
        collector = WikisourceCollector()

        mock_response = {
            "query": {
                "pages": {
                    "123": {
                        "pageid": 123,
                        "title": "테스트 수필",
                        "extract": "이것은 테스트 수필 본문입니다.",
                    }
                }
            }
        }

        with patch(
            "app.modules.writing.services.public_data_collector.httpx.AsyncClient"
        ) as mock_client:
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response_obj)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await collector.get_page_content("테스트 수필")

            assert result == "이것은 테스트 수필 본문입니다."

    @pytest.mark.asyncio
    async def test_collect_category_filters_by_length(self):
        """길이 필터링 테스트."""
        collector = WikisourceCollector()

        # 짧은 콘텐츠를 반환하도록 모킹
        with patch.object(
            collector, "list_category_pages", return_value=[{"title": "짧은글"}]
        ):
            with patch.object(collector, "get_page_content", return_value="짧아"):
                result = await collector.collect_category("수필", min_length=200)
                assert len(result) == 0  # 너무 짧아서 필터링됨

    @pytest.mark.asyncio
    async def test_collect_category_includes_valid_content(self):
        """유효한 콘텐츠 수집 테스트."""
        collector = WikisourceCollector()

        long_content = "이것은 충분히 긴 수필 본문입니다. " * 20

        with patch.object(
            collector, "list_category_pages", return_value=[{"title": "긴글"}]
        ):
            with patch.object(collector, "get_page_content", return_value=long_content):
                result = await collector.collect_category("수필", min_length=200)
                assert len(result) == 1
                assert result[0]["title"] == "긴글"
                assert result[0]["source"] == "wikisource"
                assert "content_hash" in result[0]

    @pytest.mark.asyncio
    async def test_collect_all_categories_dedup(self):
        """여러 카테고리 중복 제거 테스트."""
        collector = WikisourceCollector()

        long_content = "동일한 수필 본문입니다. " * 20

        # 두 카테고리에서 동일한 콘텐츠 반환
        with patch.object(collector, "collect_category") as mock_collect:
            item1 = {
                "title": "중복글",
                "content": long_content,
                "link": "https://example.com/1",
                "source": "wikisource",
                "content_hash": WikisourceCollector._compute_hash(long_content),
            }
            mock_collect.return_value = [item1]

            result = await collector.collect_all_categories(["카테고리1", "카테고리2"])

            # 중복 제거되어 1개만 남아야 함
            assert len(result) == 1


# ========== PublicDataCollector 테스트 ==========


class TestPublicDataCollector:
    """공공데이터 수집기 테스트."""

    def test_is_configured_without_key(self):
        """API 키 없이 설정 확인."""
        collector = PublicDataCollector(service_key="")
        assert collector.is_configured() is False

    def test_is_configured_with_key(self):
        """API 키 있을 때 설정 확인."""
        collector = PublicDataCollector(service_key="test_key")
        assert collector.is_configured() is True

    def test_register_dataset(self):
        """데이터셋 등록 테스트."""
        collector = PublicDataCollector(service_key="test")
        collector.register_dataset(
            name="테스트 데이터",
            endpoint="https://api.example.com/data",
            content_field="content",
            title_field="title",
        )
        assert len(collector.datasets) == 1
        assert collector.datasets[0]["name"] == "테스트 데이터"

    def test_extract_items_response_body_items(self):
        """응답 구조 1: response > body > items > item."""
        collector = PublicDataCollector(service_key="test")
        data = {
            "response": {
                "body": {
                    "items": {
                        "item": [{"id": 1}, {"id": 2}]
                    }
                }
            }
        }
        result = collector._extract_items(data)
        assert len(result) == 2

    def test_extract_items_data_list(self):
        """응답 구조 2: data > list."""
        collector = PublicDataCollector(service_key="test")
        data = {"data": [{"id": 1}, {"id": 2}]}
        result = collector._extract_items(data)
        assert len(result) == 2

    def test_extract_items_direct_list(self):
        """응답 구조 3: 직접 리스트."""
        collector = PublicDataCollector(service_key="test")
        data = [{"id": 1}, {"id": 2}]
        result = collector._extract_items(data)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_collect_dataset_without_config(self):
        """설정 없이 수집 시 빈 결과."""
        collector = PublicDataCollector(service_key="")
        result = await collector.collect_dataset(
            endpoint="https://api.example.com",
            content_field="content",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_collect_dataset_with_mock(self):
        """데이터셋 수집 모킹 테스트."""
        collector = PublicDataCollector(service_key="test_key")

        mock_response = {
            "response": {
                "body": {
                    "items": {
                        "item": [
                            {"title": "테스트", "content": "충분히 긴 콘텐츠입니다. " * 10}
                        ]
                    }
                }
            }
        }

        with patch(
            "app.modules.writing.services.public_data_collector.httpx.AsyncClient"
        ) as mock_client:
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response_obj)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await collector.collect_dataset(
                endpoint="https://api.example.com",
                content_field="content",
                title_field="title",
            )

            assert len(result) == 1
            assert result[0]["source"] == "data_go_kr"
