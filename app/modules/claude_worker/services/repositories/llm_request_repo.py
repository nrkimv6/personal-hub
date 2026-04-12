"""LLMRequestRepository — LLMRequest ORM 쿼리 전담."""

from datetime import date, datetime
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import LLMRequest


class LLMRequestRepository:
    """LLMRequest DB 접근 단일 창구.

    commit/rollback은 Service 레벨(UoW 패턴)에서 수행.
    """

    def __init__(self, db: Session):
        self.db = db

    # ── 생성 ──────────────────────────────────────────────────────────────

    def add(self, request: LLMRequest) -> LLMRequest:
        """세션에 추가 (commit은 호출자 책임)."""
        self.db.add(request)
        return request

    # ── 단일 조회 ─────────────────────────────────────────────────────────

    def get_by_id(self, request_id: int) -> Optional[LLMRequest]:
        return self.db.query(LLMRequest).filter(LLMRequest.id == request_id).first()

    def find_existing_pending(
        self, caller_type: str, caller_id: str, queue_name: str
    ) -> Optional[LLMRequest]:
        """enqueue dedup — 같은 queue 내 pending 중복 확인."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == caller_type,
                LLMRequest.caller_id == caller_id,
                LLMRequest.queue_name == queue_name,
                LLMRequest.status == "pending",
                LLMRequest.deleted_at.is_(None),
            )
            .first()
        )

    def find_latest_by_caller(
        self, caller_type: str, caller_id: str
    ) -> Optional[LLMRequest]:
        """가장 최근 요청 조회 (get_result용)."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == caller_type,
                LLMRequest.caller_id == caller_id,
            )
            .order_by(LLMRequest.requested_at.desc())
            .first()
        )

    def find_oldest_pending(self) -> Optional[LLMRequest]:
        """가장 오래된 pending 조회 (레거시 get_pending_request용)."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status == "pending",
                LLMRequest.deleted_at.is_(None),
            )
            .order_by(LLMRequest.requested_at.asc())
            .first()
        )

    def find_next_pending_in_queue(
        self, queue_name: str, exclude_providers: List[str] = None
    ) -> Optional[LLMRequest]:
        """특정 큐에서 가장 오래된 pending 조회."""
        query = self.db.query(LLMRequest).filter(
            LLMRequest.queue_name == queue_name,
            LLMRequest.status == "pending",
            LLMRequest.deleted_at.is_(None),
        )
        if exclude_providers:
            query = query.filter(LLMRequest.provider.notin_(exclude_providers))
        return query.order_by(LLMRequest.requested_at.asc()).first()

    # ── 목록 조회 ─────────────────────────────────────────────────────────

    def list_with_filters(
        self,
        status: str = None,
        caller_type: str = None,
        requested_by: str = None,
        include_deleted: bool = False,
        page: int = 1,
        page_size: int = 20,
        queue_name: str = None,
    ) -> Tuple[List[LLMRequest], int]:
        """필터/페이지네이션 목록 조회. (items, total) 반환."""
        query = self.db.query(LLMRequest)
        if not include_deleted:
            query = query.filter(LLMRequest.deleted_at.is_(None))
        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if len(statuses) == 1:
                query = query.filter(LLMRequest.status == statuses[0])
            elif len(statuses) > 1:
                query = query.filter(LLMRequest.status.in_(statuses))
        if caller_type:
            query = query.filter(LLMRequest.caller_type == caller_type)
        if requested_by:
            query = query.filter(LLMRequest.requested_by == requested_by)
        if queue_name:
            query = query.filter(LLMRequest.queue_name == queue_name)

        total = query.count()
        items = (
            query.order_by(LLMRequest.requested_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def find_by_ids(self, request_ids: List[int]) -> List[LLMRequest]:
        """ID 목록으로 요청 조회."""
        return (
            self.db.query(LLMRequest)
            .filter(LLMRequest.id.in_(request_ids))
            .all()
        )

    def find_quota_failed(self, provider: str) -> List[LLMRequest]:
        """quota 에러로 실패한 요청 조회."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status == "failed",
                LLMRequest.provider == provider,
                LLMRequest.deleted_at.is_(None),
            )
            .filter(
                (LLMRequest.error_message.like("%TerminalQuotaError%"))
                | (LLMRequest.error_message.like("%exhausted your capacity%"))
            )
            .all()
        )

    def find_stale_processing(self, threshold: datetime) -> List[LLMRequest]:
        """threshold보다 오래된 processing 요청 조회."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status == "processing",
                LLMRequest.requested_at < threshold,
                LLMRequest.deleted_at.is_(None),
            )
            .all()
        )

    def find_old_history(self, threshold: datetime) -> List[LLMRequest]:
        """threshold보다 오래된 완료/실패/취소 요청 조회."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status.in_(["completed", "failed", "cancelled"]),
                LLMRequest.processed_at < threshold,
                LLMRequest.deleted_at.is_(None),
            )
            .all()
        )

    def find_by_date_range(self, start: datetime, end: datetime) -> List[LLMRequest]:
        """날짜 범위 내 요청 조회 (get_history_stats용)."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.requested_at >= start,
                LLMRequest.requested_at <= end,
                LLMRequest.deleted_at.is_(None),
            )
            .all()
        )

    def find_completed_since(self, threshold: datetime) -> List[LLMRequest]:
        """threshold 이후 완료된 요청 조회 (성능 통계용)."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status == "completed",
                LLMRequest.requested_at >= threshold,
                LLMRequest.processed_at.isnot(None),
                LLMRequest.deleted_at.is_(None),
            )
            .all()
        )

    def find_by_caller_batch(self, conditions) -> List[LLMRequest]:
        """caller_key 목록으로 상세 배치 조회 (list_requests_grouped_by_caller용)."""
        from sqlalchemy import and_, or_
        return (
            self.db.query(LLMRequest)
            .filter(LLMRequest.deleted_at.is_(None), or_(*conditions))
            .order_by(
                LLMRequest.caller_type,
                LLMRequest.caller_id,
                LLMRequest.requested_at.asc(),
            )
            .all()
        )

    # ── 카운트 / 집계 ──────────────────────────────────────────────────────

    def count_pending(self) -> int:
        """Pending 요청 수."""
        return (
            self.db.query(LLMRequest)
            .filter(LLMRequest.status == "pending", LLMRequest.deleted_at.is_(None))
            .count()
        )

    def count_blocked_by_provider(self, provider: str) -> int:
        """특정 provider로 막힌 pending 수."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status == "pending",
                LLMRequest.provider == provider,
                LLMRequest.deleted_at.is_(None),
            )
            .count()
        )

    def count_failed_since(self, threshold: datetime) -> int:
        """threshold 이후 실패 요청 수."""
        return (
            self.db.query(LLMRequest)
            .filter(
                LLMRequest.status == "failed",
                LLMRequest.requested_at >= threshold,
                LLMRequest.deleted_at.is_(None),
            )
            .count()
        )

    def get_queue_stats_rows(self):
        """큐별/상태별 카운트 집계 rows 반환."""
        return (
            self.db.query(
                LLMRequest.queue_name,
                LLMRequest.status,
                func.count(LLMRequest.id).label("cnt"),
            )
            .filter(LLMRequest.deleted_at.is_(None))
            .group_by(LLMRequest.queue_name, LLMRequest.status)
            .all()
        )

    def get_caller_stats_rows(self):
        """caller_type별/상태별 카운트 집계 rows 반환."""
        return (
            self.db.query(
                LLMRequest.caller_type,
                LLMRequest.status,
                func.count(LLMRequest.id).label("count"),
            )
            .filter(LLMRequest.deleted_at.is_(None))
            .group_by(LLMRequest.caller_type, LLMRequest.status)
            .all()
        )

    def get_status_counts(self):
        """status별 카운트 집계 rows 반환 (get_stats용, deleted 포함)."""
        return (
            self.db.query(LLMRequest.status, func.count())
            .group_by(LLMRequest.status)
            .all()
        )

    def build_caller_aggregate_query(self, caller_type: str = None):
        """caller별 GROUP BY 집계 쿼리 반환 (_build_caller_aggregate_query 이전)."""
        from sqlalchemy import case as sa_case

        completed_sum = func.coalesce(
            func.sum(sa_case((LLMRequest.status == "completed", 1), else_=0)), 0
        )
        failed_sum = func.coalesce(
            func.sum(sa_case((LLMRequest.status == "failed", 1), else_=0)), 0
        )
        pending_sum = func.coalesce(
            func.sum(
                sa_case(
                    (LLMRequest.status.in_(["pending", "processing"]), 1),
                    else_=0,
                )
            ),
            0,
        )
        has_success_max = func.coalesce(
            func.max(sa_case((LLMRequest.status == "completed", 1), else_=0)), 0
        )

        q = (
            self.db.query(
                LLMRequest.caller_type,
                LLMRequest.caller_id,
                func.count().label("total_count"),
                completed_sum.label("completed_count"),
                failed_sum.label("failed_count"),
                pending_sum.label("pending_count"),
                func.max(LLMRequest.requested_at).label("last_at"),
                has_success_max.label("has_success"),
            )
            .filter(LLMRequest.deleted_at.is_(None))
            .group_by(LLMRequest.caller_type, LLMRequest.caller_id)
            .order_by(func.max(LLMRequest.requested_at).desc())
        )
        if caller_type:
            q = q.filter(LLMRequest.caller_type == caller_type)
        return q

    # ── 삭제 ──────────────────────────────────────────────────────────────

    def delete(self, request: LLMRequest) -> None:
        """물리 삭제 (commit은 호출자 책임)."""
        self.db.delete(request)
