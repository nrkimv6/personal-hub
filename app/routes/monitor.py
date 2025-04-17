from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime, date
import asyncio

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

@router.get("/targets/{target_id}", response_model=Dict[str, Any])
async def get_target_by_id(
    target_id: int,
    monitor_service: MonitorService = Depends(),
    browser_service = Depends(get_browser_service)
):
    """특정 ID의 모니터링 대상을 조회합니다."""
    try:
        target = await monitor_service.get_target(target_id)
        if not target:
            raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")
        
        target_dict = target.dict()
        
        # 태스크 실행 상태 추가
        is_monitoring = target_id in browser_service.monitoring_tasks and not browser_service.monitoring_tasks[target_id].done()
        target_dict["is_monitoring"] = is_monitoring
        
        # 태스크 상세 정보
        task_info = {}
        if target_id in browser_service.monitoring_tasks:
            task = browser_service.monitoring_tasks[target_id]
            task_info["done"] = task.done()
            task_info["cancelled"] = task.cancelled()
            if task.done() and not task.cancelled():
                try:
                    # 태스크가 예외로 종료된 경우 예외 정보 제공
                    exc = task.exception()
                    if exc:
                        task_info["exception"] = str(exc)
                except asyncio.InvalidStateError:
                    # 태스크가 아직 완료되지 않음
                    pass
        
        target_dict["task_info"] = task_info
        
        return target_dict
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"대상 조회 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"대상 조회 중 오류 발생: {str(e)}")

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
    
    # is_enabled 필드를 True로 설정
    await monitor_service.update_target(target_id, {"is_enabled": True})
    
    background_tasks.add_task(
        browser_service.start_monitoring,
        target.dict()
    )
    return {"status": "monitoring_started"}

@router.post("/targets/{target_id}/pause")
async def pause_monitoring(
    target_id: int,
    browser_service = Depends(get_browser_service),
    monitor_service: MonitorService = Depends()
):
    """특정 모니터링 대상의 모니터링을 일시 중지합니다. (is_enabled=False 설정)"""
    target = await monitor_service.get_target(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")
    
    # is_enabled 필드만 False로 설정 (is_active는 유지)
    await monitor_service.update_target(target_id, {"is_enabled": False})
    
    # 현재 실행 중이면 중지
    if target_id in browser_service.monitoring_tasks and not browser_service.monitoring_tasks[target_id].done():
        await browser_service.stop_monitoring(target_id)
    
    return {"status": "monitoring_paused"}

@router.post("/targets/{target_id}/stop")
async def stop_monitoring(
    target_id: int, 
    background_tasks: BackgroundTasks,
    browser_service = Depends(get_browser_service)
):
    """특정 모니터링 대상의 모니터링을 중지합니다."""
    background_tasks.add_task(browser_service.stop_monitoring, target_id)
    return {"status": "monitoring_stopped"}

@router.get("/stats", response_model=Dict[str, Any])
async def get_monitoring_stats(
    browser_service = Depends(get_browser_service),
    monitor_service: MonitorService = Depends()
):
    """모니터링 시스템 통계 정보를 조회합니다."""
    try:
        logger.debug(f"통계 정보 요청 시작")
        
        # 전체 대상 수 조회
        all_targets = await monitor_service.get_targets()
        total_count = len(all_targets)
        logger.debug(f"전체 대상 수: {total_count}")
        
        # 활성 대상 수 조회
        active_targets = await monitor_service.get_targets({"is_active": True})
        active_count = len(active_targets)
        logger.debug(f"활성 대상 수: {active_count}")
        
        # 활성화된 대상 수 조회 (사용자 설정)
        enabled_targets = await monitor_service.get_targets({"is_enabled": True})
        enabled_count = len(enabled_targets)
        logger.debug(f"사용자 활성화 대상 수: {enabled_count}")
        
        # 실행 중인 대상 수 조회
        running_targets = await monitor_service.get_targets({"run_status": "running"})
        running_count = len(running_targets)
        logger.debug(f"실행 중인 대상 수: {running_count}")
        
        # 오류 상태 대상 수 조회
        error_targets = await monitor_service.get_targets({"run_status": "error"})
        error_count = len(error_targets)
        logger.debug(f"오류 상태 대상 수: {error_count}")
        
        # 오늘의 변경 수 (임시로 활성 태스크 수로 대체)
        active_tasks = len(browser_service.monitoring_tasks)
        logger.debug(f"활성 태스크 수: {active_tasks}")
        
        # 실행 중인 브라우저 컨텍스트 수
        browser_contexts = len(browser_service.browser_contexts)
        logger.debug(f"브라우저 컨텍스트 수: {browser_contexts}")
        
        # 탭 풀 정보
        tab_pools = {}
        for target_id, pool in browser_service.tab_pools.items():
            tab_pools[str(target_id)] = len(pool)
        logger.debug(f"탭 풀 정보: {tab_pools}")
        
        # 현재 시각
        current_time = datetime.now()
        
        # 시스템 상태 정보
        stats = {
            "total_targets": total_count,
            "active_targets": active_count,
            "enabled_targets": enabled_count,
            "running_targets": running_count,
            "error_targets": error_count,
            "active_tasks": active_tasks,
            "browser_contexts": browser_contexts,
            "tab_pools": tab_pools,
            "server_time": current_time.isoformat(),
            "changes_today": active_count  # 임시로 활성 대상 수와 동일하게 설정
        }
        
        logger.info(f"시스템 통계 조회 완료: {stats}")
        return stats
    except Exception as e:
        logger.error(f"통계 정보 조회 실패: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"통계 정보 조회 실패: {str(e)}")

@router.post("/fix-database")
async def fix_database(
    monitor_service: MonitorService = Depends()
):
    """데이터베이스 손상 문제를 수정합니다."""
    try:
        fixed_count = await monitor_service.fix_invalid_times()
        return {
            "status": "success", 
            "message": f"데이터베이스 수정 완료. {fixed_count}개의 손상된 레코드가 수정되었습니다."
        }
    except Exception as e:
        logger.error(f"데이터베이스 수정 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"데이터베이스 수정 실패: {str(e)}") 