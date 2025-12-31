"""
Writing Service 테스트

모델, 서비스, API 동작을 검증합니다.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.models.writing import WritingSource, GeneratedWriting
from app.modules.writing.services.writing_service import WritingService


@pytest.fixture(autouse=True)
def cleanup_writing_data(test_db_session):
    """각 테스트 전후로 writing 관련 테이블 정리"""
    # 테스트 전 정리
    test_db_session.query(GeneratedWriting).delete()
    test_db_session.query(WritingSource).delete()
    test_db_session.commit()
    yield
    # 테스트 후 정리
    test_db_session.query(GeneratedWriting).delete()
    test_db_session.query(WritingSource).delete()
    test_db_session.commit()


class TestWritingModels:
    """Writing 모델 테스트"""

    def test_writing_source_creation(self, test_db_session):
        """WritingSource 생성 테스트"""
        source = WritingSource(
            content="테스트 소스 내용입니다. 이 내용은 글 생성에 사용됩니다.",
            category="test",
            source_info="테스트 출처"
        )
        test_db_session.add(source)
        test_db_session.commit()

        assert source.id is not None
        assert source.content == "테스트 소스 내용입니다. 이 내용은 글 생성에 사용됩니다."
        assert source.category == "test"
        assert source.source_info == "테스트 출처"
        assert source.created_at is not None

    def test_generated_writing_creation(self, test_db_session):
        """GeneratedWriting 생성 테스트"""
        writing = GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_MIX,
            content="생성된 글 내용입니다.",
            source_ids="1,2,3",
            rating=None
        )
        test_db_session.add(writing)
        test_db_session.commit()

        assert writing.id is not None
        assert writing.task_type == "mix"
        assert writing.content == "생성된 글 내용입니다."
        assert writing.rating is None
        assert writing.deleted_at is None

    def test_generated_writing_source_id_list(self, test_db_session):
        """source_id 목록 변환 테스트"""
        writing = GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_MIX,
            content="테스트",
            source_ids="1,2,3"
        )
        test_db_session.add(writing)
        test_db_session.commit()

        # source_id 리스트 조회
        ids = writing.get_source_id_list()
        assert ids == [1, 2, 3]

    def test_generated_writing_empty_source_ids(self, test_db_session):
        """빈 source_ids 처리 테스트"""
        writing = GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_RANDOM,
            content="랜덤 글",
            source_ids=None
        )
        test_db_session.add(writing)
        test_db_session.commit()

        ids = writing.get_source_id_list()
        assert ids == []


class TestWritingService:
    """WritingService 테스트"""

    def test_add_source(self, test_db_session):
        """소스 추가 테스트"""
        service = WritingService(test_db_session)

        source = service.add_source(
            content="새로운 소스입니다.",
            category="article",
            source_info="https://example.com"
        )

        assert source.id is not None
        assert source.content == "새로운 소스입니다."
        assert source.category == "article"

    def test_bulk_add_sources(self, test_db_session):
        """소스 일괄 추가 테스트"""
        service = WritingService(test_db_session)

        sources = [
            {"content": "소스 1", "category": "news"},
            {"content": "소스 2", "category": "blog"},
            {"content": "소스 3"},  # category 없음
        ]

        added = service.bulk_add_sources(sources)
        assert added == 3

    def test_list_sources(self, test_db_session):
        """소스 목록 조회 테스트"""
        service = WritingService(test_db_session)

        # 테스트 데이터 추가
        for i in range(5):
            service.add_source(content=f"소스 {i}", category="test")

        result = service.list_sources(page=1, page_size=3)

        assert result["total"] == 5
        assert len(result["items"]) == 3
        assert result["page"] == 1
        assert result["pages"] == 2

    def test_delete_source(self, test_db_session):
        """소스 삭제 테스트"""
        service = WritingService(test_db_session)

        source = service.add_source(content="삭제할 소스")
        source_id = source.id

        success = service.delete_source(source_id)
        assert success is True

        # 다시 삭제 시도하면 실패
        success = service.delete_source(source_id)
        assert success is False

    def test_rate_generated_writing(self, test_db_session):
        """글 평가 테스트"""
        service = WritingService(test_db_session)

        # 테스트 글 생성
        writing = GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_MIX,
            content="평가할 글"
        )
        test_db_session.add(writing)
        test_db_session.commit()

        # 추천
        updated = service.rate_generated_writing(writing.id, GeneratedWriting.RATING_LIKE)
        assert updated.rating == 1

        # 비추천으로 변경
        updated = service.rate_generated_writing(writing.id, GeneratedWriting.RATING_DISLIKE)
        assert updated.rating == -1

        # 평가 취소
        updated = service.rate_generated_writing(writing.id, None)
        assert updated.rating is None

    def test_soft_delete_writing(self, test_db_session):
        """글 소프트 삭제 테스트"""
        service = WritingService(test_db_session)

        writing = GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_RANDOM,
            content="삭제할 글"
        )
        test_db_session.add(writing)
        test_db_session.commit()
        writing_id = writing.id

        # 소프트 삭제
        success = service.delete_generated_writing(writing_id, hard_delete=False)
        assert success is True

        # 조회 시 나타나지 않음
        result = service.get_generated_writing(writing_id)
        assert result is None

    def test_hard_delete_writing(self, test_db_session):
        """글 하드 삭제 테스트"""
        service = WritingService(test_db_session)

        writing = GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_RANDOM,
            content="완전 삭제할 글"
        )
        test_db_session.add(writing)
        test_db_session.commit()
        writing_id = writing.id

        # 하드 삭제
        success = service.delete_generated_writing(writing_id, hard_delete=True)
        assert success is True

        # DB에서도 완전히 삭제됨
        deleted = test_db_session.query(GeneratedWriting).filter(
            GeneratedWriting.id == writing_id
        ).first()
        assert deleted is None

    def test_update_writing(self, test_db_session):
        """글 수정 테스트"""
        service = WritingService(test_db_session)

        writing = GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_MIX,
            content="원본 내용"
        )
        test_db_session.add(writing)
        test_db_session.commit()

        # 수정
        updated = service.update_generated_writing(
            writing.id,
            content="수정된 내용"
        )

        assert updated.content == "수정된 내용"
        assert updated.updated_at is not None

    def test_get_stats(self, test_db_session):
        """통계 조회 테스트"""
        service = WritingService(test_db_session)

        # 테스트 데이터 추가
        service.add_source(content="소스 1")
        service.add_source(content="소스 2")

        test_db_session.add(GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_MIX,
            content="믹스 글",
            rating=1
        ))
        test_db_session.add(GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_RANDOM,
            content="랜덤 글",
            rating=-1
        ))
        test_db_session.commit()

        stats = service.get_stats()

        assert stats["source_count"] == 2
        assert stats["generated_count"] == 2
        assert stats["by_type"]["mix"] == 1
        assert stats["by_type"]["random"] == 1
        assert stats["by_rating"]["liked"] == 1
        assert stats["by_rating"]["disliked"] == 1

    def test_list_generated_writings_with_filter(self, test_db_session):
        """필터를 사용한 글 목록 조회 테스트"""
        service = WritingService(test_db_session)

        # 테스트 데이터
        test_db_session.add(GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_MIX,
            content="믹스 1",
            rating=1
        ))
        test_db_session.add(GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_MIX,
            content="믹스 2",
            rating=None
        ))
        test_db_session.add(GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_RANDOM,
            content="랜덤 1",
            rating=-1
        ))
        test_db_session.commit()

        # 타입 필터
        result = service.list_generated_writings(task_type="mix")
        assert result["total"] == 2

        # 평가 필터 (추천만)
        result = service.list_generated_writings(rating=1)
        assert result["total"] == 1

        # 미평가 필터
        result = service.list_generated_writings(rating=0)
        assert result["total"] == 1


class TestWritingWorker:
    """WritingWorker 테스트"""

    @patch('app.modules.writing.worker.writing_worker.LLMService')
    def test_extract_content_from_response(self, mock_llm, test_db_session):
        """LLM 응답에서 콘텐츠 추출 테스트"""
        from app.modules.writing.worker.writing_worker import WritingWorker

        worker = WritingWorker(test_db_session)

        # --- 구분자가 있는 응답 (일반적인 패턴)
        response = """분석 내용입니다.
