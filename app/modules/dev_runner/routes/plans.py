"""plan 문서 관리 API"""

import asyncio
import base64
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.dev_runner.schemas import (
    BatchDoneResponse,
    DoneResponse,
    PlanDetailResponse,
    PlanFileResponse,
    PlanProgressResponse,
    PlanStorageRootChangeItem,
    PlanStorageRootStatusItem,
    PlanStorageRootStatusResponse,
    RegisteredPathResponse,
    VerifyResult,
)
from app.modules.dev_runner.services.plan_service import plan_service
from app.modules.dev_runner.services import archive_service
from app.modules.dev_runner.services.plan_record_service import PlanRecordService
from app.modules.dev_runner.services.plan_path_helpers import (
    collect_plan_storage_root_candidates,
    iter_repo_plan_path_candidates,
)
from app.modules.dev_runner.services.worktree_hygiene_service import WorktreeHygieneService

logger = logging.getLogger(__name__)

router = APIRouter()


def _decode_path(encoded: str) -> str:
    """URL-safe base64 디코딩 (패딩 자동 복원)"""
    padded = encoded + '=' * ((4 - len(encoded) % 4) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8")


def _parse_short_status_line(line: str) -> PlanStorageRootChangeItem:
    status = line[:2].strip() or "?"
    path = line[3:] if len(line) > 3 and line[2] == " " else line[2:].lstrip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return PlanStorageRootChangeItem(status=status, path=path)


def _status_from_counts(*, exists: bool, dirty_count: int, ahead: int, behind: int, push_needed: bool) -> str:
    if not exists:
        return "missing"
    if dirty_count > 0:
        return "dirty"
    if push_needed or ahead > 0 or behind > 0:
        return "sync_needed"
    return "clean"


def _unknown_storage_root_item(project: str, repo_root: Path, worktree_path: Path, error: Exception) -> PlanStorageRootStatusItem:
    checked_at = datetime.now().isoformat(timespec="seconds")
    return PlanStorageRootStatusItem(
        project=project,
        repo_root=str(repo_root),
        worktree_path=str(worktree_path),
        exists=worktree_path.exists(),
        status="unknown",
        checked_at=checked_at,
        error=str(error),
    )


def _collect_plan_storage_roots_status_sync() -> PlanStorageRootStatusResponse:
    checked_at = datetime.now().isoformat(timespec="seconds")
    registered_paths = plan_service.list_registered_paths()
    candidates = collect_plan_storage_root_candidates(registered_paths)
    roots: list[PlanStorageRootStatusItem] = []

    for candidate in candidates:
        if not candidate.worktree_path.exists():
            roots.append(
                PlanStorageRootStatusItem(
                    project=candidate.project,
                    repo_root=str(candidate.repo_root),
                    worktree_path=str(candidate.worktree_path),
                    exists=False,
                    status="missing",
                    checked_at=checked_at,
                )
            )
            continue

        try:
            snapshot = WorktreeHygieneService(candidate.repo_root).collect()
            plans = snapshot.plans
            dirty_count = len(plans.git_status)
            ahead = plans.upstream_ahead
            behind = plans.upstream_behind
            status = (
                _status_from_counts(
                    exists=plans.exists,
                    dirty_count=dirty_count,
                    ahead=ahead,
                    behind=behind,
                    push_needed=plans.push_needed,
                )
                if plans.branch
                else "unknown"
            )
            roots.append(
                PlanStorageRootStatusItem(
                    project=candidate.project,
                    repo_root=str(candidate.repo_root),
                    worktree_path=str(candidate.worktree_path),
                    branch=plans.branch,
                    upstream=plans.upstream,
                    exists=plans.exists,
                    status=status,
                    dirty_count=dirty_count,
                    docs_changes_count=len(plans.docs_changes),
                    archive_changes_count=len(plans.archive_changes),
                    policy_changes_count=len(plans.policy_changes),
                    ahead=ahead,
                    behind=behind,
                    push_needed=plans.push_needed,
                    checked_at=snapshot.collected_at or checked_at,
                    representative_changes=[
                        _parse_short_status_line(line)
                        for line in plans.git_status[:8]
                    ],
                )
            )
        except Exception as exc:
            logger.warning("plans storage root status failed: %s", candidate.worktree_path, exc_info=True)
            roots.append(
                _unknown_storage_root_item(
                    candidate.project,
                    candidate.repo_root,
                    candidate.worktree_path,
                    exc,
                )
            )

    return PlanStorageRootStatusResponse(
        checked_at=checked_at,
        roots=roots,
        total=len(roots),
        dirty_count=sum(1 for item in roots if item.dirty_count > 0),
        push_needed_count=sum(1 for item in roots if item.push_needed),
    )


@router.get("/plans", response_model=List[PlanFileResponse])
async def get_plans(db: Session = Depends(get_db)):
    """plan 목록 조회 (등록된 경로 탐색, active claim 정보 포함)"""
    plans = await asyncio.to_thread(plan_service.list_plans)
    try:
        from app.modules.dev_runner.services.plan_execution_claim_service import get_active_claims_map
        from datetime import datetime
        plan_paths = [p.path for p in plans]
        claims_map = get_active_claims_map(db, plan_paths)
        now = datetime.now()
        for plan in plans:
            claim = claims_map.get(plan.path)
            if claim:
                stale = claim.lease_expires_at is not None and claim.lease_expires_at < now
                plan.execution_claim_id = claim.claim_id
                plan.execution_claim_state = claim.state
                plan.execution_claim_runner_id = claim.runner_id
                plan.execution_claim_stale = stale
    except Exception as _e:
        logger.warning(f"[claim] plan 목록 claim enrichment 실패 (무시): {_e}")
    return plans


@router.delete("/plans/{encoded_path}/claim")
async def release_plan_claim(encoded_path: str, db: Session = Depends(get_db)):
    """plan의 active/queued claim을 강제 해제 (관리자 액션)"""
    plan_path = _decode_path(encoded_path)
    from app.modules.dev_runner.services.plan_execution_claim_service import (
        get_active_claim_for_plan,
        release_claim,
    )
    claim = get_active_claim_for_plan(db, plan_path)
    if not claim:
        raise HTTPException(status_code=404, detail="active claim not found")
    release_claim(db, claim.claim_id)
    return {"ok": True, "claim_id": claim.claim_id}


@router.get("/plans/ignored", response_model=List[PlanFileResponse])
async def get_ignored_plans():
    """무시된(완료/빈) plan 목록 조회"""
    return await asyncio.to_thread(plan_service.list_ignored_plans)


@router.get("/plans/paths", response_model=List[RegisteredPathResponse])
async def get_paths():
    """등록된 경로 목록 조회 (타입 + plan_count 포함)"""
    return plan_service.list_registered_paths()


@router.get("/plans/storage-roots/status", response_model=PlanStorageRootStatusResponse)
async def get_plan_storage_roots_status():
    """등록된 plan storage root별 dirty/ahead/behind compact 상태 조회."""
    return await asyncio.to_thread(_collect_plan_storage_roots_status_sync)


@router.get("/plans/{encoded_path}", response_model=PlanProgressResponse)
async def get_plan_progress(encoded_path: str):
    """특정 plan 진행률 조회 (base64 인코딩된 경로)"""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        logger.error(f"Base64 디코딩 실패: encoded_path={encoded_path}, error={e}")
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    if not plan_service.validate_path(decoded_path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    path = Path(decoded_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    return plan_service.get_plan_progress(path)


@router.get("/plans/{encoded_path}/content")
async def get_plan_content(encoded_path: str):
    """plan 파일 원본 내용 조회 (Markdown 텍스트)"""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        logger.error(f"Base64 디코딩 실패: encoded_path={encoded_path}, error={e}")
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    if not plan_service.validate_path(decoded_path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    path = Path(decoded_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")

    return {"content": content, "path": decoded_path}


@router.get("/plans/{encoded_path}/items", response_model=PlanDetailResponse)
async def get_plan_items(encoded_path: str):
    """plan 항목 상세 조회 (Phase별 체크박스 파싱)"""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        logger.error(f"Base64 디코딩 실패: encoded_path={encoded_path}, error={e}")
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    if not plan_service.validate_path(decoded_path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    path = Path(decoded_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    return await asyncio.to_thread(plan_service.parse_plan_items, path)


@router.post("/plans/{encoded_path}/summary", status_code=202)
async def generate_plan_summary(encoded_path: str, db: Session = Depends(get_db)):
    """plan 요약 생성 — LLM Worker 큐에 투입 후 202 반환"""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    if not plan_service.validate_path(decoded_path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    path = Path(decoded_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    request_id = await plan_service.generate_summary(path, db)
    return {"request_id": request_id}


class AddPathRequest(BaseModel):
    """경로 등록 요청"""
    path: str
    path_type: str = "plan"  # "plan" | "archive"


@router.post("/plans/paths")
async def add_path(request: AddPathRequest):
    """경로 등록 (JSON 파일로 영구 저장)"""
    if not plan_service.validate_path(request.path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    added = plan_service.add_path(request.path, path_type=request.path_type)
    fs_type = "folder" if path.is_dir() else "file"
    return {"success": added, "path": request.path, "type": fs_type, "path_type": request.path_type}


class AddProjectRequest(BaseModel):
    """프로젝트 등록 요청 (plan + archive 경로 동시 등록)"""
    path: str


@router.post("/plans/paths/project")
async def add_project(request: AddProjectRequest):
    """프로젝트 루트 경로 등록 — docs/* + .worktrees/plans/docs/* 4축 전부 등록"""
    if not plan_service.validate_path(request.path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    root = Path(request.path)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    added = []
    skipped = []

    for candidate_path, path_type in iter_repo_plan_path_candidates(root):
        if not candidate_path.exists():
            skipped.append(f"{candidate_path} ({path_type}, not found)")
            continue
        if plan_service.add_path(str(candidate_path), path_type=path_type):
            added.append(f"{candidate_path} ({path_type})")
        else:
            skipped.append(f"{candidate_path} ({path_type}, already registered)")

    worktree_count = sum(1 for a in added if ".worktrees" in a)
    docs_count = len(added) - worktree_count
    message = f"등록 완료 — added {len(added)}개 (worktree {worktree_count}개, docs {docs_count}개), skipped {len(skipped)}개"
    return {"added": added, "skipped": skipped, "message": message}


@router.delete("/plans/paths")
async def remove_path(request: AddPathRequest):
    """등록 경로 제거"""
    removed = plan_service.remove_path(request.path)
    if not removed:
        raise HTTPException(status_code=404, detail="Registered path not found")
    return {"success": True}


@router.post("/plans/{encoded_path}/ignore")
async def ignore_plan(encoded_path: str):
    """plan을 수동 무시 목록에 추가"""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    added = plan_service.add_to_ignore(decoded_path)
    plans = plan_service.list_plans()
    return {"success": added, "path": decoded_path, "plans": [p.model_dump() for p in plans]}


@router.delete("/plans/{encoded_path}/ignore")
async def unignore_plan(encoded_path: str):
    """plan을 수동 무시 목록에서 제거"""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    removed = plan_service.remove_from_ignore(decoded_path)
    if not removed:
        raise HTTPException(status_code=404, detail="Plan not in ignore list")
    plans = plan_service.list_plans()
    return {"success": True, "plans": [p.model_dump() for p in plans]}


@router.post("/plans/{encoded_path}/done", response_model=DoneResponse)
async def run_plan_done(
    encoded_path: str,
    runner_id: Optional[str] = None,
    x_plan_runner_id: Optional[str] = Header(default=None, alias="X-Plan-Runner-Id"),
):
    """plan 완료 처리 (아카이브, TODO→DONE, 커밋)"""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    if not plan_service.validate_path(decoded_path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    path = Path(decoded_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    effective_runner_id = x_plan_runner_id or runner_id
    result = await plan_service.run_done(decoded_path, runner_id=effective_runner_id)
    plans = plan_service.list_plans()
    return {**result, "plans": [p.model_dump() for p in plans]}


@router.post("/plans/batch-done", response_model=BatchDoneResponse)
async def batch_done():
    """완료 가능한 plan 일괄 done 처리 (아카이브, TODO→DONE, 커밋)"""
    result = await plan_service.batch_done()
    return BatchDoneResponse(**result)


@router.get("/plans/{encoded_path}/verify", response_model=VerifyResult)
async def verify_plan(encoded_path: str):
    """plan 완료 검증 — 코드베이스와 체크박스를 대조하여 완료 여부 판정"""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        logger.error(f"Base64 디코딩 실패: encoded_path={encoded_path}, error={e}")
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    if not plan_service.validate_path(decoded_path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    path = Path(decoded_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    return plan_service.verify_completion(path)


@router.post("/plans/batch-verify-done", response_model=BatchDoneResponse)
async def batch_verify_done():
    """코드베이스 검증 기반으로 완료 가능한 plan 일괄 done 처리"""
    all_plans = plan_service.list_plans(include_ignored=True)
    targets = []
    for plan in all_plans:
        path = Path(plan.path)
        if not path.exists():
            continue
        result = plan_service.verify_completion(path)
        if result.can_done:
            targets.append(plan)

    if not targets:
        return BatchDoneResponse(total=0, success=0, failed=0, results=[])

    results = []
    success_count = 0
    failed_count = 0

    for plan in targets:
        done_result = await plan_service.run_done(plan.path)
        results.append({
            "path": plan.path,
            "filename": plan.filename,
            "success": done_result["success"],
            "message": done_result["message"],
        })
        if done_result["success"]:
            success_count += 1
        else:
            failed_count += 1

    return BatchDoneResponse(
        total=len(targets),
        success=success_count,
        failed=failed_count,
        results=results,
    )


@router.post("/plans/{encoded_path}/hold")
async def hold_plan(encoded_path: str):
    """plan 상태를 '보류'로 변경"""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    if not plan_service.validate_path(decoded_path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    success = plan_service.set_plan_status(decoded_path, "보류")
    if not success:
        raise HTTPException(status_code=404, detail="Plan file not found or no title")
    plans = plan_service.list_plans()
    return {"success": True, "plans": [p.model_dump() for p in plans]}


@router.delete("/plans/{encoded_path}/hold")
async def unhold_plan(encoded_path: str):
    """plan 보류 해제 (상태를 '구현중'으로 변경)"""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    if not plan_service.validate_path(decoded_path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    success = plan_service.set_plan_status(decoded_path, "구현중")
    if not success:
        raise HTTPException(status_code=404, detail="Plan file not found or no title")
    plans = plan_service.list_plans()
    return {"success": True, "plans": [p.model_dump() for p in plans]}


@router.post("/plans/sync")
async def sync_plans():
    """plan 동기화 (재스캔) — 변경 요약 반환"""
    return plan_service.sync_plans()


class UpdateStatusRequest(BaseModel):
    status: str


@router.patch("/plans/{encoded_path}/status")
async def update_plan_status(encoded_path: str, body: UpdateStatusRequest):
    """plan 파일의 상태 필드를 업데이트한다."""
    try:
        decoded_path = _decode_path(encoded_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid encoded path: {str(e)}")

    if not plan_service.validate_path(decoded_path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    try:
        new_status = plan_service.update_plan_status(decoded_path, body.status)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    plans = plan_service.list_plans()
    return {"path": decoded_path, "status": new_status, "plans": [p.model_dump() for p in plans]}


# ── Archive 정리 ──────────────────────────────────────────────

def _get_archive_dirs() -> list[Path]:
    """등록된 경로 중 type='archive'인 디렉토리 목록을 반환한다."""
    paths = plan_service.list_registered_paths()
    return [Path(p.path) for p in paths if p.path_type == "archive" and Path(p.path).is_dir()]


@router.get("/plans/archive/preview")
async def archive_preview():
    """archive 폴더 정리 미리보기 — 이동 계획 반환 (실제 이동 없음)

    Returns:
        {"dirs": [{"archive_dir": str, "items": [...]}]}
    """
    dirs = _get_archive_dirs()
    if not dirs:
        return {"dirs": [], "message": "등록된 archive 경로가 없습니다."}

    result = []
    for d in dirs:
        items = archive_service.preview_organize(d)
        result.append({"archive_dir": str(d), "items": items})

    return {"dirs": result}


class OrganizeRequest(BaseModel):
    """정리 실행 요청 (선택 항목만 이동)"""
    archive_dir: Optional[str] = None  # None이면 등록된 모든 archive 경로 대상
    items: Optional[list[dict]] = None  # None이면 전체 이동


@router.post("/plans/archive/organize")
async def archive_organize(
    request: OrganizeRequest = OrganizeRequest(),
    db: Session = Depends(get_db),
):
    """archive 폴더 정리 실행 — 파일 이동 + DB file_path 업데이트 + path_changed 이벤트 기록

    Returns:
        {"results": [{"archive_dir": str, "moved": [...], "skipped": int, "errors": [...], "removed_dirs": [...]}]}
    """
    if request.archive_dir:
        target_dir = Path(request.archive_dir)
        if not plan_service.validate_path(request.archive_dir):
            raise HTTPException(status_code=403, detail="Path not allowed")
        if not target_dir.is_dir():
            raise HTTPException(status_code=404, detail="Archive directory not found")
        dirs = [target_dir]
    else:
        dirs = _get_archive_dirs()

    if not dirs:
        return {"results": [], "message": "등록된 archive 경로가 없습니다."}

    svc = PlanRecordService(db)
    all_results = []

    for d in dirs:
        org_result = archive_service.organize_archive(d)

        # DB 업데이트: 이동된 파일에 대해 file_path 갱신 + path_changed 이벤트
        for move in org_result["moved"]:
            try:
                record = svc.get_or_create(move["source"])
                old_path = record.file_path
                record.file_path = move["dest"]
                from datetime import datetime
                record.updated_at = datetime.now()
                from app.modules.dev_runner.services.plan_record_service import _add_event
                _add_event(db, record, "path_changed", {"from": old_path, "to": move["dest"]})
            except Exception as e:
                logger.warning(f"DB 업데이트 실패: {move['source']} → {move['dest']}: {e}")

        db.commit()
        all_results.append({"archive_dir": str(d), **org_result})

    return {"results": all_results}


@router.get("/plans/archive/duplicates")
async def archive_duplicates(similarity: float = 0.85):
    """archive 폴더 내 중복 파일 후보 감지

    Args:
        similarity: 유사도 임계값 (0~1, 기본 0.85)

    Returns:
        {"dirs": [{"archive_dir": str, "duplicates": [...]}]}
    """
    dirs = _get_archive_dirs()
    if not dirs:
        return {"dirs": [], "message": "등록된 archive 경로가 없습니다."}

    result = []
    for d in dirs:
        dupes = archive_service.detect_duplicates(d, similarity_threshold=similarity)
        result.append({"archive_dir": str(d), "duplicates": dupes})

    return {"dirs": result}


__all__ = ['router']
