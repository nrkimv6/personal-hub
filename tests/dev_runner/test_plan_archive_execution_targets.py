"""
T1+T3: PlanArchiveExecutionTarget fan-out 계약 테스트.
profile-less Codex/GPT target, fan-out N requests, 개별/일괄 통합 계약,
applied_request_id ordering guard (T3-line145), worker fan-out mock (T3-line96).
"""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_archive_execution import PlanArchiveExecutionAttempt, PlanArchiveExecutionJob
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.plan_archive_execution_service import (
    PlanArchiveExecutionService,
    _targets_to_snapshot,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _record(db, filename_hash="hash-1", content="# plan\nbody"):
    rec = PlanRecord(
        filename_hash=filename_hash,
        file_path="/archive/2026-05-06_plan.md",
        raw_content=content,
        archived_at=datetime(2026, 5, 6),
    )
    db.add(rec)
    db.flush()
    return rec


def _fake_llm():
    fake = MagicMock()
    fake.resolve_provider_model.side_effect = lambda caller_type, provider, model: (
        provider or "claude",
        model or "sonnet",
    )
    return fake


# ── _targets_to_snapshot helper ─────────────────────────────────────────────

def test_targets_to_snapshot_from_targets():
    from app.modules.dev_runner.schemas import PlanArchiveExecutionTarget
    targets = [
        PlanArchiveExecutionTarget(provider="codex", model="gpt-5.5"),
        PlanArchiveExecutionTarget(provider="claude", model="sonnet", engine="claude", profile_name="work"),
    ]
    result = _targets_to_snapshot(targets)
    assert len(result) == 2
    assert result[0]["provider"] == "codex"
    assert result[0]["dedupe_key"] == "profileless"
    assert result[1]["dedupe_key"] == "profile:claude:work"


def test_targets_to_snapshot_falls_back_to_profiles():
    result = _targets_to_snapshot(
        None,
        selected_profiles=[{"engine": "claude", "profile_name": "work"}],
    )
    assert len(result) == 1
    assert result[0]["provider"] == "claude"
    assert result[0]["dedupe_key"] == "profile:claude:work"


def test_targets_to_snapshot_empty():
    assert _targets_to_snapshot(None, None) == []
    assert _targets_to_snapshot([], []) == []


def test_targets_to_snapshot_skips_no_provider():
    result = _targets_to_snapshot([{"provider": "", "model": "x"}])
    assert len(result) == 0


# ── R: Codex/GPT profile-less bulk execution ────────────────────────────────

def test_run_archive_executions_R_queues_codex_gpt55_without_profile(db):
    rec = _record(db)
    db.commit()
    fake = _fake_llm()
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake,
    ):
        result = PlanArchiveExecutionService(db).enqueue_record(
            rec,
            trigger_source="test",
            selected_targets=[{"provider": "codex", "model": "gpt-5.5", "dedupe_key": "profileless"}],
        )
    assert result["status_key"] == "queued"
    req = db.query(LLMRequest).filter_by(id=result["request_ids"][0]).first()
    assert req is not None
    assert req.provider == "codex"
    assert req.model == "gpt-5.5"
    # cli_options에 candidate_profiles 없음 (profile-less)
    cli = json.loads(req.cli_options or "{}")
    assert not cli.get("candidate_profiles")


# ── R: N requests per N targets per record ──────────────────────────────────

def test_run_archive_executions_R_creates_N_requests_for_N_targets_per_record(db):
    rec = _record(db)
    db.commit()
    targets = [
        {"provider": "claude", "model": "sonnet", "engine": "claude", "profile_name": "work", "dedupe_key": "profile:claude:work"},
        {"provider": "codex", "model": "gpt-5.5", "dedupe_key": "profileless"},
    ]
    fake = _fake_llm()
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake,
    ):
        result = PlanArchiveExecutionService(db).enqueue_record(
            rec,
            trigger_source="test",
            selected_targets=targets,
        )
    assert result["status_key"] == "queued"
    assert len(result["request_ids"]) == 2
    # 모두 동일한 job_id
    attempts = db.query(PlanArchiveExecutionAttempt).all()
    job_ids = {a.job_id for a in attempts}
    assert len(job_ids) == 1
    # provider 다름
    reqs = db.query(LLMRequest).filter(LLMRequest.id.in_(result["request_ids"])).all()
    providers = {r.provider for r in reqs}
    assert "claude" in providers
    assert "codex" in providers


# ── R: 개별/일괄 실행 같은 target 계약 ─────────────────────────────────────

def test_candidate_queue_and_bulk_run_use_same_selected_targets_contract(db):
    """개별 enqueue_record 와 enqueue_records 가 동일한 target snapshot 을 사용하는지 검증."""
    from app.modules.dev_runner.services.plan_archive_execution_service import (
        PlanArchiveExecutionService, _targets_to_snapshot,
    )
    rec1 = _record(db, filename_hash="h1")
    rec2 = _record(db, filename_hash="h2")
    db.commit()

    targets_raw = [{"provider": "codex", "model": "gpt-5.5", "dedupe_key": "profileless"}]
    fake = _fake_llm()
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake,
    ):
        svc = PlanArchiveExecutionService(db)
        stats = svc.enqueue_records(
            [rec1, rec2],
            trigger_source="test",
            selected_targets=targets_raw,
        )
    assert stats["queued"] == 2
    # 각 record당 1개 request (targets 1개이므로)
    assert len(stats["request_ids"]) == 2
    reqs = db.query(LLMRequest).filter(LLMRequest.id.in_(stats["request_ids"])).all()
    for req in reqs:
        assert req.provider == "codex"
        assert req.model == "gpt-5.5"
        assert req.dedupe_key == "profileless"


