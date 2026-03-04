"""워크플로우 API — dev-runner 브랜치/계획서/runner 생명주기 이력 조회"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import redis as sync_redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.workflow import Workflow
from app.modules.dev_runner.schemas import WorkflowResponse, WorkflowCreateRequest

ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"

router = APIRouter()


def _to_response(wf: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=wf.id,
        slug=wf.slug,
        plan_file=wf.plan_file,
        branch=wf.branch,
        runner_id=wf.runner_id,
        status=wf.status,
        engine=wf.engine,
        error_message=wf.error_message,
        commit_hash=wf.commit_hash,
        worktree_path=wf.worktree_path,
        created_at=wf.created_at,
        started_at=wf.started_at,
        merged_at=wf.merged_at,
        finished_at=wf.finished_at,
    )


@router.get("", response_model=List[WorkflowResponse])
async def list_workflows(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """워크플로우 목록 조회 (status 필터, 최신순)"""
    query = db.query(Workflow)
    if status:
        query = query.filter(Workflow.status == status)
    workflows = query.order_by(Workflow.created_at.desc()).offset(offset).limit(limit).all()
    return [_to_response(wf) for wf in workflows]


@router.get("/orphans", response_model=List[WorkflowResponse])
async def list_orphan_workflows(db: Session = Depends(get_db)):
    """고아 워크플로우 조회 — DB에 running/merge_pending이지만 Redis active_runners에 없는 항목"""
    r = sync_redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    try:
        workflows = db.query(Workflow).filter(
            Workflow.status.in_(["running", "merge_pending"])
        ).all()
        orphans = []
        for wf in workflows:
            if wf.runner_id and not r.sismember(ACTIVE_RUNNERS_KEY, wf.runner_id):
                orphans.append(_to_response(wf))
        return orphans
    finally:
        r.close()


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: int, db: Session = Depends(get_db)):
    """워크플로우 상세 조회"""
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    return _to_response(wf)


@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(req: WorkflowCreateRequest, db: Session = Depends(get_db)):
    """워크플로우 수동 생성 (plan_file 선택적)"""
    # slug 생성
    if req.slug:
        slug = req.slug
    elif req.plan_file:
        basename = os.path.splitext(os.path.basename(req.plan_file))[0]
        if basename.endswith("_todo"):
            basename = basename[:-5]
        slug = basename
    else:
        slug = f"manual-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # slug 중복 체크
    existing = db.query(Workflow).filter(Workflow.slug == slug).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Workflow with slug '{slug}' already exists")

    wf = Workflow(
        slug=slug,
        plan_file=req.plan_file,
        status="planned",
        created_at=datetime.now(),
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return _to_response(wf)


@router.patch("/{workflow_id}/cancel", response_model=WorkflowResponse)
async def cancel_workflow(workflow_id: int, db: Session = Depends(get_db)):
    """워크플로우 취소 (planned/running 상태만 가능)"""
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    if wf.status not in ("planned", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel workflow in status '{wf.status}' (only planned/running allowed)"
        )

    wf.status = "cancelled"
    wf.finished_at = datetime.now()
    db.commit()
    db.refresh(wf)
    return _to_response(wf)


@router.patch("/{workflow_id}/reset", response_model=WorkflowResponse)
async def reset_workflow(workflow_id: int, cleanup_worktree: bool = False, db: Session = Depends(get_db)):
    """고아 워크플로우 개별 리셋 — running/merge_pending/merging/planned → failed"""
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    if wf.status not in ("running", "merge_pending", "merging", "planned"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reset workflow in status '{wf.status}'"
        )

    wf.status = "failed"
    wf.error_message = "수동 리셋"
    wf.finished_at = datetime.now()

    if cleanup_worktree and wf.worktree_path:
        try:
            scripts_dir = str(Path(__file__).resolve().parents[4] / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from worktree_manager import WorktreeManager
            WorktreeManager.remove(wf.runner_id, Path(wf.worktree_path).parent)
        except Exception:
            pass

    db.commit()
    db.refresh(wf)
    return _to_response(wf)


@router.post("/reset-all-orphans")
async def reset_all_orphans(db: Session = Depends(get_db)):
    """고아 워크플로우 일괄 리셋"""
    r = sync_redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    try:
        workflows = db.query(Workflow).filter(
            Workflow.status.in_(["running", "merge_pending"])
        ).all()
        count = 0
        for wf in workflows:
            if wf.runner_id and not r.sismember(ACTIVE_RUNNERS_KEY, wf.runner_id):
                wf.status = "failed"
                wf.error_message = "일괄 리셋"
                wf.finished_at = datetime.now()
                count += 1
        db.commit()
        return {"reset_count": count}
    finally:
        r.close()
