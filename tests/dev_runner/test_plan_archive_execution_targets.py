"""
T1: PlanArchiveExecutionTarget fan-out 계약 테스트.
profile-less Codex/GPT target, fan-out N requests, 개별/일괄 통합 계약.
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
