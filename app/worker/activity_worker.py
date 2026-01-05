"""
Activity Worker - 문화/체육센터 강좌 크롤링 워커.

센터별 크롤링을 수행하고 ImportService를 통해 데이터를 저장합니다.

주요 기능:
    - CrawlRequest(url_type='activity') 처리
    - 센터별 크롤링 실행 (crawl_method에 따라 static/dynamic/api)
    - BrowserManager 연동 (동적 크롤링 대비)

Note:
    현재는 기본 틀만 구현되어 있으며, 실제 사이트별 크롤러는
    샘플 사이트 분석 후 추가됩니다.
"""
import asyncio
import logging
from typing import Optional
from datetime import datetime

from app.worker.crawl_worker_base import CrawlWorkerBase
from app.shared.browser.browser_manager import BrowserManager
from app.database import SessionLocal
from app.models.activity import ActivityCenter, ActivityCrawlRun
from app.models.crawl_request import CrawlRequest

logger = logging.getLogger(__name__)


class ActivityWorker(CrawlWorkerBase):
    """문화/체육센터 강좌 크롤링 워커.

    CrawlWorkerBase를 상속하여 브라우저 관리, 상태 추적 등
    공통 기능을 활용합니다.

    Attributes:
        _poll_interval: 요청 폴링 간격 (초)
    """

    def __init__(
        self,
        browser_manager: Optional[BrowserManager] = None,
        poll_interval: float = 5.0,
    ):
        """ActivityWorker 초기화.

        Args:
            browser_manager: 외부에서 주입받을 BrowserManager
            poll_interval: 요청 폴링 간격 (초)
        """
        super().__init__(
            name="ActivityWorker",
            worker_type="activity",
            browser_manager=browser_manager
        )
        self._poll_interval = poll_interval
        self._processing = False

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 반환."""
        return self._poll_interval

    async def _main_loop_iteration(self):
        """메인 루프 반복 - 요청 처리."""
        if self._processing:
            return

        try:
            # pending 상태의 activity 요청 조회
            request = self._get_pending_request()
            if not request:
                return

            self._processing = True
            self._update_worker_state("processing", run_id=request.id)

            try:
                await self._process_request(request)
            except Exception as e:
                logger.error(f"[ActivityWorker] 요청 처리 오류: {e}", exc_info=True)
                self._mark_request_failed(request.id, str(e))
            finally:
                self._processing = False
                self._update_worker_state("idle")

        except Exception as e:
            logger.error(f"[ActivityWorker] 루프 오류: {e}", exc_info=True)

    def _get_pending_request(self) -> Optional[CrawlRequest]:
        """대기 중인 activity 요청 조회."""
        db = SessionLocal()
        try:
            request = db.query(CrawlRequest).filter(
                CrawlRequest.url_type == CrawlRequest.URL_TYPE_ACTIVITY,
                CrawlRequest.status == CrawlRequest.STATUS_PENDING,
            ).order_by(CrawlRequest.requested_at).first()

            if request:
                request.mark_picked(self.worker_id or "activity_worker")
                db.commit()
                db.refresh(request)

            return request

        except Exception as e:
            logger.error(f"[ActivityWorker] 요청 조회 오류: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    async def _process_request(self, request: CrawlRequest):
        """요청 처리.

        Args:
            request: CrawlRequest 인스턴스
        """
        logger.info(f"[ActivityWorker] 요청 처리 시작: id={request.id}, url={request.url}")

        db = SessionLocal()
        try:
            # 요청을 processing 상태로 변경
            req = db.query(CrawlRequest).filter(CrawlRequest.id == request.id).first()
            if req:
                req.mark_processing()
                db.commit()

            # URL에서 센터 ID 추출 또는 센터 조회
            center = self._get_center_from_url(db, request.url)

            if not center:
                raise ValueError(f"센터를 찾을 수 없습니다: {request.url}")

            # 크롤링 실행 기록 생성
            crawl_run = ActivityCrawlRun(center_id=center.id)
            db.add(crawl_run)
            db.commit()
            db.refresh(crawl_run)

            try:
                # 실제 크롤링 수행 (사이트별 크롤러 호출)
                result = await self._crawl_center(center, crawl_run.id)

                # 완료 처리
                crawl_run.mark_completed(
                    found=result.get("found", 0),
                    new=result.get("new", 0),
                    updated=result.get("updated", 0)
                )

                # 센터 마지막 크롤링 시간 업데이트
                center.last_crawled_at = datetime.now()

                # 요청 완료 처리
                req = db.query(CrawlRequest).filter(CrawlRequest.id == request.id).first()
                if req:
                    req.mark_completed("activity_crawl_run", crawl_run.id)

                db.commit()

                logger.info(
                    f"[ActivityWorker] 크롤링 완료: center={center.name}, "
                    f"found={result.get('found', 0)}, new={result.get('new', 0)}"
                )

            except Exception as e:
                crawl_run.mark_failed(str(e))
                db.commit()
                raise

        except Exception as e:
            logger.error(f"[ActivityWorker] 요청 처리 실패: {e}")
            self._mark_request_failed(request.id, str(e))
            raise
        finally:
            db.close()

    def _get_center_from_url(self, db, url: str) -> Optional[ActivityCenter]:
        """URL에서 센터 정보 추출.

        URL 형식:
            - activity://center/{center_id}
            - 또는 실제 센터 URL (crawl_url과 매칭)

        Args:
            db: DB 세션
            url: 요청 URL

        Returns:
            ActivityCenter 또는 None
        """
        # activity://center/{id} 형식
        if url.startswith("activity://center/"):
            try:
                center_id = int(url.split("/")[-1])
                return db.query(ActivityCenter).filter(
                    ActivityCenter.id == center_id
                ).first()
            except ValueError:
                pass

        # crawl_url로 매칭
        return db.query(ActivityCenter).filter(
            ActivityCenter.crawl_url == url,
            ActivityCenter.is_active == True
        ).first()

    async def _crawl_center(self, center: ActivityCenter, crawl_run_id: int) -> dict:
        """센터 크롤링 수행.

        Args:
            center: 센터 모델
            crawl_run_id: 크롤링 실행 ID

        Returns:
            결과 딕셔너리 {found, new, updated}
        """
        from app.modules.activity.crawlers import get_crawler
        from app.modules.activity.services.import_service import ImportService
        from app.modules.activity.models.schemas import CourseImportRequest

        logger.info(
            f"[ActivityWorker] 크롤링 시작: "
            f"center={center.name}, method={center.crawl_method}"
        )

        # 크롤러 획득
        page = None
        if center.crawl_method == "dynamic":
            # 동적 크롤링이 필요한 경우 브라우저 탭 사용
            if self.browser:
                await self._ensure_browser_initialized()
                # TabPoolManager를 통해 탭 획득 (center.id를 target_id로 사용)
                page = await self.browser.tab_pool_manager.get_tab(
                    target_id=center.id,
                    service_account_id=None  # 기본 계정 사용
                )

        try:
            crawler = get_crawler(center, page)

            if not crawler:
                raise ValueError(f"지원되지 않는 크롤러: {center.name}")

            # DB 세션 및 ImportService 생성
            db = SessionLocal()
            import_service = ImportService(db)

            # 수집 결과 추적
            stats = {"found": 0, "new": 0, "updated": 0}

            async def on_course_collected(course):
                """강좌 수집 콜백 - 실시간 저장."""
                nonlocal stats
                try:
                    # 단일 강좌 임포트
                    request = CourseImportRequest(
                        courses=[course],
                        update_existing=True,
                    )
                    result = import_service.import_courses(request, crawl_run_id)

                    stats["found"] += 1
                    stats["new"] += result.created
                    stats["updated"] += result.updated

                    return result.created > 0
                except Exception as e:
                    logger.error(f"[ActivityWorker] 강좌 저장 실패: {e}")
                    return False

            try:
                # 크롤링 실행
                result = await crawler.crawl(on_course_collected=on_course_collected)

                logger.info(
                    f"[ActivityWorker] 크롤링 결과: status={result.status}, "
                    f"found={stats['found']}, new={stats['new']}, updated={stats['updated']}"
                )

                if result.error_message:
                    logger.warning(
                        f"[ActivityWorker] 크롤링 오류: {result.error_message}"
                    )

                return stats

            finally:
                db.close()

        finally:
            # 동적 크롤링 탭 정리
            if page:
                try:
                    await page.close()
                except Exception as e:
                    logger.warning(f"[ActivityWorker] 페이지 정리 실패: {e}")

    def _mark_request_failed(self, request_id: int, error: str):
        """요청 실패 처리."""
        db = SessionLocal()
        try:
            req = db.query(CrawlRequest).filter(CrawlRequest.id == request_id).first()
            if req:
                req.mark_failed(error)
                db.commit()
        except Exception as e:
            logger.error(f"[ActivityWorker] 요청 실패 처리 오류: {e}")
        finally:
            db.close()

    def _cleanup_stale_requests(self):
        """오래된 processing 상태 요청 정리."""
        db = SessionLocal()
        try:
            from datetime import timedelta

            # 1시간 이상 processing 상태인 요청 정리
            stale_threshold = datetime.now() - timedelta(hours=1)

            stale_requests = db.query(CrawlRequest).filter(
                CrawlRequest.url_type == CrawlRequest.URL_TYPE_ACTIVITY,
                CrawlRequest.status.in_([
                    CrawlRequest.STATUS_PICKED,
                    CrawlRequest.STATUS_PROCESSING
                ]),
                CrawlRequest.picked_at < stale_threshold
            ).all()

            for req in stale_requests:
                req.mark_failed("워커 재시작으로 인한 정리")
                logger.info(f"[ActivityWorker] Stale 요청 정리: id={req.id}")

            if stale_requests:
                db.commit()
                logger.info(f"[ActivityWorker] {len(stale_requests)}개 stale 요청 정리됨")

        except Exception as e:
            logger.error(f"[ActivityWorker] Stale 요청 정리 오류: {e}")
            db.rollback()
        finally:
            db.close()

    def get_status(self) -> dict:
        """워커 상태 정보 반환."""
        status = super().get_status()
        status["processing"] = self._processing
        status["poll_interval"] = self._poll_interval
        return status
