from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional
import logging

from app.schemas.monitor import MonitorTarget, MonitorTargetCreate, MonitorTargetUpdate
from app.services.monitor_service import MonitorService
from app.dependencies import get_browser_service
from app.config import logger

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

@router.post("/targets", response_model=None)
async def create_monitor_target(
    target: MonitorTargetCreate,
    background_tasks: BackgroundTasks,
    monitor_service: MonitorService = Depends(),
    browser_service = Depends(get_browser_service)
):
    """새로운 모니터링 대상을 추가합니다."""
    try:
        # 로깅 향상
        logger.info(f"모니터링 대상 추가 요청 시작")
        logger.info(f"요청 데이터: {repr(target)}")
        logger.info(f"타입: {type(target)}")
        
        # 데이터 직접 출력
        for k, v in target.__dict__.items():
            logger.info(f"필드 {k} = {v} (타입: {type(v)})")
        
        # 데이터베이스에 저장
        new_target = await monitor_service.create_target(target)
        logger.info(f"모니터링 대상 생성 성공: ID {new_target.id}")
        
        # 백그라운드에서 모니터링 시작
        data_dict = {
            "id": new_target.id,
            "url": str(new_target.url),
            "base_url": str(new_target.base_url),
            "label": new_target.label,
            "date": new_target.date,
            "times": new_target.times,
            "category": new_target.category,
            "service_type": new_target.service_type,
            "is_active": new_target.is_active,
            "interval": new_target.interval,
            "custom_interval": new_target.custom_interval,
            "created_at": new_target.created_at.isoformat(),
            "updated_at": new_target.updated_at.isoformat()
        }
        
        logger.info(f"백그라운드 태스크에 전달할 데이터: {data_dict}")
        
        # 백그라운드에서 모니터링 시작
        background_tasks.add_task(
            browser_service.start_monitoring,
            data_dict
        )
        
        logger.info(f"모니터링 대상 추가 완료: ID {new_target.id}")
        
        # 성공 메시지와 함께 응답 반환
        return {
            "success": True,
            "message": "모니터링 대상이 성공적으로 등록되었습니다.",
            "data": {
                "id": new_target.id,
                "url": str(new_target.url),
                "label": new_target.label,
                "date": new_target.date
            }
        }
    except HTTPException as ex:
        # HTTP 예외는 그대로 전달
        logger.warning(f"HTTP 예외 발생: {ex.detail} (상태 코드: {ex.status_code})")
        raise
    except Exception as e:
        logger.error(f"모니터링 대상 추가 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"서버 오류가 발생했습니다: {str(e)}")

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
    browser_service = Depends(get_browser_service)
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
    browser_service = Depends(get_browser_service)
):
    """특정 모니터링 대상의 모니터링을 중지합니다."""
    success = await browser_service.stop_monitoring(target_id)
    if not success:
        raise HTTPException(status_code=404, detail="실행 중인 모니터링을 찾을 수 없습니다")
    return {"status": "monitoring_stopped"} 