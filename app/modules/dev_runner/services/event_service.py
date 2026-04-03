"""EventService — Redis keyspace notifications 기반 SSE 이벤트 스트림

plan-runner 실행 상태 변화를 Redis keyspace notifications로 감지하여
SSE 포맷으로 실시간 전달한다.

이벤트 타입:
  - status              : runner 상태 변경 (status, pid, current_cycle, start_time, plan_file)
  - tracking            : 현재 추적 중인 태스크 변경 (current_task_text)
  - plan_changed        : 추적 중인 plan_file 변경 (current_task_plan_file)
  - log                 : 로그 한 줄 (runner_id, line)
  - log_completed       : 로그 스트리밍 완료 (runner_id)
  - merge_log           : 머지 로그 한 줄 (runner_id, line)
  - merge_log_completed : 머지 로그 스트리밍 완료 (runner_id)
"""

import asyncio
import json
import time
from typing import AsyncGenerator, Optional

import redis.asyncio as aioredis
import redis as redis_sync

from app.modules.dev_runner.services.completion_reason import (
    LOG_COMPLETED_SENTINEL as _LOG_COMPLETED_SENTINEL,
    MERGE_LOG_COMPLETED_SENTINEL as _MERGE_LOG_COMPLETED_SENTINEL,
    is_log_completed_payload as _is_log_completed_payload,
    is_merge_completed_payload as _is_merge_completed_payload,
    parse_log_completed_payload as _parse_log_completed_payload,
    parse_merge_completed_payload as _parse_merge_completed_payload,
)
from app.shared.redis.client import RedisClient
from app.modules.dev_runner.services.sse_helpers import safe_close_pubsub
from app.modules.dev_runner.services.visibility import is_visible_runner

# ─── Redis 상수 ─────────────────────────────────────────────────────────────
REDIS_HOST = "localhost"
REDIS_PORT = 6379

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
REDIS_STATE_KEY = "plan-runner:state"
PLAN_FILE_ALL = "__ALL_PLANS__"  # 전체실행 sentinel (command-listener와 공유)
_LEGACY_ALL = "ALL"  # 하위 호환

# keyspace notification 채널 (DB 0)
KEYEVENT_CHANNEL = "__keyevent@0__:set"

# 로그 채널 패턴 (plan-runner:logs:{runner_id}, plan-runner:merge-log:{runner_id})
LOG_CHANNEL_PATTERN = "plan-runner:logs:*"
MERGE_LOG_CHANNEL_PATTERN = "plan-runner:merge-log:*"

# 감시할 키 접두사 → 이벤트 타입 매핑
# 키가 이 접두사로 시작하면 해당 이벤트를 발행한다.
KEY_EVENT_MAP = {
    f"{RUNNER_KEY_PREFIX}:": "status",            # plan-runner:runners:{id}:{field}
    f"{REDIS_STATE_KEY}:current_task_text": "tracking",
    f"{REDIS_STATE_KEY}:current_task_plan_file": "plan_changed",
}

HEARTBEAT_INTERVAL = 30  # 초


def _build_log_line_payload(data: str) -> object:
    """로그 payload 직렬화.

    하위호환: 단일 라인은 기존처럼 string.
    확장: 멀티라인은 {text, meta} 객체로 보내 UI가 줄바꿈 보존/보조메타를 활용할 수 있게 한다.
    """
    text = str(data or "")
    if "\n" not in text:
        return text
    line_count = text.count("\n") + 1
    return {
        "text": text,
        "meta": {
            "multiline": True,
            "line_count": line_count,
        },
    }


