"""EventService — Redis keyspace notifications 기반 SSE 이벤트 스트림

plan-runner 실행 상태 변화를 Redis keyspace notifications로 감지하여
SSE 포맷으로 실시간 전달한다.

이벤트 타입:
  - status       : runner 상태 변경 (status, pid, current_cycle, start_time, plan_file)
  - tracking     : 현재 추적 중인 태스크 변경 (current_task_text)
  - plan_changed : 추적 중인 plan_file 변경 (current_task_plan_file)
"""

import asyncio
import json
import time
from typing import AsyncGenerator, Optional

import redis.asyncio as aioredis
import redis as redis_sync

# ─── Redis 상수 ─────────────────────────────────────────────────────────────
REDIS_HOST = "localhost"
REDIS_PORT = 6379

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
REDIS_STATE_KEY = "plan-runner:state"

# keyspace notification 채널 (DB 0)
KEYEVENT_CHANNEL = "__keyevent@0__:set"

# 감시할 키 접두사 → 이벤트 타입 매핑
# 키가 이 접두사로 시작하면 해당 이벤트를 발행한다.
KEY_EVENT_MAP = {
    f"{RUNNER_KEY_PREFIX}:": "status",            # plan-runner:runners:{id}:{field}
    f"{REDIS_STATE_KEY}:current_task_text": "tracking",
    f"{REDIS_STATE_KEY}:current_task_plan_file": "plan_changed",
}

HEARTBEAT_INTERVAL = 30  # 초


class EventService:
    """Redis keyspace notifications 구독 + SSE 이벤트 생성"""

    def __init__(self):
        # 동기 클라이언트 — 현재 값 조회용 (HGETALL / GET)
        self._sync = redis_sync.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        # 비동기 클라이언트 — keyspace notification 구독용
        self._async = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )

    # ── 초기화 ──────────────────────────────────────────────────────────────

    async def _enable_keyspace_notifications(self) -> None:
        """Redis keyspace notifications 활성화 (K: keyspace, E: keyevent, x: expired, s: set 계열)"""
        try:
            # Kx: key-space + expired, E: key-event 접두사
            # s(set), g(generic) 커맨드 포함. "KEx" = keyevent + set/del/expired
            await self._async.config_set("notify-keyspace-events", "KEx")
        except Exception:
            # CONFIG SET 권한 없는 환경(managed Redis 등)에서는 무시
            pass

    # ── 현재 상태 조회 ───────────────────────────────────────────────────────

    def _build_status_payload(self, runner_id: str) -> Optional[dict]:
        """특정 runner의 현재 상태를 Redis에서 읽어 dict로 반환"""
        try:
            fields = ["status", "pid", "current_cycle", "start_time", "plan_file"]
            values = self._sync.mget([f"{RUNNER_KEY_PREFIX}:{runner_id}:{f}" for f in fields])
            data = dict(zip(fields, values))
            data["runner_id"] = runner_id
            return data
        except Exception:
            return None

    def _build_all_runners_status(self) -> list[dict]:
        """모든 active runner 상태를 묶어서 반환"""
        try:
            runner_ids = self._sync.smembers(ACTIVE_RUNNERS_KEY) or set()
            result = []
            for rid in runner_ids:
                payload = self._build_status_payload(rid)
                if payload:
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
        yield self._sse("status", {"runners": runners})

        # 초기 tracking 이벤트
        tracking = self._build_tracking_payload()
        if tracking:
            yield self._sse("tracking", tracking)

        pubsub: Optional[aioredis.client.PubSub] = None
        last_heartbeat = time.monotonic()
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 5

        while True:
            try:
                # ── pubsub 연결 (또는 재연결)
                if pubsub is None:
                    pubsub = self._async.pubsub()
                    await pubsub.psubscribe(KEYEVENT_CHANNEL)

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.5
                )

                if message and message["type"] in ("message", "pmessage"):
                    changed_key = message["data"]
                    event_type = self._classify_key(changed_key)

                    if event_type == "status":
                        runner_id = self._extract_runner_id(changed_key)
                        if runner_id:
                            payload = self._build_status_payload(runner_id)
                            if payload:
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

                else:
                    now = time.monotonic()
                    if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                        yield ": heartbeat\n\n"
                        last_heartbeat = now
                    await asyncio.sleep(0.3)

            except (redis_sync.ConnectionError, aioredis.ConnectionError, ConnectionError, OSError):
                # ── Redis 연결 실패 → 정리 후 재시도
                await _safe_close_pubsub(pubsub)
                pubsub = None
                yield "event: redis_disconnected\ndata: Redis not available\n\n"
                last_heartbeat = time.monotonic()
                await asyncio.sleep(5)

            except Exception as e:
                consecutive_errors += 1
                await _safe_close_pubsub(pubsub)
                pubsub = None
                last_heartbeat = time.monotonic()

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    yield "event: stream_error\ndata: Too many consecutive errors, stream stopped\n\n"
                    return

                yield f"data: [EventService error #{consecutive_errors}: {str(e)}]\n\n"
                await asyncio.sleep(5)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

async def _safe_close_pubsub(pubsub) -> None:
    if pubsub is None:
        return
    try:
        await pubsub.punsubscribe()
        await pubsub.aclose()
    except AttributeError:
        try:
            await pubsub.close()
        except Exception:
            pass
    except Exception:
        pass


# ── 모듈 레벨 싱글톤 ─────────────────────────────────────────────────────────
event_service = EventService()

__all__ = ["event_service", "EventService"]
