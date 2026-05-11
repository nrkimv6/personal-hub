"""Service-level integration checks for Dev Runner Postgres runner state fallback."""

from datetime import datetime
from unittest.mock import patch

import fakeredis
import fakeredis.aioredis
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.dev_runner_state import DevRunnerMergeRequest, DevRunnerState
from app.modules.dev_runner.services.dev_runner_state_repository import upsert_runner_state
from app.modules.dev_runner.services.executor_service import ExecutorService


@pytest.fixture
def runner_state_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    DevRunnerState.__table__.create(bind=engine, checkfirst=True)
    DevRunnerMergeRequest.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    with patch("app.database.SessionLocal", Session):
        try:
            yield session
        finally:
            session.close()
            engine.dispose()


@pytest.fixture
def executor_with_fakeredis():
    svc = ExecutorService.__new__(ExecutorService)
    svc.redis_client = fakeredis.FakeRedis(decode_responses=True)
    svc.async_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    svc.state = None
    svc.merge = None
    return svc


@pytest.mark.asyncio
async def test_db_row_survives_per_runner_redis_suffix_loss(runner_state_session, executor_with_fakeredis):
    rid = "integration-db-survives-001"
    await executor_with_fakeredis.async_redis.sadd("plan-runner:active_runners", rid)
    await executor_with_fakeredis.async_redis.set(f"plan-runner:runners:{rid}:status", "running")
    await executor_with_fakeredis.async_redis.set(f"plan-runner:runners:{rid}:plan_file", "docs/plan/lost.md")

    upsert_runner_state(
        runner_state_session,
        {
            "runner_id": rid,
            "plan_file": "docs/plan/lost.md",
            "status": "running",
            "branch": "impl/lost-evidence",
            "worktree_path": "D:/work/lost-evidence",
            "started_at": datetime.now(),
            "metadata": {"engine": "codex", "trigger": "user"},
        },
    )
    runner_state_session.commit()

    await executor_with_fakeredis.async_redis.delete(
        f"plan-runner:runners:{rid}:status",
        f"plan-runner:runners:{rid}:plan_file",
    )

    rows = await executor_with_fakeredis.get_all_runners()

    item = next(row for row in rows if row.runner_id == rid)
    assert item.plan_file == "docs/plan/lost.md"
    assert item.branch == "impl/lost-evidence"
    assert item.worktree_path == "D:/work/lost-evidence"
    assert item.trigger == "user"


@pytest.mark.asyncio
async def test_merge_requested_db_row_preserves_merge_evidence(runner_state_session, executor_with_fakeredis):
    rid = "integration-merge-evidence-001"
    upsert_runner_state(
        runner_state_session,
        {
            "runner_id": rid,
            "plan_file": "docs/plan/merge-evidence.md",
            "status": "머지대기",
            "branch": "impl/merge-evidence",
            "worktree_path": "D:/work/merge-evidence",
            "merge_requested": True,
            "started_at": datetime.now(),
            "metadata": {"trigger": "user"},
        },
    )
    runner_state_session.commit()

    rows = await executor_with_fakeredis.get_all_runners()

    item = next(row for row in rows if row.runner_id == rid)
    assert item.merge_status == "queued"
    assert item.branch == "impl/merge-evidence"
    assert item.worktree_path == "D:/work/merge-evidence"
    assert item.merge_evidence_missing is False
