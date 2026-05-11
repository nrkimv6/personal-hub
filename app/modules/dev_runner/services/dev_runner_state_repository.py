"""Repository helpers for Dev Runner Postgres mirror state."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.dev_runner_state import DevRunnerMergeRequest, DevRunnerState

MERGE_REQUEST_ACTIVE_STATES = ("pending", "claimed")
MERGE_REQUEST_HISTORY_STATES = ("completed", "failed", "error", "done", "merged", "test_failed")


def _now() -> datetime:
    return datetime.now()


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def upsert_runner_state(session: Session, payload: dict[str, Any]) -> DevRunnerState:
    """Create or update a runner state row by runner_id."""

    data = _clean_payload(dict(payload))
    runner_id = data.get("runner_id")
    if not runner_id:
        raise ValueError("runner_id is required")

    row = session.get(DevRunnerState, runner_id)
    if row is None:
        row = DevRunnerState(
            runner_id=runner_id,
            plan_file=data.get("plan_file") or "__ALL_PLANS__",
            project=data.get("project") or "monitor-page",
            status=data.get("status") or "starting",
            started_at=data.get("started_at") or _now(),
            updated_at=data.get("updated_at") or _now(),
            metadata_json=data.get("metadata") or data.get("metadata_json") or {},
        )
        session.add(row)

    for attr in (
        "plan_file",
        "project",
        "status",
        "started_at",
        "branch",
        "worktree_path",
        "exit_reason",
        "merge_requested",
        "completed_at",
    ):
        if attr in data:
            setattr(row, attr, data[attr])
    if "metadata" in data or "metadata_json" in data:
        row.metadata_json = data.get("metadata") or data.get("metadata_json") or {}
    row.updated_at = data.get("updated_at") or _now()
    session.flush()
    return row


def get_runner_state(session: Session, runner_id: str) -> DevRunnerState | None:
    return session.get(DevRunnerState, runner_id)


def list_runner_states(
    session: Session,
    statuses: Iterable[str] | None = None,
    limit: int = 200,
) -> list[DevRunnerState]:
    query = session.query(DevRunnerState)
    if statuses:
        query = query.filter(DevRunnerState.status.in_(list(statuses)))
    return (
        query.order_by(DevRunnerState.updated_at.desc(), DevRunnerState.started_at.desc())
        .limit(limit)
        .all()
    )


def create_merge_request(session: Session, payload: dict[str, Any]) -> DevRunnerMergeRequest:
    data = _clean_payload(dict(payload))
    runner_id = data.get("runner_id")
    if not runner_id:
        raise ValueError("runner_id is required")
    if session.get(DevRunnerState, runner_id) is None:
        upsert_runner_state(
            session,
            {
                "runner_id": runner_id,
                "plan_file": data.get("plan_file") or "__ALL_PLANS__",
                "project": data.get("project") or "monitor-page",
                "status": "머지대기" if data.get("branch") else "stopped",
                "branch": data.get("branch"),
                "worktree_path": data.get("worktree_path"),
                "merge_requested": True,
            },
        )
    row = DevRunnerMergeRequest(
        runner_id=runner_id,
        branch=data.get("branch") or "",
        worktree_path=data.get("worktree_path") or "",
        plan_file=data.get("plan_file") or "__ALL_PLANS__",
        project=data.get("project") or "monitor-page",
        state=data.get("state") or "pending",
        retry_count=int(data.get("retry_count") or 0),
        created_at=data.get("created_at") or _now(),
        claim_token=data.get("claim_token"),
        claimed_at=data.get("claimed_at"),
        completed_at=data.get("completed_at"),
        error_detail=data.get("error_detail"),
    )
    session.add(row)
    session.flush()
    return row


def claim_next_merge_request(session: Session, worker_id: str) -> DevRunnerMergeRequest | None:
    query = (
        session.query(DevRunnerMergeRequest)
        .filter(DevRunnerMergeRequest.state == "pending")
        .order_by(DevRunnerMergeRequest.created_at.asc(), DevRunnerMergeRequest.id.asc())
    )
    try:
        query = query.with_for_update(skip_locked=True)
    except TypeError:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        return None
    row.state = "claimed"
    row.claim_token = worker_id
    row.claimed_at = _now()
    session.flush()
    return row


def complete_merge_request(
    session: Session,
    request_id: int,
    state: str,
    error_detail: str | None = None,
) -> DevRunnerMergeRequest:
    row = session.get(DevRunnerMergeRequest, request_id)
    if row is None:
        raise ValueError(f"merge request not found: {request_id}")
    row.state = state
    row.completed_at = _now()
    row.error_detail = error_detail
    session.flush()
    return row


def list_merge_requests(
    session: Session,
    states: Iterable[str] | None = None,
    limit: int = 200,
) -> list[DevRunnerMergeRequest]:
    query = session.query(DevRunnerMergeRequest)
    if states:
        query = query.filter(DevRunnerMergeRequest.state.in_(list(states)))
    return query.order_by(DevRunnerMergeRequest.created_at.asc(), DevRunnerMergeRequest.id.asc()).limit(limit).all()


def count_merge_requests(session: Session, states: Iterable[str] | None = None) -> int:
    query = session.query(func.count(DevRunnerMergeRequest.id))
    if states:
        query = query.filter(DevRunnerMergeRequest.state.in_(list(states)))
    return int(query.scalar() or 0)
