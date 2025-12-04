"""
MonitorSchedule 라우트 - 일정 API
설계 문서: 2025-12-01_monitoring_restructure_design.md
업데이트: 2025-12-04 - 반복 규칙 엔드포인트 추가
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.monitor_schedule import (
    MonitorSchedule,
    MonitorScheduleUpdate,
)
from app.schemas.recurring_rule import (
    RecurringRuleCreate,
    RecurringRuleUpdate,
    RecurringRuleWithContext,
    PreviewResponse,
)
from app.services.schedule_service import schedule_service
from app.services.recurring_rule_service import recurring_rule_service

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


# =====================================================
# 반복 규칙 (Recurring Rules) - 모니터링용
# =====================================================

@router.get("/recurring")
def get_recurring_rules(
    is_enabled: Optional[bool] = Query(None, description="활성화 상태로 필터링"),
    biz_item_id: Optional[int] = Query(None, description="아이템 ID로 필터링"),
    search: Optional[str] = Query(None, description="이름/업체명/아이템명 검색"),
    db: Session = Depends(get_db)
):
    """
    반복 모니터링 규칙 목록 조회

    모니터링용 반복 규칙만 반환합니다 (type=monitor).
    """
    return recurring_rule_service.get_all_with_context(
        db,
        rule_type="monitor",
        is_enabled=is_enabled,
        biz_item_id=biz_item_id,
        search=search,
    )


@router.post("/recurring")
def create_recurring_rule(data: RecurringRuleCreate, db: Session = Depends(get_db)):
    """
    반복 모니터링 규칙 생성

    매주 지정된 요일/시간에 모니터링 일정을 자동 생성합니다.
    """
    # 타입 강제 설정
    data.type = "monitor"
    rule = recurring_rule_service.create(db, data)
    return recurring_rule_service.get_all_with_context(
        db, rule_type="monitor", biz_item_id=rule.biz_item_id
    )[0] if rule else None


@router.get("/recurring/{rule_id}")
def get_recurring_rule(rule_id: int, db: Session = Depends(get_db)):
    """반복 모니터링 규칙 상세 조회"""
    rules = recurring_rule_service.get_all_with_context(db, rule_type="monitor")
    for rule in rules:
        if rule["id"] == rule_id:
            return rule
    raise HTTPException(status_code=404, detail="Recurring rule not found")


@router.put("/recurring/{rule_id}")
def update_recurring_rule(
    rule_id: int,
    data: RecurringRuleUpdate,
    db: Session = Depends(get_db)
):
    """반복 모니터링 규칙 수정"""
    rule = recurring_rule_service.update(db, rule_id, data)
    if not rule:
        raise HTTPException(status_code=404, detail="Recurring rule not found")
    return recurring_rule_service.get_all_with_context(
        db, rule_type="monitor", biz_item_id=rule.biz_item_id
    )[0] if rule else None


@router.delete("/recurring/{rule_id}", status_code=204)
def delete_recurring_rule(rule_id: int, db: Session = Depends(get_db)):
    """반복 모니터링 규칙 삭제"""
    success = recurring_rule_service.delete(db, rule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Recurring rule not found")
    return None


@router.post("/recurring/{rule_id}/enable")
def enable_recurring_rule(rule_id: int, db: Session = Depends(get_db)):
    """반복 모니터링 규칙 활성화"""
    rule = recurring_rule_service.enable(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Recurring rule not found")
    return {"success": True, "next_trigger_at": rule.next_trigger_at.isoformat() if rule.next_trigger_at else None}


@router.post("/recurring/{rule_id}/disable")
def disable_recurring_rule(rule_id: int, db: Session = Depends(get_db)):
    """반복 모니터링 규칙 비활성화"""
    rule = recurring_rule_service.disable(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Recurring rule not found")
    return {"success": True}


@router.post("/recurring/{rule_id}/trigger")
def trigger_recurring_rule(rule_id: int, db: Session = Depends(get_db)):
    """
    반복 모니터링 규칙 수동 트리거

    즉시 모니터링 일정을 생성합니다 (테스트/수동 실행용).
    """
    result = recurring_rule_service.trigger(db, rule_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", "Trigger failed"))
    return result


@router.get("/recurring/{rule_id}/preview", response_model=PreviewResponse)
def preview_recurring_rule(rule_id: int, db: Session = Depends(get_db)):
    """
    반복 모니터링 규칙 미리보기

    트리거 시 생성될 일정 목록을 반환합니다.
    """
    preview = recurring_rule_service.preview(db, rule_id)
    if not preview:
        raise HTTPException(status_code=404, detail="Recurring rule not found")
    return preview


@router.get("/unified")
def get_unified_schedules(
    item_type: Optional[str] = Query(None, description="all|recurring|single"),
    is_enabled: Optional[bool] = Query(None, description="활성화 상태로 필터링"),
    biz_item_id: Optional[int] = Query(None, description="아이템 ID로 필터링"),
    search: Optional[str] = Query(None, description="검색어"),
    db: Session = Depends(get_db)
):
    """
    통합 일정 조회 (반복 규칙 + 단발 일정)

    일정관리 페이지에서 반복 규칙과 단발 일정을 섞어서 표시할 때 사용합니다.
    """
    items = []

    # 반복 규칙 조회
    if item_type in (None, "all", "recurring"):
        recurring_rules = recurring_rule_service.get_all_with_context(
            db,
            rule_type="monitor",
            is_enabled=is_enabled,
            biz_item_id=biz_item_id,
            search=search,
        )
        for rule in recurring_rules:
            items.append({
                "item_type": "recurring",
                **rule
            })

    # 단발 일정 조회
    if item_type in (None, "all", "single"):
        single_schedules = schedule_service.get_all_with_context(
            db,
            is_enabled=is_enabled,
            biz_item_id=biz_item_id,
            search=search,
        )
        # recurring_rule_id가 없는 것만 (반복 규칙에서 생성되지 않은 것)
        for schedule in single_schedules:
            if not schedule.get("recurring_rule_id"):
                items.append({
                    "item_type": "single",
                    **schedule
                })

    return {"items": items}
