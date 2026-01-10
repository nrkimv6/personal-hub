"""대기 중인 크롤링 요청을 Redis 큐에 수동으로 푸시합니다."""
import asyncio
import sys
from datetime import datetime

from app.shared.redis import RedisClient, RedisQueue
from app.shared.redis.queue import CRAWL_REQUEST_QUEUE


async def push_request_to_redis(request_id: int):
    """요청을 Redis 큐에 푸시합니다."""
    client = await RedisClient.get_client()
    if not client:
        print("Redis 연결 실패")
        return False

    queue = RedisQueue(client, CRAWL_REQUEST_QUEUE)
    success = await queue.push({
        "id": request_id,
        "url": f"instagram://feed?account_id=6",
        "url_type": "instagram_feed",
        "requested_by": "manual",
        "created_at": datetime.now(),
    })

    if success:
        print(f"✅ 요청 ID {request_id}을 Redis 큐에 푸시했습니다")
    else:
        print(f"❌ Redis 큐 푸시 실패: ID {request_id}")

    return success


if __name__ == "__main__":
    request_id = int(sys.argv[1]) if len(sys.argv) > 1 else 761
    asyncio.run(push_request_to_redis(request_id))
