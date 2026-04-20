"""
Writing Worker / TopicExtract Worker LLM Provider 테스트

RIGHT-BICEP 원칙:
- Right: llm_provider/model이 LLMRequest에 올바르게 전달되는가?
- Default: target_config 없을 때 resolver 결과 사용
- Boundary: llm_model="" 빈 문자열 그대로 저장

대상:
- WritingWorker._queue_mix_writing / _queue_random_writing / _queue_keyword_writing
- TopicExtractWorker.create_extract_requests
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.models.writing import WritingSource


def _create_tables(engine):
    """테스트에 필요한 테이블만 선택 생성 (UUID 테이블 제외)."""
    from sqlalchemy import MetaData
    from app.models.base import Base as AppBase

    # postgresql.UUID를 사용하는 테이블 제외
    EXCLUDE_TABLES = {"writing_collection_tasks"}

    meta = MetaData()
    for name, tbl in AppBase.metadata.tables.items():
        if name not in EXCLUDE_TABLES:
            try:
                tbl.to_metadata(meta)
            except Exception:
                pass  # 다른 문제 있는 테이블도 스킵

    meta.create_all(bind=engine)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _create_tables(engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def writing_schedule_with_gemini(test_db):
    """llm_provider=gemini 설정된 writing_task 스케줄"""
    schedule = TaskSchedule(
        name="writing_task_default",
        target_type="writing_task",
        schedule_type="time_window",
        enabled=True,
    )
    schedule.set_target_config({"llm_provider": "gemini", "llm_model": "gemini-2.0-flash"})
    test_db.add(schedule)
    test_db.commit()
    test_db.refresh(schedule)
    return schedule


@pytest.fixture
def writing_schedule_no_provider(test_db):
    """target_config 없는 writing_task 스케줄 (기본값 사용)"""
    schedule = TaskSchedule(
        name="writing_task_default2",
        target_type="writing_task",
        schedule_type="time_window",
        enabled=True,
    )
    test_db.add(schedule)
    test_db.commit()
    test_db.refresh(schedule)
    return schedule


@pytest.fixture
def schedule_run(test_db, writing_schedule_with_gemini):
    run = TaskScheduleRun(
        schedule_id=writing_schedule_with_gemini.id,
        status="running",
    )
    test_db.add(run)
    test_db.commit()
    test_db.refresh(run)
    return run


# ============================================================
# WritingWorker LLM provider 테스트
# ============================================================

class TestWritingWorkerLlmProvider:
    """Writing Worker에서 LLMRequest에 provider/model이 올바르게 설정되는지 검증"""

    def _get_worker(self, db):
        from app.modules.writing.worker.writing_worker import WritingWorker
        return WritingWorker(db)

    def test_queue_mix_writing_uses_gemini(self, test_db):
        """TC-Right: _queue_mix_writing에 gemini 전달 → LLMRequest.provider == 'gemini'"""
        from app.modules.writing.worker.writing_worker import SlotContext

        # 소스 3개 준비
        for i in range(3):
            src = WritingSource(
                content=f"테스트 소스 내용 {i} " * 100,
                source_type="rss",
                source_url=f"http://example.com/{i}",
            )
            test_db.add(src)
        test_db.commit()

        worker = self._get_worker(test_db)
        slot_context = SlotContext()
        result = worker._queue_mix_writing(
            run_id=999,
            slot_context=slot_context,
            index=0,
            llm_provider="gemini",
            llm_model="gemini-2.0-flash",
        )

        assert result is True
        req = test_db.query(LLMRequest).filter_by(caller_type="writing_generate").first()
        assert req is not None
        assert req.provider == "gemini"
        assert req.model == "gemini-2.0-flash"

    def test_queue_mix_writing_default_provider(self, test_db):
        """TC-Default: llm_provider 미전달 → resolver 결과 사용"""
        from app.modules.writing.worker.writing_worker import SlotContext

        for i in range(3):
            src = WritingSource(
                content=f"기본값 테스트 {i} " * 100,
                source_type="rss",
                source_url=f"http://default.com/{i}",
            )
            test_db.add(src)
        test_db.commit()

        worker = self._get_worker(test_db)
        slot_context = SlotContext()
        expected_provider, expected_model = worker.llm_service.resolve_provider_model(
            caller_type="writing_generate",
            provider=None,
            model=None,
        )
        result = worker._queue_mix_writing(
            run_id=998,
            slot_context=slot_context,
            index=0,
        )

        assert result is True
        req = test_db.query(LLMRequest).filter_by(caller_id="mix_998_0").first()
        assert req is not None
        assert req.provider == expected_provider
        assert req.model == expected_model

    def test_queue_mix_writing_empty_model(self, test_db):
        """TC-Boundary: llm_model='' 빈 문자열 그대로 저장"""
        from app.modules.writing.worker.writing_worker import SlotContext

        for i in range(3):
            src = WritingSource(
                content=f"빈모델 테스트 {i} " * 100,
                source_type="rss",
                source_url=f"http://empty.com/{i}",
            )
            test_db.add(src)
        test_db.commit()

        worker = self._get_worker(test_db)
        slot_context = SlotContext()
        expected_provider, expected_model = worker.llm_service.resolve_provider_model(
            caller_type="writing_generate",
            provider="gemini",
            model="",
        )
        result = worker._queue_mix_writing(
            run_id=997,
            slot_context=slot_context,
            index=0,
            llm_provider="gemini",
            llm_model="",
        )

        assert result is True
        req = test_db.query(LLMRequest).filter_by(caller_id="mix_997_0").first()
        assert req is not None
        assert req.provider == expected_provider
        assert req.model == expected_model

    def test_run_marks_failed_when_source_count_zero(self, test_db, writing_schedule_with_gemini):
        """TC-Error: source_count == 0이면 source shortage로 실패 저장."""
        worker = self._get_worker(test_db)
        run = TaskScheduleRun(
            schedule_id=writing_schedule_with_gemini.id,
            status="running",
        )
        test_db.add(run)
        test_db.commit()
        test_db.refresh(run)

        result = worker.run(writing_schedule_with_gemini, run)
        test_db.refresh(run)

        assert result["error"].startswith("소스 글이 부족합니다: 0개")
        assert run.status == TaskScheduleRun.STATUS_FAILED
        assert run.stop_reason == "source_shortage"
        assert "이관/동기화 누락" in (run.error_message or "")

    def test_run_sets_source_shortage_stop_reason(self, test_db, writing_schedule_with_gemini):
        """TC-Right: source shortage 실패는 stop_reason=source_shortage를 남긴다."""
        test_db.add(
            WritingSource(
                content="소스 1 " * 50,
                source_type="rss",
                source_url="http://example.com/1",
            )
        )
        test_db.commit()

        worker = self._get_worker(test_db)
        run = TaskScheduleRun(
            schedule_id=writing_schedule_with_gemini.id,
            status="running",
        )
        test_db.add(run)
        test_db.commit()
        test_db.refresh(run)

        worker.run(writing_schedule_with_gemini, run)
        test_db.refresh(run)

        assert run.status == TaskScheduleRun.STATUS_FAILED
        assert run.stop_reason == "source_shortage"

    def test_run_boundary_source_count_two_keeps_shortage_message(self, test_db, writing_schedule_with_gemini):
        """TC-Boundary: source_count == 2이면 0건 전용 migration 의심 문구를 쓰지 않는다."""
        for index in range(2):
            test_db.add(
                WritingSource(
                    content=f"소스 {index} " * 50,
                    source_type="rss",
                    source_url=f"http://example.com/{index}",
                )
            )
        test_db.commit()

        worker = self._get_worker(test_db)
        run = TaskScheduleRun(
            schedule_id=writing_schedule_with_gemini.id,
            status="running",
        )
        test_db.add(run)
        test_db.commit()
        test_db.refresh(run)

        result = worker.run(writing_schedule_with_gemini, run)
        test_db.refresh(run)

        assert run.status == TaskScheduleRun.STATUS_FAILED
        assert run.stop_reason == "source_shortage"
        assert result["error"] == "소스 글이 부족합니다: 2개 (최소 3개 필요)"
        assert "이관/동기화 누락" not in result["error"]


# ============================================================
# TopicExtract Worker LLM provider 테스트
# ============================================================

class TestTopicExtractWorkerLlmProvider:
    """TopicExtract Worker에서 LLMRequest에 provider/model이 올바르게 설정되는지 검증"""

    def _get_worker(self, db):
        from app.modules.writing.worker.topic_extract_worker import TopicExtractWorker
        return TopicExtractWorker(db)

    def test_create_extract_requests_gemini(self, test_db):
        """TC-Right: llm_provider='gemini' 전달 → LLMRequest.provider == 'gemini'"""

        src = WritingSource(
            content="소재 추출 테스트 내용 " * 50,
            source_type="rss",
            source_url="http://topic.com/1",
            # topic_extracted_at 없음 → 미처리 상태
        )
        test_db.add(src)
        test_db.commit()

        worker = self._get_worker(test_db)
        count = worker.create_extract_requests(
            limit=10,
            llm_provider="gemini",
            llm_model="gemini-2.0-flash",
        )

        assert count > 0
        req = test_db.query(LLMRequest).filter_by(caller_type="topic_extract").first()
        assert req is not None
        assert req.provider == "gemini"
        assert req.model == "gemini-2.0-flash"

    def test_create_extract_requests_default(self, test_db):
        """TC-Default: llm_provider 미전달 → resolver 결과 사용"""

        src = WritingSource(
            content="기본값 소재 추출 " * 50,
            source_type="rss",
            source_url="http://topic-default.com/1",
        )
        test_db.add(src)
        test_db.commit()

        worker = self._get_worker(test_db)
        expected_provider, expected_model = worker.llm_service.resolve_provider_model(
            caller_type="topic_extract",
            provider=None,
            model=None,
        )
        count = worker.create_extract_requests(limit=10)

        assert count > 0
        req = test_db.query(LLMRequest).filter_by(caller_type="topic_extract").order_by(LLMRequest.id.desc()).first()
        assert req is not None
        assert req.provider == expected_provider
        assert req.model == expected_model
