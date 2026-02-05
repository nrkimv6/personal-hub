"""
모바일 크롤링 워커

TaskSchedule에서 mobile_crawl 타입 예약을 처리합니다.
모바일 서버에 크롤링을 요청하고 결과를 DB에 저장합니다.

Mock 모드:
    - 모바일 서버 연결 실패 시 Mock 데이터로 테스트 가능
    - MOBILE_CRAWL_MOCK=true 환경변수 설정 시 항상 Mock 사용
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import TaskSchedule, TaskScheduleRun
from app.modules.mobile_crawl.services.mobile_server_client import MobileServerClient
from app.modules.mobile_crawl.services.target_service import MobileCrawlTargetService
from app.modules.mobile_crawl.services.item_service import MobileCrawlItemService
from app.shared.worker.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class MobileCrawlWorker(BaseWorker):
    """
    모바일 크롤링 워커

    TaskSchedule에서 mobile_crawl 타입의 due 예약을 찾아 실행합니다.
    모바일 서버에 크롤링을 요청하고 결과를 DB에 저장합니다.
    """

    def __init__(self, browser_manager=None):
        """
        Args:
            browser_manager: 사용하지 않음 (모바일 서버가 브라우저 관리)
        """
        super().__init__("mobile_crawl", browser_manager)
        self.check_interval = 60  # 60초마다 체크
        self.mobile_client = MobileServerClient()
        self.use_mock = os.environ.get("MOBILE_CRAWL_MOCK", "false").lower() == "true"

        if self.use_mock:
            logger.info("[MobileCrawlWorker] Mock 모드 활성화")

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 (초)"""
        return self.check_interval

    async def _main_loop_iteration(self):
        """한 사이클의 작업 수행"""
        await self._safe_execute("check_schedules", self._check_and_execute_schedules)

    async def _check_and_execute_schedules(self):
        """Due 스케줄 확인 및 실행"""
        db = SessionLocal()
        try:
            now = datetime.utcnow()

            # mobile_crawl 타입의 due 스케줄 조회
            schedules = db.query(TaskSchedule).filter(
                TaskSchedule.target_type == "mobile_crawl",
                TaskSchedule.enabled == True,
                TaskSchedule.next_run_at <= now
            ).limit(10).all()

            if not schedules:
                logger.debug("[MobileCrawlWorker] 실행할 스케줄 없음")
                return

            logger.info(f"[MobileCrawlWorker] {len(schedules)}개의 스케줄 발견")

            for schedule in schedules:
                try:
                    await self._execute_schedule(db, schedule)
                except Exception as e:
                    logger.error(
                        f"[MobileCrawlWorker] 스케줄 {schedule.id} 실행 실패: {str(e)}",
                        exc_info=True
                    )
                    # 다음 스케줄 계속 처리

            db.commit()

        except Exception as e:
            db.rollback()
            logger.error(f"[MobileCrawlWorker] 스케줄 확인 중 오류: {str(e)}", exc_info=True)
            raise
        finally:
            db.close()

    async def _execute_schedule(self, db: Session, schedule: TaskSchedule):
        """개별 스케줄 실행"""
        logger.info(f"[MobileCrawlWorker] 스케줄 {schedule.id} 실행 시작")

        # TaskScheduleRun 생성
        run = TaskScheduleRun(
            schedule_id=schedule.id,
            status="running",
            started_at=datetime.utcnow()
        )
        db.add(run)
        db.flush()  # run.id 생성

        run_id = run.id

        try:
            # target_config에서 mobile_crawl_target_id 추출
            target_id = schedule.get_target_config().get("mobile_crawl_target_id")
            if not target_id:
                raise ValueError("target_config에 mobile_crawl_target_id가 없습니다")

            # 대상 정보 조회
            target = MobileCrawlTargetService.get_target(db, target_id)
            if not target:
                raise ValueError(f"크롤링 대상 {target_id}를 찾을 수 없습니다")

            logger.info(
                f"[MobileCrawlWorker] 대상: {target.name} ({target.url})"
            )

            # 크롤링 실행 (Mock 또는 실제)
            if self.use_mock:
                result = await self._execute_mock_crawl(target)
            else:
                result = await self._execute_real_crawl(target)

            # 아이템 저장
            stats = MobileCrawlItemService.save_items(
                db=db,
                target_id=target_id,
                run_id=run_id,
                items=result["items"]
            )

            # 실행 완료 처리
            run.mark_completed(
                collected_count=result["total_count"],
                saved_count=stats["new"] + stats["updated"]
            )

            # 다음 실행 시간 갱신
            interval = int(schedule.schedule_value) if schedule.schedule_value else 3600
            next_run = datetime.utcnow() + timedelta(seconds=interval)
            schedule.update_last_run(next_run_at=next_run)

            logger.info(
                f"[MobileCrawlWorker] 스케줄 {schedule.id} 완료: "
                f"수집 {result['total_count']}건, "
                f"신규 {stats['new']}건, "
                f"변경 {stats['updated']}건"
            )

        except Exception as e:
            # 실행 실패 처리
            run.mark_failed(error_message=str(e))

            # 다음 실행 시간은 갱신 (계속 시도)
            interval = int(schedule.schedule_value) if schedule.schedule_value else 3600
            next_run = datetime.utcnow() + timedelta(seconds=interval)
            schedule.update_last_run(next_run_at=next_run)

            logger.error(
                f"[MobileCrawlWorker] 스케줄 {schedule.id} 실패: {str(e)}"
            )

    async def _execute_real_crawl(self, target) -> dict:
        """실제 모바일 서버로 크롤링 실행"""
        logger.info("[MobileCrawlWorker] 모바일 서버로 크롤링 요청")

        try:
            result = await self.mobile_client.crawl(
                url=target.url,
                parse_config=target.parse_config
            )

            return result

        except Exception as e:
            logger.warning(
                f"[MobileCrawlWorker] 모바일 서버 연결 실패, Mock 모드로 전환: {str(e)}"
            )
            return await self._execute_mock_crawl(target)

    async def _execute_mock_crawl(self, target) -> dict:
        """Mock 크롤링 실행 (테스트용)"""
        logger.info("[MobileCrawlWorker] Mock 크롤링 실행")

        # 샘플 아이템 생성
        import random

        mock_items = []
        num_items = random.randint(2, 5)

        for i in range(num_items):
            mock_items.append({
                "title": f"Mock 아이템 {i+1} - {target.name}",
                "item_url": f"{target.url}/items/mock-{i+1}",
                "image_url": f"https://via.placeholder.com/300x200?text=Mock+{i+1}",
                "attributes": {
                    "price": f"{random.randint(10, 100) * 1000}원",
                    "status": random.choice(["재고 있음", "품절", "예약 중"]),
                    "date": datetime.utcnow().strftime("%Y-%m-%d")
                },
                "raw_html": f"<div class='mock-item'>{target.name} Mock {i+1}</div>"
            })

        # 지연 시뮬레이션
        await asyncio.sleep(random.uniform(0.5, 2.0))

        return {
            "items": mock_items,
            "total_count": len(mock_items),
            "pages_crawled": 1,
            "errors": []
        }
