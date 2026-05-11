"""Plan Records API HTTP 레벨 테스트 (Phase 6)

엔드포인트: /api/v1/plans/records, /api/v1/plans/events
TestClient 사용, test_db_session 픽스처로 격리
"""
import pytest
import base64
from unittest.mock import patch
from fastapi.testclient import TestClient


pytestmark = pytest.mark.http


@pytest.fixture(scope="module")
def test_db_engine(tmp_path_factory):
    """Plan records API 전용 SQLite 엔진.

    이 모듈은 plan_records/plan_events만 직접 검증하므로, 세션 범위 전체 모델
    create_all을 타지 않게 해서 전역 테스트 DB 부트스트랩 timeout을 피한다.
    """
    from sqlalchemy import create_engine, event
    from app.models.base import Base
    from app.models.plan_record import PlanEvent, PlanRecord
    from app.models.task_schedule import TaskSchedule, TaskScheduleRun
    from app.models.tracking_item import TrackingItem, TrackingItemPlanLink
    from app.modules.claude_worker.models.llm_request import LLMRequest
    from app.modules.writing.models.writing_batch import WritingBatch

    db_path = tmp_path_factory.mktemp("plan_records_api_db") / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        bind=engine,
        tables=[
            PlanRecord.__table__,
            PlanEvent.__table__,
            TrackingItem.__table__,
            TrackingItemPlanLink.__table__,
            WritingBatch.__table__,
            LLMRequest.__table__,
            TaskSchedule.__table__,
            TaskScheduleRun.__table__,
        ],
    )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def client(test_db_engine):
    """TestClient (module scope) + test_db_engine 오버라이드

    module scope: 모듈당 1회 TestClient 생성/소멸 → lifespan 반복 없음.
    get_db는 요청마다 engine에서 새 세션을 생성하여 반환.
    테스트 데이터는 test_db_session.commit() 후 클라이언트에서 조회 가능.
    """
    from app.main import app
    from app.database import get_db
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_record(session, path, **kwargs):
    from app.modules.dev_runner.services.plan_record_service import PlanRecordService
    svc = PlanRecordService(session)
    r = svc.get_or_create(path, **kwargs)
    session.flush()
    return r


def _clear_tracking(session):
    from app.models.tracking_item import TrackingItem, TrackingItemPlanLink

    session.query(TrackingItemPlanLink).delete()
    session.query(TrackingItem).delete()
    session.commit()


class TestPlanRecordsApiDbBootstrap:
    """Plan records API 전용 DB fixture 계약."""

    def test_plan_records_bootstrap_right_creates_required_tables(self, test_db_engine):
        from sqlalchemy import inspect

        tables = set(inspect(test_db_engine).get_table_names())

        assert "plan_records" in tables
        assert "plan_events" in tables
        assert "tracking_items" in tables
        assert "tracking_item_plan_links" in tables
        assert "writing_batches" in tables
        assert "llm_requests" in tables
        assert "task_schedules" in tables
        assert "task_schedule_runs" in tables

    def test_plan_records_bootstrap_B_keeps_retrieval_readiness_tables_missing(self, test_db_engine):
        from sqlalchemy import inspect

        tables = set(inspect(test_db_engine).get_table_names())

        assert "plan_record_file_refs" not in tables

    def test_plan_records_bootstrap_right_supports_event_fk(self, test_db_session):
        from app.models.plan_record import PlanEvent, PlanRecord

        record = PlanRecord(
            filename_hash="bootstrap_contract_001",
            file_path="/plan/2026-05-03-bootstrap-contract.md",
            title="Bootstrap Contract",
        )
        test_db_session.add(record)
        test_db_session.flush()

        event = PlanEvent(plan_record_id=record.id, event_type="created")
        test_db_session.add(event)
        test_db_session.commit()

        saved = test_db_session.query(PlanEvent).filter_by(id=event.id).one()
        assert saved.record.id == record.id


# ========== /api/v1/plans/records ==========

