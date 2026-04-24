"""
Phase T3/T4: plan_archive_analyze / plan_requirements_sync E2E 테스트

DB-driven dispatch 흐름 검증:
- in-memory SQLite에 task_schedules INSERT
- _dispatch_scheduled_runs() 경로 진입 확인
- task_schedule_runs 레코드 생성 확인
- _check_plan_archive_schedule 메서드 부재 확인

Phase T4 (TestIntentExtractionE2E):
- archive → intent/scope 저장 전체 흐름 E2E 검증
"""
import ast
import asyncio
import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SCHEDULED_WORKER_PATH = Path(__file__).resolve().parents[2] / "app" / "worker" / "scheduled_worker.py"


class TestPlanArchiveE2E:
    """Registry-based plan archive dispatch tests."""

    def test_registry_includes_plan_archive_and_devguide_handlers(self):
        from app.models.task_schedule import TaskSchedule
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
        targets = {handler.target_type for handler in worker._handlers}

        assert TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE in targets
        assert TaskSchedule.TARGET_TYPE_DEVGUIDE_STALENESS in targets

    @pytest.mark.asyncio
    async def test_dispatch_claims_plan_archive_from_registry(self):
        from app.models.task_schedule import TaskSchedule
        from app.modules.dev_runner.schedulers.plan_archive_schedule import PlanArchiveScheduler
        from app.worker.schedule_handler_base import ClaimedRun
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
        handler = PlanArchiveScheduler()
        schedule = MagicMock(id=1)
        claimed = ClaimedRun(run=MagicMock(id=10), task_name="plan_archive_analyze_1_run_10")
        db = MagicMock()
        svc = MagicMock()
        svc.get_schedules_by_type.side_effect = lambda target_type, enabled_only=True: (
            [schedule] if target_type == TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE else []
        )

        with patch.object(handler, "claim_run", return_value=claimed), patch(
            "app.worker.scheduled_worker.SessionLocal",
            return_value=db,
        ), patch(
            "app.worker.scheduled_worker.TaskScheduleService",
            return_value=svc,
        ):
            worker._handlers = [handler]
            worker._schedule_claimed_run = AsyncMock()
            await worker._dispatch_scheduled_runs()

        worker._schedule_claimed_run.assert_awaited_once_with(handler, schedule, claimed)


# ──────────────────────────────────────────────────────────────
# Phase T4: archive → intent/scope 저장 전체 흐름 E2E 검증
# ──────────────────────────────────────────────────────────────

def _make_in_memory_db_e2e():
    """테스트용 in-memory SQLite DB 세션 반환."""
    from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa: F401
    from app.models.base import Base
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


