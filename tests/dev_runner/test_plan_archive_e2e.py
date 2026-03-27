"""
test_plan_archive_e2e.py — Plan Archive 파이프라인 E2E 테스트

전체 흐름 검증:
1. Listener: archive 파일 수신 → DB LLMRequest 생성 (파일 내용 포함 확인)
2. Handler: analyze 결과 저장 → requirements_sync 트리거 확인
3. Handler: requirements_sync 결과 저장 → 파일 생성 확인
4. Scheduler: 03:30 안전망 동작 확인
"""
import pytest
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanEvent
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.worker.plan_archive_listener import PlanArchiveListener
from app.modules.claude_worker.services.plan_analyze_handler import (
    save_plan_archive_result,
    save_requirements_sync_result,
)
from app.worker.scheduled_worker import ScheduledCrawlWorker


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)
    LLMRequest.__table__.create(bind=eng, checkfirst=True)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


class TestPlanArchiveE2E:
    """전체 파이프라인 E2E 흐름 테스트"""

    def test_e2e_listener_prompt_contains_file_content(self, db, tmp_path):
        """R: 임시 archive md 파일 생성 → _handle_archived_sync() 직접 호출 → DB의 LLMRequest.prompt에 파일 내용 포함 확인"""
        # 1. 파일 생성
        archive_file = tmp_path / "2026-03-01_e2e-test.md"
        content = "# E2E Test\n- [ ] Task 1\n- [ ] Task 2"
        archive_file.write_text(content, encoding="utf-8")

        # 2. Listener 준비
        listener = PlanArchiveListener.__new__(PlanArchiveListener)
        listener.name = "e2e_listener"

        # 3. 실행 (Sync 직접 호출)
        with patch("app.worker.plan_archive_listener.SessionLocal", return_value=db):
            listener._handle_archived_sync(str(archive_file))

        # 4. 검증
        req = db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").first()
        assert req is not None
        assert "Task 1" in req.prompt
        assert "Task 2" in req.prompt
        assert "e2e-test.md" in req.prompt
        # prompt에 파일 내용이 있어야 함
        assert len(req.prompt) > 100

    def test_e2e_requirements_sync_triggered_after_5th_analyze(self, db):
        """R: plan_records 4개 + 1개 신규 analyze 결과 저장 → plan_requirements_sync LLMRequest 자동 생성"""
        # 1. 4개 이미 처리됨
        for i in range(4):
            db.add(PlanRecord(
                filename_hash=f"e2e_processed_{i}",
                file_path=f"file_{i}.md",
                category="e2e-cat",
                summary=f"sum {i}",
                llm_processed_at=datetime.now(),
                archived_at=datetime.now(),
            ))
        # 2. 5번째 미처리
        fifth = PlanRecord(
            filename_hash="e2e_fifth_hash",
            file_path="fifth.md",
            category=None,
            archived_at=datetime.now(),
        )
        db.add(fifth)
        db.commit()

        # 3. 5번째 결과 저장
        mock_req = MagicMock()
        mock_req.caller_id = "e2e_fifth_hash"
        result = {
            "success": True,
            "result": {"category": "e2e-cat", "summary": "5th summary", "tags": ["feat"]}
        }

        save_plan_archive_result(db, mock_req, result)

        # 4. 검증: requirements_sync 요청 생성 확인
        sync_req = db.query(LLMRequest).filter_by(
            caller_type="plan_requirements_sync",
            caller_id="e2e-cat"
        ).first()
        assert sync_req is not None
        assert "5th summary" in sync_req.prompt

    def test_e2e_requirements_sync_file_written(self, db, tmp_path):
        """R: save_requirements_sync_result() 호출 → docs/requirements/{category}.md 파일 생성 확인"""
        # 1. Mock 요청/결과
        mock_req = MagicMock()
        mock_req.caller_id = "e2e-cat"
        result = {
            "success": True,
            "result": {
                "category": "e2e-cat",
                "requirements": "# E2E Requirements\n\n- Feature 1\n- Feature 2"
            }
        }

        # 2. Path 모킹하여 임시 디렉토리 쓰기 확인
        # pathlib.Path를 직접 패치
        with patch("pathlib.Path") as mock_path_cls:
            mock_path_inst = MagicMock()
            mock_path_cls.return_value = mock_path_inst
            mock_path_inst.parent = mock_path_inst
            mock_path_inst.__truediv__.return_value = mock_path_inst
            
            save_requirements_sync_result(db, mock_req, result)
            
            # 검증: write_text가 호출되었는지
            assert mock_path_inst.write_text.called
            args, _ = mock_path_inst.write_text.call_args
            assert "# E2E Requirements" in args[0]

    def test_e2e_scheduled_worker_03_30_fires(self, db):
        """R: 03:30 스케줄러 → 미생성 category 일괄 처리 확인"""
        worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
        worker.name = "e2e_scheduled"

        # 1. 조건 충족하는 category 생성 (5개 이상)
        for i in range(5):
            db.add(PlanRecord(
                filename_hash=f"sched_{i}",
                file_path=f"file_{i}.md",
                category="sched-cat",
                summary="sum",
                llm_processed_at=datetime.now(),
                archived_at=datetime.now(),
            ))
        db.commit()

        # 2. 현재 시간 mock (03:30)
        now_mock = datetime(2026, 3, 9, 3, 30)
        with patch("app.worker.scheduled_worker.datetime") as mock_datetime:
            mock_datetime.now.return_value = now_mock
            mock_datetime.date.return_value = now_mock.date()
            
            with patch("app.worker.scheduled_worker.SessionLocal", return_value=db):
                # Act
                worker._check_requirements_sync_schedule()
                
                # Assert: LLMRequest 생성 확인
                req = db.query(LLMRequest).filter_by(
                    caller_type="plan_requirements_sync",
                    caller_id="sched-cat"
                ).first()
                assert req is not None

    def test_e2e_scheduled_worker_no_double_run_same_day(self, db):
        """B: 같은 날 2회 호출 → 1회만 실행"""
        worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
        worker.name = "e2e_scheduled"

        for i in range(5):
            db.add(PlanRecord(
                filename_hash=f"double_{i}",
                file_path=f"file_{i}.md",
                category="double-cat",
                summary="sum",
                llm_processed_at=datetime.now(),
                archived_at=datetime.now(),
            ))
        db.commit()

        now_mock = datetime(2026, 3, 9, 3, 30)
        with patch("app.worker.scheduled_worker.datetime") as mock_datetime:
            mock_datetime.now.return_value = now_mock
            mock_datetime.date.return_value = now_mock.date()
            
            with patch("app.worker.scheduled_worker.SessionLocal", return_value=db):
                # 1차 실행
                worker._check_requirements_sync_schedule()
                assert db.query(LLMRequest).filter_by(caller_id="double-cat").count() == 1
                
                # 2차 실행 (같은 날)
                worker._check_requirements_sync_schedule()
                # 갯수 그대로 1개여야 함
                assert db.query(LLMRequest).filter_by(caller_id="double-cat").count() == 1


