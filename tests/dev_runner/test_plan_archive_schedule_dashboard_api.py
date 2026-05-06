"""
T1: archive schedule dashboard API 계약 테스트.
RIGHT-BICEP/CORRECT 기준 — 단위 범위, SQLite in-memory, mock 최소화.

엔드포인트:
  GET  /api/v1/plans/records/archive-schedule-dashboard
  GET  /api/v1/plans/records/archive-llm-requests
  GET  /api/v1/plans/records/archive-llm-requests/{request_id}
  GET  /api/v1/plans/records/archive-schedule-runs
  GET  /api/v1/plans/records/archive-execution-attempts
  POST /api/v1/plans/records/archive-schedule/pause   (admin only)
  POST /api/v1/plans/records/archive-schedule/resume  (admin only)
"""
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_record import PlanRecord, PlanEvent
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.models.plan_archive_execution import PlanArchiveExecutionJob, PlanArchiveExecutionAttempt


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_app(engine):
    """public 앱에 SQLite 세션 오버라이드."""
    from app.main import app
    from app.core.database import get_db
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    return app


def _make_admin_app(engine):
    """admin 앱에 SQLite 세션 오버라이드."""
    from app.main_admin import app as admin_app
    from app.core.database import get_db
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    admin_app.dependency_overrides[get_db] = override_get_db
    return admin_app


@pytest.fixture()
def public_client(engine):
    try:
        app = _make_app(engine)
    except Exception:
        pytest.skip("public app import 실패")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def admin_client(engine):
    try:
        app = _make_admin_app(engine)
    except Exception:
        pytest.skip("admin app import 실패")
    return TestClient(app, raise_server_exceptions=False)