---
이것은 생성된 글 내용입니다. 충분히 긴 내용이어야 합니다.
이 글은 LLM이 생성한 것으로, 여러 줄에 걸쳐 작성됩니다.
내용이 최소 100자 이상이어야 합니다."""
        content = worker._extract_generated_content(response)
        assert "이것은 생성된 글 내용입니다" in content

        # 구분자 없는 응답 (전체 반환)
        response = "그냥 텍스트 응답"
        content = worker._extract_generated_content(response)
        assert content == "그냥 텍스트 응답"

        # 빈 응답
        content = worker._extract_generated_content("")
        assert content == ""

    @patch('app.modules.writing.worker.writing_worker.LLMService')
    def test_worker_prompt_loading(self, mock_llm, test_db_session):
        """프롬프트 로딩 테스트"""
        from app.modules.writing.worker.writing_worker import WritingWorker

        # 프롬프트 파일이 없어도 기본값으로 동작해야 함
        worker = WritingWorker(test_db_session)

        # 프롬프트 템플릿이 로드되었는지 확인
        # (파일 없으면 빈 문자열이지만 속성은 존재해야 함)
        assert hasattr(worker, 'mix_prompt_template')
        assert hasattr(worker, 'random_prompt_template')
        # 빈 문자열이어도 None은 아님
        assert worker.mix_prompt_template is not None
        assert worker.random_prompt_template is not None