class TestListRecords:

    def test_list_records_empty(self, client):
        """빈 배열 반환"""
        resp = client.get("/api/v1/plans/records?project=__nonexistent_project__")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_records_with_pagination(self, client, test_db_session):
        """skip/limit 파라미터 정상 처리"""
        for i in range(5):
            _make_record(test_db_session, f"/plan/2026-03-{i+1:02d}-paging.md", project="paging_test")
        test_db_session.commit()

        resp = client.get("/api/v1/plans/records?project=paging_test&skip=0&limit=3")
        assert resp.status_code == 200
        assert len(resp.json()) <= 3

        resp2 = client.get("/api/v1/plans/records?project=paging_test&skip=3&limit=3")
        assert resp2.status_code == 200
        assert isinstance(resp2.json(), list)

    def test_list_records_filter_by_project(self, client, test_db_session):
        """project 필터"""
        _make_record(test_db_session, "/plan/2026-03-06-alpha.md", project="proj-alpha-http")
        _make_record(test_db_session, "/plan/2026-03-07-beta.md", project="proj-beta-http")
        test_db_session.commit()

        resp = client.get("/api/v1/plans/records?project=proj-alpha-http")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert all(r["project"] == "proj-alpha-http" for r in data)

    def test_list_records_filter_by_status(self, client, test_db_session):
        """status 필터"""
        r = _make_record(test_db_session, "/plan/2026-03-08-status.md")
        r.status = "구현중"
        test_db_session.commit()

        resp = client.get("/api/v1/plans/records?status=구현중")
        assert resp.status_code == 200
        data = resp.json()
        assert any(item["status"] == "구현중" for item in data)

    def test_get_archive_health_http_right_counts(self, client):
        """Plan Archive health HTTP contract exposes split backlog counts."""
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService

        expected = {
            "archived_total": 4,
            "llm_processed": 1,
            "llm_unprocessed": 3,
            "real_unprocessed": 2,
            "temp_pytest_total": 1,
            "temp_pytest_unprocessed": 1,
            "pending_or_processing_requests": 1,
            "failed_requests": 1,
            "file_retention_due": 2,
            "file_retention_scheduled": 3,
            "file_removed": 4,
            "oldest_file_delete_after": "2026-05-12T01:00:00",
            "latest_failed_request": {
                "id": 10,
                "caller_id": "failed_hash",
                "status": "failed",
                "error_message": "quota",
                "requested_at": "2026-05-05T01:00:00",
            },
            "oldest_unprocessed_at": "2026-05-04T01:00:00",
            "plan_archive_schedule": {
                "id": 3,
                "enabled": False,
                "schedule_value": "02:10",
                "last_run": None,
                "last_success": None,
                "last_failure": "2026-05-05T02:10:00",
            },
            "retrieval_db_readiness": {
                "ok": True,
                "required_tables": [
                    "plan_record_chunks",
                    "plan_record_file_refs",
                    "plan_record_repo_refs",
                    "plan_record_relations",
                    "plan_record_search_runs",
                ],
                "missing_tables": [],
            },
            "execution_db_readiness": {
                "ok": True,
                "required_tables": [
                    "plan_archive_execution_jobs",
                    "plan_archive_execution_attempts",
                    "llm_request_profile_claims",
                    "llm_profile_assignments",
                    "llm_schedule_profile_policies",
                ],
                "missing_tables": [],
            },
        }

        with patch.object(PlanRecordService, "get_plan_archive_health", return_value=expected):
            resp = client.get("/api/v1/plans/records/archive-health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["real_unprocessed"] == 2
        assert data["temp_pytest_unprocessed"] == 1
        assert data["pending_or_processing_requests"] == 1
        assert data["failed_requests"] == 1
        assert data["file_retention_due"] == 2
        assert data["file_retention_scheduled"] == 3
        assert data["file_removed"] == 4
        assert data["latest_failed_request"]["caller_id"] == "failed_hash"
        assert data["retrieval_db_readiness"]["ok"] is True
        assert data["execution_db_readiness"]["ok"] is True

    def test_archive_health_right_keeps_temp_counts_separate_after_purge(self, client):
        """R: purge 이후에도 archive-health temp/real split schema is stable."""
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService

        expected = {
            "archived_total": 1,
            "llm_processed": 0,
            "llm_unprocessed": 1,
            "real_unprocessed": 1,
            "temp_pytest_total": 0,
            "temp_pytest_unprocessed": 0,
            "pending_or_processing_requests": 0,
            "failed_requests": 0,
            "file_retention_due": 0,
            "file_retention_scheduled": 0,
            "file_removed": 0,
            "oldest_file_delete_after": None,
            "latest_failed_request": None,
            "oldest_unprocessed_at": "2026-05-04T01:00:00",
            "plan_archive_schedule": None,
            "retrieval_db_readiness": {
                "ok": False,
                "required_tables": [
                    "plan_record_chunks",
                    "plan_record_file_refs",
                    "plan_record_repo_refs",
                    "plan_record_relations",
                    "plan_record_search_runs",
                ],
                "missing_tables": ["plan_record_file_refs"],
            },
            "execution_db_readiness": {
                "ok": False,
                "required_tables": [
                    "plan_archive_execution_jobs",
                    "plan_archive_execution_attempts",
                    "llm_request_profile_claims",
                    "llm_profile_assignments",
                    "llm_schedule_profile_policies",
                ],
                "missing_tables": ["llm_schedule_profile_policies"],
            },
        }

        with patch.object(PlanRecordService, "get_plan_archive_health", return_value=expected):
            resp = client.get("/api/v1/plans/records/archive-health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["real_unprocessed"] == 1
        assert data["temp_pytest_total"] == 0
        assert data["temp_pytest_unprocessed"] == 0
        assert data["retrieval_db_readiness"]["missing_tables"] == ["plan_record_file_refs"]
        assert data["execution_db_readiness"]["missing_tables"] == ["llm_schedule_profile_policies"]

    def test_retrieval_search_http_error_missing_readiness(self, client):
        """E: retrieval search returns structured 503 when DB tables are missing."""
        resp = client.post("/api/v1/plans/retrieval/search", json={"q": "anything"})

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["retrieval_db_readiness"]["ok"] is False
        assert "plan_record_file_refs" in detail["retrieval_db_readiness"]["missing_tables"]


class TestGetRecord:

    def test_get_record_with_events(self, client, test_db_session):
        """특정 record + events 포함 반환"""
        r = _make_record(test_db_session, "/plan/2026-03-09-detail.md", title="HTTP Detail Plan")
        test_db_session.commit()

        resp = client.get(f"/api/v1/plans/records/{r.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == r.id
        assert data["title"] == "HTTP Detail Plan"
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_get_record_not_found(self, client):
        """존재하지 않는 id → 404"""
        resp = client.get("/api/v1/plans/records/99999")
        assert resp.status_code == 404

    def test_analyze_record_preview_success(self, client):
        """R: manual analyze preview endpoint returns service response."""
        expected = {
            "success": True,
            "mode": "preview",
            "result": {"category": "infra"},
            "raw_response": '{"category":"infra"}',
            "provider": "codex",
            "model": "gpt-5.2",
            "record_id": 1,
            "filename_hash": "hash",
            "file_path": "/archive/file.md",
            "elapsed_ms": 10,
            "prompt_preview": None,
            "warnings": [],
            "saved": False,
            "record_after": None,
            "save_error": None,
        }
        with patch(
            "app.modules.dev_runner.services.plan_archive_manual_analyze_service.PlanArchiveManualAnalyzeService.analyze",
            return_value=expected,
        ):
            resp = client.post("/api/v1/plans/records/1/analyze", json={"mode": "preview"})

        assert resp.status_code == 200
        assert resp.json()["result"]["category"] == "infra"
        assert resp.json()["saved"] is False

    def test_analyze_record_apply_success(self, client):
        """R: manual analyze apply endpoint returns saved record snapshot."""
        expected = {
            "success": True,
            "mode": "apply",
            "result": {"category": "infra"},
            "raw_response": '{"category":"infra"}',
            "provider": "codex",
            "model": "gpt-5.2",
            "record_id": 1,
            "filename_hash": "hash",
            "file_path": "/archive/file.md",
            "elapsed_ms": 10,
            "prompt_preview": None,
            "warnings": [],
            "saved": True,
            "record_after": {"category": "infra", "summary": "manual apply"},
            "save_error": None,
        }
        with patch(
            "app.modules.dev_runner.services.plan_archive_manual_analyze_service.PlanArchiveManualAnalyzeService.analyze",
            return_value=expected,
        ) as mock_analyze:
            resp = client.post("/api/v1/plans/records/1/analyze", json={"mode": "apply"})

        assert resp.status_code == 200
        assert resp.json()["saved"] is True
        assert resp.json()["record_after"]["summary"] == "manual apply"
        assert mock_analyze.call_args.kwargs["mode"] == "apply"

    def test_analyze_dry_run_rejects_apply(self, client):
        """E: analyze-dry-run alias remains preview-only."""
        resp = client.post("/api/v1/plans/records/1/analyze-dry-run", json={"mode": "apply"})

        assert resp.status_code == 400


class TestMemoUpdate:

    def test_memo_draft_save(self, client, test_db_session):
        """draft 저장 → memo_draft 갱신"""
        r = _make_record(test_db_session, "/plan/2026-03-10-draft.md")
        test_db_session.commit()

        resp = client.patch(
            f"/api/v1/plans/records/{r.id}/memo",
            json={"action": "draft", "text": "임시 저장 내용"}
        )
        assert resp.status_code == 200
        assert resp.json()["memo_draft"] == "임시 저장 내용"

    def test_memo_confirm(self, client, test_db_session):
        """memo 확정 → memo 갱신, memo_draft 초기화"""
        r = _make_record(test_db_session, "/plan/2026-03-11-confirm.md")
        r.memo_draft = "확정할 내용"
        test_db_session.commit()

        resp = client.patch(
            f"/api/v1/plans/records/{r.id}/memo",
            json={"action": "confirm"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["memo"] == "확정할 내용"
        assert data["memo_draft"] is None

    def test_memo_rollback(self, client, test_db_session):
        """롤백 → memo_draft를 확정 memo로 되돌림"""
        r = _make_record(test_db_session, "/plan/2026-03-12-rollback.md")
        r.memo = "확정 memo"
        r.memo_draft = "미확정"
        test_db_session.commit()

        resp = client.patch(
            f"/api/v1/plans/records/{r.id}/memo",
            json={"action": "rollback"}
        )
        assert resp.status_code == 200
        assert resp.json()["memo_draft"] == "확정 memo"

    def test_memo_invalid_action(self, client, test_db_session):
        """잘못된 action → 400"""
        r = _make_record(test_db_session, "/plan/2026-03-13-invalid.md")
        test_db_session.commit()

        resp = client.patch(
            f"/api/v1/plans/records/{r.id}/memo",
            json={"action": "invalid_action"}
        )
        assert resp.status_code == 400

    def test_memo_record_not_found(self, client):
        """존재하지 않는 record → 404"""
        resp = client.patch(
            "/api/v1/plans/records/99999/memo",
            json={"action": "draft", "text": "test"}
        )
        assert resp.status_code == 404


class TestSyncEndpoint:

    def test_sync_endpoint(self, client):
        """동기화 엔드포인트 → 정상 응답"""
        mock_svc_paths = []
        with patch(
            "app.modules.dev_runner.routes.plan_records._plan_service.list_registered_paths",
            return_value=mock_svc_paths
        ):
            resp = client.post("/api/v1/plans/records/sync")

        assert resp.status_code == 200
        data = resp.json()
        assert "created" in data
        assert "updated" in data
        assert "missing" in data
        assert "archive_created" in data
        assert "archive_normalized" in data
        assert "wait_tracking_created" in data
        assert "wait_tracking_updated" in data
        assert "wait_tracking_skipped" in data

    def test_sync_endpoint_returns_wait_tracking_counts_and_links(self, client, test_db_session, tmp_path):
        """records sync가 예약대기 plan을 TrackingItem으로 자동 연결한다."""
        from app.models.tracking_item import TrackingItem, TrackingItemPlanLink

        _clear_tracking(test_db_session)
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()
        plan_path = plan_dir / "2026-05-11_http-waiting-plan.md"
        plan_path.write_text(
            "\n".join(
                [
                    "# HTTP 예약대기",
                    "> 상태: 예약대기",
                    "> 검토 예정일: 2026-06-07",
                    "> 요약: sync endpoint coverage",
                ]
            ),
            encoding="utf-8",
        )

        registered = [type("RegisteredPath", (), {"path": str(plan_dir), "path_type": "plan"})()]
        with patch(
            "app.modules.dev_runner.routes.plan_records._plan_service.list_registered_paths",
            return_value=registered,
        ):
            resp = client.post("/api/v1/plans/records/sync")

        assert resp.status_code == 200
        data = resp.json()
        assert data["wait_tracking_created"] == 1
        assert data["wait_tracking_updated"] == 0
        assert data["wait_tracking_skipped"] == 0
        item = test_db_session.query(TrackingItem).one()
        link = test_db_session.query(TrackingItemPlanLink).one()
        assert item.title == "예약대기 plan: HTTP 예약대기"
        assert link.tracking_item_id == item.id

    def test_status_patch_reserved_upserts_wait_tracking(self, client, test_db_session, tmp_path):
        """status mutation 경계에서만 예약대기 TrackingItem을 만든다."""
        from app.models.tracking_item import TrackingItem

        _clear_tracking(test_db_session)
        plan_path = tmp_path / "2026-05-11_status-waiting-plan.md"
        plan_path.write_text(
            "\n".join(
                [
                    "# Status 예약대기",
                    "> 상태: 초안",
                    "> 검토 예정일: 2026-06-07",
                ]
            ),
            encoding="utf-8",
        )
        encoded = base64.urlsafe_b64encode(str(plan_path).encode("utf-8")).decode("ascii").rstrip("=")

        with patch("app.modules.dev_runner.routes.plans.plan_service.validate_path", return_value=True), patch(
            "app.modules.dev_runner.routes.plans.plan_service.list_plans",
            return_value=[],
        ):
            resp = client.patch(
                f"/api/v1/dev-runner/plans/{encoded}/status",
                json={"status": "예약대기"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["wait_tracking"]["action"] == "created"
        assert test_db_session.query(TrackingItem).count() == 1

    def test_status_patch_non_waiting_does_not_write_tracking(self, client, test_db_session, tmp_path):
        """예약대기가 아닌 status mutation은 wait tracking upsert를 건너뛴다."""
        from app.models.tracking_item import TrackingItem

        _clear_tracking(test_db_session)
        plan_path = tmp_path / "2026-05-11_status-active-plan.md"
        plan_path.write_text("# Status active\n> 상태: 초안\n> 검토 예정일: 2026-06-07\n", encoding="utf-8")
        encoded = base64.urlsafe_b64encode(str(plan_path).encode("utf-8")).decode("ascii").rstrip("=")

        with patch("app.modules.dev_runner.routes.plans.plan_service.validate_path", return_value=True), patch(
            "app.modules.dev_runner.routes.plans.plan_service.list_plans",
            return_value=[],
        ):
            resp = client.patch(
                f"/api/v1/dev-runner/plans/{encoded}/status",
                json={"status": "구현중"},
            )

        assert resp.status_code == 200
        assert resp.json()["wait_tracking"] == {"action": "skipped", "reason": "not_waiting_status"}
        assert test_db_session.query(TrackingItem).count() == 0

    def test_archive_candidates_endpoint(self, client, tmp_path):
        """archive 후보 엔드포인트 → 파일/DB 후보 요약 반환"""
        archive_dir = tmp_path / "archive" / "common"
        archive_dir.mkdir(parents=True)
        (archive_dir / "2026-05-06_http-archive-candidate.md").write_text("# HTTP Candidate\n", encoding="utf-8")

        registered = [type("RegisteredPath", (), {"path": str(tmp_path / "archive"), "path_type": "archive"})()]
        with patch(
            "app.modules.dev_runner.routes.plan_records._plan_service.list_registered_paths",
            return_value=registered,
        ):
            resp = client.get("/api/v1/plans/records/archive-candidates?include_temp=true")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert data["file_only"] >= 1
        assert len(data["candidates"]) >= 1

    def test_queue_archive_analyze_accepts_codex_without_profile(self, client, test_db_session):
        """profile 없는 Codex target으로 archive 분석 요청을 큐잉할 수 있다."""
        from datetime import datetime
        from app.models.plan_record import PlanRecord

        record = PlanRecord(
            filename_hash="http_codex_archive_analyze_001",
            file_path="/archive/common/2026-05-06_http-codex-archive-analyze.md",
            project="common",
            status="archived",
            archived_at=datetime.now(),
            raw_content="# Codex Archive Analyze\n",
        )
        test_db_session.add(record)
        test_db_session.commit()
        test_db_session.refresh(record)

        resp = client.post(
            f"/api/v1/plans/records/archive-analyze/{record.id}",
            json={"provider": "codex", "model": "gpt-5.5"},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["caller_type"] == "plan_archive_analyze"
        assert data["caller_id"] == record.filename_hash
        assert data["provider"] == "codex"
        assert data["model"] == "gpt-5.5"
        assert data["profile_key"] is None


# ========== /api/v1/plans/events ==========

class TestListEvents:

    def test_list_events_empty(self, client):
        """이벤트 없으면 빈 배열"""
        resp = client.get("/api/v1/plans/events?event_type=__nonexistent_type_xyz__")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_events_with_filters(self, client, test_db_session):
        """event_type 필터 동작"""
        _make_record(test_db_session, "/plan/2026-03-14-event.md")
        test_db_session.commit()

        resp = client.get("/api/v1/plans/events?event_type=created")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert all(e["event_type"] == "created" for e in data)

    def test_list_events_pagination(self, client):
        """skip/limit 파라미터 정상 처리"""
        resp = client.get("/api/v1/plans/events?skip=0&limit=10")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ========== /api/v1/plans/records/by-path ==========

class TestGetRecordByPath:

    def test_get_or_create_by_path(self, client):
        """file_path로 get_or_create → 레코드 반환"""
        resp = client.get("/api/v1/plans/records/by-path?file_path=/plan/2026-03-15-by-path.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_path"] == "/plan/2026-03-15-by-path.md"
        assert data["id"] is not None


# ========== /api/v1/plans/records/ingest ==========

class TestIngestSingleRecord:

    def test_ingest_single_updates_existing_record_archive_path_http(self, client, test_db_session):
        """POST /records/ingest updates existing filename-hash record to archive path."""
        from app.models.plan_record import PlanRecord
        from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash

        plan_path = "/workspace/docs/plan/2026-05-03_http-archive-path.md"
        archive_path = "/workspace/docs/archive/2026-05-03_http-archive-path.md"
        filename_hash = _compute_filename_hash(plan_path)
        test_db_session.query(PlanRecord).filter_by(filename_hash=filename_hash).delete(synchronize_session=False)
        test_db_session.commit()

        record = PlanRecord(
            filename_hash=filename_hash,
            file_path=plan_path,
            title="Old HTTP Plan",
            project="monitor-page",
            status="planned",
            raw_content="# Old HTTP Plan",
        )
        test_db_session.add(record)
        test_db_session.commit()

        resp = client.post(
            "/api/v1/plans/records/ingest",
            json={
                "file_path": archive_path,
                "project": "monitor-page",
                "raw_content": "# Archived HTTP Plan\n\nnew body",
                "title": "Archived HTTP Plan",
                "status": "archived",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == record.id
        assert data["filename_hash"] == filename_hash
        assert data["file_path"] == archive_path
        assert data["file_path"] != plan_path

        content_resp = client.get(f"/api/v1/plans/records/{record.id}/content")
        assert content_resp.status_code == 200
        assert content_resp.json()["raw_content"] == "# Archived HTTP Plan\n\nnew body"


# ========== Phase T4: import-archived + category/tags 필터 ==========

class TestImportArchived:

    def test_import_archived_endpoint(self, client, tmp_path):
        """POST /api/v1/plans/records/import-archived → 200 + created/updated/... 응답"""
        d = tmp_path / "archive" / "naver-booking"
        d.mkdir(parents=True)
        (d / "2026-02-01_t4-plan-a.md").write_text("# T4 Plan A\ncontent", encoding="utf-8")
        (d / "2026-02-02_t4-plan-b.md").write_text("# T4 Plan B\ncontent", encoding="utf-8")

        resp = client.post(
            f"/api/v1/plans/records/import-archived?archive_dir={tmp_path / 'archive'}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "created" in data
        assert "updated" in data
        assert "skipped" in data
        assert "errors" in data
        assert data["created"] >= 2

    def test_import_archived_no_dir(self, client, tmp_path):
        """POST /api/v1/plans/records/import-archived (존재하지 않는 경로) → 200 + errors 포함"""
        resp = client.post(
            "/api/v1/plans/records/import-archived?archive_dir=/nonexistent/path/archive"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" in data
        assert data["created"] == 0

    def test_list_records_category_filter_http(self, client, test_db_session):
        """GET /api/v1/plans/records?category=instagram → 해당 카테고리만 반환"""
        from app.models.plan_record import PlanRecord
        from datetime import datetime
        test_db_session.query(PlanRecord).filter_by(filename_hash="t4_instagram_001").delete(synchronize_session=False)
        test_db_session.commit()
        r = PlanRecord(
            filename_hash="t4_instagram_001",
            file_path="/archive/instagram/2026-02-10_t4-insta.md",
            project="instagram",
            category="instagram",
            archived_at=datetime.now(),
            status="archived",
        )
        test_db_session.add(r)
        test_db_session.commit()

        resp = client.get("/api/v1/plans/records?category=instagram")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert all(item["category"] == "instagram" for item in data)

    def test_list_records_tags_filter_http(self, client, test_db_session):
        """GET /api/v1/plans/records?tags=feat,fix → 태그 포함 레코드만 반환"""
        from app.models.plan_record import PlanRecord
        from datetime import datetime
        test_db_session.query(PlanRecord).filter_by(filename_hash="t4_tags_feat_001").delete(synchronize_session=False)
        test_db_session.commit()
        r = PlanRecord(
            filename_hash="t4_tags_feat_001",
            file_path="/archive/common/2026-02-11_t4-tagged.md",
            project="common",
            category="common",
            tags=["feat", "fix"],
            archived_at=datetime.now(),
            status="archived",
        )
        test_db_session.add(r)
        test_db_session.commit()

        resp = client.get("/api/v1/plans/records?tags=feat")
        assert resp.status_code == 200
        data = resp.json()
        assert any(item.get("tags") and "feat" in item["tags"] for item in data)


# ========== Phase T5: 신규 intent/scope 필드 응답 검증 ==========

class TestIntentFieldsInResponse:
    """Phase 8 T5: API 응답에 intent/trigger/scope/plan_date/applied_at 포함 확인"""

    def test_records_api_right_new_fields_in_response(self, client, test_db_session):
        """record에 intent/trigger/scope/plan_date/applied_at 데이터 있을 때 API 응답에 5개 필드 포함"""
        import json
        from datetime import date, datetime
        from app.models.plan_record import PlanRecord
        test_db_session.query(PlanRecord).filter_by(filename_hash="t5_intent_fields_001").delete(synchronize_session=False)
        test_db_session.commit()

        r = PlanRecord(
            filename_hash="t5_intent_fields_001",
            file_path="/archive/monitor/2026-03-20_t5-intent.md",
            project="monitor-t5",
            status="archived",
            archived_at=datetime(2026, 3, 20, 12, 0),
            intent="네이버 예약 스나이핑 재시도 로직 버그를 수정한다.",
            trigger="bug_recurrence",
            scope=json.dumps(["naver_booking", "worker/orchestrator.py"], ensure_ascii=False),
            plan_date=date(2026, 3, 15),
            applied_at=datetime(2026, 3, 20, 13, 52),
        )
        test_db_session.add(r)
        test_db_session.commit()

        # 단건 조회로 5개 필드 확인
        resp = client.get(f"/api/v1/plans/records/{r.id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["intent"] == "네이버 예약 스나이핑 재시도 로직 버그를 수정한다."
        assert data["trigger"] == "bug_recurrence"
        assert data["scope"] == ["naver_booking", "worker/orchestrator.py"]
        assert data["plan_date"] == "2026-03-15"
        assert data["applied_at"] is not None and "2026-03-20" in data["applied_at"]

    def test_records_api_boundary_null_fields_returned_as_none(self, client, test_db_session):
        """값 없는 레코드 조회 → 5개 신규 필드 모두 null로 반환 (500 아님)"""
        from datetime import datetime
        from app.models.plan_record import PlanRecord
        test_db_session.query(PlanRecord).filter_by(filename_hash="t5_null_fields_001").delete(synchronize_session=False)
        test_db_session.commit()

        r = PlanRecord(
            filename_hash="t5_null_fields_001",
            file_path="/archive/monitor/2026-03-21_t5-null.md",
            project="monitor-t5-null",
            status="archived",
            archived_at=datetime(2026, 3, 21, 9, 0),
            # intent, trigger, scope, plan_date, applied_at 모두 미설정
        )
        test_db_session.add(r)
        test_db_session.commit()

        resp = client.get(f"/api/v1/plans/records/{r.id}")
        assert resp.status_code == 200, f"500이 아닌 200이어야 함: {resp.text}"
        data = resp.json()

        assert data["intent"] is None
        assert data["trigger"] is None
        assert data["scope"] is None
        assert data["plan_date"] is None
        assert data["applied_at"] is None


class TestGetOrCreateDefaultStatus:
    """Phase 4: get_or_create 기본 status=planned 검증"""

    def test_get_or_create_default_status_planned(self, test_db_session):
        """신규 생성 시 status='planned' 자동 설정 (RIGHT)"""
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService
        svc = PlanRecordService(test_db_session)
        record = svc.get_or_create(
            "/plan/monitor/2026-03-30_test-default-status.md",
            title="Default Status Test",
            project="monitor",
        )
        test_db_session.flush()
        assert record.status == "planned", f"status는 'planned'이어야 함, 실제: {record.status}"

    def test_get_or_create_existing_record_status_unchanged(self, test_db_session):
        """기존 레코드 조회 시 status 변경 없음 (기존 status 유지)"""
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService
        from app.models.plan_record import PlanRecord as PlanRecordModel
        from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash

        path = "/plan/monitor/2026-03-30_test-existing-status.md"
        # 기존 레코드 직접 삽입 (status='in_progress')
        existing = PlanRecordModel(
            filename_hash=_compute_filename_hash(path),
            file_path=path,
            title="Existing",
            project="monitor",
            status="in_progress",
        )
        test_db_session.add(existing)
        test_db_session.flush()

        svc = PlanRecordService(test_db_session)
        record = svc.get_or_create(path)
        assert record.status == "in_progress", "기존 레코드 status는 변경되지 않아야 함"


# ─────────────────────────────────────────────────────────
# T3: include_claim 하위 호환성
# ─────────────────────────────────────────────────────────

class TestGetRecordByPathIncludeClaim:
    """/api/v1/plans/records/by-path include_claim 파라미터 하위 호환성 검증."""

    def test_R_base_response_without_include_claim(self, client, test_db_session):
        """R: include_claim 없이 기본 응답 → execution_claim 필드 없음"""
        path = "docs/plan/no-claim-base.md"
        resp = client.get(f"/api/v1/plans/records/by-path?file_path={path}")
        assert resp.status_code == 200
        data = resp.json()
        assert "file_path" in data
        assert "execution_claim" not in data, (
            "기본 응답(include_claim 미설정)에 execution_claim이 포함됨 — 하위 호환성 위반"
        )

    def test_R_include_claim_false_is_same_as_base(self, client, test_db_session):
        """R: include_claim=false 명시 → execution_claim 필드 없음"""
        path = "docs/plan/no-claim-false.md"
        resp = client.get(f"/api/v1/plans/records/by-path?file_path={path}&include_claim=false")
        assert resp.status_code == 200
        data = resp.json()
        assert "execution_claim" not in data

    def test_R_include_claim_true_adds_execution_claim_field(self, client, test_db_session):
        """R: include_claim=true → execution_claim 필드 포함 (claim 없으면 null)"""
        path = "docs/plan/no-claim-true.md"
        resp = client.get(f"/api/v1/plans/records/by-path?file_path={path}&include_claim=true")
        assert resp.status_code == 200
        data = resp.json()
        assert "execution_claim" in data, (
            "include_claim=true인데 execution_claim 필드가 없음"
        )

    def test_B_include_claim_true_no_active_claim_returns_null(self, client, test_db_session):
        """B: include_claim=true이고 active claim 없으면 execution_claim=null"""
        path = "docs/plan/no-active-claim.md"
        with patch(
            "app.modules.dev_runner.services.plan_record_service.PlanRecordService.get_active_claim",
            return_value=None,
        ):
            resp = client.get(
                f"/api/v1/plans/records/by-path?file_path={path}&include_claim=true"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_claim"] is None

    def test_Co_base_response_fields_intact_with_include_claim(self, client, test_db_session):
        """Co: include_claim=true 시 기존 응답 필드(file_path, memo 등)가 유지된다"""
        path = "docs/plan/co-intact.md"
        resp = client.get(f"/api/v1/plans/records/by-path?file_path={path}&include_claim=true")
        assert resp.status_code == 200
        data = resp.json()
        # PlanRecordResponse 기본 필드 확인
        assert "file_path" in data
        assert "id" in data
        assert "execution_claim" in data
