"""
PlanExecutionClaim 서비스

claim lifecycle:
  queued → active → released
                 → stale (heartbeat 만료)

> 실행점유: {claim_id} 헤더 포인터와 DB row를 한 계약으로 갱신한다.
pid는 관측 필드이며 식별자 아님. 식별자는 claim_id(UUID4)와 DB row다.
"""
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models.plan_execution_claim import PlanExecutionClaim
from app.modules.dev_runner.services.plan_frontmatter import (
    write_claim_id,
    clear_claim_id,
    read_claim_id,
)

logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 300  # 5분 — heartbeat 없으면 stale 후보
STALE_THRESHOLD_SECONDS = 600  # 10분 — heartbeat_at 기준 stale 판정


def claim_plan(
    db: Session,
    plan_path: str,
    *,
    engine: Optional[str] = None,
    session_id: Optional[str] = None,
    runner_id: Optional[str] = None,
    plan_record_id: Optional[int] = None,
    queue_after: Optional[datetime] = None,
    claim_metadata: Optional[dict] = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    write_header: bool = True,
) -> PlanExecutionClaim:
    """plan_path에 대한 queued claim을 생성하고 필요 시 헤더 포인터를 기록한다.

    중복 active/queued claim이 있으면 ClaimConflictError를 발생시킨다.
    """
    existing = get_active_claim_for_plan(db, plan_path)
    if existing:
        raise ClaimConflictError(
            f"plan already claimed: claim_id={existing.claim_id} state={existing.state}",
            existing,
        )

    claim_id = str(uuid.uuid4())
    now = datetime.now()
    metadata = dict(claim_metadata or {})
    metadata.setdefault("header_written", bool(write_header))
    claim = PlanExecutionClaim(
        claim_id=claim_id,
        plan_record_id=plan_record_id,
        plan_path=plan_path,
        state="queued",
        engine=engine,
        session_id=session_id,
        runner_id=runner_id,
        host=_hostname(),
        claimed_at=now,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
        queue_after=queue_after,
        claim_metadata=metadata,
    )
    db.add(claim)
    db.flush()

    if write_header:
        _write_header(plan_path, claim_id)
    db.commit()
    return claim


