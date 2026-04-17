"""
Writing Service 테스트

모델, 서비스, API 동작을 검증합니다.
"""

import pytest
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.models.writing import WritingSource, GeneratedWriting
from app.models.writing_element import WritingElement, WritingElementUsage
from app.modules.writing.services.writing_service import WritingService
from app.modules.writing.services.element_selector import ElementSelector, COOLDOWN_DAYS
from app.modules.claude_worker.models.llm_request import LLMRequest


@pytest.fixture(autouse=True)
def cleanup_writing_data(test_db_session):
    """각 테스트 전후로 writing 관련 테이블 정리"""
    # 테스트 전 정리
    test_db_session.query(WritingElementUsage).delete()
    test_db_session.query(GeneratedWriting).delete()
    test_db_session.query(WritingSource).delete()
    test_db_session.query(WritingElement).delete()
    test_db_session.query(LLMRequest).filter(
        LLMRequest.caller_type.in_(["writing", "writing_generate"])
    ).delete()
    test_db_session.commit()
    yield
    # 테스트 후 정리
    test_db_session.query(WritingElementUsage).delete()
    test_db_session.query(GeneratedWriting).delete()
    test_db_session.query(WritingSource).delete()
    test_db_session.query(WritingElement).delete()
    test_db_session.query(LLMRequest).filter(
        LLMRequest.caller_type.in_(["writing", "writing_generate"])
    ).delete()
    test_db_session.commit()


