"""Writing Service - 글 생성 관련 비즈니스 로직."""

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.crawl_schedule import CrawlSchedule, CrawlScheduleRun
from app.models.writing import WritingSource, GeneratedWriting


class WritingService:
    """글 생성 서비스."""

    def __init__(self, db: Session):
        self.db = db

    # ========== 생성된 글 조회 ==========

    def list_generated_writings(
        self,
        task_type: Optional[str] = None,
        rating: Optional[int] = None,
        include_deleted: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """생성된 글 목록 조회."""
        query = self.db.query(GeneratedWriting)

        if not include_deleted:
            query = query.filter(GeneratedWriting.deleted_at.is_(None))

        if task_type:
            query = query.filter(GeneratedWriting.task_type == task_type)

        if rating is not None:
            if rating == 0:
                # 미평가
                query = query.filter(GeneratedWriting.rating.is_(None))
            else:
                query = query.filter(GeneratedWriting.rating == rating)

        total = query.count()
        items = (
            query.order_by(GeneratedWriting.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total > 0 else 1,
        }

    def get_generated_writing(self, writing_id: int) -> Optional[GeneratedWriting]:
        """생성된 글 상세 조회."""
        return (
            self.db.query(GeneratedWriting)
            .filter(
                GeneratedWriting.id == writing_id,
                GeneratedWriting.deleted_at.is_(None),
            )
            .first()
        )

    # ========== 글 관리 ==========

    def update_generated_writing(
        self,
        writing_id: int,
        content: Optional[str] = None,
    ) -> Optional[GeneratedWriting]:
        """생성된 글 수정."""
        writing = self.get_generated_writing(writing_id)
        if not writing:
            return None

        if content is not None:
            writing.content = content

        writing.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(writing)
        return writing

    def delete_generated_writing(
        self,
        writing_id: int,
        hard_delete: bool = False,
    ) -> bool:
        """생성된 글 삭제."""
        writing = self.db.query(GeneratedWriting).filter(
            GeneratedWriting.id == writing_id
        ).first()
        if not writing:
            return False

        if hard_delete:
            self.db.delete(writing)
        else:
            writing.deleted_at = datetime.now()

        self.db.commit()
        return True

    def rate_generated_writing(
        self,
        writing_id: int,
        rating: Optional[int],
    ) -> Optional[GeneratedWriting]:
        """생성된 글 평가."""
        writing = self.get_generated_writing(writing_id)
        if not writing:
            return None

        writing.rating = rating
        writing.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(writing)
        return writing

    # ========== 소스 관리 ==========

    def list_sources(
        self,
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """글 소스 목록 조회."""
        query = self.db.query(WritingSource)

        if category:
            query = query.filter(WritingSource.category == category)

        total = query.count()
        items = (
            query.order_by(WritingSource.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total > 0 else 1,
        }

    def add_source(
        self,
        content: str,
        category: Optional[str] = None,
        source_info: Optional[str] = None,
    ) -> WritingSource:
        """글 소스 추가."""
        source = WritingSource(
            content=content,
            category=category,
            source_info=source_info,
        )
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def bulk_add_sources(self, sources: list[dict]) -> int:
        """소스 일괄 추가."""
        added = 0
        for src in sources:
            content = src.get("content")
            if content:
                self.db.add(
                    WritingSource(
                        content=content,
                        category=src.get("category"),
                        source_info=src.get("source_info"),
                    )
                )
                added += 1
        self.db.commit()
        return added

    def delete_source(self, source_id: int) -> bool:
        """글 소스 삭제."""
        source = self.db.query(WritingSource).filter(
            WritingSource.id == source_id
        ).first()
        if not source:
            return False

        self.db.delete(source)
        self.db.commit()
        return True

    # ========== 통계 ==========

    def get_stats(self) -> dict:
        """통계 조회."""
        source_count = self.db.query(WritingSource).count()

        base_query = self.db.query(GeneratedWriting).filter(
            GeneratedWriting.deleted_at.is_(None)
        )
        generated_count = base_query.count()

        # 타입별 카운트
        mix_count = base_query.filter(
            GeneratedWriting.task_type == GeneratedWriting.TASK_TYPE_MIX
        ).count()
        random_count = base_query.filter(
            GeneratedWriting.task_type == GeneratedWriting.TASK_TYPE_RANDOM
        ).count()

        # 평가별 카운트
        liked_count = base_query.filter(
            GeneratedWriting.rating == GeneratedWriting.RATING_LIKE
        ).count()
        disliked_count = base_query.filter(
            GeneratedWriting.rating == GeneratedWriting.RATING_DISLIKE
        ).count()

        # 오늘 생성 수
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = base_query.filter(
            GeneratedWriting.created_at >= today
        ).count()

        return {
            "source_count": source_count,
            "generated_count": generated_count,
            "by_type": {"mix": mix_count, "random": random_count},
            "by_rating": {"liked": liked_count, "disliked": disliked_count},
            "today_count": today_count,
        }

    # ========== 스케줄 실행 ==========

    def get_writing_schedule(self) -> Optional[CrawlSchedule]:
        """작문 스케줄 조회."""
        return (
            self.db.query(CrawlSchedule)
            .filter(
                CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_WRITING_TASK,
                CrawlSchedule.enabled == True,
            )
            .first()
        )

    def run_writing_task(self) -> dict:
        """작문 태스크 수동 실행.

        Returns:
            실행 결과 dict
        """
        from app.modules.writing.worker.writing_worker import WritingWorker

        # 스케줄 조회 또는 생성
        schedule = self.get_writing_schedule()
        if not schedule:
            # 임시 스케줄 생성 (수동 실행용)
            schedule = CrawlSchedule(
                name="writing_task_manual",
                display_name="수동 글쓰기",
                target_type=CrawlSchedule.TARGET_TYPE_WRITING_TASK,
                schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL,
                enabled=True,
            )
            self.db.add(schedule)
            self.db.commit()
            self.db.refresh(schedule)

        # 실행 기록 생성
        run = CrawlScheduleRun(
            schedule_id=schedule.id,
            started_at=datetime.now(),
            status=CrawlScheduleRun.STATUS_RUNNING,
            worker_id="manual",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

        # 워커 실행
        worker = WritingWorker(self.db)
        result = worker.run(schedule, run)

        # 스케줄 업데이트
        schedule.last_run_at = datetime.now()
        self.db.commit()

        return {
            "run_id": run.id,
            "schedule_id": schedule.id,
            **result,
        }

    def check_and_run_due_schedule(self) -> Optional[dict]:
        """예정된 스케줄 확인 및 실행.

        next_run_at이 현재 시간 이전인 스케줄이 있으면 실행합니다.

        Returns:
            실행 결과 dict 또는 None (실행할 스케줄 없음)
        """
        from app.modules.writing.worker.writing_worker import WritingWorker
        from datetime import timedelta

        now = datetime.now()

        # 실행 대기 중인 스케줄 조회
        schedule = (
            self.db.query(CrawlSchedule)
            .filter(
                CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_WRITING_TASK,
                CrawlSchedule.enabled == True,
                CrawlSchedule.next_run_at <= now,
            )
            .first()
        )

        if not schedule:
            return None

        # 이미 실행 중인지 확인
        running = (
            self.db.query(CrawlScheduleRun)
            .filter(
                CrawlScheduleRun.schedule_id == schedule.id,
                CrawlScheduleRun.status == CrawlScheduleRun.STATUS_RUNNING,
            )
            .first()
        )
        if running:
            return None

        # 실행 기록 생성
        run = CrawlScheduleRun(
            schedule_id=schedule.id,
            started_at=datetime.now(),
            status=CrawlScheduleRun.STATUS_RUNNING,
            worker_id="scheduled",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

        # 워커 실행
        worker = WritingWorker(self.db)
        result = worker.run(schedule, run)

        # 다음 실행 시간 계산 (내일 같은 시간)
        next_run = now + timedelta(days=1)
        schedule.last_run_at = now
        schedule.next_run_at = next_run.replace(
            hour=6, minute=0, second=0, microsecond=0
        )
        self.db.commit()

        return {
            "run_id": run.id,
            "schedule_id": schedule.id,
            **result,
        }