class TestRecurrenceDetectionE2E:
    """반복 감지 전체 흐름 E2E 테스트"""

    def test_e2e_right_two_plans_same_scope_triggers_recurrence_check(self, db):
        """R: scope 겹치는 plan 2개 archive mock → detect_recurrence 호출 확인 + LLM 큐 등록 확인"""
        from app.modules.claude_worker.services.plan_analyze_handler import detect_recurrence
        import json

        # Arrange: 기존 plan (scope 겹침)
        existing = PlanRecord(
            filename_hash="existing_e2e_hash",
            file_path="/path/existing.md",
            category="naver-booking",
            scope=json.dumps(["plan_service.py", "routes.py"]),
            applied_at=datetime.now() - timedelta(days=30),
            intent="기존 버그 수정",
            plan_date=(datetime.now() - timedelta(days=30)).date(),
        )
        db.add(existing)
        db.commit()

        # 현재 plan
        current = PlanRecord(
            filename_hash="current_e2e_hash",
            file_path="/path/current.md",
            category="naver-booking",
            scope=json.dumps(["plan_service.py", "new_feature.py"]),
            intent="동일 모듈 재수정",
            plan_date=datetime.now().date(),
        )
        db.add(current)
        db.commit()

        # Act
        result = detect_recurrence(db, current)

        # Assert: LLM 큐 등록됨
        assert result is True
        req = db.query(LLMRequest).filter_by(
            caller_type="plan_recurrence_check",
            caller_id="current_e2e_hash"
        ).first()
        assert req is not None
        assert "plan_service.py" in req.prompt

    def test_e2e_right_second_plan_linked_after_llm_result(self, db):
        """R: save_recurrence_check_result 호출 → record.superseded_by + recurrence_count=2 설정 확인"""
        from app.modules.claude_worker.services.plan_analyze_handler import save_recurrence_check_result

        # Arrange
        first_plan = PlanRecord(
            filename_hash="first_e2e_plan",
            file_path="/path/first.md",
            category="naver-booking",
            recurrence_count=1,
        )
        second_plan = PlanRecord(
            filename_hash="second_e2e_plan",
            file_path="/path/second.md",
            category="naver-booking",
            recurrence_count=1,
        )
        db.add(first_plan)
        db.add(second_plan)
        db.commit()

        # LLM 결과 mock
        req = MagicMock()
        req.caller_id = "second_e2e_plan"
        result = {"result": {
            "is_recurrence": True,
            "matched_hash": "first_e2e_plan",
            "confidence": "high",
            "reason": "same bug pattern"
        }}

        # Act
        save_recurrence_check_result(db, req, result)

        # Assert
        db.expire_all()
        updated = db.query(PlanRecord).filter_by(filename_hash="second_e2e_plan").first()
        assert updated.superseded_by == "first_e2e_plan"
        assert updated.recurrence_count == 2

    def test_e2e_boundary_no_scope_skips_detection(self, db):
        """B: scope=None인 plan archive → detect_recurrence 호출 안 됨"""
        from app.modules.claude_worker.services.plan_analyze_handler import detect_recurrence

        # scope=None인 plan
        no_scope_plan = PlanRecord(
            filename_hash="no_scope_e2e",
            file_path="/path/no_scope.md",
            category="naver-booking",
            scope=None,
            intent="some intent",
        )
        db.add(no_scope_plan)
        db.commit()

        # Act: save_plan_archive_result 내부 로직 중 "intent and scope" 조건 검증
        # detect_recurrence는 scope가 None이면 candidates=[] → False 반환
        result = detect_recurrence(db, no_scope_plan)

        # Assert: scope=None → 빈 scope로 처리 → candidates 없음 → False
        assert result is False
        # LLM 큐 미등록
        req = db.query(LLMRequest).filter_by(
            caller_type="plan_recurrence_check",
            caller_id="no_scope_e2e"
        ).first()
        assert req is None
