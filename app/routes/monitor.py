from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional

from app.schemas.monitor import MonitorTarget, MonitorTargetCreate, MonitorTargetUpdate
from app.services.monitor_service import MonitorService
from app.services.browser_service import BrowserService

router = APIRouter(
    prefix="/monitor",
    tags=["monitor"]
)

@router.get("/targets", response_model=List[MonitorTarget])
async def get_monitor_targets(
    service_type: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    monitor_service: MonitorService = Depends()
):
    """모니터링 대상 목록을 조회합니다."""
    filters = {}
    if service_type:
        filters["service_type"] = service_type
    if category:
        filters["category"] = category
    if is_active is not None:
        filters["is_active"] = is_active
    
    return await monitor_service.get_targets(filters)

@router.post("/targets", response_model=MonitorTarget)
async def create_monitor_target(
    target: MonitorTargetCreate,
    background_tasks: BackgroundTasks,
    monitor_service: MonitorService = Depends(),
    browser_service: BrowserService = Depends()
):
    """새로운 모니터링 대상을 추가합니다."""
    new_target = await monitor_service.create_target(target)
    # 백그라운드에서 모니터링 시작
    background_tasks.add_task(
        browser_service.start_monitoring,
        new_target.dict()
    )
    return new_target

@router.get("/targets/{target_id}", response_model=MonitorTarget)
async def get_monitor_target(
    target_id: int,
    monitor_service: MonitorService = Depends()
):
    """특정 모니터링 대상의 상세 정보를 조회합니다."""
    target = await monitor_service.get_target(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")
    return target

@router.put("/targets/{target_id}", response_model=MonitorTarget)
async def update_monitor_target(
    target_id: int,
    target: MonitorTargetUpdate,
    monitor_service: MonitorService = Depends()
):
    """모니터링 대상의 정보를 수정합니다."""
    updated_target = await monitor_service.update_target(target_id, target)
    if not updated_target:
        raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")
    return updated_target

@router.delete("/targets/{target_id}")
async def delete_monitor_target(
    target_id: int,
    monitor_service: MonitorService = Depends()
):
    """모니터링 대상을 삭제합니다."""
    success = await monitor_service.delete_target(target_id)
    if not success:
        raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")
    return {"status": "success"}

@router.post("/targets/{target_id}/start")
async def start_monitoring(
    target_id: int,
    background_tasks: BackgroundTasks,
    monitor_service: MonitorService = Depends(),
    browser_service: BrowserService = Depends()
):
    """특정 모니터링 대상의 모니터링을 시작합니다."""
    target = await monitor_service.get_target(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")
    
    background_tasks.add_task(
        browser_service.start_monitoring,
        target.dict()
    )
    return {"status": "monitoring_started"}

@router.post("/targets/{target_id}/stop")
async def stop_monitoring(
    target_id: int,
    browser_service: BrowserService = Depends()
):
    """특정 모니터링 대상의 모니터링을 중지합니다."""
    success = await browser_service.stop_monitoring(target_id)
    if not success:
        raise HTTPException(status_code=404, detail="실행 중인 모니터링을 찾을 수 없습니다")
    return {"status": "monitoring_stopped"} 