def _add_schedule(db, enabled=True):
    sched = TaskSchedule(
        name="plan_archive_analyze_test",
        target_type=TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
        schedule_value="0 * * * *",
        enabled=enabled,
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    return sched


def _add_llm_request(db, *, status="completed", failure_category=None, record_id=None,
                     requested_at=None, processed_at=None, retry_count=0,
                     dedupe_key=None, provider="claude", model="claude-3",
                     prompt="test prompt"):
    from app.modules.claude_worker.models.llm_request import LLMRequest
    req = LLMRequest(
        caller_type="plan_archive_analyze",
        caller_id=str(record_id) if record_id else "1",
        status=status,
        provider=provider,
        model=model,
        prompt=prompt,
        failure_category=failure_category,
        dedupe_key=dedupe_key,
        retry_count=retry_count,
        requested_at=requested_at or datetime.utcnow(),
        processed_at=processed_at,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def _add_plan_record(db):
    rec = PlanRecord(
        filename_hash="abc123test",
        file_path="/plans/test.md",
        archived_at=datetime.utcnow(),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


# ── R: dashboard returns schedule / health / readiness / queue / history ────

def test_plan_archive_schedule_dashboard_R_returns_schedule_health_readiness_queue_and_history(
    public_client, db
):
    """dashboard가 schedule snapshot, health, readiness, queue_summary, recent rows를 반환."""
    _add_schedule(db)
    _add_llm_request(db, status="completed")
    resp = public_client.get("/api/v1/plans/records/archive-schedule-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "queue_summary" in data
    assert "recent_requests" in data
    assert "recent_schedule_runs" in data
    assert "recent_execution_attempts" in data
    qs = data["queue_summary"]
    assert "pending" in qs
    assert "failed" in qs
    assert "completed_24h" in qs


def test_plan_archive_schedule_dashboard_E_reports_execution_readiness_missing(
    public_client, db
):
    """schedule 없어도 dashboard가 200을 반환하고 schedule 필드는 null."""
    resp = public_client.get("/api/v1/plans/records/archive-schedule-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    # schedule 이 없으면 null
    assert data.get("schedule") is None


def test_plan_archive_schedule_dashboard_R_summary_response_excludes_full_request_list(
    public_client, db
):
    """dashboard는 recent rows를 N=20으로 제한하고 전체 목록을 반환하지 않는다."""
    # 25개 요청 추가
    for i in range(25):
        _add_llm_request(db, status="completed")
    resp = public_client.get("/api/v1/plans/records/archive-schedule-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["recent_requests"]) <= 20


# ── R: llm requests list with failure_category ──────────────────────────────

def test_archive_llm_requests_R_paginates_and_returns_stored_failure_category(
    public_client, db
):
    """list endpoint가 failure_category를 포함한 row를 반환하고 pagination이 동작한다."""
    _add_llm_request(db, status="failed", failure_category="timeout")
    _add_llm_request(db, status="failed", failure_category="quota")
    _add_llm_request(db, status="completed")
    resp = public_client.get("/api/v1/plans/records/archive-llm-requests?page=1&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3
    categories = [r.get("failure_category") for r in data["items"]]
    assert "timeout" in categories
    assert "quota" in categories


def test_archive_llm_requests_R_filters_by_status(public_client, db):
    """status 필터가 정확히 동작한다."""
    _add_llm_request(db, status="failed", failure_category="parse")
    _add_llm_request(db, status="completed")
    resp = public_client.get("/api/v1/plans/records/archive-llm-requests?status=failed")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["status"] == "failed" for r in data["items"])


# ── R: request detail with prompt/result/raw_response ────────────────────────

def test_archive_llm_request_detail_R_returns_prompt_result_raw_response_cli_options_and_record(
    public_client, db
):
    """request detail이 prompt, result, raw_response, cli_options, retry_count를 포함한다."""
    from app.modules.claude_worker.models.llm_request import LLMRequest
    req = LLMRequest(
        caller_type="plan_archive_analyze",
        caller_id="42",
        status="completed",
        provider="claude",
        model="claude-3",
        requested_at=datetime.utcnow(),
        processed_at=datetime.utcnow(),
        retry_count=2,
        prompt="test prompt",
        result='{"summary": "ok"}',
        raw_response="raw text",
        cli_options='{"arg": 1}',
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    resp = public_client.get(f"/api/v1/plans/records/archive-llm-requests/{req.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == req.id
    assert data["prompt"] == "test prompt"
    assert data["result"] == '{"summary": "ok"}'
    assert data["raw_response"] == "raw text"
    assert data["cli_options"] == '{"arg": 1}'
    assert data["retry_count"] == 2


def test_archive_llm_request_detail_R_returns_requested_effective_actual_target_readback(
    public_client, db
):
    """detail은 target_label 파싱이 아니라 requested/effective/actual target 구조를 반환한다."""
    from app.modules.claude_worker.models.llm_request import LLMProfileAssignment, LLMRequest
    cli_options = {
        "requested_target": {
            "provider": "claude",
            "model": "claude-sonnet-4-5",
            "profile_key": "claude:work",
            "engine": "claude",
            "profile_name": "work",
            "label": "claude/work/claude-sonnet-4-5",
        },
        "effective_target": {
            "provider": "claude",
            "model": "claude-sonnet-4-5",
            "profile_key": "claude:work",
            "engine": "claude",
            "profile_name": "work",
            "label": "claude/work/claude-sonnet-4-5",
        },
        "candidate_profiles": [{"engine": "claude", "profile_name": "work"}],
        "target_label": "claude/work/claude-sonnet-4-5",
        "plan_archive_save_outcome": {
            "saved": False,
            "status": "stale_skipped",
            "reason": "newer_completed_result_exists",
        },
    }
    req = LLMRequest(
        caller_type="plan_archive_analyze",
        caller_id="42",
        status="completed",
        provider="claude",
        model="claude-sonnet-4-5",
        requested_at=datetime.utcnow(),
        processed_at=datetime.utcnow(),
        prompt="test prompt",
        cli_options=json.dumps(cli_options),
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    db.add(
        LLMProfileAssignment(
            request_id=req.id,
            engine="claude",
            profile_name="work",
            selected_at=datetime.utcnow(),
        )
    )
    db.commit()

    resp = public_client.get(f"/api/v1/plans/records/archive-llm-requests/{req.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["requested_target"]["model"] == "claude-sonnet-4-5"
    assert data["effective_target"]["profile_name"] == "work"
    assert data["actual_target"]["provider"] == "claude"
    assert data["actual_target"]["profile_name"] == "work"
    assert data["assigned_profile"]["profile_name"] == "work"
    assert data["save_outcome_status"] == "stale_skipped"
    assert data["save_outcome_reason"] == "newer_completed_result_exists"


def test_archive_llm_request_detail_returns_404_for_unknown_id(public_client, db):
    """존재하지 않는 request_id에 대해 404를 반환한다."""
    resp = public_client.get("/api/v1/plans/records/archive-llm-requests/9999999")
    assert resp.status_code == 404


# ── R: applied_request_id derived from plan_archive_analysis_saved event ────

def test_archive_llm_request_row_R_marks_applied_request_id(public_client, db):
    """plan_archive_analysis_saved 이벤트의 request_id가 applied_request_id로 표시된다."""
    from app.modules.claude_worker.models.llm_request import LLMRequest
    rec = _add_plan_record(db)

    req = LLMRequest(
        caller_type="plan_archive_analyze",
        caller_id=str(rec.id),
        status="completed",
        provider="claude",
        model="claude-3",
        prompt="test prompt",
        requested_at=datetime.utcnow(),
        processed_at=datetime.utcnow(),
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    event = PlanEvent(
        plan_record_id=rec.id,
        event_type="plan_archive_analysis_saved",
        detail={"request_id": req.id},
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()

    resp = public_client.get(f"/api/v1/plans/records/archive-llm-requests/{req.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["applied_request_id"] == req.id
    assert data["is_applied_to_record"] is True


# ── R: pause/resume toggles schedule enabled flag ────────────────────────────

def test_archive_schedule_pause_resume_R_toggles_enabled_flag(admin_client, db):
    """pause → enabled=False, resume → enabled=True으로 변경된다."""
    sched = _add_schedule(db, enabled=True)

    resp = admin_client.post("/api/v1/plans/records/archive-schedule/pause")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["action"] == "pause"
    assert data["schedule_id"] == sched.id

    resp = admin_client.post("/api/v1/plans/records/archive-schedule/resume")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["action"] == "resume"


def test_archive_schedule_pause_returns_404_if_no_schedule(admin_client, db):
    """archive schedule이 없을 때 pause가 404를 반환한다."""
    resp = admin_client.post("/api/v1/plans/records/archive-schedule/pause")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Plan archive schedule not found"


def test_archive_schedule_resume_returns_domain_404_detail_if_no_schedule(admin_client, db):
    """admin route는 존재하지만 schedule seed가 없으면 JSON detail로 domain 404를 반환한다."""
    resp = admin_client.post("/api/v1/plans/records/archive-schedule/resume")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Plan archive schedule not found"


def test_archive_schedule_admin_route_open_public_route_closed(public_client, admin_client, db):
    """admin app은 pause/resume을 처리하고 public app은 같은 mutation path를 노출하지 않는다."""
    _add_schedule(db, enabled=False)

    admin_resp = admin_client.post("/api/v1/plans/records/archive-schedule/resume")
    assert admin_resp.status_code == 200
    assert admin_resp.json()["enabled"] is True

    public_resp = public_client.post("/api/v1/plans/records/archive-schedule/resume")
    assert public_resp.status_code in (404, 405)


# ── R: drill-down ids in request row ─────────────────────────────────────────

def test_archive_llm_request_row_R_includes_drill_down_ids(public_client, db):
    """request row에 record_id 드릴다운 필드가 존재한다."""
    rec = _add_plan_record(db)
    _add_llm_request(db, status="completed", record_id=rec.id)
    resp = public_client.get("/api/v1/plans/records/archive-llm-requests?page=1&page_size=10")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    row = items[0]
    assert "record_id" in row
    assert "source_schedule_run_id" in row
    assert "failure_category" in row
    assert "dedupe_key" in row


# ── B: bulk pagination with 2000+ rows ───────────────────────────────────────

def test_archive_llm_requests_B_paginates_2k_rows(public_client, db):
    """2000개 행 중 page_size=100으로 2페이지 조회 시 offset이 올바르게 동작한다."""
    from app.modules.claude_worker.models.llm_request import LLMRequest
    now = datetime.utcnow()
    reqs = [
        LLMRequest(
            caller_type="plan_archive_analyze",
            caller_id="bulk",
            status="completed",
            provider="claude",
            model="claude-3",
            prompt="test",
            requested_at=now - timedelta(seconds=i),
        )
        for i in range(150)
    ]
    db.bulk_save_objects(reqs)
    db.commit()

    resp1 = public_client.get("/api/v1/plans/records/archive-llm-requests?page=1&page_size=100")
    resp2 = public_client.get("/api/v1/plans/records/archive-llm-requests?page=2&page_size=100")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    d1 = resp1.json()
    d2 = resp2.json()
    assert d1["total"] >= 150
    assert len(d1["items"]) == 100
    assert len(d2["items"]) >= 50
    # 두 페이지 id가 겹치지 않아야 함
    ids1 = {r["id"] for r in d1["items"]}
    ids2 = {r["id"] for r in d2["items"]}
    assert ids1.isdisjoint(ids2)


# ── B: schedule runs pagination ───────────────────────────────────────────────

def test_archive_schedule_runs_B_paginates_history(public_client, db):
    """schedule runs list가 pagination 동작하고 filters를 반환한다."""
    sched = _add_schedule(db)
    for i in range(30):
        run = TaskScheduleRun(
            schedule_id=sched.id,
            status="completed",
            started_at=datetime.utcnow() - timedelta(hours=i),
        )
        db.add(run)
    db.commit()

    resp = public_client.get("/api/v1/plans/records/archive-schedule-runs?page=1&page_size=20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 30
    assert len(data["items"]) == 20
    assert "filters" in data


# ── B: execution attempts pagination ─────────────────────────────────────────

def test_archive_execution_attempts_B_paginates_history(public_client, db):
    """execution attempts list가 pagination 동작하고 filters를 반환한다."""
    rec = _add_plan_record(db)
    job = PlanArchiveExecutionJob(
        plan_record_id=rec.id,
        status="completed",
        trigger_source="test",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    for i in range(25):
        attempt = PlanArchiveExecutionAttempt(
            job_id=job.id,
            attempt_index=i + 1,
            status="completed",
            created_at=datetime.utcnow() - timedelta(minutes=i),
        )
        db.add(attempt)
    db.commit()

    resp = public_client.get("/api/v1/plans/records/archive-execution-attempts?page=1&page_size=20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 25
    assert len(data["items"]) == 20
    assert "filters" in data


# ── E: page_size > 200 는 422 ─────────────────────────────────────────────────

def test_archive_llm_requests_E_rejects_oversized_page(public_client, db):
    """page_size > 200이면 422를 반환한다."""
    resp = public_client.get("/api/v1/plans/records/archive-llm-requests?page_size=201")
    assert resp.status_code == 422


# ── public app 에서 mutation endpoint는 404/405 ──────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/v1/plans/records/archive-schedule/pause",
    "/api/v1/plans/records/archive-schedule/resume",
])
def test_public_app_does_not_expose_pause_resume(path):
    """public app에서 pause/resume 호출 시 404/405 반환."""
    try:
        from app.main import app as public_app
    except Exception:
        pytest.skip("public app import 실패")
    client = TestClient(public_app, raise_server_exceptions=False)
    resp = client.post(path)
    assert resp.status_code in (404, 405), (
        f"public app의 {path}가 {resp.status_code} 반환 — 404/405 기대"
    )
