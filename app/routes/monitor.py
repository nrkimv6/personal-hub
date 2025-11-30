"""
모니터링 대상 관리 API

프로세스 분리 아키텍처:
    - API 서버: DB 상태만 변경
    - 워커: DB를 확인하여 실제 모니터링 수행
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime, date
import asyncio

from app.schemas.monitor import MonitorTarget, MonitorTargetCreate, MonitorTargetUpdate
from app.services.monitoring_system_manager import MonitoringSystemManager
from app.dependencies import get_monitoring_manager
from app.config import logger
from app.database import SessionLocal
from sqlalchemy import text

router = APIRouter(
    prefix="/monitor",
    tags=["monitor"]
)


def get_worker_status_from_db() -> dict:
    """데이터베이스에서 워커 상태를 조회합니다."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT pid, status, active_tasks FROM worker_status WHERE id = 1
        """)).fetchone()
        if result:
            return {
                "pid": result[0],
                "status": result[1],
                "active_tasks": result[2] or 0
            }
        return {"pid": None, "status": "not_started", "active_tasks": 0}
    except Exception:
        return {"pid": None, "status": "unknown", "active_tasks": 0}
    finally:
        db.close()


@router.get("/targets", response_model=List[MonitorTarget])
async def get_monitor_targets(
    service_type: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """모니터링 대상 목록을 조회합니다."""
    filters = {}
    if service_type:
        filters["service_type"] = service_type
    if category:
        filters["category"] = category
    if is_active is not None:
        filters["is_active"] = is_active

    targets = await monitoring_manager.get_targets(filters)
    return targets


@router.post("/targets", response_model=None)
async def create_monitor_target(
    target: MonitorTargetCreate,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """새로운 모니터링 대상을 추가합니다."""
    try:
        logger.info(f"모니터링 대상 추가 요청 시작")
        logger.info(f"요청 데이터: {repr(target)}")

        # 데이터베이스에 저장
        new_target = await monitoring_manager.create_target(target)
        logger.info(f"모니터링 대상 생성 성공: ID {new_target.id}")

        # run_status를 pending으로 설정하여 워커가 감지하도록 함
        await monitoring_manager.update_target(new_target.id, {
            "is_active": True,
            "run_status": "pending"  # 워커가 이 상태를 감지하여 모니터링 시작
        })

        logger.info(f"모니터링 대상 추가 완료: ID {new_target.id} (워커가 자동으로 시작)")

        return {
            "success": True,
            "message": "모니터링 대상이 성공적으로 등록되었습니다. 워커가 자동으로 모니터링을 시작합니다.",
            "data": {
                "id": new_target.id,
                "url": str(new_target.url),
                "label": new_target.label,
                "date": new_target.date
            }
        }
    except HTTPException as ex:
        logger.warning(f"HTTP 예외 발생: {ex.detail} (상태 코드: {ex.status_code})")
        raise
    except Exception as e:
        logger.error(f"모니터링 대상 추가 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"서버 오류가 발생했습니다: {str(e)}")


@router.get("/targets/{target_id}", response_model=Dict[str, Any])
async def get_target_by_id(
    target_id: int,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """특정 ID의 모니터링 대상을 조회합니다."""
    try:
        target = await monitoring_manager.get_target(target_id)
        if not target:
            raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")

        target_dict = target.dict()

        # DB 기반 모니터링 상태 확인
        is_monitoring = target.run_status in ["running", "queued"]
        target_dict["is_monitoring"] = is_monitoring

        # 태스크 정보 (DB 기반)
        task_info = {
            "run_status": target.run_status,
            "error_count": target.error_count,
            "last_error": target.last_error
        }
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
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """모니터링 대상의 정보를 수정합니다."""
    updated_target = await monitoring_manager.update_target(target_id, target)
    if not updated_target:
        raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")
    return updated_target


@router.delete("/targets/{target_id}")
async def delete_monitor_target(
    target_id: int,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """모니터링 대상을 삭제합니다."""
    # 먼저 중지 상태로 변경
    await monitoring_manager.update_target(target_id, {"run_status": "stopped", "is_active": False})

    success = await monitoring_manager.delete_target(target_id)
    if not success:
        raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")
    return {"status": "success"}


@router.post("/targets/{target_id}/start")
async def start_monitoring(
    target_id: int,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """특정 모니터링 대상의 모니터링을 시작합니다."""
    target = await monitoring_manager.get_target(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")

    # DB 상태만 변경 - 워커가 감지하여 시작
    await monitoring_manager.update_target(target_id, {
        "is_enabled": True,
        "is_active": True,
        "run_status": "pending"  # 워커가 이 상태를 감지
    })

    return {"status": "monitoring_started", "message": "워커가 자동으로 모니터링을 시작합니다."}


@router.post("/targets/{target_id}/pause")
async def pause_monitoring(
    target_id: int,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """특정 모니터링 대상의 모니터링을 일시 중지합니다. (is_enabled=False 설정)"""
    target = await monitoring_manager.get_target(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="모니터링 대상을 찾을 수 없습니다")

    # DB 상태만 변경 - 워커가 감지하여 중지
    await monitoring_manager.update_target(target_id, {
        "is_enabled": False,
        "run_status": "paused"
    })

    return {"status": "monitoring_paused", "message": "모니터링이 일시 중지되었습니다."}


@router.post("/targets/{target_id}/stop")
async def stop_monitoring(
    target_id: int,
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """특정 모니터링 대상의 모니터링을 중지합니다."""
    # DB 상태만 변경 - 워커가 감지하여 중지
    await monitoring_manager.update_target(target_id, {
        "is_active": False,
        "run_status": "stopped"
    })

    return {"status": "monitoring_stopped", "message": "모니터링이 중지되었습니다."}


@router.get("/stats", response_model=Dict[str, Any])
async def get_monitoring_stats(
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """모니터링 시스템 통계 정보를 조회합니다."""
    try:
        logger.debug(f"통계 정보 요청 시작")

        # 전체 대상 수 조회
        all_targets = await monitoring_manager.get_targets()
        total_count = len(all_targets)

        # 활성 대상 수 조회
        active_targets = await monitoring_manager.get_targets({"is_active": True})
        active_count = len(active_targets)

        # 활성화된 대상 수 조회 (사용자 설정)
        enabled_targets = await monitoring_manager.get_targets({"is_enabled": True})
        enabled_count = len(enabled_targets)

        # 실행 중인 대상 수 조회
        running_targets = await monitoring_manager.get_targets({"run_status": "running"})
        running_count = len(running_targets)

        # 오류 상태 대상 수 조회
        error_targets = await monitoring_manager.get_targets({"run_status": "error"})
        error_count = len(error_targets)

        # 대기열 대상 수 조회
        queued_targets = await monitoring_manager.get_targets({"run_status": "queued"})
        queued_count = len(queued_targets)

        # 워커 상태 조회
        worker_status = get_worker_status_from_db()

        # 현재 시각
        current_time = datetime.now()

        # 시스템 상태 정보
        stats = {
            "total_targets": total_count,
            "active_targets": active_count,
            "enabled_targets": enabled_count,
            "running_targets": running_count,
            "error_targets": error_count,
            "queued_targets": queued_count,
            "worker_status": worker_status["status"],
            "worker_pid": worker_status["pid"],
            "active_tasks": worker_status["active_tasks"],
            "server_time": current_time.isoformat(),
            "changes_today": active_count
        }

        logger.info(f"시스템 통계 조회 완료: {stats}")
        return stats
    except Exception as e:
        logger.error(f"통계 정보 조회 실패: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"통계 정보 조회 실패: {str(e)}")


@router.post("/fix-database")
async def fix_database(
    monitoring_manager: MonitoringSystemManager = Depends(get_monitoring_manager)
):
    """데이터베이스 손상 문제를 수정합니다."""
    try:
        fixed_count = await monitoring_manager.fix_invalid_times()
        return {
            "status": "success",
            "message": f"데이터베이스 수정 완료. {fixed_count}개의 손상된 레코드가 수정되었습니다."
        }
    except Exception as e:
        logger.error(f"데이터베이스 수정 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"데이터베이스 수정 실패: {str(e)}")