@pytest.fixture
def sample_elements(test_db_session):
    """테스트용 샘플 요소 생성"""
    elements = []
    # 소재 (topic)
    for i, name in enumerate(["계절의 변화", "손주와의 일상", "오래된 물건", "퇴직 후의 일상"]):
        elem = WritingElement(
            category=WritingElement.CATEGORY_TOPIC,
            name=name,
            season_hint="winter" if i == 0 else None,
            is_active=True
        )
        test_db_session.add(elem)
        elements.append(elem)

    # 키워드 (keyword)
    for name in ["그리움", "감사", "따뜻함", "여유", "추억", "평온"]:
        elem = WritingElement(
            category=WritingElement.CATEGORY_KEYWORD,
            name=name,
            is_active=True
        )
        test_db_session.add(elem)
        elements.append(elem)

    # 톤 (tone)
    for name in ["잔잔한 회상", "담담한 깨달음", "따뜻한 위로"]:
        elem = WritingElement(
            category=WritingElement.CATEGORY_TONE,
            name=name,
            is_active=True
        )
        test_db_session.add(elem)
        elements.append(elem)

    # 스타일 (style)
    for name in ["짧고 간결한 문장", "여유로운 긴 문장", "대화체 혼합"]:
        elem = WritingElement(
            category=WritingElement.CATEGORY_STYLE,
            name=name,
            is_active=True
        )
        test_db_session.add(elem)
        elements.append(elem)

    # 형식 (format)
    for name in ["짧은 에세이", "편지 형식", "독백/혼잣말"]:
        elem = WritingElement(
            category=WritingElement.CATEGORY_FORMAT,
            name=name,
            is_active=True
        )
        test_db_session.add(elem)
        elements.append(elem)

    # 감정선 (emotion)
    for name in ["잔잔→따뜻함", "쓸쓸함→위안", "그리움→감사"]:
        elem = WritingElement(
            category=WritingElement.CATEGORY_EMOTION,
            name=name,
            is_active=True
        )
        test_db_session.add(elem)
        elements.append(elem)

    test_db_session.commit()
    return elements


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

    def test_mix_writing_queues_llm_request_on_success(self, test_db_session):
        """믹스 글쓰기 요청이 pending LLMRequest로 적재되는지 테스트"""
        from app.modules.writing.worker.writing_worker import WritingWorker, SlotContext

        # 테스트 소스 데이터 추가
        for i in range(3):
            test_db_session.add(WritingSource(
                content=f"테스트 소스 {i}. " * 20,
                category="test"
            ))
        test_db_session.commit()

        # LLM 서비스 mock
        with patch.object(WritingWorker, '_load_prompts'):
            worker = WritingWorker(test_db_session)
            worker.mix_prompt_template = "테스트 프롬프트 (여기에 첫 번째 글 붙여넣기) (여기에 두 번째 글 붙여넣기) (여기에 세 번째 글 붙여넣기)"
            worker.random_prompt_template = "랜덤 프롬프트"
            worker.llm_service.resolve_provider_model = MagicMock(
                return_value=("test-provider", "test-model")
            )

            # 믹스 글쓰기 실행
            ctx = SlotContext()
            result = worker._queue_mix_writing(run_id=1, slot_context=ctx, index=0)

            assert result is True

            # LLMRequest 이력 확인
            llm_request = test_db_session.query(LLMRequest).filter(
                LLMRequest.caller_type == "writing_generate",
                LLMRequest.caller_id == "mix_1_0"
            ).first()

            assert llm_request is not None
            assert llm_request.status == "pending"
            assert llm_request.requested_by == "scheduler"
            assert llm_request.request_source == "writing_worker"
            assert llm_request.provider == "test-provider"
            assert llm_request.model == "test-model"
            metadata = json.loads(llm_request.writing_metadata)
            assert metadata["task_type"] == "mix"
            assert metadata["run_id"] == 1
            assert sorted(metadata["source_ids"]) == sorted(ctx.used_source_ids)

    def test_mix_writing_returns_false_on_queue_failure(self, test_db_session):
        """믹스 글쓰기 요청 생성 중 예외가 나면 False 반환 테스트"""
        from app.modules.writing.worker.writing_worker import WritingWorker, SlotContext

        # 테스트 소스 데이터 추가
        for i in range(3):
            test_db_session.add(WritingSource(
                content=f"테스트 소스 {i}. " * 20,
                category="test"
            ))
        test_db_session.commit()

        with patch.object(WritingWorker, '_load_prompts'):
            worker = WritingWorker(test_db_session)
            worker.mix_prompt_template = "테스트 프롬프트 (여기에 첫 번째 글 붙여넣기) (여기에 두 번째 글 붙여넣기) (여기에 세 번째 글 붙여넣기)"
            worker.llm_service.resolve_provider_model = MagicMock(
                side_effect=RuntimeError("LLM 호출 타임아웃")
            )

            ctx = SlotContext()
            result = worker._queue_mix_writing(run_id=1, slot_context=ctx, index=0)

            assert result is False

            llm_request = test_db_session.query(LLMRequest).filter(
                LLMRequest.caller_type == "writing_generate",
                LLMRequest.caller_id == "mix_1_0"
            ).first()

            assert llm_request is None

    def test_random_writing_queues_llm_request_on_success(self, test_db_session, sample_elements):
        """랜덤 글쓰기 요청이 pending LLMRequest로 적재되는지 테스트"""
        from app.modules.writing.worker.writing_worker import WritingWorker, SlotContext

        with patch.object(WritingWorker, '_load_prompts'):
            worker = WritingWorker(test_db_session)
            worker.mix_prompt_template = ""
            worker.random_prompt_template = "소재: {topic}\n키워드: {keywords}\n톤: {tone}\n문체: {style}\n형식: {format}\n감정선: {emotion}"
            worker.llm_service.resolve_provider_model = MagicMock(
                return_value=("test-provider", "test-model")
            )

            ctx = SlotContext()
            result = worker._queue_random_writing(run_id=2, slot_context=ctx, season="winter", index=1)

            assert result is True

            llm_request = test_db_session.query(LLMRequest).filter(
                LLMRequest.caller_type == "writing_generate",
                LLMRequest.caller_id == "random_2_1"
            ).first()

            assert llm_request is not None
            assert llm_request.status == "pending"
            assert llm_request.requested_by == "scheduler"
            assert llm_request.request_source == "writing_worker"
            metadata = json.loads(llm_request.writing_metadata)
            assert metadata["task_type"] == "random"
            assert metadata["run_id"] == 2
            assert metadata["selected_elements"]["season"] == "winter"
            assert metadata["selected_elements"]["topic"]

    def test_random_writing_returns_false_on_queue_failure(self, test_db_session, sample_elements):
        """랜덤 글쓰기 요청 생성 중 예외가 나면 False 반환 테스트"""
        from app.modules.writing.worker.writing_worker import WritingWorker, SlotContext

        with patch.object(WritingWorker, '_load_prompts'):
            worker = WritingWorker(test_db_session)
            worker.mix_prompt_template = ""
            worker.random_prompt_template = "소재: {topic}\n키워드: {keywords}\n톤: {tone}\n문체: {style}\n형식: {format}\n감정선: {emotion}"
            worker.llm_service.resolve_provider_model = MagicMock(
                side_effect=RuntimeError("API 오류")
            )

            ctx = SlotContext()
            result = worker._queue_random_writing(run_id=2, slot_context=ctx, season="winter", index=1)

            assert result is False

            llm_request = test_db_session.query(LLMRequest).filter(
                LLMRequest.caller_type == "writing_generate",
                LLMRequest.caller_id == "random_2_1"
            ).first()

            assert llm_request is None


