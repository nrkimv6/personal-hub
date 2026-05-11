"""Dev Runner Postgres mirror repository tests."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.dev_runner_state import DevRunnerMergeRequest, DevRunnerState
from app.modules.dev_runner.services.dev_runner_state_repository import (
    claim_next_merge_request,
    complete_merge_request,
    create_merge_request,
    get_runner_state,
    upsert_runner_state,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    DevRunnerState.__table__.create(bind=engine, checkfirst=True)
    DevRunnerMergeRequest.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_upsert_runner_state_R_creates_and_updates_row(db):
    row = upsert_runner_state(
        db,
        {
            "runner_id": "runner-upsert",
            "plan_file": "docs/plan/test.md",
            "project": "monitor-page",
            "status": "running",
            "metadata": {"engine": "codex"},
        },
    )
    assert row.runner_id == "runner-upsert"
    assert row.status == "running"

    updated = upsert_runner_state(
        db,
        {
            "runner_id": "runner-upsert",
            "plan_file": "docs/plan/test.md",
            "status": "stopped",
            "exit_reason": "completed",
            "metadata": {"engine": "codex", "trigger": "user"},
        },
    )

    assert updated.runner_id == row.runner_id
    assert get_runner_state(db, "runner-upsert").status == "stopped"
    assert get_runner_state(db, "runner-upsert").metadata_json["trigger"] == "user"


def test_runner_state_B_merge_waiting_requires_branch(db):
    with pytest.raises(IntegrityError):
        upsert_runner_state(
            db,
            {
                "runner_id": "runner-no-branch",
                "plan_file": "docs/plan/test.md",
                "status": "머지대기",
            },
        )
        db.commit()


def test_create_merge_request_R_links_runner_state(db):
    state = upsert_runner_state(
        db,
        {
            "runner_id": "runner-merge",
            "plan_file": "docs/plan/merge.md",
            "status": "running",
            "branch": "impl/test",
        },
    )

    request = create_merge_request(
        db,
        {
            "runner_id": state.runner_id,
            "branch": "impl/test",
            "worktree_path": "D:/work/wt",
            "plan_file": "docs/plan/merge.md",
        },
    )

    assert request.runner_id == state.runner_id
    assert request.runner_state.runner_id == state.runner_id
    assert request.state == "pending"


def test_claim_next_merge_request_O_oldest_pending_first(db):
    upsert_runner_state(db, {"runner_id": "runner-old", "plan_file": "old.md", "status": "running", "branch": "impl/old"})
    upsert_runner_state(db, {"runner_id": "runner-new", "plan_file": "new.md", "status": "running", "branch": "impl/new"})
    create_merge_request(
        db,
        {
            "runner_id": "runner-new",
            "branch": "impl/new",
            "worktree_path": "D:/new",
            "plan_file": "new.md",
            "created_at": datetime.now(),
        },
    )
    old = create_merge_request(
        db,
        {
            "runner_id": "runner-old",
            "branch": "impl/old",
            "worktree_path": "D:/old",
            "plan_file": "old.md",
            "created_at": datetime.now() - timedelta(minutes=5),
        },
    )

    claimed = claim_next_merge_request(db, "worker-1")

    assert claimed.id == old.id
    assert claimed.state == "claimed"
    assert claimed.claim_token == "worker-1"
    assert claimed.claimed_at is not None


def test_complete_merge_request_E_missing_request_returns_none_or_raises_domain_error(db):
    with pytest.raises(ValueError, match="merge request not found"):
        complete_merge_request(db, 999999, "completed")
