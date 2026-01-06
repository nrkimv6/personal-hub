"""Redis List 기반 큐 유틸리티.

FIFO 큐를 Redis List로 구현합니다.
LPUSH로 추가하고 BRPOP/RPOP으로 가져옵니다.
"""
import json
import logging
from datetime import datetime
from typing import Any, Optional

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)


# 큐 이름 상수
CRAWL_REQUEST_QUEUE = "crawl:requests"
GOOGLE_SEARCH_QUEUE = "google:searches"
LLM_REQUEST_QUEUE = "llm:requests"


class RedisQueue:
    """Redis List 기반 작업 큐.

    FIFO 순서를 보장하며, blocking/non-blocking pop을 지원합니다.

    Attributes:
        client: Redis 클라이언트
        queue_name: 전체 큐 이름 (prefix 포함)
    """

    def __init__(self, client: redis.Redis, queue_name: str):
        """RedisQueue 초기화.

        Args:
            client: Redis 클라이언트
            queue_name: 큐 이름 (prefix 없이)
        """
        self.client = client
        self.queue_name = f"{settings.REDIS_QUEUE_PREFIX}:{queue_name}"

    async def push(self, data: dict) -> bool:
        """큐에 작업 추가 (LPUSH).

        큐의 왼쪽에 추가하여 FIFO 순서를 유지합니다.

        Args:
            data: 추가할 데이터 (JSON 직렬화 가능해야 함)

        Returns:
            bool: 성공 여부
        """
        try:
            # datetime 객체 처리
            serialized = self._serialize(data)
            await self.client.lpush(self.queue_name, json.dumps(serialized))
            logger.debug(f"큐 push 성공: {self.queue_name}, data={data.get('id', 'N/A')}")
            return True
        except Exception as e:
            logger.error(f"큐 push 실패: {self.queue_name}, error={e}")
            return False

    async def pop(self, timeout: int = 0) -> Optional[dict]:
        """큐에서 작업 가져오기 (BRPOP, blocking).

        큐의 오른쪽에서 가져와 FIFO 순서를 유지합니다.
        timeout=0이면 무한 대기합니다.

        Args:
            timeout: 대기 시간 (초). 0이면 무한 대기.

        Returns:
            dict | None: 작업 데이터 또는 None
        """
        try:
            result = await self.client.brpop(self.queue_name, timeout=timeout)
            if result:
                _, data = result
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"큐 pop(blocking) 실패: {self.queue_name}, error={e}")
            return None

    async def pop_nowait(self) -> Optional[dict]:
        """큐에서 작업 가져오기 (RPOP, non-blocking).

        큐가 비어있으면 즉시 None을 반환합니다.

        Returns:
            dict | None: 작업 데이터 또는 None
        """
        try:
            data = await self.client.rpop(self.queue_name)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"큐 pop_nowait 실패: {self.queue_name}, error={e}")
            return None

    async def pop_batch(self, count: int) -> list[dict]:
        """큐에서 여러 작업 가져오기 (non-blocking).

        Args:
            count: 가져올 최대 개수

        Returns:
            list[dict]: 작업 데이터 목록
        """
        results = []
        try:
            # Redis 6.2+ RPOP count 지원
            # 하위 호환성을 위해 루프로 구현
            for _ in range(count):
                data = await self.client.rpop(self.queue_name)
                if data:
                    results.append(json.loads(data))
                else:
                    break
        except Exception as e:
            logger.error(f"큐 pop_batch 실패: {self.queue_name}, error={e}")
        return results

    async def length(self) -> int:
        """큐 길이 조회.

        Returns:
            int: 큐에 있는 항목 수
        """
        try:
            return await self.client.llen(self.queue_name)
        except Exception as e:
            logger.error(f"큐 length 조회 실패: {self.queue_name}, error={e}")
            return 0

    async def peek(self, count: int = 10) -> list[dict]:
        """큐 내용 미리보기 (제거하지 않음).

        가장 오래된 항목부터 반환합니다.

        Args:
            count: 조회할 최대 개수

        Returns:
            list[dict]: 작업 데이터 목록
        """
        try:
            # LRANGE는 왼쪽(새 항목)부터 인덱싱
            # 오른쪽(오래된 항목)부터 가져오려면 음수 인덱스 사용
            items = await self.client.lrange(self.queue_name, -count, -1)
            # 오래된 순서로 반환 (FIFO 순서)
            return [json.loads(item) for item in reversed(items)]
        except Exception as e:
            logger.error(f"큐 peek 실패: {self.queue_name}, error={e}")
            return []

    async def clear(self) -> int:
        """큐 비우기.

        Returns:
            int: 삭제된 항목 수
        """
        try:
            length = await self.length()
            await self.client.delete(self.queue_name)
            logger.info(f"큐 초기화: {self.queue_name}, 삭제={length}개")
            return length
        except Exception as e:
            logger.error(f"큐 clear 실패: {self.queue_name}, error={e}")
            return 0

    def _serialize(self, data: dict) -> dict:
        """데이터 직렬화 (datetime 처리).

        Args:
            data: 원본 데이터

        Returns:
            dict: 직렬화된 데이터
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, dict):
                result[key] = self._serialize(value)
            else:
                result[key] = value
        return result

    async def get_status(self) -> dict:
        """큐 상태 정보 반환.

        Returns:
            dict: 상태 정보
        """
        return {
            "name": self.queue_name,
            "length": await self.length(),
        }

    async def remove_by_id(self, request_id: int) -> bool:
        """ID로 큐에서 항목 제거 (best effort).

        큐 전체를 순회하면서 ID가 일치하는 항목을 찾아 제거합니다.
        Redis List의 특성상 정확한 제거가 보장되지 않을 수 있습니다.

        Args:
            request_id: 제거할 요청 ID

        Returns:
            bool: 제거 성공 여부
        """
        try:
            # 큐 전체를 조회
            items = await self.client.lrange(self.queue_name, 0, -1)

            for item in items:
                try:
                    data = json.loads(item)
                    if data.get("id") == request_id:
                        # 해당 항목 제거 (count=1: 첫 번째 일치 항목만)
                        removed = await self.client.lrem(self.queue_name, 1, item)
                        if removed > 0:
                            logger.info(f"큐에서 항목 제거 성공: {self.queue_name}, id={request_id}")
                            return True
                except json.JSONDecodeError:
                    continue

            logger.debug(f"큐에서 항목을 찾지 못함: {self.queue_name}, id={request_id}")
            return False

        except Exception as e:
            logger.warning(f"큐에서 항목 제거 실패: {self.queue_name}, id={request_id}, error={e}")
            return False