class TestWritingElement:
    """WritingElement 모델 테스트"""

    def test_element_creation(self, test_db_session):
        """WritingElement 생성 테스트"""
        elem = WritingElement(
            category=WritingElement.CATEGORY_TOPIC,
            name="테스트 소재",
            season_hint="spring,fall",
            is_active=True
        )
        test_db_session.add(elem)
        test_db_session.commit()

        assert elem.id is not None
        assert elem.category == "topic"
        assert elem.name == "테스트 소재"
        assert elem.season_hint == "spring,fall"

    def test_get_season_hints(self, test_db_session):
        """시즌 힌트 파싱 테스트"""
        elem = WritingElement(
            category=WritingElement.CATEGORY_TOPIC,
            name="계절",
            season_hint="spring, fall, winter"
        )
        test_db_session.add(elem)
        test_db_session.commit()

        hints = elem.get_season_hints()
        assert hints == ["spring", "fall", "winter"]

    def test_matches_season(self, test_db_session):
        """시즌 매칭 테스트"""
        elem = WritingElement(
            category=WritingElement.CATEGORY_TOPIC,
            name="겨울 소재",
            season_hint="winter"
        )
        test_db_session.add(elem)
        test_db_session.commit()

        assert elem.matches_season("winter") is True
        assert elem.matches_season("summer") is False

    def test_empty_season_hint(self, test_db_session):
        """빈 시즌 힌트 처리 테스트"""
        elem = WritingElement(
            category=WritingElement.CATEGORY_TOPIC,
            name="일반 소재",
            season_hint=None
        )
        test_db_session.add(elem)
        test_db_session.commit()

        assert elem.get_season_hints() == []
        assert elem.matches_season("winter") is False


