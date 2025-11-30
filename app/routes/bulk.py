"""
일괄 작업 API 엔드포인트

프로세스 분리 아키텍처:
    - API 서버: DB 상태만 변경
    - 워커: DB를 확인하여 실제 모니터링 수행

- URL 일괄 임포트
- 일괄 시작/중지 (DB 상태 변경으로)
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

from app.services.monitoring_system_manager import MonitoringSystemManager
from app.schemas.monitor import MonitorTargetCreate
from app.dependencies import get_monitoring_manager
from app.config import logger

router = APIRouter(
    prefix="/bulk",
    tags=["bulk"]
)


# ============================================================
# Request/Response 스키마
# ============================================================

class BulkImportItem(BaseModel):
    """일괄 임포트 항목"""
    url: str
    label: str
    date: Optional[str] = None
    times: Optional[List[str]] = None
    category: Optional[str] = "default"
    service_type: Optional[str] = "naver"
    time_range: Optional[str] = None
    auto_booking_enabled: Optional[bool] = False


class BulkImportRequest(BaseModel):
    """일괄 임포트 요청"""
    items: List[BulkImportItem]
    start_monitoring: bool = False  # 임포트 후 즉시 모니터링 시작


class BulkImportResponse(BaseModel):
    """일괄 임포트 응답"""
    success_count: int
    failed_count: int
    results: List[Dict[str, Any]]


class BulkActionRequest(BaseModel):
    """일괄 작업 요청"""
    target_ids: Optional[List[int]] = None  # None이면 전체
    filter_service_type: Optional[str] = None
    filter_category: Optional[str] = None


class BulkActionResponse(BaseModel):
    """일괄 작업 응답"""
    affected_count: int
    results: List[Dict[str, Any]]


# ============================================================
# API 엔드포인트
# ============================================================

@router.post("/import", response_model=BulkImportResponse)
async def bulk_import(
    request: BulkImportRequest,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """
    URL을 일괄 임포트합니다.

    - 여러 URL을 한 번에 등록
    - start_monitoring=True이면 pending 상태로 설정하여 워커가 자동 시작
    """
    results = []
    success_count = 0
    failed_count = 0

    for item in request.items:
        try:
            # base_url 추출
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(item.url)
            base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

            # 날짜 추출 (URL에서)
            date = item.date
            if not date:
                query_params = parse_qs(parsed.query)
                date = query_params.get('startDate', [None])[0] or \
                       query_params.get('startDateTime', [''])[0][:10] or \
                       datetime.now().strftime('%Y-%m-%d')

            # MonitorTargetCreate 생성
            target_data = MonitorTargetCreate(
                url=item.url,
                base_url=base_url,
                label=item.label,
                date=date,
                times=item.times or [],
                category=item.category or "default",
                service_type=item.service_type or "naver"
            )

            # 데이터베이스에 저장
            new_target = await monitoring_manager.create_target(target_data)

            # 예약 관련 설정 업데이트
            update_data = {}
            if item.time_range:
                update_data["time_range"] = item.time_range
            if item.auto_booking_enabled:
                update_data["auto_booking_enabled"] = item.auto_booking_enabled

            # 모니터링 시작 여부
            if request.start_monitoring:
                update_data["is_active"] = True
                update_data["run_status"] = "pending"  # 워커가 감지하여 시작

            if update_data:
                await monitoring_manager.update_target(new_target.id, update_data)

            results.append({
                "url": item.url,
                "label": item.label,
                "success": True,
                "target_id": new_target.id
            })
            success_count += 1

        except Exception as e:
            logger.error(f"URL 임포트 실패 ({item.url}): {e}")
            results.append({
                "url": item.url,
                "label": item.label,
                "success": False,
                "error": str(e)
            })
            failed_count += 1

    return BulkImportResponse(
        success_count=success_count,
        failed_count=failed_count,
        results=results
    )


@router.post("/start", response_model=BulkActionResponse)
async def bulk_start(
    request: BulkActionRequest,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """
    모니터링을 일괄 시작합니다.

    - target_ids가 지정되면 해당 대상만
    - 지정되지 않으면 필터 조건에 맞는 모든 대상
    - DB 상태만 pending으로 변경, 워커가 자동으로 시작
    """
    results = []

    # 대상 조회
    filters = {}
    if request.filter_service_type:
        filters["service_type"] = request.filter_service_type
    if request.filter_category:
        filters["category"] = request.filter_category

    if request.target_ids:
        targets = [await monitoring_manager.get_target(tid) for tid in request.target_ids]
        targets = [t for t in targets if t is not None]
    else:
        targets = await monitoring_manager.get_targets(filters)

    for target in targets:
        try:
            # DB 상태 변경 - 워커가 감지하여 시작
            await monitoring_manager.update_target(target.id, {
                "is_enabled": True,
                "is_active": True,
                "run_status": "pending"
            })

            results.append({
                "target_id": target.id,
                "label": target.label,
                "success": True
            })

        except Exception as e:
            logger.error(f"모니터링 시작 실패 (ID: {target.id}): {e}")
            results.append({
                "target_id": target.id,
                "label": target.label,
                "success": False,
                "error": str(e)
            })

    return BulkActionResponse(
        affected_count=len([r for r in results if r["success"]]),
        results=results
    )


@router.post("/stop", response_model=BulkActionResponse)
async def bulk_stop(
    request: BulkActionRequest,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """
    모니터링을 일괄 중지합니다.

    DB 상태만 stopped로 변경, 워커가 감지하여 중지
    """
    results = []

    # 대상 조회
    filters = {}
    if request.filter_service_type:
        filters["service_type"] = request.filter_service_type
    if request.filter_category:
        filters["category"] = request.filter_category

    if request.target_ids:
        targets = [await monitoring_manager.get_target(tid) for tid in request.target_ids]
        targets = [t for t in targets if t is not None]
    else:
        targets = await monitoring_manager.get_targets(filters)

    for target in targets:
        try:
            # DB 상태 변경 - 워커가 감지하여 중지
            await monitoring_manager.update_target(target.id, {
                "is_enabled": False,
                "is_active": False,
                "run_status": "stopped"
            })

            results.append({
                "target_id": target.id,
                "label": target.label,
                "success": True
            })

        except Exception as e:
            logger.error(f"모니터링 중지 실패 (ID: {target.id}): {e}")
            results.append({
                "target_id": target.id,
                "label": target.label,
                "success": False,
                "error": str(e)
            })

    return BulkActionResponse(
        affected_count=len([r for r in results if r["success"]]),
        results=results
    )


@router.post("/pause", response_model=BulkActionResponse)
async def bulk_pause(
    request: BulkActionRequest,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """
    모니터링을 일괄 일시 중지합니다 (is_enabled=False).

    DB 상태만 paused로 변경, 워커가 감지하여 일시 중지
    """
    results = []

    if request.target_ids:
        targets = [await monitoring_manager.get_target(tid) for tid in request.target_ids]
        targets = [t for t in targets if t is not None]
    else:
        filters = {"is_enabled": True}  # 활성화된 대상만
        if request.filter_service_type:
            filters["service_type"] = request.filter_service_type
        targets = await monitoring_manager.get_targets(filters)

    for target in targets:
        try:
            # DB 상태 변경 - 워커가 감지하여 일시 중지
            await monitoring_manager.update_target(target.id, {
                "is_enabled": False,
                "run_status": "paused"
            })

            results.append({
                "target_id": target.id,
                "label": target.label,
                "success": True
            })

        except Exception as e:
            results.append({
                "target_id": target.id,
                "label": target.label,
                "success": False,
                "error": str(e)
            })

    return BulkActionResponse(
        affected_count=len([r for r in results if r["success"]]),
        results=results
    )


@router.delete("/delete", response_model=BulkActionResponse)
async def bulk_delete(
    request: BulkActionRequest,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """
    대상을 일괄 삭제합니다.

    주의: 이 작업은 되돌릴 수 없습니다.
    """
    results = []

    if not request.target_ids:
        raise HTTPException(
            status_code=400,
            detail="target_ids를 지정해야 합니다. 전체 삭제는 지원하지 않습니다."
        )

    for target_id in request.target_ids:
        try:
            # 먼저 중지 상태로 변경 (워커가 감지)
            await monitoring_manager.update_target(target_id, {
                "is_active": False,
                "run_status": "stopped"
            })

            # 삭제
            success = await monitoring_manager.delete_target(target_id)

            results.append({
                "target_id": target_id,
                "success": success
            })

        except Exception as e:
            logger.error(f"대상 삭제 실패 (ID: {target_id}): {e}")
            results.append({
                "target_id": target_id,
                "success": False,
                "error": str(e)
            })

    return BulkActionResponse(
        affected_count=len([r for r in results if r["success"]]),
        results=results
    )
