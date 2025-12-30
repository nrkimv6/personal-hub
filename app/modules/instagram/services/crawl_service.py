"""Instagram Crawl Service - 크롤링 실행 및 관리 서비스."""

import asyncio
import logging
from datetime import datetime, date
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import CrawlSchedule, CrawlScheduleRun, ServiceAccount, InstagramPost
from app.services.crawl_schedule_service import CrawlScheduleService
from .crawler import InstagramCrawler, CrawlOptions, PostData
from .post_service import PostService
from .scheduler import InstagramScheduler
from .classifier_service import ClassifierService
from ..models.schemas import (
    TimeWindow,
    StatsSchema,
    TodayScheduleItem,
    RunningCrawlInfo,
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
        self.classifier_service = ClassifierService(db)
        self._schedule_service = CrawlScheduleService(db)

    async def run_crawl(
        self,
        crawler: InstagramCrawler,
        service_account_id: int,
        options: Optional[CrawlOptions] = None,
        schedule_run_id: Optional[int] = None,
    ) -> CrawlScheduleRun:
        """크롤링 실행.

        게시물을 수집하면서 즉시 DB에 저장합니다 (실시간 저장).
        크롤러가 중간에 죽어도 그때까지 수집한 데이터는 보존됩니다.

        Args:
            crawler: InstagramCrawler 인스턴스
            service_account_id: 수집 계정 ID
            options: 크롤링 옵션
            schedule_run_id: 기존 실행 기록 ID (없으면 새로 생성)

        Returns:
            크롤링 실행 기록 (CrawlScheduleRun)
        """
        # 실행 기록 조회 또는 생성
        if schedule_run_id:
            crawl_run = self._schedule_service.get_run_by_id(schedule_run_id)
            if not crawl_run:
                raise ValueError(f"Schedule run {schedule_run_id} not found")
        else:
            # 기존 호환성을 위해 run 생성 (스케줄 없이 직접 호출 시)
            # Instagram 피드용 기본 스케줄 조회 또는 임시 run 생성
            schedule = self._get_or_create_default_schedule(service_account_id)
            crawl_run = self._schedule_service.start_run(
                schedule_id=schedule.id,
                worker_id="crawl_service",
                config_snapshot={}
            )

        # 실시간 저장 통계
        save_stats = {"new_saved": 0, "total_collected": 0}

        async def on_post_collected(post: PostData) -> bool:
            """게시물 수집 즉시 저장 콜백."""
            save_stats["total_collected"] += 1
            saved = self._save_post(post, service_account_id, crawl_run.id)
            if saved:
                save_stats["new_saved"] += 1

            # 10개마다 DB에 중간 통계 업데이트 (실시간 진행 상황 조회용)
            if save_stats["total_collected"] % 10 == 0:
                try:
                    self._schedule_service.update_run_progress(
                        crawl_run.id,
                        collected_count=save_stats["total_collected"],
                        saved_count=save_stats["new_saved"]
                    )
                    logger.info(f"[Progress] {save_stats['total_collected']} collected, {save_stats['new_saved']} new")
                except Exception as e:
                    logger.warning(f"Failed to update progress: {e}")

            return saved

        try:
            # 크롤링 옵션 설정
            if options is None:
                schedule = self._schedule_service.get_schedule_by_id(crawl_run.schedule_id)
                if schedule:
                    config = schedule.get_target_config()
                    options = CrawlOptions(
                        max_posts=config.get("max_posts", 20),
                        scroll_count=config.get("scroll_count", 3),
                        duplicate_stop_count=config.get("duplicate_stop_count", 5),
                    )
                else:
                    options = CrawlOptions(max_posts=20, scroll_count=3, duplicate_stop_count=5)

            # DB 중복 체크 콜백 설정
            crawler._db_duplicate_checker = lambda post_id: self.post_service.exists_by_post_id(post_id)

            # 크롤링 실행 (실시간 저장 콜백 전달)
            posts = await crawler.crawl_feed(options, on_post_collected=on_post_collected)

            # 실행 기록 업데이트
            self._schedule_service.complete_run(
                crawl_run.id,
                collected_count=save_stats["total_collected"],
                saved_count=save_stats["new_saved"],
                stop_reason=getattr(crawler, '_stop_reason', None)
            )

            logger.info(f"Crawl completed: {save_stats['total_collected']} collected, {save_stats['new_saved']} new (realtime saved)")

        except (Exception, asyncio.CancelledError) as e:
            # 에러 발생해도 그때까지 저장된 데이터는 보존됨
            self.db.rollback()  # 먼저 세션 복구
            try:
                self._schedule_service.fail_run(crawl_run.id, str(e)[:500])
            except Exception:
                pass
            logger.error(f"Crawl failed after saving {save_stats['new_saved']} posts: {e}")

        # 최신 상태 반환
        crawl_run = self._schedule_service.get_run_by_id(crawl_run.id)
        return crawl_run

    def _get_or_create_default_schedule(self, service_account_id: int) -> CrawlSchedule:
        """기본 Instagram 피드 스케줄 조회 또는 생성."""
        schedule_name = f"instagram_feed_account_{service_account_id}"
        schedule = self._schedule_service.get_schedule_by_name(schedule_name)

        if not schedule:
            schedule = self._schedule_service.create_schedule(
                name=schedule_name,
                display_name=f"Instagram 피드 (계정 {service_account_id})",
                target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
                target_config={
                    "service_account_id": service_account_id,
                    "max_posts": 20,
                    "scroll_count": 3,
                    "duplicate_stop_count": 5,
                },
                schedule_type="time_window",
                schedule_value={"daily_runs": 3, "time_windows": []},
                enabled=True,
            )

        return schedule

    async def recrawl_single_post(
        self,
        crawler: InstagramCrawler,
        post_id: int,
    ) -> dict:
        """개별 게시물 재크롤링 실행.

        Args:
            crawler: InstagramCrawler 인스턴스
            post_id: DB 게시물 ID

        Returns:
            dict: {"success": bool, "message": str, "post": InstagramPost | None}
        """
        # 게시물 조회
        post = self.db.query(InstagramPost).filter(InstagramPost.id == post_id).first()
        if not post:
            return {"success": False, "message": f"Post {post_id} not found", "post": None}

        if not post.url:
            return {"success": False, "message": f"Post {post_id} has no URL", "post": None}

        logger.info(f"Starting single post recrawl for post {post_id}: {post.url}")

        try:
            # 크롤링 실행
            crawled_data = await crawler.crawl_single_post(post.url)

            if not crawled_data:
                return {"success": False, "message": "Failed to crawl post - no data returned", "post": None}

            # DB 업데이트
            if crawled_data.caption:
                post.caption = crawled_data.caption
            if crawled_data.images:
                post.images = crawled_data.images
            if crawled_data.is_ad is not None:
                post.is_ad = crawled_data.is_ad
            if crawled_data.datetime_str:
                try:
                    post.posted_at = datetime.fromisoformat(crawled_data.datetime_str.replace("Z", "+00:00"))
                except Exception:
                    pass
            if crawled_data.display_time:
                post.display_time = crawled_data.display_time

            post.collected_at = datetime.now()  # 재수집 시간 업데이트

            self.db.commit()
            self.db.refresh(post)

            logger.info(f"Successfully recrawled post {post_id}")
            return {"success": True, "message": "Post updated successfully", "post": post}

        except Exception as e:
            logger.error(f"Failed to recrawl post {post_id}: {e}")
            self.db.rollback()
            return {"success": False, "message": str(e), "post": None}

    async def crawl_by_url(
        self,
        crawler: InstagramCrawler,
        url: str,
        service_account_id: int,
    ) -> dict:
        """URL로 단일 게시물 수집.

        새 게시물이면 DB에 추가하고, 기존 게시물이면 정보를 업데이트합니다.

        Args:
            crawler: InstagramCrawler 인스턴스
            url: Instagram 게시물 URL
            service_account_id: 사용할 계정 ID

        Returns:
            dict: {"success": bool, "message": str, "post": InstagramPost | None, "is_new": bool}
        """
        logger.info(f"Starting URL crawl: {url}")

        # URL에서 post_id 추출
        post_id = self._extract_post_id(url)
        if not post_id:
            return {"success": False, "message": "Invalid URL format", "post": None, "is_new": False}

        try:
            # 크롤링 실행
            crawled_data = await crawler.crawl_single_post(url)

            if not crawled_data:
                return {"success": False, "message": "Failed to crawl post - no data returned", "post": None, "is_new": False}

            # 기존 게시물 확인
            existing_post = self.post_service.get_post_by_instagram_id(post_id)

            if existing_post:
                # 기존 게시물 업데이트
                if crawled_data.caption:
                    existing_post.caption = crawled_data.caption
                if crawled_data.images:
                    existing_post.images = crawled_data.images
                if crawled_data.is_ad is not None:
                    existing_post.is_ad = crawled_data.is_ad
                if crawled_data.datetime_str:
                    try:
                        existing_post.posted_at = datetime.fromisoformat(
                            crawled_data.datetime_str.replace("Z", "+00:00")
                        )
                    except Exception:
                        pass
                if crawled_data.display_time:
                    existing_post.display_time = crawled_data.display_time
                if crawled_data.likes is not None:
                    existing_post.likes = crawled_data.likes
                if crawled_data.comments is not None:
                    existing_post.comments = crawled_data.comments

                existing_post.collected_at = datetime.now()

                self.db.commit()
                self.db.refresh(existing_post)

                logger.info(f"Updated existing post {post_id}")
                return {"success": True, "message": "Post updated", "post": existing_post, "is_new": False}

            else:
                # 새 게시물 생성
                posted_at = None
                if crawled_data.datetime_str:
                    try:
                        posted_at = datetime.fromisoformat(
                            crawled_data.datetime_str.replace("Z", "+00:00")
                        )
                    except Exception:
                        pass

                new_post = self.post_service.create_post(
                    post_id=post_id,
                    account=crawled_data.account,
                    url=url,
                    caption=crawled_data.caption,
                    images=crawled_data.images,
                    posted_at=posted_at,
                    display_time=crawled_data.display_time,
                    is_ad=crawled_data.is_ad,
                    post_type=crawled_data.post_type,
                    likes=crawled_data.likes,
                    comments=crawled_data.comments,
                    service_account_id=service_account_id,
                    crawl_run_id=None,  # 단일 URL 수집은 crawl_run 없음
                )

                if new_post:
                    # 자동 분류 실행
                    try:
                        tags = self.classifier_service.classify_post(new_post)
                        if tags:
                            logger.debug(f"Post {new_post.id} classified: {[t['tag'] for t in tags]}")
                    except Exception as e:
                        logger.warning(f"Failed to classify post {new_post.id}: {e}")

                    logger.info(f"Created new post {post_id} from URL")
                    return {"success": True, "message": "New post created", "post": new_post, "is_new": True}
                else:
                    return {"success": False, "message": "Failed to create post", "post": None, "is_new": False}

        except Exception as e:
            logger.error(f"Failed to crawl URL {url}: {e}")
            self.db.rollback()
            return {"success": False, "message": str(e), "post": None, "is_new": False}

    def _save_post(
        self,
        post: PostData,
        service_account_id: int,
        crawl_run_id: int,
    ) -> bool:
        """게시물 저장 및 자동 분류.

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
            post_type=post.post_type,
            likes=post.likes,
            comments=post.comments,
            service_account_id=service_account_id,
            crawl_run_id=crawl_run_id,
        )

        # 신규 저장된 게시물 자동 분류
        if result is not None:
            try:
                tags = self.classifier_service.classify_post(result)
                if tags:
                    logger.debug(f"Post {result.id} classified: {[t['tag'] for t in tags]}")
            except Exception as e:
                logger.warning(f"Failed to classify post {result.id}: {e}")

        return result is not None

    def _extract_post_id(self, url: Optional[str]) -> Optional[str]:
        """URL에서 게시물 ID 추출.

        /p/ (일반 게시물) 및 /reel/ (릴스) 패턴 모두 지원합니다.
        쿼리 파라미터와 trailing slash는 자동 제거됩니다.
        """
        if not url:
            return None

        # 쿼리 파라미터 먼저 제거
        url_clean = url.split("?")[0]

        # https://www.instagram.com/p/ABC123/
        if "/p/" in url_clean:
            parts = url_clean.split("/p/")
            if len(parts) > 1:
                return parts[1].rstrip("/")

        # https://www.instagram.com/reel/ABC123/
        if "/reel/" in url_clean:
            parts = url_clean.split("/reel/")
            if len(parts) > 1:
                return parts[1].rstrip("/")

        return None

    def get_crawl_runs(
        self,
        limit: int = 10,
        service_account_id: Optional[int] = None,
    ) -> List[CrawlScheduleRun]:
        """크롤링 실행 기록 조회.

        Args:
            limit: 조회 개수
            service_account_id: 계정 필터 (현재는 사용되지 않음 - 스케줄 기반 필터링으로 변경 예정)

        Returns:
            실행 기록 목록
        """
        query = self.db.query(CrawlScheduleRun).join(CrawlSchedule).filter(
            CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED
        )

        if service_account_id:
            # target_config에서 service_account_id를 필터링
            # JSON 문자열에서 검색 (SQLite JSON 지원 제한으로 like 사용)
            query = query.filter(
                CrawlSchedule.target_config.like(f'%"service_account_id": {service_account_id}%')
            )

        return query.order_by(desc(CrawlScheduleRun.started_at)).limit(limit).all()

    def get_crawl_runs_paginated(
        self,
        page: int = 1,
        limit: int = 20,
        period: Optional[str] = None,
        status: Optional[str] = None,
        service_account_id: Optional[int] = None,
    ) -> tuple[List[CrawlScheduleRun], int]:
        """크롤링 실행 기록 조회 (페이징 지원).

        Args:
            page: 페이지 번호 (1부터 시작)
            limit: 페이지당 개수
            period: 기간 필터 ('1d', '7d', '30d', 'all')
            status: 상태 필터 ('completed', 'failed', 'all')
            service_account_id: 계정 필터 (현재는 사용되지 않음)

        Returns:
            (실행 기록 목록, 전체 개수)
        """
        from datetime import timedelta

        query = self.db.query(CrawlScheduleRun).join(CrawlSchedule).filter(
            CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED
        )

        # 기간 필터
        if period and period != 'all':
            days = {'1d': 1, '7d': 7, '30d': 30}.get(period, 7)
            cutoff = datetime.now() - timedelta(days=days)
            query = query.filter(CrawlScheduleRun.started_at >= cutoff)

        # 상태 필터 (success/failed -> completed/failed로 매핑)
        if status and status != 'all':
            if status == 'success':
                query = query.filter(CrawlScheduleRun.status == CrawlScheduleRun.STATUS_COMPLETED)
            elif status == 'failed':
                query = query.filter(CrawlScheduleRun.status == CrawlScheduleRun.STATUS_FAILED)

        # 계정 필터
        if service_account_id:
            query = query.filter(
                CrawlSchedule.target_config.like(f'%"service_account_id": {service_account_id}%')
            )

        # 전체 개수
        total = query.count()

        # 페이징
        offset = (page - 1) * limit
        runs = query.order_by(desc(CrawlScheduleRun.started_at)).offset(offset).limit(limit).all()

        return runs, total

    def get_crawl_run_by_id(self, run_id: int) -> Optional[CrawlScheduleRun]:
        """크롤링 실행 기록 상세 조회.

        Args:
            run_id: 실행 기록 ID

        Returns:
            실행 기록 (없으면 None)
        """
        return self._schedule_service.get_run_by_id(run_id)

    def get_run_stats(self, days: int = 7) -> dict:
        """실행 통계 조회.

        Args:
            days: 통계 기간 (일)

        Returns:
            통계 dict
        """
        from datetime import timedelta
        from sqlalchemy import func

        cutoff = datetime.now() - timedelta(days=days)

        # Instagram 피드 타입으로 필터링된 기본 쿼리
        base_query = self.db.query(CrawlScheduleRun).join(CrawlSchedule).filter(
            CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            CrawlScheduleRun.started_at >= cutoff
        )

        total_runs = base_query.count()
        success_runs = base_query.filter(
            CrawlScheduleRun.status == CrawlScheduleRun.STATUS_COMPLETED
        ).count()
        failed_runs = total_runs - success_runs
        success_rate = success_runs / total_runs if total_runs > 0 else 0.0

        # 평균 수집 수 (saved_count 사용)
        avg_collected = self.db.query(func.avg(CrawlScheduleRun.saved_count)).join(CrawlSchedule).filter(
            CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            CrawlScheduleRun.started_at >= cutoff,
            CrawlScheduleRun.status == CrawlScheduleRun.STATUS_COMPLETED
        ).scalar() or 0.0

        # 평균 소요 시간
        runs_with_duration = base_query.filter(
            CrawlScheduleRun.finished_at != None
        ).all()

        total_duration = 0
        duration_count = 0
        for run in runs_with_duration:
            if run.finished_at and run.started_at:
                duration = (run.finished_at - run.started_at).total_seconds()
                total_duration += duration
                duration_count += 1

        avg_duration = total_duration / duration_count if duration_count > 0 else 0.0

        # 일별 트렌드
        daily_trend = []
        for i in range(days):
            day = (datetime.now() - timedelta(days=days - 1 - i)).date()
            day_start = datetime.combine(day, datetime.min.time())
            day_end = datetime.combine(day, datetime.max.time())

            day_runs = self.db.query(CrawlScheduleRun).join(CrawlSchedule).filter(
                CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
                CrawlScheduleRun.started_at >= day_start,
                CrawlScheduleRun.started_at <= day_end
            ).all()

            day_total = len(day_runs)
            day_success = sum(1 for r in day_runs if r.status == CrawlScheduleRun.STATUS_COMPLETED)
            day_failed = day_total - day_success
            day_collected = sum(r.collected_count or 0 for r in day_runs)
            day_saved = sum(r.saved_count or 0 for r in day_runs)

            daily_trend.append({
                "date": day.isoformat(),
                "total_runs": day_total,
                "success_runs": day_success,
                "failed_runs": day_failed,
                "total_collected": day_collected,
                "new_saved": day_saved,
            })

        return {
            "total_runs": total_runs,
            "success_runs": success_runs,
            "failed_runs": failed_runs,
            "success_rate": success_rate,
            "avg_collected": float(avg_collected),
            "avg_duration_seconds": avg_duration,
            "daily_trend": daily_trend,
        }

    def get_last_run(self, service_account_id: Optional[int] = None) -> Optional[CrawlScheduleRun]:
        """마지막 실행 기록."""
        query = self.db.query(CrawlScheduleRun).join(CrawlSchedule).filter(
            CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED
        )

        if service_account_id:
            query = query.filter(
                CrawlSchedule.target_config.like(f'%"service_account_id": {service_account_id}%')
            )

        return query.order_by(desc(CrawlScheduleRun.started_at)).first()

    def get_schedule_config(self) -> Optional[CrawlSchedule]:
        """스케줄 설정 조회 (기본 Instagram 피드 스케줄 반환)."""
        return self.db.query(CrawlSchedule).filter(
            CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED
        ).first()

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
        service_account_id: Optional[int] = None,
    ) -> CrawlSchedule:
        """스케줄 설정 업데이트.

        Returns:
            업데이트된 설정
        """
        import json

        schedule = self.get_schedule_config()

        if schedule is None:
            # 기본 스케줄 생성
            schedule = CrawlSchedule(
                name="instagram_feed_default",
                display_name="Instagram 피드 크롤링",
                target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
                schedule_type=CrawlSchedule.SCHEDULE_TYPE_TIME_WINDOW,
                enabled=True,
            )
            self.db.add(schedule)
            self.db.flush()

        if enabled is not None:
            schedule.enabled = enabled

        # target_config 업데이트
        target_config = schedule.get_target_config()

        if max_posts is not None:
            target_config["max_posts"] = max_posts

        if scroll_count is not None:
            target_config["scroll_count"] = scroll_count

        if duplicate_stop_count is not None:
            target_config["duplicate_stop_count"] = duplicate_stop_count

        if min_interval_hours is not None:
            target_config["min_interval_hours"] = min_interval_hours

        if max_retries is not None:
            target_config["max_retries"] = max_retries

        if retry_interval_minutes is not None:
            target_config["retry_interval_minutes"] = retry_interval_minutes

        if service_account_id is not None:
            target_config["service_account_id"] = service_account_id

        schedule.set_target_config(target_config)

        # schedule_value 업데이트 (time_windows, daily_runs)
        schedule_value = {}
        if schedule.schedule_value:
            try:
                schedule_value = json.loads(schedule.schedule_value)
            except json.JSONDecodeError:
                pass

        if daily_runs is not None:
            schedule_value["daily_runs"] = daily_runs

        if time_windows is not None:
            schedule_value["time_windows"] = [tw.model_dump() for tw in time_windows]

        schedule.schedule_value = json.dumps(schedule_value, ensure_ascii=False)
        schedule.updated_at = datetime.now()

        self.db.commit()
        self.db.refresh(schedule)

        return schedule

    def get_stats(self) -> StatsSchema:
        """통계 조회."""
        import json

        total_posts = self.post_service.get_total_count()
        today_posts = self.post_service.get_today_count()

        # 오늘 실행 통계 (Instagram 피드 타입만)
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_runs_query = self.db.query(CrawlScheduleRun).join(CrawlSchedule).filter(
            CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            CrawlScheduleRun.started_at >= today_start
        )
        total_runs = today_runs_query.count()
        success_runs = today_runs_query.filter(
            CrawlScheduleRun.status == CrawlScheduleRun.STATUS_COMPLETED
        ).count()

        # 마지막 완료된 실행
        last_run = self.get_last_run()
        last_run_at = last_run.started_at if last_run else None

        # 다음 실행 시간 계산
        schedule = self.get_schedule_config()
        next_crawl_time = None

        if schedule and schedule.enabled:
            schedule_value = {}
            if schedule.schedule_value:
                try:
                    schedule_value = json.loads(schedule.schedule_value)
                except json.JSONDecodeError:
                    pass

            daily_runs = schedule_value.get("daily_runs", 3)
            time_windows_data = schedule_value.get("time_windows", [])

            scheduler = InstagramScheduler(
                daily_runs=daily_runs,
                time_windows=[TimeWindow(**tw) for tw in time_windows_data],
            )
            next_crawl_time = scheduler.get_next_run_time()

        # 활성 계정 수 (스케줄별 target_config에서 추출 - 현재는 단순화)
        from sqlalchemy import func
        unique_schedules = self.db.query(func.count(func.distinct(CrawlScheduleRun.schedule_id))).join(CrawlSchedule).filter(
            CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            CrawlScheduleRun.started_at >= today_start
        ).scalar() or 0

        # 실행 중인 크롤러 정보 (status가 running인 경우)
        running_crawl = None
        running_run = self.db.query(CrawlScheduleRun).join(CrawlSchedule).filter(
            CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            CrawlScheduleRun.status == CrawlScheduleRun.STATUS_RUNNING
        ).order_by(desc(CrawlScheduleRun.started_at)).first()

        if running_run:
            # 스케줄의 target_config에서 service_account_id 추출
            schedule = running_run.schedule
            target_config = schedule.get_target_config() if schedule else {}
            service_account_id = target_config.get("service_account_id")

            account = None
            if service_account_id:
                account = self.db.query(ServiceAccount).filter(ServiceAccount.id == service_account_id).first()

            running_crawl = RunningCrawlInfo(
                run_id=running_run.id,
                service_account_id=service_account_id,
                account_username=account.identifier if account else None,
                started_at=running_run.started_at,
                total_collected=running_run.collected_count or 0,
                new_saved=running_run.saved_count or 0,
            )

        return StatsSchema(
            total_posts=total_posts,
            today_posts=today_posts,
            total_runs=total_runs,
            success_runs=success_runs,
            last_run_at=last_run_at,
            next_crawl_time=next_crawl_time,
            unique_accounts=unique_schedules,
            running_crawl=running_crawl,
        )

    def get_today_schedule(self) -> List[TodayScheduleItem]:
        """오늘 스케줄 조회.

        Returns:
            오늘의 스케줄 항목 리스트.
            각 항목은 scheduled_time, status, run_id를 포함.
            status: 'pending' (미래), 'completed' (완료), 'missed' (놓침)
        """
        import json

        schedule = self.get_schedule_config()

        if not schedule or not schedule.enabled:
            return []

        # schedule_value에서 설정 추출
        schedule_value = {}
        if schedule.schedule_value:
            try:
                schedule_value = json.loads(schedule.schedule_value)
            except json.JSONDecodeError:
                pass

        daily_runs = schedule_value.get("daily_runs", 3)
        time_windows_data = schedule_value.get("time_windows", [])

        scheduler = InstagramScheduler(
            daily_runs=daily_runs,
            time_windows=[TimeWindow(**tw) for tw in time_windows_data],
        )

        # 오늘 실행 기록 (Instagram 피드 타입만)
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_runs = self.db.query(CrawlScheduleRun).join(CrawlSchedule).filter(
            CrawlSchedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            CrawlScheduleRun.started_at >= today_start
        ).all()

        now = datetime.now()
        schedule_times = scheduler.generate_daily_schedule(now.date())

        result = []
        for run_time in schedule_times:
            # 해당 시간대에 실행된 기록 찾기 (1시간 이내)
            matching_run = None
            for run in today_runs:
                if abs((run.started_at - run_time).total_seconds()) < 3600:
                    matching_run = run
                    break

            # 상태 결정 (status 필드 사용)
            if matching_run:
                status = "completed" if matching_run.status == CrawlScheduleRun.STATUS_COMPLETED else "missed"
                run_id = matching_run.id
            elif run_time <= now:
                status = "missed"
                run_id = None
            else:
                status = "pending"
                run_id = None

            result.append(TodayScheduleItem(
                scheduled_time=run_time.strftime("%H:%M"),
                status=status,
                run_id=run_id,
            ))

        return result

    def classify_failure(self, error: Exception) -> str:
        """실패 원인 분류.

        Args:
            error: 발생한 예외

        Returns:
            실패 원인 문자열
        """
        error_str = str(error).lower()

        if "login" in error_str or "로그인" in error_str:
            return "login_required"
        elif "timeout" in error_str or "timed out" in error_str:
            return "timeout"
        elif "network" in error_str or "connection" in error_str:
            return "network_error"
        elif "rate" in error_str or "limit" in error_str:
            return "rate_limit"
        else:
            return "unknown"

    def should_retry(self, run: CrawlScheduleRun, max_retries: int = 3) -> bool:
        """재시도 가능 여부 확인.

        Args:
            run: 크롤링 실행 기록
            max_retries: 최대 재시도 횟수

        Returns:
            재시도 가능하면 True
        """
        if run.status == CrawlScheduleRun.STATUS_COMPLETED:
            return False

        retry_count = run.retry_count or 0
        if retry_count >= max_retries:
            return False

        # 로그인 필요 에러는 재시도 불가
        if run.error_message and "login" in run.error_message.lower():
            return False

        return True

    def get_retry_delay(self, retry_count: int, base_minutes: int = 5) -> int:
        """재시도 대기 시간 계산 (지수 백오프).

        Args:
            retry_count: 현재 재시도 횟수
            base_minutes: 기본 대기 시간 (분)

        Returns:
            대기 시간 (분)
        """
        # 지수 백오프: 5분 -> 10분 -> 20분 -> 40분
        return base_minutes * (2 ** retry_count)

    def mark_run_failed(
        self,
        run_id: int,
        error: Exception,
    ) -> CrawlScheduleRun:
        """크롤링 실패 기록.

        Args:
            run_id: 크롤링 실행 ID
            error: 발생한 예외

        Returns:
            업데이트된 실행 기록
        """
        run = self._schedule_service.get_run_by_id(run_id)
        if not run:
            raise ValueError(f"CrawlRun {run_id} not found")

        failure_reason = self.classify_failure(error)
        error_message = f"{failure_reason}: {str(error)}"
        run.mark_failed(error_message)

        self.db.commit()
        self.db.refresh(run)

        logger.warning(f"Run {run_id} failed: {failure_reason} - {error}")
        return run