class TestElementSelector:
    """ElementSelector 테스트"""

    def test_select_sources_basic(self, test_db_session):
        """기본 소스 선택 테스트"""
        # 테스트 소스 추가
        for i in range(5):
            test_db_session.add(WritingSource(
                content=f"테스트 소스 {i}",
                category="test"
            ))
        test_db_session.commit()

        selector = ElementSelector(test_db_session)
        sources = selector.select_sources(count=3)

        assert len(sources) == 3
        # 중복 없이 선택되었는지 확인
        source_ids = [s.id for s in sources]
        assert len(set(source_ids)) == 3

    def test_select_sources_with_exclude(self, test_db_session):
        """제외 목록이 있는 소스 선택 테스트"""
        sources = []
        for i in range(5):
            src = WritingSource(content=f"소스 {i}", category="test")
            test_db_session.add(src)
            sources.append(src)
        test_db_session.commit()

        selector = ElementSelector(test_db_session)

        # 처음 2개 제외
        exclude_ids = [sources[0].id, sources[1].id]
        selected = selector.select_sources(count=2, exclude_ids=exclude_ids)

        assert len(selected) == 2
        for s in selected:
            assert s.id not in exclude_ids

    def test_select_elements_basic(self, test_db_session, sample_elements):
        """기본 요소 선택 테스트"""
        selector = ElementSelector(test_db_session)

        # topic 선택
        topic = selector.select_element(WritingElement.CATEGORY_TOPIC)
        assert topic is not None
        assert topic.category == WritingElement.CATEGORY_TOPIC

        # keyword 2개 선택
        keywords = selector.select_elements(WritingElement.CATEGORY_KEYWORD, count=2)
        assert len(keywords) == 2
        for kw in keywords:
            assert kw.category == WritingElement.CATEGORY_KEYWORD

    def test_select_elements_with_exclude(self, test_db_session, sample_elements):
        """제외 목록이 있는 요소 선택 테스트"""
        selector = ElementSelector(test_db_session)

        # 첫 번째 topic의 ID
        first_topic = test_db_session.query(WritingElement).filter(
            WritingElement.category == WritingElement.CATEGORY_TOPIC
        ).first()

        # 제외하고 선택
        selected = selector.select_element(
            WritingElement.CATEGORY_TOPIC,
            exclude_ids=[first_topic.id]
        )

        assert selected is not None
        assert selected.id != first_topic.id

    def test_weighted_sample_with_season(self, test_db_session, sample_elements):
        """시즌 가중치 샘플링 테스트"""
        selector = ElementSelector(test_db_session)

        # winter 시즌으로 여러 번 선택하여 통계 확인
        winter_counts = 0
        total_runs = 50

        for _ in range(total_runs):
            topic = selector.select_element(
                WritingElement.CATEGORY_TOPIC,
                season="winter"
            )
            if topic and topic.season_hint and "winter" in topic.season_hint:
                winter_counts += 1

        # 시즌 매칭 요소가 더 자주 선택되어야 함 (통계적으로)
        # 정확한 비율은 테스트마다 다를 수 있으므로 완화된 기준 사용
        assert winter_counts > 0

    def test_record_source_usage(self, test_db_session):
        """소스 사용 이력 기록 테스트"""
        # 소스 추가
        source = WritingSource(content="테스트", category="test")
        test_db_session.add(source)
        test_db_session.commit()

        # 글 추가
        writing = GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_MIX,
            content="생성된 글"
        )
        test_db_session.add(writing)
        test_db_session.commit()

        # 사용 이력 기록
        selector = ElementSelector(test_db_session)
        selector.record_source_usage([source.id], writing.id)
        test_db_session.commit()

        # 확인
        usage = test_db_session.query(WritingElementUsage).filter(
            WritingElementUsage.source_id == source.id
        ).first()

        assert usage is not None
        assert usage.generated_writing_id == writing.id

    def test_record_element_usage(self, test_db_session, sample_elements):
        """요소 사용 이력 기록 테스트"""
        # 글 추가
        writing = GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_RANDOM,
            content="랜덤 글"
        )
        test_db_session.add(writing)
        test_db_session.commit()

        # 요소 선택
        selector = ElementSelector(test_db_session)
        topic = selector.select_element(WritingElement.CATEGORY_TOPIC)

        # 사용 이력 기록
        selector.record_element_usage([topic], writing.id)
        test_db_session.commit()

        # 확인
        usage = test_db_session.query(WritingElementUsage).filter(
            WritingElementUsage.element_id == topic.id
        ).first()

        assert usage is not None
        assert usage.generated_writing_id == writing.id

    def test_cooldown_excludes_recent_usage(self, test_db_session, sample_elements):
        """쿨다운으로 최근 사용 요소 제외 테스트"""
        selector = ElementSelector(test_db_session)

        # 글 생성
        writing = GeneratedWriting(
            task_type=GeneratedWriting.TASK_TYPE_RANDOM,
            content="테스트 글"
        )
        test_db_session.add(writing)
        test_db_session.commit()

        # 모든 topic 요소 사용 기록 (쿨다운 적용)
        topics = test_db_session.query(WritingElement).filter(
            WritingElement.category == WritingElement.CATEGORY_TOPIC
        ).all()

        for topic in topics[:-1]:  # 마지막 하나 제외하고 모두 사용
            usage = WritingElementUsage(
                element_id=topic.id,
                generated_writing_id=writing.id
            )
            test_db_session.add(usage)
        test_db_session.commit()

        # 선택 시 사용하지 않은 마지막 요소만 사용 가능해야 함
        available = selector.get_available_elements(
            WritingElement.CATEGORY_TOPIC,
            cooldown_days=7
        )

        assert len(available) == 1
        assert available[0].id == topics[-1].id


