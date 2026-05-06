"""
T1: 동시 큐잉 race condition 방어 테스트.
Phase 2B: dedupe_key partial unique index 기반 중복 방어.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.plan_archive_execution_service import (
    PlanArchiveExecutionService,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    # SQLite: partial unique index를 직접 생성 (마이그레이션 SQL 모사)
    with engine.connect() as conn:
        conn.execute(text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_requests_active_dedup
            ON llm_requests(caller_type, caller_id, provider, model, dedupe_key)
            WHERE status IN ('pending', 'processing') AND deleted_at IS NULL AND dedupe_key IS NOT NULL
            """
        ))
        conn.commit()
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _record(db):
    rec = PlanRecord(
        filename_hash="race-hash-001",
        file_path="/archive/2026-05-06_race.md",
        raw_content="# race test\nbody",
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


def test_concurrent_enqueue_same_record_target_only_one_succeeds(db):
    """동일 (record, target) 동시 큐잉 시 한 쪽만 성공하고 다른 쪽은 already_queued 응답."""
    rec = _record(db)
    db.commit()

    target = [{"provider": "claude", "model": "sonnet", "dedupe_key": "profileless"}]
    fake = _fake_llm()
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake,
    ):
        svc = PlanArchiveExecutionService(db)
        r1 = svc.enqueue_record(rec, trigger_source="test1", selected_targets=target)
        db.commit()

        # 두 번째 시도: active_job 이 있으므로 skipped
        r2 = svc.enqueue_record(rec, trigger_source="test2", selected_targets=target)

    assert r1["status_key"] == "queued"
    assert r2["status_key"] in ("skipped_active_job", "skipped_active_request")

    active_reqs = db.query(LLMRequest).filter(
        LLMRequest.caller_type == "plan_archive_analyze",
        LLMRequest.caller_id == str(rec.id),
        LLMRequest.status.in_(["pending", "processing"]),
    ).count()
    assert active_reqs == 1, "active request 는 정확히 1개여야 함"


def test_dedupe_key_stored_on_llm_request(db):
    """enqueue_record 후 LLMRequest.dedupe_key 가 설정됐는지 확인."""
    rec = _record(db)
    db.commit()

    target = [{"provider": "claude", "model": "sonnet", "engine": "claude", "profile_name": "work", "dedupe_key": "profile:claude:work"}]
    fake = _fake_llm()
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake,
    ):
        result = PlanArchiveExecutionService(db).enqueue_record(
            rec, trigger_source="test", selected_targets=target
        )

    assert result["status_key"] == "queued"
    req = db.query(LLMRequest).filter_by(id=result["request_ids"][0]).first()
    assert req.dedupe_key == "profile:claude:work"


def test_different_targets_for_same_record_both_succeed(db):
    """동일 record라도 dedupe_key 가 다른 target 은 모두 큐잉 가능."""
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
            rec, trigger_source="test", selected_targets=targets
        )

    assert result["status_key"] == "queued"
    assert len(result["request_ids"]) == 2
