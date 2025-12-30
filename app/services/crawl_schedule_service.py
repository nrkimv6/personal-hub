"""크롤링 스케줄 서비스."""

from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from app.models import CrawlSchedule, CrawlScheduleRun


class CrawlScheduleService:
    """크롤링 스케줄 관리 서비스."""

    def __init__(self, db: Session):
        self.db = db

    def create_schedule(
        self,
        name: str,
        target_type: str,
        schedule_type: str,
        display_name: Optional[str] = None,
        target_config: Optional[dict] = None,
        schedule_value: Optional[str] = None,
        enabled: bool = True
    ) -> CrawlSchedule:
        """새 스케줄 생성."""
        schedule = CrawlSchedule(
            name=name,
            display_name=display_name,
            target_type=target_type,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            enabled=enabled
        )
        if target_config:
            schedule.set_target_config(target_config)

        self.db.add(schedule)
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def get_schedule_by_name(self, name: str) -> Optional[CrawlSchedule]:
        """이름으로 스케줄 조회."""
        return self.db.query(CrawlSchedule).filter(
            CrawlSchedule.name == name
        ).first()

    def get_schedule_by_id(self, schedule_id: int) -> Optional[CrawlSchedule]:
        """ID로 스케줄 조회."""
        return self.db.query(CrawlSchedule).filter(
            CrawlSchedule.id == schedule_id
        ).first()

    def get_schedules_by_type(
        self,
        target_type: str,
        enabled_only: bool = True
    ) -> list[CrawlSchedule]:
        """타입별 스케줄 조회."""
        query = self.db.query(CrawlSchedule).filter(
            CrawlSchedule.target_type == target_type
        )
        if enabled_only:
            query = query.filter(CrawlSchedule.enabled == True)
        return query.all()

    def get_due_schedules(self) -> list[CrawlSchedule]:
        """실행 대기 중인 스케줄 조회."""
        now = datetime.now()
        return self.db.query(CrawlSchedule).filter(
            CrawlSchedule.enabled == True,
            CrawlSchedule.next_run_at <= now
        ).all()

    def update_schedule(
        self,
        schedule_id: int,
        **updates
    ) -> Optional[CrawlSchedule]:
        """스케줄 업데이트."""
        schedule = self.get_schedule_by_id(schedule_id)
        if not schedule:
            return None

        for key, value in updates.items():
            if key == "target_config" and isinstance(value, dict):
                schedule.set_target_config(value)
            elif hasattr(schedule, key):
                setattr(schedule, key, value)

        schedule.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def toggle_schedule(self, schedule_id: int, enabled: bool) -> Optional[CrawlSchedule]:
        """스케줄 활성화/비활성화."""
        return self.update_schedule(schedule_id, enabled=enabled)

    def start_run(
        self,
        schedule_id: int,
        worker_id: Optional[str] = None,
        config_snapshot: Optional[dict] = None
    ) -> CrawlScheduleRun:
        """스케줄 실행 시작."""
        run = CrawlScheduleRun(
            schedule_id=schedule_id,
            started_at=datetime.now(),
            status=CrawlScheduleRun.STATUS_RUNNING,
            worker_id=worker_id
        )
        if config_snapshot:
            run.set_config_snapshot(config_snapshot)

        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def complete_run(
        self,
        run_id: int,
        collected_count: int,
        saved_count: int,
        stop_reason: Optional[str] = None
    ) -> Optional[CrawlScheduleRun]:
        """실행 완료 처리."""
        run = self.db.query(CrawlScheduleRun).filter(
            CrawlScheduleRun.id == run_id
        ).first()

        if run:
            run.mark_completed(collected_count, saved_count, stop_reason)
            self.db.commit()
            self.db.refresh(run)
        return run

    def fail_run(
        self,
        run_id: int,
        error_message: str
    ) -> Optional[CrawlScheduleRun]:
        """실행 실패 처리."""
        run = self.db.query(CrawlScheduleRun).filter(
            CrawlScheduleRun.id == run_id
        ).first()

        if run:
            run.mark_failed(error_message)
            self.db.commit()
            self.db.refresh(run)
        return run

    def update_schedule_after_run(
        self,
        schedule_id: int,
        next_run_at: Optional[datetime] = None
    ):
        """실행 후 스케줄 상태 업데이트."""
        schedule = self.get_schedule_by_id(schedule_id)
        if schedule:
            schedule.update_last_run(next_run_at)
            self.db.commit()

    def get_runs_paginated(
        self,
        schedule_id: Optional[int] = None,
        page: int = 1,
        limit: int = 20,
        status: Optional[str] = None
    ) -> dict:
        """실행 이력 페이징 조회."""
        query = self.db.query(CrawlScheduleRun)

        if schedule_id:
            query = query.filter(CrawlScheduleRun.schedule_id == schedule_id)
        if status:
            query = query.filter(CrawlScheduleRun.status == status)

        total = query.count()
        items = query.order_by(
            CrawlScheduleRun.started_at.desc()
        ).offset((page - 1) * limit).limit(limit).all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }

    def get_latest_run(self, schedule_id: int) -> Optional[CrawlScheduleRun]:
        """스케줄의 최신 실행 조회."""
        return self.db.query(CrawlScheduleRun).filter(
            CrawlScheduleRun.schedule_id == schedule_id
        ).order_by(CrawlScheduleRun.started_at.desc()).first()

    def get_run_stats(
        self,
        schedule_id: Optional[int] = None,
        days: int = 7
    ) -> dict:
        """실행 통계 조회."""
        since = datetime.now() - timedelta(days=days)

        query = self.db.query(CrawlScheduleRun).filter(
            CrawlScheduleRun.started_at >= since
        )
        if schedule_id:
            query = query.filter(CrawlScheduleRun.schedule_id == schedule_id)

        runs = query.all()

        total_runs = len(runs)
        completed_runs = sum(1 for r in runs if r.status == CrawlScheduleRun.STATUS_COMPLETED)
        failed_runs = sum(1 for r in runs if r.status == CrawlScheduleRun.STATUS_FAILED)
        total_collected = sum(r.collected_count or 0 for r in runs)
        total_saved = sum(r.saved_count or 0 for r in runs)

        return {
            "period_days": days,
            "total_runs": total_runs,
            "completed_runs": completed_runs,
            "failed_runs": failed_runs,
            "success_rate": completed_runs / total_runs * 100 if total_runs > 0 else 0,
            "total_collected": total_collected,
            "total_saved": total_saved
        }