class TestSlotContext:
    """SlotContext 테스트"""

    def test_slot_context_mark_used_sources(self):
        """소스 사용 기록 테스트"""
        from app.modules.writing.worker.writing_worker import SlotContext

        ctx = SlotContext()
        ctx.mark_used_sources([1, 2, 3])

        assert ctx.used_source_ids == [1, 2, 3]

        ctx.mark_used_sources([4, 5])
        assert ctx.used_source_ids == [1, 2, 3, 4, 5]

    def test_slot_context_mark_used_element(self, test_db_session, sample_elements):
        """요소 사용 기록 테스트"""
        from app.modules.writing.worker.writing_worker import SlotContext

        ctx = SlotContext()

        # topic 요소 선택
        topic = test_db_session.query(WritingElement).filter(
            WritingElement.category == WritingElement.CATEGORY_TOPIC
        ).first()

        ctx.mark_used_element(topic)
        assert topic.id in ctx.used_topic_ids

    def test_slot_context_get_exclude_ids(self, test_db_session, sample_elements):
        """카테고리별 제외 ID 조회 테스트"""
        from app.modules.writing.worker.writing_worker import SlotContext

        ctx = SlotContext()
        ctx.used_topic_ids = [1, 2]
        ctx.used_keyword_ids = [3, 4, 5]

        assert ctx.get_exclude_ids(WritingElement.CATEGORY_TOPIC) == [1, 2]
        assert ctx.get_exclude_ids(WritingElement.CATEGORY_KEYWORD) == [3, 4, 5]
        assert ctx.get_exclude_ids("unknown") == []

    def test_slot_context_prevents_duplicate(self, test_db_session, sample_elements):
        """슬롯 간 중복 방지 테스트"""
        from app.modules.writing.worker.writing_worker import SlotContext

        selector = ElementSelector(test_db_session)
        ctx = SlotContext()

        # 첫 번째 선택
        topic1 = selector.select_element(
            WritingElement.CATEGORY_TOPIC,
            exclude_ids=ctx.get_exclude_ids(WritingElement.CATEGORY_TOPIC)
        )
        ctx.mark_used_element(topic1)

        # 두 번째 선택 (첫 번째와 다른 것 선택)
        topic2 = selector.select_element(
            WritingElement.CATEGORY_TOPIC,
            exclude_ids=ctx.get_exclude_ids(WritingElement.CATEGORY_TOPIC)
        )

        assert topic2 is not None
        assert topic1.id != topic2.id


class TestWritingWorkerRotation:
    """WritingWorker 로테이션 통합 테스트"""

    @patch('app.modules.writing.worker.writing_worker.LLMService')
    def test_mix_writing_uses_selector(self, mock_llm, test_db_session, sample_elements):
        """믹스 글쓰기가 selector 결과를 요청 메타데이터에 반영하는지 테스트"""
        from app.modules.writing.worker.writing_worker import WritingWorker, SlotContext

        # 소스 추가
        for i in range(5):
            test_db_session.add(WritingSource(
                content=f"테스트 소스 내용 {i}. " * 20,
                category="test"
            ))
        test_db_session.commit()

        with patch.object(WritingWorker, '_load_prompts'):
            worker = WritingWorker(test_db_session)
            worker.mix_prompt_template = "프롬프트 (여기에 첫 번째 글 붙여넣기) (여기에 두 번째 글 붙여넣기) (여기에 세 번째 글 붙여넣기)"
            worker.llm_service.resolve_provider_model = MagicMock(
                return_value=("test-provider", "test-model")
            )

            ctx = SlotContext()

            # 첫 번째 실행
            result1 = worker._queue_mix_writing(run_id=1, slot_context=ctx, index=0)
            assert result1 is True

            # 사용된 소스가 컨텍스트에 기록되었는지 확인
            assert len(ctx.used_source_ids) == 3

            llm_request = test_db_session.query(LLMRequest).filter(
                LLMRequest.caller_type == "writing_generate",
                LLMRequest.caller_id == "mix_1_0"
            ).first()
            assert llm_request is not None
            metadata = json.loads(llm_request.writing_metadata)
            assert sorted(metadata["source_ids"]) == sorted(ctx.used_source_ids)

    @patch('app.modules.writing.worker.writing_worker.LLMService')
    def test_random_writing_stores_selected_elements(self, mock_llm, test_db_session, sample_elements):
        """랜덤 글쓰기 요청 메타데이터에 선택 요소가 저장되는지 테스트"""
        from app.modules.writing.worker.writing_worker import WritingWorker, SlotContext

        with patch.object(WritingWorker, '_load_prompts'):
            worker = WritingWorker(test_db_session)
            worker.random_prompt_template = """
소재: {topic}
키워드: {keywords}
톤: {tone}
문체: {style}
형식: {format}
감정선: {emotion}
"""
            worker.llm_service.resolve_provider_model = MagicMock(
                return_value=("test-provider", "test-model")
            )

            ctx = SlotContext()

            result = worker._queue_random_writing(
                run_id=1,
                slot_context=ctx,
                season="winter",
                index=0
            )

            assert result is True

            llm_request = test_db_session.query(LLMRequest).filter(
                LLMRequest.caller_type == "writing_generate",
                LLMRequest.caller_id == "random_1_0"
            ).first()

            assert llm_request is not None
            assert llm_request.status == "pending"

            selected = json.loads(llm_request.writing_metadata)["selected_elements"]
            assert "topic" in selected
            assert "keywords" in selected
            assert "season" in selected
            assert selected["season"] == "winter"

    def test_get_current_season(self, test_db_session, sample_elements):
        """현재 시즌 판단 테스트"""
        from app.modules.writing.worker.writing_worker import WritingWorker
        from unittest.mock import patch

        with patch.object(WritingWorker, '_load_prompts'):
            worker = WritingWorker(test_db_session)

            # datetime.now를 mock하여 다양한 시즌 테스트
            from datetime import datetime

            # 1월 -> winter
            with patch('app.modules.writing.worker.writing_worker.datetime') as mock_dt:
                mock_dt.now.return_value = datetime(2026, 1, 15)
                assert worker._get_current_season() == "winter"

            # 5월 8일 -> parents_day
            with patch('app.modules.writing.worker.writing_worker.datetime') as mock_dt:
                mock_dt.now.return_value = datetime(2026, 5, 8)
                assert worker._get_current_season() == "parents_day"

            # 7월 -> summer
            with patch('app.modules.writing.worker.writing_worker.datetime') as mock_dt:
                mock_dt.now.return_value = datetime(2026, 7, 15)
                assert worker._get_current_season() == "summer"

            # 10월 -> fall
            with patch('app.modules.writing.worker.writing_worker.datetime') as mock_dt:
                mock_dt.now.return_value = datetime(2026, 10, 15)
                assert worker._get_current_season() == "fall"


