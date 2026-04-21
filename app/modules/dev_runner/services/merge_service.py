"""Merge 서비스 — merge queue/status/history/command 관련 책임 분리"""

import json
from datetime import datetime
from typing import Callable, Optional

import redis
import redis.asyncio as aioredis
from fastapi import HTTPException

from app.config import logger

__all__ = ["MergeService"]


class MergeService:
    """merge queue·status·history·direct-merge 명령 처리 서비스.

    의존성을 생성자에서 주입받아 ExecutorService에 직접 결합하지 않는다.
    """

    def __init__(
        self,
        async_redis: aioredis.Redis,
        runner_key_fn: Callable[[str, str], str],
        send_command_fn: Callable[[dict], object],
    ):
        self.async_redis = async_redis
        self._runner_key = runner_key_fn
        self._send_command = send_command_fn

    # ------------------------------------------------------------------
    # merge queue 조회
    # ------------------------------------------------------------------

    async def get_merge_queue(self) -> list:
        """merge 상태 통합 조회 — merging/queued/done 3개 소스 병합

        merge_queue.py 기반: SCAN plan-runner:merge-queue:* 1패턴만 사용.
        index 0 = merging 러너, index 1+ = queued 러너.
        """
        try:
            result = []
            seen_runners: set[str] = set()

            # 1) merging + queued: SCAN plan-runner:merge-queue:* (1-SCAN)
            async for key in self.async_redis.scan_iter(match="plan-runner:merge-queue:*"):
                items = await self.async_redis.lrange(key, 0, -1)
                for idx, rid in enumerate(items):
                    if rid and rid not in seen_runners:
                        seen_runners.add(rid)
                        status = "merging" if idx == 0 else "queued"
                        result.append(await self._merge_queue_item(rid, status))

            # 2) done/failed: merge-results 최근 10건
            for raw in await self.async_redis.lrange("plan-runner:merge-results", 0, 9):
                try:
                    item = json.loads(raw)
                    rid = item.get("runner_id", "")
                    status = item.get("status", "done")
                    result.append({
                        "runner_id": rid,
                        "branch": item.get("branch", ""),
                        "plan_file": item.get("plan_file", ""),
                        "project": "monitor-page",
                        "status": status,
                        "timestamp": item.get("timestamp", ""),
                        "worktree_path": "",
                    })
                except Exception:
                    pass

            return result
        except Exception:
            return []

    async def get_merge_queue_length(self) -> int:
        """순수 대기 수 반환 (실행 중 runner 제외).

        SCAN plan-runner:merge-queue:* → 각 키 max(0, LLEN-1) 합산.
        index 0 = 실행 중 러너이므로 대기 수 = LLEN - 1.
        외부 소비자(모니터링 스크립트 등)용 경량 엔드포인트.
        """
        try:
            total = 0
            async for key in self.async_redis.scan_iter(match="plan-runner:merge-queue:*"):
                length = await self.async_redis.llen(key)
                total += max(0, length - 1)
            return total
        except Exception:
            return 0

    async def _merge_queue_item(self, runner_id: str, status: str) -> dict:
        """runner Redis 키에서 상세 정보 조회"""
        return {
            "runner_id": runner_id,
            "branch": await self.async_redis.get(self._runner_key(runner_id, "branch")) or "",
            "plan_file": await self.async_redis.get(self._runner_key(runner_id, "plan_file")) or "",
            "project": "monitor-page",
            "status": status,
            "timestamp": await self.async_redis.get(self._runner_key(runner_id, "start_time")) or "",
            "worktree_path": await self.async_redis.get(self._runner_key(runner_id, "worktree_path")) or "",
        }

    # ------------------------------------------------------------------
    # merge status / history
    # ------------------------------------------------------------------

    async def get_merge_status(self, runner_id: str) -> Optional[dict]:
        """runner Redis 키에서 merge_status 조회"""
        try:
            status = await self.async_redis.get(self._runner_key(runner_id, "merge_status"))
            if status is None:
                return None
            reason = await self.async_redis.get(self._runner_key(runner_id, "merge_reason"))
            quarantine_diff_path = await self.async_redis.get(self._runner_key(runner_id, "quarantine_diff_path"))
            message = await self.async_redis.get(self._runner_key(runner_id, "merge_message")) or ""
            if not reason:
                reason = await self.async_redis.get(self._runner_key(runner_id, "done_post_merge_error"))
            return {
                "runner_id": runner_id,
                "status": status,
                "test_passed": None,
                "fix_attempts": 0,
                "message": message,
                "reason": reason,
                "quarantine_diff_path": quarantine_diff_path,
            }
        except Exception:
            return None

    async def get_merge_history(self, limit: int = 50) -> list:
        """Redis merge-results 이력 조회 → list[MergeHistoryItem] (최신순)"""
        try:
            raw_items = await self.async_redis.lrange("plan-runner:merge-results", 0, limit - 1)
            result = []
            for raw in raw_items:
                try:
                    item = json.loads(raw)
                    # status 필드 보정: 없으면 success 값으로 유추
                    if "status" not in item:
                        item["status"] = "completed" if item.get("success") else "failed"
                    result.append(item)
                except Exception:
                    pass
            return result
        except Exception:
            return []

    # ------------------------------------------------------------------
    # direct-merge 명령
    # ------------------------------------------------------------------

    async def send_direct_merge_command(
        self,
        branch: str,
        worktree_path: Optional[str],
        plan_file: Optional[str],
    ) -> dict:
        """direct-merge 명령 전송 — runner_id 없이 branch/worktree만으로 머지 실행"""
        try:
            await self.async_redis.ping()
        except (redis.ConnectionError, ConnectionRefusedError, OSError):
            raise HTTPException(status_code=503, detail="Redis에 연결할 수 없습니다.")

        command = {
            "action": "direct-merge",
            "branch": branch,
            "worktree_path": worktree_path,
            "plan_file": plan_file,
            "source": "monitor-page-api",
            "timestamp": datetime.now().isoformat(),
        }
        result = await self._send_command(command)
        if result is None:
            return {"success": False, "message": "Command timeout"}
        return result
