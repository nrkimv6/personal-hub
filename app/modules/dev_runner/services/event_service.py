# sanitized
# sanitized
# sanitized
# sanitized
# sanitized
# sanitized
  # sanitized
  # sanitized
  # sanitized
  # sanitized
  # sanitized
  # sanitized
  # sanitized
# sanitized

import asyncio
import logging
import time
from typing import AsyncGenerator, Optional


import redis.asyncio as aioredis
import redis as redis_sync

from app.modules.dev_runner.config import config
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
from app.modules.dev_runner.services.event_routing import (  # noqa: F401 ??re-export ?ы븿
    classify_key,
    extract_runner_id,
    extract_runner_id_from_channel,
    REDIS_HOST,
    REDIS_PORT,
    RUNNER_KEY_PREFIX,
    ACTIVE_RUNNERS_KEY,
    RECENT_RUNNERS_KEY,
    MAX_RECENT_IN_SSE,
    MAX_RECENT_RUNNERS,
    REDIS_STATE_KEY,
    PLAN_FILE_ALL,
    _LEGACY_ALL,
    KEYEVENT_CHANNEL,
    LOG_CHANNEL_PATTERN,
    MERGE_LOG_CHANNEL_PATTERN,
    KEY_EVENT_MAP,
)
from app.modules.dev_runner.services.event_sse import (  # noqa: F401 ??re-export ?ы븿
    sse_format,
    build_log_line_payload as _build_log_line_payload,
)
from app.modules.dev_runner.services.event_payload import (
    build_status_payload,
    build_all_runners_status,
    build_tracking_payload,
    read_runner_error_with_retry,
    stabilize_commit_failed_status_payload,
)
from app.modules.dev_runner.services.log_file_resolver import LogFileResolver
from app.modules.dev_runner.services.event_log_tailer import LogTailer

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # 珥?
FILE_POLL_TIMEOUT = 5.0
FILE_POLL_INTERVAL = 1.0

# ??? pmessage ?섏떊 ?ъ뒪 寃뚯씠吏 (in-memory, 5遺??щ씪?대뵫 ?덈룄?? ?????????????????
import collections as _collections

_PMSG_WINDOW_SEC = 300  # 5遺??щ씪?대뵫 ?덈룄??
_pmsg_timestamps: "collections.deque[float]" = _collections.deque()  # ?섏떊 ?쒓컖 紐⑸줉


def _record_pmsg_received() -> None:
    # sanitized
    now = time.monotonic()
    _pmsg_timestamps.append(now)
    # ?ㅻ옒????ぉ ?뺣━ (>5遺?
    while _pmsg_timestamps and now - _pmsg_timestamps[0] > _PMSG_WINDOW_SEC:
        _pmsg_timestamps.popleft()


def get_pmsg_count_last5min() -> int:
    # sanitized
    if not _pmsg_timestamps:
        return 0
    now = time.monotonic()
    # ?덈룄??????ぉ留?移댁슫??(deque???쇱そ??媛???ㅻ옒??
    cutoff = now - _PMSG_WINDOW_SEC
    count = sum(1 for t in _pmsg_timestamps if t >= cutoff)
    return count
class EventService:
    # sanitized

    def __init__(self):
        # ?숆린 ?대씪?댁뼵?????꾩옱 媛?議고쉶??(HGETALL / GET)
        sync_client = RedisClient.get_sync_client()
        self._sync = sync_client if sync_client is not None else redis_sync.Redis(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=5,
        )
        # 鍮꾨룞湲??대씪?댁뼵????keyspace notification 援щ룆??(ConnectionPool濡??곌껐 ???쒗븳)
        self._async_pool = aioredis.ConnectionPool(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
            socket_connect_timeout=5, max_connections=50,
        )
        self._async = aioredis.Redis(connection_pool=self._async_pool)
        # LogTailer ??tail state, dedup, ?꾨즺 異붿쟻, ?뚯씪 ?대쭅
        _log_resolver = LogFileResolver(config, self._sync)
        self._log_tailer = LogTailer(self._sync, _log_resolver)
        self._file_poll_timeout = FILE_POLL_TIMEOUT
        self._file_poll_interval_sec = FILE_POLL_INTERVAL

    # ?? 珥덇린????????????????????????????????????????????????????????????????

    async def _enable_keyspace_notifications(self) -> None:
        # sanitized
        # sanitized
            # sanitized
            # sanitized
            # sanitized
            # sanitized
            # sanitized
        # sanitized
            # sanitized
            # sanitized
