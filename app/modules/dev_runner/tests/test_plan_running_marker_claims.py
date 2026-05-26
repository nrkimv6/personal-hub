from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_execution_claim import PlanExecutionClaim
from app.models.plan_record import PlanRecord
from app.modules.dev_runner.services.plan_execution_claim_service import (
    attach_task_execution_claims,
    claim_plan,
    claim_task_execution,
    get_active_task_execution_claims_for_plan,
    release_task_execution_claim,
)
from app.modules.dev_runner.services.plan_scanner import PlanScanner


class _Registry:
    _registered_paths = []
    _ignored_plans = set()

    def register_mutation_callback(self, _callback):
        return None


@pytest.fixture
def scanner():
    return PlanScanner(_Registry())


@pytest.fixture
def claim_db():
    engine = create_engine("sqlite:///:memory:")
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanExecutionClaim.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        PlanExecutionClaim.__table__.drop(bind=engine, checkfirst=True)
        PlanRecord.__table__.drop(bind=engine, checkfirst=True)


def _write_plan(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "# Running Marker",
                "",
                "## Phase 1: Impl",
                "- [ ] pending task",
                "- [/] running task",
                "- [x] done task",
                "1. [/] numbered running task",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_plan_progress_counts_running_marker_as_pending(tmp_path, scanner):
    plan = _write_plan(tmp_path / "plan.md")

    progress = scanner.get_plan_progress(plan)

    assert progress.total == 4
    assert progress.done == 1
    assert progress.percent == 25


def test_plan_items_exposes_running_marker_and_claims(tmp_path, scanner):
    plan = _write_plan(tmp_path / "plan.md")

    detail = scanner.parse_plan_items(plan)
    running_item = detail.phases[0].items[1]
    assert running_item.marker == "/"
    assert running_item.checked is False
    assert running_item.state == "running"

    from app.modules.dev_runner.schemas import PlanTaskExecutionClaimResponse

    claim = PlanTaskExecutionClaimResponse(
        task_claim_id="task-claim-a",
        state="active",
        runner_id="runner-a",
        job_id="job-a",
        task_key=running_item.task_key,
    )
    attach_task_execution_claims(detail, [claim])

    assert running_item.execution_claims[0].runner_id == "runner-a"
    assert running_item.execution_claims[0].job_id == "job-a"
    assert running_item.state == "running"


def test_parallel_claim_release_preserves_other_active_claim(tmp_path, claim_db):
    plan = str(tmp_path / "plan.md")
    Path(plan).write_text("- [/] task\n", encoding="utf-8")
    plan_claim = claim_plan(claim_db, plan, runner_id="runner-plan", write_header=False)

    first = claim_task_execution(
        claim_db,
        plan_claim.claim_id,
        phase_name="Phase 1",
        item_ordinal="1",
        text="task",
        runner_id="runner-a",
        job_id="job-a",
        task_claim_id="task-a",
    )
    second = claim_task_execution(
        claim_db,
        plan_claim.claim_id,
        phase_name="Phase 1",
        item_ordinal="1",
        text="task",
        runner_id="runner-b",
        job_id="job-b",
        task_claim_id="task-b",
    )

    released = release_task_execution_claim(claim_db, task_claim_id=first.task_claim_id)
    active = get_active_task_execution_claims_for_plan(claim_db, plan)

    assert [claim.task_claim_id for claim in released] == [first.task_claim_id]
    assert [claim.task_claim_id for claim in active] == [second.task_claim_id]
    assert active[0].runner_id == "runner-b"
