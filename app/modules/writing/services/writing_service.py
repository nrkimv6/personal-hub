"""Writing Service - 글 생성 관련 비즈니스 로직."""

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.models.writing import (
    WritingSource,
    GeneratedWriting,
    WritingRssFeed,
    WritingSearchQuery,
)


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

    def get_writing_schedule(self) -> Optional[TaskSchedule]:
        """작문 스케줄 조회."""
        return (
            self.db.query(TaskSchedule)
            .filter(
                TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_WRITING_TASK,
                TaskSchedule.enabled == True,
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
            schedule = TaskSchedule(
                name="writing_task_manual",
                display_name="수동 글쓰기",
                target_type=TaskSchedule.TARGET_TYPE_WRITING_TASK,
                schedule_type=TaskSchedule.SCHEDULE_TYPE_MANUAL,
                enabled=True,
            )
            self.db.add(schedule)
            self.db.commit()
            self.db.refresh(schedule)

        # 실행 기록 생성
        run = TaskScheduleRun(
            schedule_id=schedule.id,
            started_at=datetime.now(),
            status=TaskScheduleRun.STATUS_RUNNING,
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
            self.db.query(TaskSchedule)
            .filter(
                TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_WRITING_TASK,
                TaskSchedule.enabled == True,
                TaskSchedule.next_run_at <= now,
            )
            .first()
        )

        if not schedule:
            return None

        # 이미 실행 중인지 확인
        running = (
            self.db.query(TaskScheduleRun)
            .filter(
                TaskScheduleRun.schedule_id == schedule.id,
                TaskScheduleRun.status == TaskScheduleRun.STATUS_RUNNING,
            )
            .first()
        )
        if running:
            return None

        # 실행 기록 생성
        run = TaskScheduleRun(
            schedule_id=schedule.id,
            started_at=datetime.now(),
            status=TaskScheduleRun.STATUS_RUNNING,
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

    # ========== RSS 피드 관리 ==========

    def list_feeds(
        self,
        source_type: Optional[str] = None,
        enabled_only: bool = True,
    ) -> list[WritingRssFeed]:
        """RSS 피드 목록 조회."""
        query = self.db.query(WritingRssFeed)

        if enabled_only:
            query = query.filter(WritingRssFeed.enabled == 1)

        if source_type:
            query = query.filter(WritingRssFeed.source_type == source_type)

        return query.order_by(WritingRssFeed.id.desc()).all()

    def get_feed(self, feed_id: int) -> Optional[WritingRssFeed]:
        """RSS 피드 상세 조회."""
        return self.db.query(WritingRssFeed).filter(WritingRssFeed.id == feed_id).first()

    def add_feed(
        self,
        name: str,
        url: str,
        source_type: str = WritingRssFeed.SOURCE_TYPE_TISTORY,
    ) -> WritingRssFeed:
        """RSS 피드 추가."""
        feed = WritingRssFeed(
            name=name,
            url=url,
            source_type=source_type,
            enabled=1,
        )
        self.db.add(feed)
        self.db.commit()
        self.db.refresh(feed)
        return feed

    def update_feed(
        self,
        feed_id: int,
        name: Optional[str] = None,
        url: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[WritingRssFeed]:
        """RSS 피드 수정."""
        feed = self.get_feed(feed_id)
        if not feed:
            return None

        if name is not None:
            feed.name = name
        if url is not None:
            feed.url = url
        if enabled is not None:
            feed.enabled = 1 if enabled else 0

        self.db.commit()
        self.db.refresh(feed)
        return feed

    def delete_feed(self, feed_id: int) -> bool:
        """RSS 피드 삭제."""
        feed = self.get_feed(feed_id)
        if not feed:
            return False

        self.db.delete(feed)
        self.db.commit()
        return True

    def update_feed_status(
        self,
        feed_id: int,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """RSS 피드 상태 업데이트."""
        feed = self.get_feed(feed_id)
        if not feed:
            return

        feed.last_fetched_at = datetime.now()
        feed.fetch_count += 1

        if not success:
            feed.error_count += 1
            feed.last_error = error_message

        self.db.commit()

    # ========== RSS 수집 ==========

    async def collect_from_feeds(
        self,
        min_length: int = 300,
        max_length: int = 3000,
    ) -> dict:
        """모든 활성 RSS 피드에서 글 수집.

        Returns:
            수집 결과 dict
        """
        from app.modules.writing.services.rss_collector import RSSCollector

        feeds = self.list_feeds(enabled_only=True)
        if not feeds:
            return {"collected": 0, "feeds": 0, "message": "No enabled feeds"}

        collector = RSSCollector()
        feed_urls = [feed.url for feed in feeds]

        # 수집
        items = await collector.collect_from_feeds(
            feed_urls,
            min_length=min_length,
            max_length=max_length,
        )

        # DB에 저장 (중복 체크)
        added = 0
        for item in items:
            # 해시로 중복 체크
            existing = (
                self.db.query(WritingSource)
                .filter(WritingSource.content_hash == item.get("content_hash"))
                .first()
            )
            if existing:
                continue

            # URL로도 중복 체크
            if item.get("link"):
                url_existing = (
                    self.db.query(WritingSource)
                    .filter(WritingSource.source_url == item["link"])
                    .first()
                )
                if url_existing:
                    continue

            # 새 소스 추가
            source = WritingSource(
                content=item["content"],
                category=None,  # 자동 분류 필요시 추후 구현
                source_info=item.get("author") or item.get("source"),
                source_url=item.get("link"),
                source_type=WritingSource.SOURCE_TYPE_RSS,
                content_hash=item.get("content_hash"),
            )
            self.db.add(source)
            added += 1

        self.db.commit()

        # 피드별 상태 업데이트
        for feed in feeds:
            self.update_feed_status(feed.id, success=True)

        return {
            "collected": added,
            "total_fetched": len(items),
            "feeds": len(feeds),
        }

    # ========== 검색 쿼리 관리 ==========

    def list_search_queries(
        self,
        source_type: Optional[str] = None,
        enabled_only: bool = True,
    ) -> list[WritingSearchQuery]:
        """검색 쿼리 목록 조회."""
        query = self.db.query(WritingSearchQuery)

        if enabled_only:
            query = query.filter(WritingSearchQuery.enabled == 1)

        if source_type:
            query = query.filter(WritingSearchQuery.source_type == source_type)

        return query.order_by(
            WritingSearchQuery.priority.desc(),
            WritingSearchQuery.id.desc(),
        ).all()

    def get_search_query(self, query_id: int) -> Optional[WritingSearchQuery]:
        """검색 쿼리 상세 조회."""
        return (
            self.db.query(WritingSearchQuery)
            .filter(WritingSearchQuery.id == query_id)
            .first()
        )

    def add_search_query(
        self,
        query: str,
        source_type: str = WritingSearchQuery.SOURCE_TYPE_NAVER,
        search_target: str = WritingSearchQuery.TARGET_BLOG,
        priority: int = 0,
    ) -> WritingSearchQuery:
        """검색 쿼리 추가."""
        search_query = WritingSearchQuery(
            query=query,
            source_type=source_type,
            search_target=search_target,
            priority=priority,
            enabled=1,
        )
        self.db.add(search_query)
        self.db.commit()
        self.db.refresh(search_query)
        return search_query

    def update_search_query(
        self,
        query_id: int,
        query: Optional[str] = None,
        source_type: Optional[str] = None,
        search_target: Optional[str] = None,
        enabled: Optional[bool] = None,
        priority: Optional[int] = None,
    ) -> Optional[WritingSearchQuery]:
        """검색 쿼리 수정."""
        search_query = self.get_search_query(query_id)
        if not search_query:
            return None

        if query is not None:
            search_query.query = query
        if source_type is not None:
            search_query.source_type = source_type
        if search_target is not None:
            search_query.search_target = search_target
        if enabled is not None:
            search_query.enabled = 1 if enabled else 0
        if priority is not None:
            search_query.priority = priority

        self.db.commit()
        self.db.refresh(search_query)
        return search_query

    def delete_search_query(self, query_id: int) -> bool:
        """검색 쿼리 삭제."""
        search_query = self.get_search_query(query_id)
        if not search_query:
            return False

        self.db.delete(search_query)
        self.db.commit()
        return True

    def update_search_query_status(
        self,
        query_id: int,
        success: bool,
        result_count: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """검색 쿼리 상태 업데이트."""
        search_query = self.get_search_query(query_id)
        if not search_query:
            return

        search_query.last_searched_at = datetime.now()
        search_query.result_count += result_count

        if success:
            search_query.success_count += 1
        else:
            search_query.error_count += 1
            search_query.last_error = error_message

        self.db.commit()

    # ========== 검색 수집 ==========

    async def collect_from_searches(
        self,
        source_type: Optional[str] = None,
        min_length: int = 100,
        max_length: int = 5000,
        max_queries: int = 10,
    ) -> dict:
        """검색 API에서 글 수집.

        Args:
            source_type: 검색 엔진 ('naver', 'kakao', None=전체)
            min_length: 최소 글자 수
            max_length: 최대 글자 수
            max_queries: 최대 쿼리 수

        Returns:
            수집 결과 dict
        """
        from app.modules.writing.services.search_collector import (
            NaverSearchCollector,
            KakaoSearchCollector,
            SearchContentFilter,
        )

        # 검색 쿼리 조회
        queries = self.list_search_queries(source_type=source_type, enabled_only=True)
        if not queries:
            return {"collected": 0, "queries": 0, "message": "No enabled queries"}

        # 최대 쿼리 수 제한
        queries = queries[:max_queries]

        # 수집기 초기화
        naver_collector = NaverSearchCollector()
        kakao_collector = KakaoSearchCollector()

        all_items = []
        query_results = []

        for q in queries:
            items = []
            error_message = None

            try:
                if q.source_type == WritingSearchQuery.SOURCE_TYPE_NAVER:
                    if not naver_collector.is_configured():
                        error_message = "Naver API not configured"
                    elif q.search_target == WritingSearchQuery.TARGET_BLOG:
                        items = await naver_collector.search_blog(q.query)
                    elif q.search_target == WritingSearchQuery.TARGET_CAFE:
                        items = await naver_collector.search_cafe(q.query)

                elif q.source_type == WritingSearchQuery.SOURCE_TYPE_KAKAO:
                    if not kakao_collector.is_configured():
                        error_message = "Kakao API not configured"
                    elif q.search_target == WritingSearchQuery.TARGET_BLOG:
                        items = await kakao_collector.search_blog(q.query)
                    elif q.search_target == WritingSearchQuery.TARGET_CAFE:
                        items = await kakao_collector.search_cafe(q.query)

                # 쿼리 상태 업데이트
                self.update_search_query_status(
                    q.id,
                    success=error_message is None,
                    result_count=len(items),
                    error_message=error_message,
                )

                all_items.extend(items)
                query_results.append({
                    "query": q.query,
                    "source_type": q.source_type,
                    "count": len(items),
                    "error": error_message,
                })

            except Exception as e:
                self.update_search_query_status(
                    q.id,
                    success=False,
                    error_message=str(e),
                )
                query_results.append({
                    "query": q.query,
                    "source_type": q.source_type,
                    "count": 0,
                    "error": str(e),
                })

        # 필터링
        filtered_items = SearchContentFilter.filter_items(
            all_items,
            min_length=min_length,
            max_length=max_length,
        )

        # DB에 저장 (중복 체크)
        added = 0
        for item in filtered_items:
            # 해시로 중복 체크
            existing = (
                self.db.query(WritingSource)
                .filter(WritingSource.content_hash == item.get("content_hash"))
                .first()
            )
            if existing:
                continue

            # URL로도 중복 체크
            if item.get("link"):
                url_existing = (
                    self.db.query(WritingSource)
                    .filter(WritingSource.source_url == item["link"])
                    .first()
                )
                if url_existing:
                    continue

            # 새 소스 추가
            source = WritingSource(
                content=item["content"],
                category=None,
                source_info=item.get("author") or item.get("source"),
                source_url=item.get("link"),
                source_type=WritingSource.SOURCE_TYPE_API,
                content_hash=item.get("content_hash"),
            )
            self.db.add(source)
            added += 1

        self.db.commit()

        return {
            "collected": added,
            "total_fetched": len(all_items),
            "filtered": len(filtered_items),
            "queries": len(queries),
            "query_results": query_results,
        }

    # ========== 위키문헌 수집 ==========

    async def collect_from_wikisource(
        self,
        categories: Optional[list[str]] = None,
        min_length: int = 200,
        max_length: int = 10000,
    ) -> dict:
        """위키문헌에서 글 수집.

        Args:
            categories: 카테고리 목록 (None이면 기본 카테고리)
            min_length: 최소 글자 수
            max_length: 최대 글자 수

        Returns:
            수집 결과 dict
        """
        from app.modules.writing.services.public_data_collector import (
            WikisourceCollector,
        )

        collector = WikisourceCollector()
        items = await collector.collect_all_categories(
            categories=categories,
            min_length=min_length,
            max_length=max_length,
        )

        if not items:
            return {"collected": 0, "total_fetched": 0, "message": "No items found"}

        # DB에 저장 (중복 체크)
        added = 0
        for item in items:
            # 해시로 중복 체크
            existing = (
                self.db.query(WritingSource)
                .filter(WritingSource.content_hash == item.get("content_hash"))
                .first()
            )
            if existing:
                continue

            # URL로도 중복 체크
            if item.get("link"):
                url_existing = (
                    self.db.query(WritingSource)
                    .filter(WritingSource.source_url == item["link"])
                    .first()
                )
                if url_existing:
                    continue

            # 새 소스 추가
            source = WritingSource(
                content=item["content"],
                category="위키문헌",
                source_info=item.get("title"),
                source_url=item.get("link"),
                source_type="wikisource",
                content_hash=item.get("content_hash"),
            )
            self.db.add(source)
            added += 1

        self.db.commit()

        return {
            "collected": added,
            "total_fetched": len(items),
        }
