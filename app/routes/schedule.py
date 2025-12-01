"""
MonitorSchedule 라우트 - 일정 API
설계 문서: 2025-12-01_monitoring_restructure_design.md
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.monitor_schedule import (
    MonitorSchedule,
    MonitorScheduleUpdate,
)
from app.services.schedule_service import schedule_service

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])


@router.get("/", response_model=List[MonitorSchedule])
def get_all_schedules(
    is_enabled: Optional[bool] = Query(None, description="활성화 상태로 필터링"),
    db: Session = Depends(get_db)
):
    """
    전체 일정 목록 조회

    - is_enabled=true: 활성화된 일정만
    - is_enabled=false: 비활성화된 일정만
    - 파라미터 없음: 전체 일정
    """
    if is_enabled is True:
        return schedule_service.get_all_enabled(db)
    elif is_enabled is False:
        # 비활성화된 일정 조회 (필요시 서비스에 추가)
        from app.models.monitor_schedule import MonitorSchedule as ScheduleModel
        return db.query(ScheduleModel).filter(
            ScheduleModel.is_enabled == False
        ).order_by(ScheduleModel.date).all()
    else:
        from app.models.monitor_schedule import MonitorSchedule as ScheduleModel
        return db.query(ScheduleModel).order_by(ScheduleModel.date).all()


@router.get("/active")
def get_active_schedules(db: Session = Depends(get_db)):
    """
    활성화된 일정 + 상위 컨텍스트 조회 (워커용)

    워커에서 모니터링에 필요한 모든 정보를 포함하여 반환합니다.
    """
    return schedule_service.get_enabled_with_context(db)


@router.get("/{schedule_id}", response_model=MonitorSchedule)
def get_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """일정 상세 조회"""
    schedule = schedule_service.get_by_id(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.put("/{schedule_id}", response_model=MonitorSchedule)
def update_schedule(schedule_id: int, data: MonitorScheduleUpdate, db: Session = Depends(get_db)):
    """일정 수정"""
    schedule = schedule_service.update(db, schedule_id, data)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """일정 삭제"""
    success = schedule_service.delete(db, schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return None


@router.post("/{schedule_id}/enable", response_model=MonitorSchedule)
def enable_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """일정 활성화 (is_enabled=true, run_status=pending)"""
    schedule = schedule_service.enable(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.post("/{schedule_id}/disable", response_model=MonitorSchedule)
def disable_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """일정 비활성화 (is_enabled=false, run_status=paused)"""
    schedule = schedule_service.disable(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule
