"""plan 문서 관리 API"""

import base64
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.modules.dev_runner.schemas import PlanFileResponse, PlanProgressResponse, PlanDetailResponse, RegisteredPathResponse, DoneResponse
from app.modules.dev_runner.services.plan_service import plan_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _decode_path(encoded: str) -> str:
    """URL-safe base64 디코딩 (패딩 자동 복원)"""
    padded = encoded + '=' * ((4 - len(encoded) % 4) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8")


@router.get("/plans", response_model=List[PlanFileResponse])
async def get_plans():
    """plan 목록 조회 (등록된 경로 탐색)"""
    return plan_service.list_plans()


@router.get("/plans/ignored", response_model=List[PlanFileResponse])
async def get_ignored_plans():
    """무시된(완료/빈) plan 목록 조회"""
    return plan_service.list_ignored_plans()


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


@router.post("/plans/paths")
async def add_path(request: AddPathRequest):
    """경로 등록 (JSON 파일로 영구 저장)"""
    if not plan_service.validate_path(request.path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    added = plan_service.add_path(request.path)
    path_type = "folder" if path.is_dir() else "file"
    return {"success": added, "path": request.path, "type": path_type}


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


@router.post("/plans/sync")
async def sync_plans():
    """plan 동기화 (재스캔) — 변경 요약 반환"""
    return plan_service.sync_plans()


__all__ = ['router']