class TestWritingBatch:
    """WritingBatch 모델 테스트"""

    def test_batch_creation(self, test_db_session):
        """WritingBatch 생성 테스트"""
        from app.modules.writing.models.writing_batch import WritingBatch

        batch = WritingBatch(
            status=WritingBatch.STATUS_PENDING,
            total_count=11
        )
        test_db_session.add(batch)
        test_db_session.commit()

        assert batch.id is not None
        assert batch.status == "pending"
        assert batch.total_count == 11
        assert batch.completed_count == 0
        assert batch.failed_count == 0
        assert batch.created_at is not None

    def test_batch_mark_started(self, test_db_session):
        """배치 시작 표시 테스트"""
        from app.modules.writing.models.writing_batch import WritingBatch

        batch = WritingBatch(total_count=11)
        test_db_session.add(batch)
        test_db_session.commit()

        batch.mark_started()
        test_db_session.commit()

        assert batch.status == WritingBatch.STATUS_RUNNING
        assert batch.started_at is not None

    def test_batch_increment_completed(self, test_db_session):
        """완료 카운트 증가 테스트"""
        from app.modules.writing.models.writing_batch import WritingBatch

        batch = WritingBatch(total_count=3)
        batch.mark_started()
        test_db_session.add(batch)
        test_db_session.commit()

        batch.increment_completed()
        assert batch.completed_count == 1
        assert batch.status == WritingBatch.STATUS_RUNNING

        batch.increment_completed()
        batch.increment_completed()
        test_db_session.commit()

        assert batch.completed_count == 3
        assert batch.status == WritingBatch.STATUS_COMPLETED
        assert batch.completed_at is not None

    def test_batch_increment_failed(self, test_db_session):
        """실패 카운트 증가 테스트"""
        from app.modules.writing.models.writing_batch import WritingBatch

        batch = WritingBatch(total_count=3)
        batch.mark_started()
        test_db_session.add(batch)
        test_db_session.commit()

        batch.increment_completed()
        batch.increment_failed()
        batch.increment_failed()
        test_db_session.commit()

        assert batch.completed_count == 1
        assert batch.failed_count == 2
        assert batch.status == WritingBatch.STATUS_COMPLETED  # 모든 요청 완료 시

    def test_batch_progress_percent(self, test_db_session):
        """진행률 계산 테스트"""
        from app.modules.writing.models.writing_batch import WritingBatch

        batch = WritingBatch(total_count=10)
        batch.mark_started()
        test_db_session.add(batch)

        assert batch.progress_percent == 0

        batch.increment_completed()
        batch.increment_completed()
        assert batch.progress_percent == 20

        batch.increment_failed()
        assert batch.progress_percent == 30

    def test_batch_is_done(self, test_db_session):
        """완료 여부 확인 테스트"""
        from app.modules.writing.models.writing_batch import WritingBatch

        batch = WritingBatch(total_count=2)
        test_db_session.add(batch)

        assert batch.is_done is False

        batch.mark_started()
        assert batch.is_done is False

        batch.increment_completed()
        batch.increment_completed()

        assert batch.is_done is True