class TestIntentExtractionE2E:
    """archive → intent/scope 저장 전체 흐름 E2E 검증 (Phase T4)."""

    def _make_record(self, db, filename_hash="e2e_hash_001"):
        """테스트용 PlanRecord 생성."""
        from app.models.plan_record import PlanRecord
        record = PlanRecord(
            filename_hash=filename_hash,
            file_path=f"/fake/plan/{filename_hash}.md",
            project="monitor-page",
            title="E2E 테스트 계획서",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def test_e2e_intent_fields_saved_after_llm_result(self):
        """R: mock LLM 결과(intent/trigger/scope 포함) → save_plan_archive_result 호출 → DB에 3개 필드 저장 확인."""
        from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result
        from app.models.plan_record import PlanRecord

        db = _make_in_memory_db_e2e()
        record = self._make_record(db)

        request = MagicMock()
        request.caller_id = record.filename_hash

        llm_result = {
            "result": {
                "category": "naver-booking",
                "tags": ["feat"],
                "summary": "E2E 요약",
                "intent": "네이버 예약 슬롯 스나이핑 기능 추가",
                "trigger": "new_feature",
                "scope": ["naver-booking", "worker", "plan_archive_listener"],
            }
        }
        save_plan_archive_result(db, request, llm_result)

        db.refresh(record)

        # intent/trigger/scope 저장 확인
        assert record.intent == "네이버 예약 슬롯 스나이핑 기능 추가", "intent 저장 확인"
        assert record.trigger == "new_feature", "trigger 저장 확인"
        assert record.scope is not None, "scope 저장 확인"
        scope_parsed = json.loads(record.scope)
        assert "naver-booking" in scope_parsed
        assert "worker" in scope_parsed

        # 기존 필드도 함께 저장됐는지 확인 (회귀 없음)
        assert record.category == "naver-booking", "category 저장 회귀 없음"
        assert record.summary == "E2E 요약", "summary 저장 회귀 없음"

    def test_e2e_plan_date_extracted_via_git(self):
        """R: git tracked 파일 archive → plan_date 자동 설정 확인 (전체 흐름 통합)."""
        from app.worker.plan_archive_listener import get_git_first_commit_date
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService

        db = _make_in_memory_db_e2e()

        # git tracked 파일 사용
        tracked_file = str(
            Path(__file__).resolve().parents[2] / "app" / "worker" / "plan_archive_listener.py"
        )

        # PlanRecordService.get_or_create → plan_date 설정 흐름 재현
        svc = PlanRecordService(db)
        record = svc.get_or_create(file_path=tracked_file)

        if record.plan_date is None:
            record.plan_date = get_git_first_commit_date(tracked_file)
        db.commit()
        db.refresh(record)

        assert record.plan_date is not None, "git tracked 파일은 plan_date가 설정되어야 함"
        assert isinstance(record.plan_date, date), f"date 타입이어야 함, 실제: {type(record.plan_date)}"


# ──────────────────────────────────────────────────────────────
# Phase T4: queue_archived_plans.main() 진입점 E2E 검증
# ──────────────────────────────────────────────────────────────

class TestQueueScriptE2E:
    """T4: queue_archived_plans.main() DB-first + skip 검증."""

    def _make_db_and_seed(self):
        import hashlib
        from datetime import datetime
        from app.models.base import Base
        from app.models.plan_record import PlanRecord
        from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        raw = "# DB 원본 계획서\n이 내용이 LLM 분석 대상"
        h1 = hashlib.sha256(Path("/archive/2026-01-01_has-content.md").name.encode()).hexdigest()
        from app.models.plan_record import PlanRecord as PR
        db.add(PR(
            filename_hash=h1, file_path="/archive/2026-01-01_has-content.md",
            raw_content=raw, archived_at=datetime(2026, 1, 1), llm_processed_at=None,
        ))

        h2 = hashlib.sha256(Path("/nonexistent/2026-01-02_no-content.md").name.encode()).hexdigest()
        db.add(PR(
            filename_hash=h2, file_path="/nonexistent/2026-01-02_no-content.md",
            raw_content=None, archived_at=datetime(2026, 1, 1), llm_processed_at=None,
        ))
        db.commit()
        return db

    def test_queue_script_e2e_raw_content_and_skip(self, capsys):
        """E2E: raw_content 있는 record는 LLMRequest 생성, 없고 파일도 없으면 SKIP."""
        import sys as _sys
        import importlib

        db = self._make_db_and_seed()
        mock_session = MagicMock(wraps=db)
        mock_session.close = MagicMock()

        project_root = Path(__file__).resolve().parents[2]
        scripts_path = str(project_root / "scripts" / "plan_runner")
        if scripts_path not in _sys.path:
            _sys.path.insert(0, scripts_path)

        import queue_archived_plans
        importlib.reload(queue_archived_plans)

        with patch.object(_sys, "argv", ["queue_archived_plans.py"]):
            with patch("queue_archived_plans.SessionLocal", return_value=mock_session):
                queue_archived_plans.main()

        captured = capsys.readouterr()
        assert "[SKIP] 내용 없음" in captured.out
        assert "INSERT: 1" in captured.out

        from app.modules.claude_worker.models.llm_request import LLMRequest
        reqs = db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").all()
        assert len(reqs) == 1
        assert "DB 원본 계획서" in reqs[0].prompt
        assert "2026-01-01_has-content.md" in reqs[0].prompt
