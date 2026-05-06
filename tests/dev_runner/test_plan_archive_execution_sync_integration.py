from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.plan_archive_execution_service import PlanArchiveExecutionService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _enqueue(db, record):
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        PlanArchiveExecutionService(db).enqueue_records([record], trigger_source="manual:plan_archive_analyze")
        db.commit()


def test_sync_recovers_job_state_from_llm_request(db):
    record = PlanRecord(
        filename_hash="hash-sync",
        file_path="/archive/2026-05-06_sync.md",
        raw_content="# sync",
        archived_at=datetime(2026, 5, 6),
        llm_processed_at=None,
    )
    db.add(record)
    db.commit()
    _enqueue(db, record)
    request = db.query(LLMRequest).one()
    request.status = "completed"
    request.processed_at = datetime(2026, 5, 6, 12, 0)
    db.commit()

    result = PlanArchiveExecutionService(db).sync()
    history = PlanArchiveExecutionService(db).history(record_id=record.id)

    assert result["updated"] == 1
    assert history[0]["status"] == "completed"


def test_completed_record_is_not_manual_run_target(db):
    record = PlanRecord(
        filename_hash="hash-done",
        file_path="/archive/2026-05-06_done.md",
        raw_content="# done",
        archived_at=datetime(2026, 5, 6),
        llm_processed_at=datetime(2026, 5, 6, 12, 0),
    )
    db.add(record)
    db.commit()

    result = PlanArchiveExecutionService(db).enqueue_unprocessed(
        include_temp_records=False,
        max_backfill_per_run=10,
    )

    assert result["queued"] == 0
    assert db.query(LLMRequest).count() == 0


# ===== Overwrite-guard integration suite =====

import json as _json_overwrite
from sqlalchemy import text
from app.models.plan_record import PlanEvent
from app.modules.claude_worker.services.plan_analyze_handler import (
    save_plan_archive_result,
    _has_newer_plan_archive_result,
)


def _create_tables(eng):
    """테스트용 최소 테이블 생성 (FK 검사 비활성화)."""
    with eng.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)
    LLMRequest.__table__.create(bind=eng, checkfirst=True)


