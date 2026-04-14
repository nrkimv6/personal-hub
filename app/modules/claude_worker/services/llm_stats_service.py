"""LLMStatsService — 통계, cleanup, caller 그룹 조회.

DB 접근: LLMRequestRepository 경유.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMRequest

logger = logging.getLogger("claude_worker.llm_stats_service")


class LLMStatsService:
    """통계, cleanup, caller별 그룹 조회."""

    # 상수 정의
    STALE_PROCESSING_TIMEOUT_MINUTES = 65  # 시스템건 타임아웃(60분) + 여유 5분
    HISTORY_RETENTION_DAYS = 7

    def __init__(self, repo, db: Session):
        self._repo = repo
        self.db = db

    # ── 통계 ──────────────────────────────────────────────────────────────────

    def get_history_stats(
        self,
        start_date: date = None,
        end_date: date = None,
        group_by: str = "day",
    ) -> dict:
        """기간별 통계.

        Args:
            start_date: 시작일 (기본: 7일 전)
            end_date: 종료일 (기본: 오늘)
            group_by: 그룹 단위 (day, week, month)

        Returns:
            {"data": [...], "summary": {...}}
        """
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = end_date - timedelta(days=7)

        all_requests = self._repo.find_by_date_range(
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.max.time()),
        )

        # 일별 그룹화
        daily_data = {}
        for req in all_requests:
            day_key = req.requested_at.date().isoformat()
            if day_key not in daily_data:
                daily_data[day_key] = {"date": day_key, "total": 0, "completed": 0, "failed": 0, "pending": 0}
            daily_data[day_key]["total"] += 1
            if req.status == "completed":
                daily_data[day_key]["completed"] += 1
            elif req.status == "failed":
                daily_data[day_key]["failed"] += 1
            elif req.status in ("pending", "processing"):
                daily_data[day_key]["pending"] += 1

        data = sorted(daily_data.values(), key=lambda x: x["date"])

        total = len(all_requests)
        completed = sum(1 for r in all_requests if r.status == "completed")
        failed = sum(1 for r in all_requests if r.status == "failed")

        processing_times = []
        for req in all_requests:
            if req.status == "completed" and req.processed_at and req.requested_at:
                seconds = (req.processed_at - req.requested_at).total_seconds()
                processing_times.append(seconds)

        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0

        return {
            "data": data,
            "summary": {
                "total": total,
                "completed": completed,
                "failed": failed,
                "success_rate": round(completed / total * 100, 1) if total > 0 else 0,
                "avg_processing_time_seconds": round(avg_processing_time, 1),
            },
        }

    def get_caller_stats(self) -> dict:
        """호출자별 통계."""
        results = self._repo.get_caller_stats_rows()

        stats = {}
        for caller_type, status, count in results:
            if caller_type not in stats:
                stats[caller_type] = {"total": 0, "pending": 0, "processing": 0, "completed": 0, "failed": 0}
            stats[caller_type][status] = count
            stats[caller_type]["total"] += count

        return stats

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup_stale_processing(self, timeout_minutes: int = None) -> int:
        """Stale processing 요청을 failed로 변경.

        Args:
            timeout_minutes: 타임아웃 (분). 기본값: STALE_PROCESSING_TIMEOUT_MINUTES

        Returns:
            처리된 요청 수
        """
        if timeout_minutes is None:
            timeout_minutes = self.STALE_PROCESSING_TIMEOUT_MINUTES

        threshold = datetime.now() - timedelta(minutes=timeout_minutes)
        stale_requests = self._repo.find_stale_processing(threshold)

        count = 0
        for request in stale_requests:
            request.status = "failed"
            request.processed_at = datetime.now()
            request.error_message = f"Stale processing: timeout after {timeout_minutes} minutes"
            request.retry_count += 1
            count += 1
            logger.info(
                f"Stale processing 정리: id={request.id}, "
                f"caller={request.caller_type}:{request.caller_id}"
            )

        if count > 0:
            self.db.commit()
            logger.info(f"Stale processing 정리 완료: {count}개")

        return count

    def cleanup_old_history(self, days: int = None, hard_delete: bool = True) -> int:
        """오래된 이력 삭제.

        Args:
            days: 보관 기간 (일). 기본값: HISTORY_RETENTION_DAYS
            hard_delete: True면 물리 삭제, False면 soft delete

        Returns:
            삭제된 요청 수
        """
        if days is None:
            days = self.HISTORY_RETENTION_DAYS

        threshold = datetime.now() - timedelta(days=days)
        old_requests = self._repo.find_old_history(threshold)

        count = 0
        for request in old_requests:
            if hard_delete:
                self._repo.delete(request)
            else:
                request.deleted_at = datetime.now()
            count += 1

        if count > 0:
            self.db.commit()
            logger.info(f"오래된 이력 삭제 완료: {count}개 (days={days}, hard_delete={hard_delete})")

        return count

    def run_cleanup(self) -> dict:
        """전체 cleanup 실행.

        Returns:
            {"stale_processing": n, "old_history": n}
        """
        stale = self.cleanup_stale_processing()
        old = self.cleanup_old_history()
        return {"stale_processing": stale, "old_history": old}

    # ── caller별 그룹 조회 ────────────────────────────────────────────────────

    def _build_caller_aggregate_query(self, caller_type: str = None):
        """caller별 집계 쿼리 빌더 — repo에 위임."""
        return self._repo.build_caller_aggregate_query(caller_type)

    def list_requests_grouped_by_caller(
        self,
        caller_type: str = None,
        only_without_success: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """caller_id별 그룹 요청 목록. GROUP BY 집계 + 배치 상세 2-query."""
        from sqlalchemy import and_

        # 집계 쿼리 실행 — 로우 수 = distinct (caller_type, caller_id) 수
        all_agg = self._build_caller_aggregate_query(caller_type).all()

        # summary: only_without_success 필터 전(전체 caller 기준)
        total_callers = len(all_agg)
        callers_with_success = sum(1 for r in all_agg if r.has_success)
        callers_without_success = total_callers - callers_with_success
        summary = {
            "total_callers": total_callers,
            "callers_with_success": callers_with_success,
            "callers_without_success": callers_without_success,
        }

        # only_without_success 필터 (ORDER BY는 DB에 위임됨)
        filtered = [r for r in all_agg if not r.has_success] if only_without_success else all_agg

        total = len(filtered)
        pages = (total + page_size - 1) // page_size if total > 0 else 1
        paged = filtered[(page - 1) * page_size : page * page_size]

        if not paged:
            return {
                "items": [],
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": pages,
                "summary": summary,
            }

        # 페이지 caller 키셋으로 상세 배치 조회 (최대 page_size건 OR 조건)
        caller_keys = [(r.caller_type, r.caller_id) for r in paged]
        conditions = [
            and_(LLMRequest.caller_type == ct, LLMRequest.caller_id == ci)
            for ct, ci in caller_keys
        ]
        detail_rows = self._repo.find_by_caller_batch(conditions)

        # caller별 상세 매핑
        # ASC 정렬이므로: 첫 row = prompt, 마지막 row = last_status/last_error
        caller_detail: dict = {}
        for req in detail_rows:
            key = (req.caller_type, req.caller_id)
            caller_detail.setdefault(key, {
                "prompt": req.prompt,  # ASC 첫 row의 prompt
                "last_status": req.status,
                "last_error": None,
                "request_ids": [],
            })
            d = caller_detail[key]
            d["last_status"] = req.status  # ASC 마지막 row로 덮어쓰기
            if req.status == "failed":
                d["request_ids"].append(req.id)
                if req.error_message:
                    d["last_error"] = req.error_message  # ASC 마지막 failed row의 error

        # 결과 조립
        items = []
        for r in paged:
            key = (r.caller_type, r.caller_id)
            detail = caller_detail.get(
                key,
                {"prompt": None, "last_status": None, "last_error": None, "request_ids": []},
            )
            items.append(
                {
                    "caller_type": r.caller_type,
                    "caller_id": r.caller_id,
                    "total_count": r.total_count,
                    "completed_count": r.completed_count,
                    "failed_count": r.failed_count,
                    "pending_count": r.pending_count,
                    "has_success": bool(r.has_success),
                    "last_status": detail["last_status"],
                    "last_requested_at": r.last_at.isoformat() if r.last_at else None,
                    "last_error": detail["last_error"],
                    "request_ids": detail["request_ids"],
                    "prompt": detail["prompt"],
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "summary": summary,
        }

    def retry_failed_callers_without_success(self, caller_type: str = None) -> dict:
        """성공한 적 없는 caller들의 실패 요청을 일괄 재시도.

        Args:
            caller_type: 호출자 타입 필터 (선택)

        Returns:
            {"retried": n, "callers": n}
        """
        grouped = self.list_requests_grouped_by_caller(
            caller_type=caller_type,
            only_without_success=True,
            page=1,
            page_size=10000,
        )

        retried = 0
        callers = 0

        for group in grouped["items"]:
            if group["request_ids"]:
                callers += 1
                for request_id in group["request_ids"]:
                    request = self._repo.get_by_id(request_id)
                    if request and request.status == "failed":
                        request.status = "pending"
                        request.error_message = None
                        request.result = None
                        request.raw_response = None
                        request.processed_at = None
                        retried += 1

        if retried > 0:
            self.db.commit()
            logger.info(f"성공 없는 caller 일괄 재시도: {retried}개 요청, {callers}개 caller")

        return {"retried": retried, "callers": callers}

    # ── 기본 통계 / 성능 분석 ─────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """통계 조회. 목록/큐 화면과 동일하게 soft-deleted 요청은 제외한다."""
        rows = self._repo.get_status_counts()
        counts = {s: n for s, n in rows}
        return {
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "processing": counts.get("processing", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
        }

    def get_performance_stats(self, hours: int = 24) -> dict:
        """성능 분석 통계.

        Args:
            hours: 분석 기간 (시간)

        Returns:
            LLM 처리 시간 통계, 시간대별 분포 등
        """
        from datetime import datetime, timedelta

        threshold = datetime.now() - timedelta(hours=hours)

        completed_requests = self._repo.find_completed_since(threshold)
        failed_count = self._repo.count_failed_since(threshold)

        processing_times = []
        for req in completed_requests:
            if req.processed_at and req.requested_at:
                seconds = (req.processed_at - req.requested_at).total_seconds()
                processing_times.append(seconds)

        if processing_times:
            processing_times.sort()
            total_requests = len(processing_times)
            avg_time = sum(processing_times) / total_requests
            min_time = processing_times[0]
            max_time = processing_times[-1]
            p50 = processing_times[int(total_requests * 0.5)]
            p95 = processing_times[int(total_requests * 0.95)] if total_requests >= 20 else max_time
        else:
            total_requests = 0
            avg_time = min_time = max_time = p50 = p95 = 0

        by_hour = []
        for i in range(min(hours, 24)):
            hour_start = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=i)
            hour_end = hour_start + timedelta(hours=1)

            hour_requests = [
                r for r in completed_requests
                if r.processed_at and hour_start <= r.processed_at < hour_end
            ]

            hour_times = []
            for req in hour_requests:
                if req.processed_at and req.requested_at:
                    seconds = (req.processed_at - req.requested_at).total_seconds()
                    hour_times.append(seconds)

            by_hour.append({
                "hour": hour_start.strftime("%H:00"),
                "count": len(hour_requests),
                "avg_time": round(sum(hour_times) / len(hour_times), 1) if hour_times else 0,
            })

        by_hour.reverse()

        slow_requests = []
        if completed_requests:
            sorted_by_time = sorted(
                completed_requests,
                key=lambda r: (r.processed_at - r.requested_at).total_seconds() if r.processed_at and r.requested_at else 0,
                reverse=True,
            )[:10]

            for req in sorted_by_time:
                if req.processed_at and req.requested_at:
                    slow_requests.append({
                        "id": req.id,
                        "caller_type": req.caller_type,
                        "caller_id": req.caller_id,
                        "processing_time": round((req.processed_at - req.requested_at).total_seconds(), 1),
                        "requested_at": req.requested_at.isoformat(),
                    })

        return {
            "period_hours": hours,
            "llm_stats": {
                "total_requests": total_requests,
                "failed_count": failed_count,
                "avg_processing_time": round(avg_time, 1),
                "min_time": round(min_time, 1),
                "max_time": round(max_time, 1),
                "p50": round(p50, 1),
                "p95": round(p95, 1),
            },
            "by_hour": by_hour,
            "slow_requests": slow_requests,
        }
