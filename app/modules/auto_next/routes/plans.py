"""plan 문서 관리 API"""

import base64
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from app.modules.auto_next.schemas import PlanFileResponse, PlanProgressResponse
from app.modules.auto_next.services.plan_service import plan_service

router = APIRouter()


@router.get("/plans", response_model=List[PlanFileResponse])
async def get_plans():
    """plan 목록 조회"""
    return plan_service.list_plans()


@router.get("/plans/{encoded_path}", response_model=PlanProgressResponse)
async def get_plan_progress(encoded_path: str):
    """특정 plan 진행률 조회 (base64 인코딩된 경로)"""
    try:
        # base64 디코딩
        decoded_path = base64.urlsafe_b64decode(encoded_path).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid encoded path")

    # 경로 화이트리스트 검증
    if not plan_service.validate_external_path(decoded_path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    path = Path(decoded_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    return plan_service.get_plan_progress(path)


class AddExternalPlanRequest(BaseModel):
    """외부 plan 추가 요청"""
    path: str


@router.post("/plans/add-external")
async def add_external_plan(request: AddExternalPlanRequest):
    """외부 plan 경로 추가 (메모리 캐시 - 향후 JSON 파일로 영구 저장 가능)"""
    # 경로 검증
    if not plan_service.validate_external_path(request.path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    # TODO: 영구 저장소에 추가 (현재는 메모리 캐시만)
    return {"message": "External plan added (memory cache)", "path": request.path}


__all__ = ['router']
