"""Facebook Crawl Service - 크롤링 실행 및 관리 서비스."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import TaskSchedule, TaskScheduleRun, ServiceAccount
from app.models.facebook_post import FacebookPost
from app.services.task_schedule_service import TaskScheduleService
from .crawler import FacebookCrawler, CrawlOptions, FacebookPostData
from .post_service import PostService

logger = logging.getLogger("facebook.crawl_service")


class CrawlService:
    """Facebook 크롤링 실행 및 관리 서비스."""

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db
        self.post_service = PostService(db)
        self._schedule_service = TaskScheduleService(db)

    async def run_crawl(
        self,
        crawler: FacebookCrawler,
        service_account_id: int,
        options: Optional[CrawlOptions] = None,
        target_url: str = "https://www.facebook.com/",
        schedule_run_id: Optional[int] = None,
    ) -> TaskScheduleRun:
        """크롤링 실행.

        게시물을 수집하면서 즉시 DB에 저장합니다 (실시간 저장).
        크롤링 중간에 실패해도 그때까지 수집한 데이터는 보존됩니다.

        Args:
            crawler: FacebookCrawler 인스턴스
            service_account_id: 수집 계정 ID
            options: 크롤링 옵션
            target_url: 크롤링 대상 Facebook URL
            schedule_run_id: 기존 실행 기록 ID (없으면 새로 생성)

        Returns:
            크롤링 실행 기록 (TaskScheduleRun)
        """
        if schedule_run_id:
            crawl_run = self._schedule_service.get_run_by_id(schedule_run_id)
            if not crawl_run:
                raise ValueError(f"Schedule run {schedule_run_id} not found")
        else:
            schedule = self._get_or_create_default_schedule(service_account_id)
            crawl_run = self._schedule_service.start_run(
                schedule_id=schedule.id,
                worker_id="facebook_crawl_service",
                config_snapshot={},
            )

        save_stats = {"new_saved": 0, "total_collected": 0}

        async def on_post_collected(post: FacebookPostData):
            """게시물 수집 즉시 저장 콜백."""
            save_stats["total_collected"] += 1
            try:
                saved = self.post_service.save_post(
                    post=post,
                    service_account_id=service_account_id,
                    crawl_run_id=crawl_run.id,
                )
                if saved:
                    save_stats["new_saved"] += 1
            except Exception as e:
                logger.error(f"게시물 저장 실패 (post_id={post.post_id}): {e}")

        # DB 중복 체크 콜백
        async def db_duplicate_checker(post_id: str) -> bool:
            exists = (
                self.db.query(FacebookPost)
                .filter(FacebookPost.post_id == post_id)
                .first()
            )
            return exists is not None

        crawler._db_duplicate_checker = db_duplicate_checker

        try:
            result = await crawler.crawl_feed(
                url=target_url,
                options=options,
                on_post_collected=on_post_collected,
            )

            # 실행 기록 완료
            self._schedule_service.finish_run(
                run_id=crawl_run.id,
                status="success",
                result={
                    "total_collected": save_stats["total_collected"],
                    "new_saved": save_stats["new_saved"],
                    "stop_reason": result.stop_reason,
                    "scroll_performed": result.scroll_performed,
                    "refresh_count": result.refresh_count,
                },
            )

            logger.info(
                f"크롤링 완료: 수집={save_stats['total_collected']}, "
                f"신규저장={save_stats['new_saved']}, 사유={result.stop_reason}"
            )

        except Exception as e:
            logger.error(f"크롤링 오류: {e}", exc_info=True)
            self._schedule_service.finish_run(
                run_id=crawl_run.id,
                status="error",
                result={"error": str(e)},
            )
            raise

        return crawl_run

    def _get_or_create_default_schedule(self, service_account_id: int) -> TaskSchedule:
        """기본 Facebook 스케줄을 조회하거나 생성합니다."""
        schedule = (
            self.db.query(TaskSchedule)
            .filter(
                TaskSchedule.task_type == "facebook_crawl",
                TaskSchedule.service_account_id == service_account_id,
                TaskSchedule.is_active == True,
            )
            .first()
        )

        if not schedule:
            schedule = TaskSchedule(
                task_type="facebook_crawl",
                service_account_id=service_account_id,
                name=f"Facebook 크롤 (account={service_account_id})",
                is_active=True,
                config={},
            )
            self.db.add(schedule)
            self.db.commit()
            self.db.refresh(schedule)

        return schedule