# sanitized
    # sanitized
        # sanitized

        # remove invisible runners from RECENT
        # keep visible runner list consistent
        # cap RECENT size at MAX_RECENT_RUNNERS
        # sanitized
        # sanitized
            # sanitized
            # sanitized
                # sanitized
                # sanitized
                    # sanitized
            # sanitized
            # sanitized
        # sanitized
            # sanitized
# sanitized
    # sanitized
        # sanitized
            # sanitized
        # sanitized
            # sanitized
# sanitized
        # sanitized
        # sanitized
            # sanitized
            # sanitized
            # sanitized
                # sanitized
                # sanitized
                # sanitized
            # sanitized
                # sanitized
                # sanitized
            # sanitized
                # sanitized
        # sanitized
# sanitized
    # sanitized
        # sanitized
        return build_status_payload(self._sync, runner_id)

    def _build_all_runners_status(self):
        # sanitized
        return build_all_runners_status(self._sync)

    def _ensure_log_tailer(self) -> None:
        # sanitized
        if not hasattr(self, "_log_tailer"):
            _log_resolver = LogFileResolver(config, self._sync)
            self._log_tailer = LogTailer(self._sync, _log_resolver)
        if not hasattr(self, "_file_poll_timeout"):
            self._file_poll_timeout = FILE_POLL_TIMEOUT
        if not hasattr(self, "_file_poll_interval_sec"):
            self._file_poll_interval_sec = FILE_POLL_INTERVAL

    # ?? 硫붿씤 ?ㅽ듃由???????????????????????????????????????????????????????????

    async def stream_events(self) -> AsyncGenerator[str, None]:
        # sanitized
        # yield SSE events for Redis keyspace notifications
