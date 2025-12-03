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


def _fill_account_name(schedule):
    """schedule에 account_name 채우기"""
    if schedule and schedule.account:
        schedule.account_name = schedule.account.name
    return schedule


def _fill_account_names(schedules):
    """여러 schedule에 account_name 채우기"""
    for schedule in schedules:
        _fill_account_name(schedule)
    return schedules


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
    from sqlalchemy.orm import joinedload
    from app.models.monitor_schedule import MonitorSchedule as ScheduleModel

    if is_enabled is True:
        schedules = db.query(ScheduleModel).options(
            joinedload(ScheduleModel.account)
        ).filter(
            ScheduleModel.is_enabled == True
        ).order_by(ScheduleModel.date).all()
    elif is_enabled is False:
        schedules = db.query(ScheduleModel).options(
            joinedload(ScheduleModel.account)
        ).filter(
            ScheduleModel.is_enabled == False
        ).order_by(ScheduleModel.date).all()
    else:
        schedules = db.query(ScheduleModel).options(
            joinedload(ScheduleModel.account)
        ).order_by(ScheduleModel.date).all()

    return _fill_account_names(schedules)


@router.get("/with-context")
def get_schedules_with_context(
    is_enabled: Optional[bool] = Query(None, description="활성화 상태로 필터링"),
    business_id: Optional[int] = Query(None, description="업체 ID로 필터링"),
    biz_item_id: Optional[int] = Query(None, description="아이템 ID로 필터링"),
    date_from: Optional[str] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="업체명/아이템명 검색"),
    db: Session = Depends(get_db)
):
    """
    전체 일정 + 상위 컨텍스트 조회 (일정 관리 페이지용)

    업체/아이템 정보를 포함하여 반환합니다.
    """
    return schedule_service.get_all_with_context(
        db,
        is_enabled=is_enabled,
        business_id=business_id,
        biz_item_id=biz_item_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )


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
    return _fill_account_name(schedule)


@router.put("/{schedule_id}", response_model=MonitorSchedule)
def update_schedule(schedule_id: int, data: MonitorScheduleUpdate, db: Session = Depends(get_db)):
    """일정 수정"""
    schedule = schedule_service.update(db, schedule_id, data)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    # 다시 로드하여 account 정보 포함
    schedule = schedule_service.get_by_id(db, schedule_id)
    return _fill_account_name(schedule)


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
    schedule = schedule_service.get_by_id(db, schedule_id)
    return _fill_account_name(schedule)


@router.post("/{schedule_id}/disable", response_model=MonitorSchedule)
def disable_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """일정 비활성화 (is_enabled=false, run_status=paused)"""
    schedule = schedule_service.disable(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    schedule = schedule_service.get_by_id(db, schedule_id)
    return _fill_account_name(schedule)
