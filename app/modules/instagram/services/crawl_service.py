"""Instagram Crawl Service - 크롤링 실행 및 관리 서비스."""

import json
import logging
from datetime import datetime, date
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import InstagramCrawlRun, InstagramScheduleConfig
from .crawler import InstagramCrawler, CrawlOptions, PostData
from .post_service import PostService
from .scheduler import InstagramScheduler
from ..models.schemas import (
    TimeWindow,
    ScheduleConfigSchema,
    StatsSchema,
    TodayScheduleItem,
)

logger = logging.getLogger("instagram.crawl_service")


class CrawlService:
    """Instagram 크롤링 실행 및 관리 서비스."""

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db
        self.post_service = PostService(db)

    async def run_crawl(
        self,
        crawler: InstagramCrawler,
        account_id: int,
        options: Optional[CrawlOptions] = None,
    ) -> InstagramCrawlRun:
        """크롤링 실행.

        Args:
            crawler: InstagramCrawler 인스턴스
            account_id: 수집 계정 ID
            options: 크롤링 옵션

        Returns:
            크롤링 실행 기록
        """
        # 실행 기록 생성
        crawl_run = InstagramCrawlRun(
            account_id=account_id,
            started_at=datetime.utcnow(),
        )
        self.db.add(crawl_run)
        self.db.commit()
        self.db.refresh(crawl_run)

        try:
            # 크롤링 실행
            if options is None:
                config = self.get_schedule_config()
                options = CrawlOptions(
                    max_posts=config.max_posts if config else 20,
                    scroll_count=config.scroll_count if config else 3,
                    duplicate_stop_count=getattr(config, 'duplicate_stop_count', 5) if config else 5,
                )

            # DB 중복 체크 콜백 설정
            crawler._db_duplicate_checker = lambda post_id: self.post_service.exists_by_post_id(post_id)

            posts = await crawler.crawl_feed(options)

            # 게시물 저장
            new_saved = 0
            for post in posts:
                saved = self._save_post(post, account_id, crawl_run.id)
                if saved:
                    new_saved += 1

            # 실행 기록 업데이트
            crawl_run.success = True
            crawl_run.total_collected = len(posts)
            crawl_run.new_saved = new_saved
            crawl_run.finished_at = datetime.utcnow()

            logger.info(f"Crawl completed: {len(posts)} collected, {new_saved} new")

        except Exception as e:
            crawl_run.success = False
            crawl_run.error_message = str(e)
            crawl_run.finished_at = datetime.utcnow()
            logger.error(f"Crawl failed: {e}")

        self.db.commit()
        self.db.refresh(crawl_run)

        return crawl_run

    def _save_post(
        self,
        post: PostData,
        account_id: int,
        crawl_run_id: int,
    ) -> bool:
        """게시물 저장.

        Returns:
            저장 성공 여부 (중복이면 False)
        """
        # URL에서 post_id 추출
        post_id = self._extract_post_id(post.url) or f"unknown_{post.index}"

        # posted_at 파싱
        posted_at = None
        if post.datetime_str:
            try:
                posted_at = datetime.fromisoformat(post.datetime_str.replace("Z", "+00:00"))
            except Exception:
                pass

        result = self.post_service.create_post(
            post_id=post_id,
            account=post.account,
            url=post.url,
            caption=post.caption,
            images=post.images,
            posted_at=posted_at,
            display_time=post.display_time,
            is_ad=post.is_ad,
            account_id=account_id,
            crawl_run_id=crawl_run_id,
        )

        return result is not None

    def _extract_post_id(self, url: Optional[str]) -> Optional[str]:
        """URL에서 게시물 ID 추출."""
        if not url:
            return None

        # https://www.instagram.com/p/ABC123/
        if "/p/" in url:
            parts = url.split("/p/")
            if len(parts) > 1:
                return parts[1].rstrip("/").split("?")[0]

        return None

    def get_crawl_runs(
        self,
        limit: int = 10,
        account_id: Optional[int] = None,
    ) -> List[InstagramCrawlRun]:
        """크롤링 실행 기록 조회.

        Args:
            limit: 조회 개수
            account_id: 계정 필터

        Returns:
            실행 기록 목록
        """
        query = self.db.query(InstagramCrawlRun)

        if account_id:
            query = query.filter(InstagramCrawlRun.account_id == account_id)

        return query.order_by(desc(InstagramCrawlRun.started_at)).limit(limit).all()

    def get_last_run(self, account_id: Optional[int] = None) -> Optional[InstagramCrawlRun]:
        """마지막 실행 기록."""
        query = self.db.query(InstagramCrawlRun)

        if account_id:
            query = query.filter(InstagramCrawlRun.account_id == account_id)

        return query.order_by(desc(InstagramCrawlRun.started_at)).first()

    def get_schedule_config(self) -> Optional[InstagramScheduleConfig]:
        """스케줄 설정 조회."""
        return self.db.query(InstagramScheduleConfig).first()

    def update_schedule_config(
        self,
        enabled: Optional[bool] = None,
        daily_runs: Optional[int] = None,
        time_windows: Optional[List[TimeWindow]] = None,
        max_posts: Optional[int] = None,
        scroll_count: Optional[int] = None,
        min_interval_hours: Optional[int] = None,
        duplicate_stop_count: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_interval_minutes: Optional[int] = None,
    ) -> InstagramScheduleConfig:
        """스케줄 설정 업데이트.

        Returns:
            업데이트된 설정
        """
        config = self.get_schedule_config()

        if config is None:
            # 기본 설정 생성
            config = InstagramScheduleConfig()
            self.db.add(config)

        if enabled is not None:
            config.enabled = enabled

        if daily_runs is not None:
            config.daily_runs = daily_runs

        if time_windows is not None:
            config.time_windows = [tw.model_dump() for tw in time_windows]

        if max_posts is not None:
            config.max_posts = max_posts

        if scroll_count is not None:
            config.scroll_count = scroll_count

        # 고급 설정
        if min_interval_hours is not None:
            config.min_interval_hours = min_interval_hours

        if duplicate_stop_count is not None:
            config.duplicate_stop_count = duplicate_stop_count

        if max_retries is not None:
            config.max_retries = max_retries

        if retry_interval_minutes is not None:
            config.retry_interval_minutes = retry_interval_minutes

        config.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(config)

        return config

    def get_stats(self) -> StatsSchema:
        """통계 조회."""
        total_posts = self.post_service.get_total_count()
        today_collected = self.post_service.get_today_count()

        last_run = self.get_last_run()
        last_crawl_time = last_run.started_at if last_run else None

        # 다음 실행 시간 계산
        config = self.get_schedule_config()
        next_crawl_time = None

        if config and config.enabled:
            scheduler = InstagramScheduler(
                daily_runs=config.daily_runs,
                time_windows=[TimeWindow(**tw) for tw in (config.time_windows or [])],
            )
            next_crawl_time = scheduler.get_next_run_time()

        return StatsSchema(
            total_posts=total_posts,
            today_collected=today_collected,
            last_crawl_time=last_crawl_time,
            next_crawl_time=next_crawl_time,
            accounts_active=0,  # TODO: 활성 계정 수
        )

    def get_today_schedule(self) -> List[TodayScheduleItem]:
        """오늘 스케줄 조회."""
        config = self.get_schedule_config()

        if not config or not config.enabled:
            return []

        scheduler = InstagramScheduler(
            daily_runs=config.daily_runs,
            time_windows=[TimeWindow(**tw) for tw in (config.time_windows or [])],
        )

        # 오늘 실행 기록
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_runs = self.db.query(InstagramCrawlRun).filter(
            InstagramCrawlRun.started_at >= today_start
        ).all()

        last_runs = [run.started_at for run in today_runs]

        schedule_status = scheduler.get_today_schedule_status(last_runs)

        return [
            TodayScheduleItem(
                time=run_time.strftime("%H:%M"),
                completed=completed,
            )
            for run_time, completed in schedule_status
        ]
