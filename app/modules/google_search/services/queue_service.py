"""Google 검색 큐 공통 서비스."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.google_search import GoogleSearchQueue
from app.shared.redis import RedisClient, RedisQueue
from app.shared.redis.queue import GOOGLE_SEARCH_QUEUE


def _build_google_search_payload(queue_item: GoogleSearchQueue) -> dict:
    """Redis 큐에 넣을 Google 검색 payload 구성."""
    return {
        "id": queue_item.id,
        "search_id": queue_item.search_id,
        "query": queue_item.query,
        "date_filter": queue_item.date_filter,
        "max_pages": queue_item.max_pages,
        "service_account_id": queue_item.service_account_id,
        "saved_search_id": queue_item.saved_search_id,
        "schedule_id": queue_item.schedule_id,
        "search_params": queue_item.search_params,
        "created_at": queue_item.created_at,
    }


async def enqueue_google_search(queue_item: GoogleSearchQueue, db: Session) -> str:
    """Google 검색 요청을 Redis 큐에 추가하고 fallback 상태를 반영."""
    redis_client = await RedisClient.get_client()
    if redis_client:
        queue = RedisQueue(redis_client, GOOGLE_SEARCH_QUEUE)
        success = await queue.push(_build_google_search_payload(queue_item))
        if success:
            return GoogleSearchQueue.STATUS_QUEUED

    queue_item.status = GoogleSearchQueue.STATUS_PENDING
    db.commit()
    return GoogleSearchQueue.STATUS_PENDING


async def recover_pending_google_searches(
    db: Session,
    limit: int | None = None,
) -> dict[str, int]:
    """Redis 큐에 누락된 pending Google 검색 요청 복구."""
    pending_query = (
        db.query(GoogleSearchQueue)
        .filter(GoogleSearchQueue.status == GoogleSearchQueue.STATUS_PENDING)
        .order_by(GoogleSearchQueue.created_at.asc())
    )
    if limit is not None:
        pending_query = pending_query.limit(limit)

    pending_items = pending_query.all()
    pending_found = len(pending_items)
    if pending_found == 0:
        return {
            "pending_found": 0,
            "recovered": 0,
            "failed_push": 0,
        }

    recovered = 0
    failed_push = 0

    for queue_item in pending_items:
        status = await enqueue_google_search(queue_item, db)
        if status == GoogleSearchQueue.STATUS_QUEUED:
            queue_item.status = GoogleSearchQueue.STATUS_QUEUED
            recovered += 1
        else:
            failed_push += 1

    if recovered > 0:
        db.commit()

    return {
        "pending_found": pending_found,
        "recovered": recovered,
        "failed_push": failed_push,
    }