# ── T3: applied_request_id ordering guard (line 145) ─────────────────────────

def test_applied_request_id_guard_skips_stale_result_when_newer_completed(db):
    """fan-out N 요청 중 나중에 완료된 것(higher id)이 먼저 저장되면,
    이전(lower id) 결과 저장 시 _has_newer_plan_archive_result가 True를 반환해 저장을 막는다."""
    from app.modules.claude_worker.services.plan_analyze_handler import (
        save_plan_archive_result,
        _has_newer_plan_archive_result,
    )

    rec = _record(db, filename_hash="hash-ordering-test")
    db.commit()

    # 두 개의 LLMRequest를 순서대로 생성 (id 작은 것 = 먼저 큐잉)
    req_old = LLMRequest(
        caller_type="plan_archive_analyze",
        caller_id=str(rec.id),
        prompt="p",
        provider="claude",
        model="sonnet",
        status="completed",
        result='{"category":"fix","tags":[],"summary":"old result"}',
    )
    db.add(req_old)
    db.flush()
    old_id = req_old.id

    req_new = LLMRequest(
        caller_type="plan_archive_analyze",
        caller_id=str(rec.id),
        prompt="p",
        provider="codex",
        model="gpt-5.5",
        status="completed",
        result='{"category":"feat","tags":["x"],"summary":"new result"}',
    )
    db.add(req_new)
    db.flush()
    new_id = req_new.id
    db.commit()

    assert new_id > old_id  # 순서 전제

    # 더 최신 요청(new)이 먼저 DB 반영됐다고 가정 → save_plan_archive_result(new) 먼저 호출
    new_result = {"success": True, "result": {"category": "feat", "tags": ["x"], "summary": "new result"}}
    saved_new = save_plan_archive_result(db, req_new, new_result)
    assert saved_new is True
    db.refresh(rec)
    assert rec.category == "feat"
    assert rec.summary == "new result"

    # 이제 오래된 요청(old) 결과 저장 시도 → guard가 차단해야 함
    old_result = {"success": True, "result": {"category": "fix", "tags": [], "summary": "old result"}}
    saved_old = save_plan_archive_result(db, req_old, old_result)
    assert saved_old is False  # guard가 차단

    # record 값은 new result 그대로 유지
    db.refresh(rec)
    assert rec.category == "feat"
    assert rec.summary == "new result"


def test_applied_request_id_guard_allows_result_when_no_newer_request(db):
    """newer request가 없으면 guard가 False를 반환해 정상 저장이 허용된다."""
    from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result

    rec = _record(db, filename_hash="hash-no-newer")
    db.commit()

    req = LLMRequest(
        caller_type="plan_archive_analyze",
        caller_id=str(rec.id),
        prompt="p",
        provider="claude",
        model="sonnet",
        status="completed",
        result='{"category":"fix","tags":[],"summary":"only result"}',
    )
    db.add(req)
    db.commit()

    result = {"success": True, "result": {"category": "fix", "tags": [], "summary": "only result"}}
    saved = save_plan_archive_result(db, req, result)
    assert saved is True
    db.refresh(rec)
    assert rec.category == "fix"
    assert rec.summary == "only result"


# ── T3: worker fan-out mock validation (line 96) ─────────────────────────────

def test_worker_fanout_N_requests_only_newest_applied_to_record(db):
    """fan-out N개 요청이 완료 순서가 뒤섞여도 가장 최신(highest id) 결과만 record에 반영된다.
    결정: mock-based unit 검증 (실제 worker 기동 불필요)."""
    from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result

    rec = _record(db, filename_hash="hash-fanout-mixed-order")
    db.commit()

    targets = [
        {"provider": "claude", "model": "sonnet", "dedupe_key": "profile:claude:default"},
        {"provider": "codex", "model": "gpt-5.5", "dedupe_key": "profileless"},
        {"provider": "gemini", "model": "flash", "dedupe_key": "profile:gemini:default"},
    ]
    fake = _fake_llm()
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake,
    ):
        result = PlanArchiveExecutionService(db).enqueue_record(
            rec,
            trigger_source="test-fanout",
            selected_targets=targets,
        )

    assert result["status_key"] == "queued"
    request_ids = sorted(result["request_ids"])  # id 오름차순 = 큐잉 순서
    assert len(request_ids) == 3

    # 순서를 섞어 처리: 중간(request_ids[1]) 먼저, 마지막(request_ids[2]) 다음, 처음(request_ids[0]) 마지막
    processing_order = [request_ids[1], request_ids[2], request_ids[0]]
    categories_by_id = {
        request_ids[0]: "first-queued",
        request_ids[1]: "second-queued",
        request_ids[2]: "third-queued-newest",
    }

    for req_id in processing_order:
        req = db.query(LLMRequest).filter_by(id=req_id).first()
        req.status = "completed"
        req.result = f'{{"category":"{categories_by_id[req_id]}","tags":[],"summary":"summary-{req_id}"}}'
        db.commit()
        save_plan_archive_result(
            db, req,
            {"success": True, "result": {"category": categories_by_id[req_id], "tags": [], "summary": f"summary-{req_id}"}}
        )

    # 최신(highest id = request_ids[2])의 결과만 record에 반영돼야 함
    db.refresh(rec)
    assert rec.category == "third-queued-newest", (
        f"Expected 'third-queued-newest', got '{rec.category}'. "
        "Guard should have prevented older requests from overwriting newer result."
    )