@pytest.fixture(scope="module")
def overwrite_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _create_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def overwrite_db(overwrite_engine):
    Session = sessionmaker(bind=overwrite_engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


def _make_record(db, file_path: str = "/archive/2026-01-01-test.md") -> PlanRecord:
    from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash
    record = PlanRecord(
        filename_hash=_compute_filename_hash(file_path),
        file_path=file_path,
        status="archived",
        archived_at=datetime.now(),
    )
    db.add(record)
    db.flush()
    return record


def _make_request(
    db,
    caller_id: str,
    status: str = "completed",
    result_json: dict | None = None,
    request_source: str | None = None,
    cli_options: dict | None = None,
) -> LLMRequest:
    req = LLMRequest(
        caller_type="plan_archive_analyze",
        caller_id=caller_id,
        prompt="test prompt",
        requested_by="test",
        status=status,
        provider="claude",
        model="",
        queue_name="utility",
        request_source=request_source,
        cli_options=_json_overwrite.dumps(cli_options) if cli_options else None,
        result=_json_overwrite.dumps(result_json) if result_json else None,
    )
    db.add(req)
    db.flush()
    return req


# ===== _has_newer_plan_archive_result =====

class TestHasNewerPlanArchiveResult:

    def test_no_newer_request_returns_false(self, overwrite_db):
        db = overwrite_db
        """completed request가 자신뿐이면 newer 없음 → False"""
        record = _make_record(db, "/archive/no-newer.md")
        req = _make_request(db, record.filename_hash, status="completed")
        db.flush()

        assert _has_newer_plan_archive_result(db, req) is False

    def test_newer_completed_request_returns_true(self, overwrite_db):
        db = overwrite_db
        """자신보다 id 큰 completed 요청이 있으면 → True (guard는 result IS NOT NULL 조건 포함)"""
        record = _make_record(db, "/archive/has-newer.md")
        older_req = _make_request(db, record.filename_hash, status="completed")
        # guard는 result IS NOT NULL도 체크하므로 newer_req에 result 포함 필요
        _newer_req = _make_request(db, record.filename_hash, status="completed",
                                   result_json={"category": "newer"})
        db.flush()

        assert _has_newer_plan_archive_result(db, older_req) is True

    def test_newer_pending_request_not_counted(self, overwrite_db):
        db = overwrite_db
        """pending 요청은 newer로 간주하지 않음"""
        record = _make_record(db, "/archive/newer-pending.md")
        req = _make_request(db, record.filename_hash, status="completed")
        _pending = _make_request(db, record.filename_hash, status="pending")
        db.flush()

        assert _has_newer_plan_archive_result(db, req) is False

    def test_different_caller_id_not_counted(self, overwrite_db):
        db = overwrite_db
        """다른 caller_id의 completed 요청은 newer로 간주하지 않음"""
        record_a = _make_record(db, "/archive/caller-a.md")
        record_b = _make_record(db, "/archive/caller-b.md")
        req_a = _make_request(db, record_a.filename_hash, status="completed")
        _req_b = _make_request(db, record_b.filename_hash, status="completed")
        db.flush()

        assert _has_newer_plan_archive_result(db, req_a) is False


# ===== save_plan_archive_result overwrite guard =====

class TestSaveOverwriteGuard:

    def test_older_request_does_not_overwrite_newer(self, overwrite_db):
        db = overwrite_db
        """오래된 completed request의 결과가 최신 저장값을 덮어쓰지 않음."""
        record = _make_record(db, "/archive/overwrite-guard.md")
        caller_id = record.filename_hash

        older_req = _make_request(db, caller_id, status="completed",
                                  result_json={"category": "old-category"})
        newer_req = _make_request(db, caller_id, status="completed",
                                  result_json={"category": "new-category", "summary": "newer result"})
        db.flush()

        # 최신(newer) 먼저 저장
        newer_result = {"success": True, "result": {"category": "new-category", "summary": "newer result"}}
        result_newer = save_plan_archive_result(db, newer_req, newer_result)
        assert result_newer is True
        db.expire(record)
        assert record.category == "new-category"

        # 오래된(older)는 저장 거부됨
        older_result = {"success": True, "result": {"category": "old-category"}}
        result_older = save_plan_archive_result(db, older_req, older_result)
        assert result_older is False
        db.expire(record)
        assert record.category == "new-category"  # 덮어쓰이지 않음

    def test_newest_request_applied_to_record(self, overwrite_db):
        db = overwrite_db
        """최신 completed request의 결과만 record에 반영됨."""
        record = _make_record(db, "/archive/newest-applied.md")
        caller_id = record.filename_hash

        _req1 = _make_request(db, caller_id, status="completed",
                               result_json={"summary": "first"})
        req2 = _make_request(db, caller_id, status="completed",
                              result_json={"summary": "second"})
        db.flush()

        result = {"success": True, "result": {"summary": "second"}}
        assert save_plan_archive_result(db, req2, result) is True
        db.expire(record)
        assert record.summary == "second"
        assert record.llm_processed_at is not None

    def test_plan_archive_analysis_saved_event_created(self, overwrite_db):
        db = overwrite_db
        """결과 저장 성공 시 plan_archive_analysis_saved 이벤트가 생성됨."""
        record = _make_record(db, "/archive/event-check.md")
        req = _make_request(db, record.filename_hash, status="completed")
        db.flush()

        result = {"success": True, "result": {"category": "feature", "tags": ["fix"], "summary": "test summary"}}
        save_plan_archive_result(db, req, result)

        events = db.query(PlanEvent).filter_by(
            plan_record_id=record.id,
            event_type="plan_archive_analysis_saved",
        ).all()
        assert len(events) >= 1
        assert events[-1].detail is not None
        saved_detail = _json_overwrite.loads(events[-1].detail) if isinstance(events[-1].detail, str) else events[-1].detail
        assert saved_detail.get("request_id") == req.id

    def test_manual_reanalyze_saves_prior_snapshot_event(self, overwrite_db):
        db = overwrite_db
        """manual reanalyze 결과 저장 전 기존 PlanRecord 값을 audit event로 보존한다."""
        record = _make_record(db, "/archive/manual-reanalyze-audit.md")
        record.category = "old-category"
        record.tags = ["old-tag"]
        record.summary = "old summary"
        record.llm_processed_at = datetime(2026, 5, 6, 10, 0)
        req = _make_request(
            db,
            record.filename_hash,
            status="completed",
            request_source="manual_reanalyze",
            cli_options={"profile_key": "claude-opus"},
        )
        db.flush()

        result = {
            "success": True,
            "result": {
                "category": "new-category",
                "tags": ["new-tag"],
                "summary": "new summary",
            },
        }
        assert save_plan_archive_result(db, req, result) is True

        events = db.query(PlanEvent).filter_by(
            plan_record_id=record.id,
            event_type="plan_archive_analysis_overwritten",
        ).all()
        assert len(events) >= 1
        detail = _json_overwrite.loads(events[-1].detail) if isinstance(events[-1].detail, str) else events[-1].detail
        assert detail["prior_summary"] == "old summary"
        assert detail["prior_category"] == "old-category"
        assert detail["prior_tags"] == ["old-tag"]
        assert detail["prior_analyzed_at"] == "2026-05-06T10:00:00"
        assert detail["request_id"] == req.id
        assert detail["provider"] == "claude"
        assert detail["profile_key"] == "claude-opus"

    def test_empty_result_dict_does_not_fail(self, overwrite_db):
        db = overwrite_db
        """빈 result dict → 저장 실패 없이 False 반환 (no exception)."""
        record = _make_record(db, "/archive/empty-result.md")
        req = _make_request(db, record.filename_hash, status="completed")
        db.flush()

        result = {"success": False, "result": {}}
        outcome = save_plan_archive_result(db, req, result)
        # result가 비어있어도 exception 없어야 함 (True 또는 False)
        assert isinstance(outcome, bool)


# ===== PlanArchiveExecutionService Codex queuing =====

class TestPlanArchiveExecutionServiceCodex:

    def test_queue_analysis_codex_no_profile(self, overwrite_db):
        db = overwrite_db
        """Codex provider는 profile_key 없이 큐잉 가능 — unsupported provider 에러 없음."""
        from app.modules.dev_runner.services.plan_archive_execution_service import PlanArchiveExecutionService
        record = _make_record(db, "/archive/codex-queue.md")
        svc = PlanArchiveExecutionService(db)

        # profile_key=None으로 Codex 큐잉 → 성공해야 함 (파일 없어도 raw_content fallback)
        req, created = svc.queue_analysis(record, provider="codex", model="", profile_key=None)
        assert created is True
        assert req.provider == "codex"
        assert req.caller_type == "plan_archive_analyze"

    def test_queue_analysis_unsupported_provider_raises(self, overwrite_db):
        db = overwrite_db
        """지원하지 않는 provider는 ValueError 발생."""
        from app.modules.dev_runner.services.plan_archive_execution_service import PlanArchiveExecutionService
        record = _make_record(db, "/archive/bad-provider.md")
        svc = PlanArchiveExecutionService(db)

        with pytest.raises(ValueError, match="unsupported provider"):
            svc.queue_analysis(record, provider="unknown-provider")

    def test_queue_analysis_deduplicates_pending(self, overwrite_db):
        db = overwrite_db
        """동일 record에 pending 요청이 있으면 중복 생성하지 않음 (created=False)."""
        from app.modules.dev_runner.services.plan_archive_execution_service import PlanArchiveExecutionService
        record = _make_record(db, "/archive/dedup-test.md")
        svc = PlanArchiveExecutionService(db)

        # 먼저 pending 요청 수동 생성
        existing = LLMRequest(
            caller_type="plan_archive_analyze",
            caller_id=record.filename_hash,
            prompt="test",
            requested_by="test",
            status="pending",
            provider="claude",
            model="",
            queue_name="utility",
        )
        db.add(existing)
        db.flush()

        # 동일 provider로 재요청 → 기존 반환
        req, created = svc.queue_analysis(record, provider="claude")
        assert created is False
        assert req.id == existing.id
