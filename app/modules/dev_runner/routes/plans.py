"""plan 문서 관리 API"""

import asyncio
import base64
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.dev_runner.schemas import PlanFileResponse, PlanProgressResponse, PlanDetailResponse, RegisteredPathResponse, DoneResponse, BatchDoneResponse, VerifyResult
from app.modules.dev_runner.services.plan_service import plan_service
from app.modules.dev_runner.services import archive_service
from app.modules.dev_runner.services.plan_record_service import PlanRecordService

logger = logging.getLogger(__name__)

router = APIRouter()


def _decode_path(encoded: str) -> str:
    """URL-safe base64 디코딩 (패딩 자동 복원)"""
    padded = encoded + '=' * ((4 - len(encoded) % 4) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8")


@router.get("/plans", response_model=List[PlanFileResponse])
async def get_plans():
    """plan 목록 조회 (등록된 경로 탐색)"""
    return await asyncio.to_thread(plan_service.list_plans)


@router.get("/plans/ignored", response_model=List[PlanFileResponse])
async def get_ignored_plans():
    """무시된(완료/빈) plan 목록 조회"""
    return await asyncio.to_thread(plan_service.list_ignored_plans)


@router.get("/plans/paths", response_model=List[RegisteredPathResponse])
async def get_paths():
    """등록된 경로 목록 조회 (타입 + plan_count 포함)"""
    return plan_service.list_registered_paths()


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

    return plan_service.parse_plan_items(path)


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
    """프로젝트 루트 경로 등록 — docs/plan(plan) + docs/archive(archive) 동시 등록"""
    if not plan_service.validate_path(request.path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    root = Path(request.path)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    added = []
    skipped = []

    for sub, path_type in [("docs/plan", "plan"), ("docs/archive", "archive")]:
        sub_path = root / sub
        if not sub_path.exists():
            skipped.append(f"{sub_path} ({path_type}, not found)")
            continue
        if plan_service.add_path(str(sub_path), path_type=path_type):
            added.append(f"{sub_path} ({path_type})")
        else:
            skipped.append(f"{sub_path} ({path_type}, already registered)")

    return {"added": added, "skipped": skipped}


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
    return {"success": added, "path": decoded_path}


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
    return {"success": True}


@router.post("/plans/{encoded_path}/done", response_model=DoneResponse)
async def run_plan_done(encoded_path: str):
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

    result = await plan_service.run_done(decoded_path)
    return DoneResponse(**result)


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
    return {"success": True}


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
    return {"success": True}


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

    return {"path": decoded_path, "status": new_status}


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