class EventService:
    """Redis keyspace notifications 구독 + SSE 이벤트 생성"""

    def __init__(self):
        # 동기 클라이언트 — 현재 값 조회용 (HGETALL / GET)
        sync_client = RedisClient.get_sync_client()
        self._sync = sync_client if sync_client is not None else redis_sync.Redis(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=5,
        )
        # 비동기 클라이언트 — keyspace notification 구독용 (ConnectionPool로 연결 수 제한)
        self._async_pool = aioredis.ConnectionPool(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
            socket_connect_timeout=5, max_connections=50,
        )
        self._async = aioredis.Redis(connection_pool=self._async_pool)

    # ── 초기화 ──────────────────────────────────────────────────────────────

    async def _enable_keyspace_notifications(self) -> None:
        """Redis keyspace notifications 활성화"""
        try:
            # K: keyspace events 접두사 활성화
            # E: keyevent events 접두사 활성화
            # x: expired events
            # $: string commands (SET, GETSET 등) — runner 상태 키 변경 감지에 필요
            await self._async.config_set("notify-keyspace-events", "KEx$")
        except Exception:
            # CONFIG SET 권한 없는 환경(managed Redis 등)에서는 무시
            pass

    # ── 현재 상태 조회 ───────────────────────────────────────────────────────

    def _build_status_payload(self, runner_id: str) -> Optional[dict]:
        """특정 runner의 현재 상태를 Redis에서 읽어 dict로 반환"""
        try:
            fields = [
                "status",
                "pid",
                "current_cycle",
                "start_time",
                "plan_file",
                "engine",
                "branch",
                "trigger",
                "exit_reason",
                "error",
            ]
            values = self._sync.mget([f"{RUNNER_KEY_PREFIX}:{runner_id}:{f}" for f in fields])
            data = dict(zip(fields, values))
            data["runner_id"] = runner_id
            data["visible"] = is_visible_runner(data.get("trigger"), runner_id)
            # plan_file이 None(Redis 키 미설정)이면 None 반환 — sentinel fallback 제거
            # (프론트엔드에서 null과 sentinel을 구분하여 처리)
            if not data.get("plan_file"):
                data["plan_file"] = None
            return data
        except Exception:
            return None

    def _read_runner_error(self, runner_id: str) -> Optional[str]:
        """runner error 값을 Redis에서 읽는다."""
        try:
            return self._sync.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:error")
        except Exception:
            return None

    async def _read_runner_error_with_retry(
        self,
        runner_id: str,
        retries: int = 1,
        delay: float = 0.05,
    ) -> Optional[str]:
        """commit_failed 같은 순서 경쟁을 흡수하기 위해 error를 한 번 더 재조회한다."""
        error = self._read_runner_error(runner_id)
        if error:
            return error
        for _ in range(retries):
            await asyncio.sleep(delay)
            error = self._read_runner_error(runner_id)
            if error:
                return error
        return None

    async def _stabilize_commit_failed_status_payload(self, runner_id: str, payload: dict) -> dict:
        """exit_reason=commit_failed일 때 error 키 반영이 늦어도 한 번 더 흡수한다."""
        if payload.get("exit_reason") != "commit_failed" or payload.get("error"):
            return payload

        await asyncio.sleep(0.05)
        refreshed = self._build_status_payload(runner_id)
        if refreshed and refreshed.get("error"):
            return refreshed
        return payload

    def _build_all_runners_status(self) -> list[dict]:
        """모든 active runner 상태를 묶어서 반환"""
        try:
            runner_ids = self._sync.smembers(ACTIVE_RUNNERS_KEY) or set()
            result = []
            for rid in runner_ids:
                payload = self._build_status_payload(rid)
                if payload:
                    if not payload.get("visible", False):
                        continue
                    result.append(payload)
            return result
        except Exception:
            return []

    def _build_tracking_payload(self) -> Optional[dict]:
        """현재 추적 중인 태스크 정보를 Redis에서 읽어 dict로 반환"""
        try:
            keys = [
                f"{REDIS_STATE_KEY}:current_task_text",
                f"{REDIS_STATE_KEY}:current_task_confidence",
                f"{REDIS_STATE_KEY}:current_task_line_num",
                f"{REDIS_STATE_KEY}:current_task_plan_file",
            ]
            text, confidence, line_num, plan_file = self._sync.mget(keys)
            if not text:
                return None
            return {
                "text": text,
                "confidence": confidence,
                "line_num": int(line_num) if line_num else None,
                "plan_file": plan_file,
            }
        except Exception:
            return None

    # ── 이벤트 타입 판별 ─────────────────────────────────────────────────────

    def _classify_key(self, key: str) -> Optional[str]:
        """변경된 Redis 키로부터 SSE 이벤트 타입 결정. 무관한 키는 None."""
        # tracking / plan_changed 먼저 (더 구체적)
        if key == f"{REDIS_STATE_KEY}:current_task_text":
            return "tracking"
        if key == f"{REDIS_STATE_KEY}:current_task_plan_file":
            return "plan_changed"
        # runner 상태 키: plan-runner:runners:{runner_id}:{field}
        if key.startswith(f"{RUNNER_KEY_PREFIX}:"):
            parts = key.split(":")
            # parts: ["plan-runner", "runners", runner_id, field]
            if len(parts) >= 4:
                return "status"
        return None

    def _extract_runner_id(self, key: str) -> Optional[str]:
        """키에서 runner_id 추출 (status 이벤트 전용)"""
        # plan-runner:runners:{runner_id}:{field}
        parts = key.split(":")
        if len(parts) >= 4:
            return parts[2]
        return None

    def _extract_runner_id_from_channel(self, channel: str) -> Optional[str]:
        """로그 채널명에서 runner_id 추출.

        Examples:
            "plan-runner:logs:abc123"      → "abc123"
            "plan-runner:merge-log:def456" → "def456"
        """
        if not channel or ":" not in channel:
            return None
        runner_id = channel.split(":")[-1]
        return runner_id if runner_id else None

    # ── SSE 포맷 헬퍼 ────────────────────────────────────────────────────────

    @staticmethod
    def _sse(event: str, data: object) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    # ── 메인 스트림 ──────────────────────────────────────────────────────────

    async def stream_events(self) -> AsyncGenerator[str, None]:
        """
        Redis keyspace notifications를 구독하고 SSE 이벤트를 yield한다.

        이벤트 타입:
          - connected    : 연결 직후 1회 (EventSource MIME 검증용)
          - status       : runner 상태 변경
          - tracking     : 현재 추적 태스크 변경
          - plan_changed : 추적 plan_file 변경
        """
        await self._enable_keyspace_notifications()

        # ── 초기 연결 이벤트 (클라이언트가 연결 직후 현재 상태를 받도록)
        yield "event: connected\ndata: ok\n\n"

        # 초기 status 이벤트 1회 즉시 발행
        runners = self._build_all_runners_status()
        stabilized_runners = []
        for payload in runners:
            runner_id = payload.get("runner_id") if isinstance(payload, dict) else None
            if runner_id:
                payload = await self._stabilize_commit_failed_status_payload(runner_id, payload)
            stabilized_runners.append(payload)
        runners = stabilized_runners
        yield self._sse("status", {"runners": runners})

        # 초기 tracking 이벤트
        tracking = self._build_tracking_payload()
        if tracking:
            yield self._sse("tracking", tracking)

        pubsub: Optional[aioredis.client.PubSub] = None
        log_pubsub: Optional[aioredis.client.PubSub] = None
        last_heartbeat = time.monotonic()
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 5

        try:
            while True:
                try:
                    # ── pubsub 연결 (또는 재연결)
                    if pubsub is None:
                        pubsub = self._async.pubsub()
                        await pubsub.psubscribe(KEYEVENT_CHANNEL)

                    if log_pubsub is None:
                        log_pubsub = self._async.pubsub()
                        await log_pubsub.psubscribe(LOG_CHANNEL_PATTERN, MERGE_LOG_CHANNEL_PATTERN)

                    # ── keyspace 메시지 폴링
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.25
                    )

                    if message and message["type"] in ("message", "pmessage"):
                        changed_key = message["data"]
                        event_type = self._classify_key(changed_key)

                        if event_type == "status":
                            runner_id = self._extract_runner_id(changed_key)
                            if runner_id:
                                payload = self._build_status_payload(runner_id)
                                if payload and payload.get("visible", False):
                                    payload = await self._stabilize_commit_failed_status_payload(runner_id, payload)
                                    yield self._sse("status", {"runners": [payload]})
                        elif event_type == "tracking":
                            payload = self._build_tracking_payload()
                            if payload:
                                yield self._sse("tracking", payload)
                        elif event_type == "plan_changed":
                            payload = self._build_tracking_payload()
                            yield self._sse("plan_changed", payload or {})

                        last_heartbeat = time.monotonic()
                        consecutive_errors = 0

                    # ── 로그 채널 메시지 폴링
                    log_message = await log_pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.25
                    )

                    if log_message and log_message["type"] in ("message", "pmessage"):
                        channel = log_message.get("channel") or log_message.get("pattern", "")
                        data = log_message.get("data")

                        if not data:
                            pass  # 빈 데이터 무시
                        else:
                            runner_id = self._extract_runner_id_from_channel(channel)
                            if runner_id:
                                is_merge = channel.startswith("plan-runner:merge-log:")
                                if _is_merge_completed_payload(data):
                                    status, reason = _parse_merge_completed_payload(data)
                                    yield self._sse(
                                        "merge_log_completed",
                                        {"runner_id": runner_id, "status": status, "reason": reason},
                                    )
                                elif _is_log_completed_payload(data):
                                    status, reason = _parse_log_completed_payload(data)
                                    payload = {"runner_id": runner_id, "status": status, "reason": reason}
                                    try:
                                        error = await self._read_runner_error_with_retry(
                                            runner_id,
                                            retries=2 if reason == "commit_failed" else 0,
                                        )
                                    except Exception:
                                        error = None
                                    if error:
                                        payload["error"] = error
                                    yield self._sse(
                                        "log_completed",
                                        payload,
                                    )
                                elif is_merge:
                                    yield self._sse(
                                        "merge_log",
                                        {"runner_id": runner_id, "line": _build_log_line_payload(data)},
                                    )
                                else:
                                    yield self._sse(
                                        "log",
                                        {"runner_id": runner_id, "line": _build_log_line_payload(data)},
                                    )

                        last_heartbeat = time.monotonic()
                        consecutive_errors = 0

                    if not message and not log_message:
                        now = time.monotonic()
                        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                            yield ": heartbeat\n\n"
                            last_heartbeat = now
                        await asyncio.sleep(0.1)

                except (redis_sync.ConnectionError, aioredis.ConnectionError, ConnectionError, OSError):
                    # ── Redis 연결 실패 → 정리 후 재시도
                    await safe_close_pubsub(pubsub)
                    pubsub = None
                    await safe_close_pubsub(log_pubsub)
                    log_pubsub = None
                    yield "event: redis_disconnected\ndata: Redis not available\n\n"
                    last_heartbeat = time.monotonic()
                    await asyncio.sleep(5)

                except Exception as e:
                    consecutive_errors += 1
                    await safe_close_pubsub(pubsub)
                    pubsub = None
                    await safe_close_pubsub(log_pubsub)
                    log_pubsub = None
                    last_heartbeat = time.monotonic()

                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        yield "event: stream_error\ndata: Too many consecutive errors, stream stopped\n\n"
                        return

                    yield f"data: [EventService error #{consecutive_errors}: {str(e)}]\n\n"
                    await asyncio.sleep(5)
        finally:
            await safe_close_pubsub(pubsub)
            await safe_close_pubsub(log_pubsub)


# ── 모듈 레벨 싱글톤 ─────────────────────────────────────────────────────────
event_service = EventService()

__all__ = ["event_service", "EventService"]