def activate_claim(
    db: Session,
    claim_id: str,
    *,
    runner_id: Optional[str] = None,
    pid: Optional[int] = None,
    branch: Optional[str] = None,
    worktree_path: Optional[str] = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> PlanExecutionClaim:
    """queued → active 전환. runner spawn 성공 시 호출한다."""
    claim = _get_claim(db, claim_id)
    now = datetime.now()
    claim.state = "active"
    if runner_id:
        claim.runner_id = runner_id
    if pid:
        claim.pid = pid
    if branch:
        claim.branch = branch
    if worktree_path:
        claim.worktree_path = worktree_path
    claim.heartbeat_at = now
    claim.lease_expires_at = now + timedelta(seconds=lease_seconds)
    db.commit()
    return claim


def heartbeat_claim(
    db: Session,
    claim_id: str,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> PlanExecutionClaim:
    """heartbeat_at과 lease_expires_at을 갱신한다."""
    claim = _get_claim(db, claim_id)
    now = datetime.now()
    claim.heartbeat_at = now
    claim.lease_expires_at = now + timedelta(seconds=lease_seconds)
    db.commit()
    return claim


def release_claim(
    db: Session,
    claim_id: str,
) -> PlanExecutionClaim:
    """active/queued → released 전환. 헤더 포인터를 빈 값으로 초기화한다."""
    claim = _get_claim(db, claim_id)
    claim.state = "released"
    claim.released_at = datetime.now()
    db.commit()

    metadata = claim.claim_metadata if isinstance(claim.claim_metadata, dict) else {}
    if metadata.get("header_written", True):
        _clear_header(claim.plan_path)
    return claim


def mark_stale_claims(db: Session, threshold_seconds: int = STALE_THRESHOLD_SECONDS) -> list[PlanExecutionClaim]:
    """heartbeat_at 또는 lease_expires_at 기준으로 만료된 active/queued claim을 stale로 전환한다.

    stale claim은 자동 탈취하지 않는다. UI/API에서 명시 release/reclaim 절차를 거친다.
    """
    cutoff = datetime.now() - timedelta(seconds=threshold_seconds)
    now = datetime.now()
    candidates = (
        db.query(PlanExecutionClaim)
        .filter(
            PlanExecutionClaim.state.in_(["queued", "active"]),
            PlanExecutionClaim.lease_expires_at < now,
        )
        .all()
    )
    stale = []
    for claim in candidates:
        if claim.state == "queued" or claim.heartbeat_at is None or claim.heartbeat_at < cutoff:
            claim.state = "stale"
            stale.append(claim)
    if stale:
        db.commit()
    return stale


def get_claim_for_plan(db: Session, plan_path: str) -> Optional[PlanExecutionClaim]:
    """plan_path의 가장 최근 claim을 반환 (상태 무관)."""
    return (
        db.query(PlanExecutionClaim)
        .filter(PlanExecutionClaim.plan_path == plan_path)
        .order_by(PlanExecutionClaim.claimed_at.desc())
        .first()
    )


def get_active_claim_for_plan(db: Session, plan_path: str) -> Optional[PlanExecutionClaim]:
    """plan_path의 active 또는 queued claim을 반환."""
    return (
        db.query(PlanExecutionClaim)
        .filter(
            PlanExecutionClaim.plan_path == plan_path,
            PlanExecutionClaim.state.in_(["queued", "active"]),
        )
        .order_by(PlanExecutionClaim.claimed_at.desc())
        .first()
    )


def get_active_claim_for_runner(db: Session, runner_id: str) -> Optional[PlanExecutionClaim]:
    """runner_id의 active 또는 queued claim을 반환."""
    if not runner_id:
        return None
    return (
        db.query(PlanExecutionClaim)
        .filter(
            PlanExecutionClaim.runner_id == runner_id,
            PlanExecutionClaim.state.in_(["queued", "active"]),
        )
        .order_by(PlanExecutionClaim.claimed_at.desc())
        .first()
    )


def get_active_claims_map(db: Session, plan_paths: list[str]) -> dict[str, PlanExecutionClaim]:
    """plan_path 목록에 대한 active/queued claim을 dict{plan_path→claim}으로 반환."""
    if not plan_paths:
        return {}
    rows = (
        db.query(PlanExecutionClaim)
        .filter(
            PlanExecutionClaim.plan_path.in_(plan_paths),
            PlanExecutionClaim.state.in_(["queued", "active"]),
        )
        .all()
    )
    result: dict[str, PlanExecutionClaim] = {}
    for row in rows:
        if row.plan_path not in result or row.claimed_at > result[row.plan_path].claimed_at:
            result[row.plan_path] = row
    return result


class ClaimConflictError(Exception):
    def __init__(self, message: str, existing_claim: PlanExecutionClaim):
        super().__init__(message)
        self.existing_claim = existing_claim


# ─── internal helpers ────────────────────────────────────────────────────────


def _get_claim(db: Session, claim_id: str) -> PlanExecutionClaim:
    claim = db.query(PlanExecutionClaim).filter(PlanExecutionClaim.claim_id == claim_id).first()
    if not claim:
        raise ValueError(f"claim not found: {claim_id}")
    return claim


def _hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "unknown"


def _write_header(plan_path: str, claim_id: str) -> None:
    try:
        write_claim_id(Path(plan_path), claim_id)
    except Exception as e:
        logger.warning("claim header write failed: %s — %s", plan_path, e)


def _clear_header(plan_path: str) -> None:
    try:
        clear_claim_id(Path(plan_path))
    except Exception as e:
        logger.warning("claim header clear failed: %s — %s", plan_path, e)
