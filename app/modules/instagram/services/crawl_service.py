"""Instagram Crawl Service - 크롤링 실행 및 관리 서비스."""

import json
import logging
from datetime import datetime, date
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import InstagramCrawlRun, InstagramScheduleConfig, ServiceAccount, InstagramPost
from .crawler import InstagramCrawler, CrawlOptions, PostData
from .post_service import PostService
from .scheduler import InstagramScheduler
from .classifier_service import ClassifierService
from ..models.schemas import (
    TimeWindow,
    ScheduleConfigSchema,
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

    async def run_crawl(
        self,
        crawler: InstagramCrawler,
        service_account_id: int,
        options: Optional[CrawlOptions] = None,
    ) -> InstagramCrawlRun:
        """크롤링 실행.

        게시물을 수집하면서 즉시 DB에 저장합니다 (실시간 저장).
        크롤러가 중간에 죽어도 그때까지 수집한 데이터는 보존됩니다.

        Args:
            crawler: InstagramCrawler 인스턴스
            service_account_id: 수집 계정 ID
            options: 크롤링 옵션

        Returns:
            크롤링 실행 기록
        """
        # 실행 기록 생성
        crawl_run = InstagramCrawlRun(
            service_account_id=service_account_id,
            started_at=datetime.now(),
        )
        self.db.add(crawl_run)
        self.db.commit()
        self.db.refresh(crawl_run)

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
                    crawl_run.total_collected = save_stats["total_collected"]
                    crawl_run.new_saved = save_stats["new_saved"]
                    self.db.commit()
                    logger.info(f"[Progress] {save_stats['total_collected']} collected, {save_stats['new_saved']} new")
                except Exception as e:
                    logger.warning(f"Failed to update progress: {e}")

            return saved

        try:
            # 크롤링 옵션 설정
            if options is None:
                config = self.get_schedule_config()
                options = CrawlOptions(
                    max_posts=config.max_posts if config else 20,
                    scroll_count=config.scroll_count if config else 3,
                    duplicate_stop_count=getattr(config, 'duplicate_stop_count', 5) if config else 5,
                )

            # DB 중복 체크 콜백 설정
            crawler._db_duplicate_checker = lambda post_id: self.post_service.exists_by_post_id(post_id)

            # 크롤링 실행 (실시간 저장 콜백 전달)
            posts = await crawler.crawl_feed(options, on_post_collected=on_post_collected)

            # 실행 기록 업데이트
            crawl_run.success = True
            crawl_run.total_collected = save_stats["total_collected"]
            crawl_run.new_saved = save_stats["new_saved"]
            crawl_run.finished_at = datetime.now()

            logger.info(f"Crawl completed: {save_stats['total_collected']} collected, {save_stats['new_saved']} new (realtime saved)")

        except Exception as e:
            # 에러 발생해도 그때까지 저장된 데이터는 보존됨
            self.db.rollback()  # 먼저 세션 복구
            crawl_run = self.db.query(InstagramCrawlRun).get(crawl_run.id)  # 다시 조회
            if crawl_run:
                crawl_run.success = False
                crawl_run.error_message = str(e)[:500]  # 에러 메시지 길이 제한
                crawl_run.total_collected = save_stats["total_collected"]
                crawl_run.new_saved = save_stats["new_saved"]
                crawl_run.finished_at = datetime.now()
            logger.error(f"Crawl failed after saving {save_stats['new_saved']} posts: {e}")

        try:
            self.db.commit()
            self.db.refresh(crawl_run)
        except Exception as commit_error:
            logger.error(f"Failed to commit crawl_run update: {commit_error}")
            self.db.rollback()

        return crawl_run

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
    ) -> List[InstagramCrawlRun]:
        """크롤링 실행 기록 조회.

        Args:
            limit: 조회 개수
            service_account_id: 계정 필터

        Returns:
            실행 기록 목록
        """
        query = self.db.query(InstagramCrawlRun)

        if service_account_id:
            query = query.filter(InstagramCrawlRun.service_account_id == service_account_id)

        return query.order_by(desc(InstagramCrawlRun.started_at)).limit(limit).all()

    def get_crawl_runs_paginated(
        self,
        page: int = 1,
        limit: int = 20,
        period: Optional[str] = None,
        status: Optional[str] = None,
        service_account_id: Optional[int] = None,
    ) -> tuple[List[InstagramCrawlRun], int]:
        """크롤링 실행 기록 조회 (페이징 지원).

        Args:
            page: 페이지 번호 (1부터 시작)
            limit: 페이지당 개수
            period: 기간 필터 ('1d', '7d', '30d', 'all')
            status: 상태 필터 ('success', 'failed', 'all')
            service_account_id: 계정 필터

        Returns:
            (실행 기록 목록, 전체 개수)
        """
        from datetime import timedelta

        query = self.db.query(InstagramCrawlRun)

        # 기간 필터
        if period and period != 'all':
            days = {'1d': 1, '7d': 7, '30d': 30}.get(period, 7)
            cutoff = datetime.now() - timedelta(days=days)
            query = query.filter(InstagramCrawlRun.started_at >= cutoff)

        # 상태 필터
        if status and status != 'all':
            if status == 'success':
                query = query.filter(InstagramCrawlRun.success == True)
            elif status == 'failed':
                query = query.filter(InstagramCrawlRun.success == False)

        # 계정 필터
        if service_account_id:
            query = query.filter(InstagramCrawlRun.service_account_id == service_account_id)

        # 전체 개수
        total = query.count()

        # 페이징
        offset = (page - 1) * limit
        runs = query.order_by(desc(InstagramCrawlRun.started_at)).offset(offset).limit(limit).all()

        return runs, total

    def get_crawl_run_by_id(self, run_id: int) -> Optional[InstagramCrawlRun]:
        """크롤링 실행 기록 상세 조회.

        Args:
            run_id: 실행 기록 ID

        Returns:
            실행 기록 (없으면 None)
        """
        return self.db.query(InstagramCrawlRun).filter(
            InstagramCrawlRun.id == run_id
        ).first()

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

        # 기본 통계
        query = self.db.query(InstagramCrawlRun).filter(
            InstagramCrawlRun.started_at >= cutoff
        )

        total_runs = query.count()
        success_runs = query.filter(InstagramCrawlRun.success == True).count()
        failed_runs = total_runs - success_runs
        success_rate = success_runs / total_runs if total_runs > 0 else 0.0

        # 평균 수집 수
        avg_collected = self.db.query(func.avg(InstagramCrawlRun.new_saved)).filter(
            InstagramCrawlRun.started_at >= cutoff,
            InstagramCrawlRun.success == True
        ).scalar() or 0.0

        # 평균 소요 시간
        runs_with_duration = query.filter(
            InstagramCrawlRun.finished_at != None
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

            day_runs = self.db.query(InstagramCrawlRun).filter(
                InstagramCrawlRun.started_at >= day_start,
                InstagramCrawlRun.started_at <= day_end
            ).all()

            day_total = len(day_runs)
            day_success = sum(1 for r in day_runs if r.success)
            day_failed = day_total - day_success
            day_collected = sum(r.total_collected for r in day_runs)
            day_saved = sum(r.new_saved for r in day_runs)

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

    def get_last_run(self, service_account_id: Optional[int] = None) -> Optional[InstagramCrawlRun]:
        """마지막 실행 기록."""
        query = self.db.query(InstagramCrawlRun)

        if service_account_id:
            query = query.filter(InstagramCrawlRun.service_account_id == service_account_id)

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
        service_account_id: Optional[int] = None,
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

        # 계정 지정
        if service_account_id is not None:
            config.service_account_id = service_account_id

        config.updated_at = datetime.now()

        self.db.commit()
        self.db.refresh(config)

        return config

    def get_stats(self) -> StatsSchema:
        """통계 조회."""
        total_posts = self.post_service.get_total_count()
        today_posts = self.post_service.get_today_count()

        # 오늘 실행 통계
        today_start = datetime.combine(date.today(), datetime.min.time())
        total_runs = self.db.query(InstagramCrawlRun).filter(
            InstagramCrawlRun.started_at >= today_start
        ).count()
        success_runs = self.db.query(InstagramCrawlRun).filter(
            InstagramCrawlRun.started_at >= today_start,
            InstagramCrawlRun.success == True
        ).count()

        # 마지막 완료된 실행
        last_run = self.get_last_run()
        last_run_at = last_run.started_at if last_run else None

        # 다음 실행 시간 계산
        config = self.get_schedule_config()
        next_crawl_time = None

        if config and config.enabled:
            scheduler = InstagramScheduler(
                daily_runs=config.daily_runs,
                time_windows=[TimeWindow(**tw) for tw in (config.time_windows or [])],
            )
            next_crawl_time = scheduler.get_next_run_time()

        # 활성 계정 수 (오늘 실행된 고유 계정)
        from sqlalchemy import func
        unique_accounts = self.db.query(func.count(func.distinct(InstagramCrawlRun.service_account_id))).filter(
            InstagramCrawlRun.started_at >= today_start
        ).scalar() or 0

        # 실행 중인 크롤러 정보 (finished_at이 None인 경우)
        running_crawl = None
        running_run = self.db.query(InstagramCrawlRun).filter(
            InstagramCrawlRun.finished_at == None
        ).order_by(desc(InstagramCrawlRun.started_at)).first()

        if running_run:
            # 계정 정보 조회
            account = self.db.query(ServiceAccount).filter(ServiceAccount.id == running_run.service_account_id).first()
            running_crawl = RunningCrawlInfo(
                run_id=running_run.id,
                service_account_id=running_run.service_account_id,
                account_username=account.identifier if account else None,
                started_at=running_run.started_at,
                total_collected=running_run.total_collected or 0,
                new_saved=running_run.new_saved or 0,
            )

        return StatsSchema(
            total_posts=total_posts,
            today_posts=today_posts,
            total_runs=total_runs,
            success_runs=success_runs,
            last_run_at=last_run_at,
            next_crawl_time=next_crawl_time,
            unique_accounts=unique_accounts,
            running_crawl=running_crawl,
        )

    def get_today_schedule(self) -> List[TodayScheduleItem]:
        """오늘 스케줄 조회.

        Returns:
            오늘의 스케줄 항목 리스트.
            각 항목은 scheduled_time, status, run_id를 포함.
            status: 'pending' (미래), 'completed' (완료), 'missed' (놓침)
        """
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

            # 상태 결정
            if matching_run:
                status = "completed" if matching_run.success else "missed"
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

    def should_retry(self, run: InstagramCrawlRun, max_retries: int = 3) -> bool:
        """재시도 가능 여부 확인.

        Args:
            run: 크롤링 실행 기록
            max_retries: 최대 재시도 횟수

        Returns:
            재시도 가능하면 True
        """
        if run.success:
            return False

        retry_count = getattr(run, 'retry_count', 0) or 0
        if retry_count >= max_retries:
            return False

        # 로그인 필요 에러는 재시도 불가
        failure_reason = getattr(run, 'failure_reason', None)
        if failure_reason == "login_required":
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
    ) -> InstagramCrawlRun:
        """크롤링 실패 기록.

        Args:
            run_id: 크롤링 실행 ID
            error: 발생한 예외

        Returns:
            업데이트된 실행 기록
        """
        run = self.db.query(InstagramCrawlRun).get(run_id)
        if not run:
            raise ValueError(f"CrawlRun {run_id} not found")

        run.success = False
        run.error_message = str(error)
        run.failure_reason = self.classify_failure(error)
        run.finished_at = datetime.now()

        self.db.commit()
        self.db.refresh(run)

        logger.warning(f"Run {run_id} failed: {run.failure_reason} - {error}")
        return run