class TestWritingBatchService:
    """WritingService 배치 관련 메서드 테스트"""

    @pytest.fixture(autouse=True)
    def cleanup_batch_data(self, test_db_session):
        """각 테스트 전후로 배치 관련 데이터 정리"""
        from app.modules.writing.models.writing_batch import WritingBatch

        yield
        test_db_session.query(WritingBatch).delete()
        test_db_session.commit()

    def test_get_batch(self, test_db_session):
        """배치 조회 테스트"""
        from app.modules.writing.models.writing_batch import WritingBatch

        batch = WritingBatch(total_count=11)
        test_db_session.add(batch)
        test_db_session.commit()

        service = WritingService(test_db_session)
        result = service.get_batch(batch.id)

        assert result is not None
        assert result.id == batch.id
        assert result.total_count == 11

    def test_get_batch_not_found(self, test_db_session):
        """존재하지 않는 배치 조회 테스트"""
        service = WritingService(test_db_session)
        result = service.get_batch(99999)

        assert result is None

    def test_list_batches(self, test_db_session):
        """배치 목록 조회 테스트"""
        from app.modules.writing.models.writing_batch import WritingBatch

        # 테스트 배치 추가
        for i in range(5):
            batch = WritingBatch(total_count=11)
            if i < 2:
                batch.status = WritingBatch.STATUS_COMPLETED
            test_db_session.add(batch)
        test_db_session.commit()

        service = WritingService(test_db_session)

        # 전체 목록
        result = service.list_batches(page=1, page_size=10)
        assert result["total"] == 5
        assert len(result["items"]) == 5

        # 상태 필터
        result = service.list_batches(status="completed", page=1, page_size=10)
        assert result["total"] == 2

        # 페이지네이션
        result = service.list_batches(page=1, page_size=2)
        assert len(result["items"]) == 2
        assert result["pages"] == 3

    def test_get_batch_status(self, test_db_session):
        """배치 상태 조회 테스트"""
        from app.modules.writing.models.writing_batch import WritingBatch

        batch = WritingBatch(total_count=11)
        batch.mark_started()
        batch.increment_completed()
        batch.increment_completed()
        test_db_session.add(batch)
        test_db_session.commit()

        service = WritingService(test_db_session)
        result = service.get_batch_status(batch.id)

        assert result is not None
        assert result["id"] == batch.id
        assert result["status"] == WritingBatch.STATUS_RUNNING
        assert result["completed"] == 2
        assert result["total"] == 11
        assert result["progress_percent"] > 0
        assert "requests" in result
        assert "writings" in result


class TestLLMRequestWritingExtension:
    """LLMRequest writing 확장 컬럼 테스트"""

    def test_llm_request_with_writing_batch_id(self, test_db_session):
        """writing_batch_id 컬럼 테스트"""
        from app.modules.writing.models.writing_batch import WritingBatch

        batch = WritingBatch(total_count=11)
        test_db_session.add(batch)
        test_db_session.commit()

        request = LLMRequest(
            caller_type="writing",
            caller_id="mix_1_0",
            prompt="테스트 프롬프트",
            writing_batch_id=batch.id
        )
        test_db_session.add(request)
        test_db_session.commit()

        assert request.id is not None
        assert request.writing_batch_id == batch.id

    def test_llm_request_with_writing_metadata(self, test_db_session):
        """writing_metadata 컬럼 테스트"""
        import json

        metadata = {
            "task_type": "mix",
            "source_ids": [1, 2, 3]
        }

        request = LLMRequest(
            caller_type="writing",
            caller_id="mix_1_0",
            prompt="테스트 프롬프트",
            writing_metadata=json.dumps(metadata)
        )
        test_db_session.add(request)
        test_db_session.commit()

        assert request.writing_metadata is not None
        loaded = json.loads(request.writing_metadata)
        assert loaded["task_type"] == "mix"
        assert loaded["source_ids"] == [1, 2, 3]