# sanitized
        # sanitized
          # sanitized
          # sanitized
          # sanitized
          # sanitized
        # sanitized
        await self._enable_keyspace_notifications()

        # ?? 珥덇린 ?곌껐 ?대깽??(?대씪?댁뼵?멸? ?곌껐 吏곹썑 ?꾩옱 ?곹깭瑜?諛쏅룄濡?
        yield "event: connected\ndata: ok\n\n"

        # API ?ъ떆????SSE ?ъ뿰寃???fallback 以묐났 ?ъ쟾??諛⑹?: tail offset??EOF濡?珥덇린??
        # (?대씪?댁뼵??catchUp()???뚯씪 ?꾩옱 ?댁슜??濡쒕뱶?섎?濡??쒕쾭 fallback? ?댄썑 ?좉퇋 ?쇱씤留??대떦)
        try:
            _init_visible = self._list_visible_active_runner_ids()
            await self._log_tailer.init_offsets_for_active_runners(_init_visible)
        except Exception as _e:
            logger.warning("[events-init-offsets] 珥덇린??以??덉쇅 (?ㅽ듃由?怨꾩냽): %s", _e)

        # SSE ?곌껐 珥덇린????invisible runner ?ъ쟾 ?뺣━ (RECENT set ?ㅼ뿼 諛⑹?)
        self._cleanup_invisible_recent_runners()

        # 珥덇린 status ?대깽??1??利됱떆 諛쒗뻾
        runners = build_all_runners_status(self._sync)
        stabilized_runners = []
        for payload in runners:
            runner_id = payload.get("runner_id") if isinstance(payload, dict) else None
            if runner_id:
                payload = await stabilize_commit_failed_status_payload(self._sync, runner_id, payload)
            stabilized_runners.append(payload)
        runners = stabilized_runners
        yield sse_format("status", {"runners": runners})

        # 珥덇린 tracking ?대깽??
        tracking = build_tracking_payload(self._sync)
        if tracking:
            yield sse_format("tracking", tracking)

        pubsub: Optional[aioredis.client.PubSub] = None
        log_pubsub: Optional[aioredis.client.PubSub] = None
        last_heartbeat = time.monotonic()
        last_log_activity = time.monotonic()
        last_fallback_poll = 0.0
        consecutive_errors = 0
        fallback_active = False
        fallback_enter_count = 0
        fallback_exit_count = 0
        dedup_skip_counts: dict[str, int] = {}
        dedup_skip_last_logged_at = 0.0
        MAX_CONSECUTIVE_ERRORS = 5
        self._ensure_log_tailer()

        try:
            while True:
                try:
                    # ?? pubsub ?곌껐 (?먮뒗 ?ъ뿰寃?
                    if pubsub is None:
                        pubsub = self._async.pubsub()
                        await pubsub.psubscribe(KEYEVENT_CHANNEL)

                    if log_pubsub is None:
                        log_pubsub = self._async.pubsub()
                        await log_pubsub.psubscribe(LOG_CHANNEL_PATTERN, MERGE_LOG_CHANNEL_PATTERN)

                    # ?? keyspace 硫붿떆吏 ?대쭅
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.25
                    )

                    if message and message["type"] in ("message", "pmessage"):
                        if fallback_active:
                            fallback_active = False
                            fallback_exit_count += 1
                            logger.debug(
                                "[events-fallback] exit #%s (reason=keyspace_message)",
                                fallback_exit_count,
                            )
                            if dedup_skip_counts:
                                logger.debug(
                                    "[events-fallback] dedup-skip summary (reason=keyspace_message): %s",
                                    dedup_skip_counts,
                                )
                                dedup_skip_counts = {}
                        changed_key = message["data"]
                        event_type = classify_key(changed_key)

                        if event_type == "status":
                            runner_id = extract_runner_id(changed_key)
                            if runner_id:
                                payload = build_status_payload(self._sync, runner_id)
                                if payload:
                                    payload = await stabilize_commit_failed_status_payload(self._sync, runner_id, payload)
                                    if payload.get("visible", False):
                                        yield sse_format("status", {"runners": [payload]})
                                    else:
                                        self._log_tailer.drop_tail_state(runner_id)
                                    if payload.get("status") != "running":
                                        self._log_tailer.drop_tail_state(runner_id)
                                    else:
                                        self._log_tailer._completed_runners.pop(runner_id, None)
                        elif event_type == "tracking":
                            payload = build_tracking_payload(self._sync)
                            if payload:
                                yield sse_format("tracking", payload)
                        elif event_type == "plan_changed":
                            payload = build_tracking_payload(self._sync)
                            yield sse_format("plan_changed", payload or {})

                        last_heartbeat = time.monotonic()
                        consecutive_errors = 0

                    # ?? 濡쒓렇 梨꾨꼸 硫붿떆吏 ?대쭅
                    log_message = await log_pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.25
                    )

                    if log_message and log_message["type"] in ("message", "pmessage"):
                        # pmessage ?섏떊 寃뚯씠吏 湲곕줉 (?ъ뒪泥댄겕??
                        _record_pmsg_received()
                        if fallback_active:
                            fallback_active = False
                            fallback_exit_count += 1
                            logger.debug(
                                "[events-fallback] exit #%s (reason=log_message)",
                                fallback_exit_count,
                            )
                            if dedup_skip_counts:
                                logger.debug(
                                    "[events-fallback] dedup-skip summary (reason=log_message): %s",
                                    dedup_skip_counts,
                                )
                                dedup_skip_counts = {}
                        channel = log_message.get("channel") or log_message.get("pattern", "")
                        data = log_message.get("data")

                        if not data:
                            pass  # 鍮??곗씠??臾댁떆
                        else:
                            runner_id = extract_runner_id_from_channel(channel)
                            if runner_id:
                                is_merge = channel.startswith("plan-runner:merge-log:")
                                if _is_merge_completed_payload(data):
                                    status, reason = _parse_merge_completed_payload(data)
                                    yield sse_format(
                                        "merge_log_completed",
                                        {"runner_id": runner_id, "status": status, "reason": reason},
                                    )
                                elif _is_log_completed_payload(data):
                                    status, reason = _parse_log_completed_payload(data)
                                    payload = {"runner_id": runner_id, "status": status, "reason": reason}
                                    try:
                                        error = await read_runner_error_with_retry(self._sync,
                                            runner_id,
                                            retries=2 if reason == "commit_failed" else 0,
                                        )
                                    except Exception:
                                        error = None
                                    if error:
                                        payload["error"] = error
                                    self._log_tailer.mark_runner_completed(runner_id)
                                    yield sse_format(
                                        "log_completed",
                                        payload,
                                    )
                                elif is_merge:
                                    yield sse_format(
                                        "merge_log",
                                        {"runner_id": runner_id, "line": _build_log_line_payload(data)},
                                    )
                                else:
                                    self._log_tailer._completed_runners.pop(runner_id, None)
                                    if self._log_tailer._is_duplicate_log_line(runner_id, str(data)):
                                        dedup_skip_counts[runner_id] = (
                                            dedup_skip_counts.get(runner_id, 0) + 1
                                        )
                                        continue
                                    yield sse_format(
                                        "log",
                                        {"runner_id": runner_id, "line": _build_log_line_payload(data)},
                                    )

                        last_heartbeat = time.monotonic()
                        last_log_activity = time.monotonic()
                        consecutive_errors = 0

                    if not message and not log_message:
                        now = time.monotonic()
                        if (
                            now - last_log_activity >= self._file_poll_timeout
                            and now - last_fallback_poll >= self._file_poll_interval_sec
                        ):
                            visible_runner_ids = self._list_visible_active_runner_ids()
                            if not fallback_active:
                                fallback_active = True
                                fallback_enter_count += 1
                                logger.debug(
                                    "[events-fallback] enter #%s (idle_sec=%.2f, visible=%s)",
                                    fallback_enter_count,
                                    now - last_log_activity,
                                    len(visible_runner_ids),
                                )
                            self._log_tailer.cleanup_stale_state(set(visible_runner_ids))
                            fallback_emitted = False
                            for runner_id in visible_runner_ids:
                                fallback_events, dedup_skipped = self._log_tailer.poll_runner_log_delta(runner_id)
                                if dedup_skipped > 0:
                                    dedup_skip_counts[runner_id] = (
                                        dedup_skip_counts.get(runner_id, 0) + dedup_skipped
                                    )
                                if not fallback_events:
                                    continue
                                fallback_emitted = True
                                for event_name, payload in fallback_events:
                                    yield sse_format(event_name, payload)
                            if dedup_skip_counts and (
                                dedup_skip_last_logged_at == 0.0
                                or (now - dedup_skip_last_logged_at) >= 15.0
                            ):
                                logger.debug(
                                    "[events-fallback] dedup-skip aggregate: %s",
                                    dedup_skip_counts,
                                )
                                dedup_skip_last_logged_at = now
                            if fallback_emitted:
                                last_heartbeat = now
                                last_log_activity = now
                                consecutive_errors = 0
                            last_fallback_poll = now
                        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                            yield ": heartbeat\n\n"
                            last_heartbeat = now
                        await asyncio.sleep(0.1)

                except (redis_sync.ConnectionError, aioredis.ConnectionError, ConnectionError, OSError) as redis_err:
                    # ?? Redis ?곌껐 ?ㅽ뙣 ???뺣━ ???ъ떆??
                    logger.warning("[events] Redis ?곌껐 ?ㅽ뙣: %s: %s", type(redis_err).__name__, redis_err)
                    if fallback_active:
                        fallback_active = False
                        fallback_exit_count += 1
                        logger.debug(
                            "[events-fallback] exit #%s (reason=redis_disconnected)",
                            fallback_exit_count,
                        )
                    await safe_close_pubsub(pubsub)
                    pubsub = None
                    await safe_close_pubsub(log_pubsub)
                    log_pubsub = None
                    yield "event: redis_disconnected\ndata: Redis not available\n\n"
                    last_heartbeat = time.monotonic()
                    last_log_activity = time.monotonic()
                    last_fallback_poll = 0.0
                    await asyncio.sleep(5)

                except Exception as e:
                    consecutive_errors += 1
                    if fallback_active:
                        fallback_active = False
                        fallback_exit_count += 1
                        logger.debug(
                            "[events-fallback] exit #%s (reason=stream_exception)",
                            fallback_exit_count,
                        )
                    await safe_close_pubsub(pubsub)
                    pubsub = None
                    await safe_close_pubsub(log_pubsub)
                    log_pubsub = None
                    last_heartbeat = time.monotonic()
                    last_log_activity = time.monotonic()
                    last_fallback_poll = 0.0

                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        yield "event: stream_error\ndata: Too many consecutive errors, stream stopped\n\n"
                        return

                    yield f"data: [EventService error #{consecutive_errors}: {str(e)}]\n\n"
                    await asyncio.sleep(5)
        finally:
            await safe_close_pubsub(pubsub)
            await safe_close_pubsub(log_pubsub)


# ?? 紐⑤뱢 ?덈꺼 ?깃????????????????????????????????????????????????????????????
event_service = EventService()

__all__ = [
    "event_service",
    "EventService",
    # re-export: ?몃? import ?명솚 (from event_service import X)
    "RUNNER_KEY_PREFIX",
    "ACTIVE_RUNNERS_KEY",
    "RECENT_RUNNERS_KEY",
    "REDIS_STATE_KEY",
    "PLAN_FILE_ALL",
    "_LEGACY_ALL",
    "KEYEVENT_CHANNEL",
    "LOG_CHANNEL_PATTERN",
    "MERGE_LOG_CHANNEL_PATTERN",
    "KEY_EVENT_MAP",
    "MAX_RECENT_IN_SSE",
    "MAX_RECENT_RUNNERS",
    "_build_log_line_payload",
    "_LOG_COMPLETED_SENTINEL",
    "_MERGE_LOG_COMPLETED_SENTINEL",
    "get_pmsg_count_last5min",
]

