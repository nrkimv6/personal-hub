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
import glob
import hashlib
import logging
import time
from collections import deque
from pathlib import Path
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
from app.modules.dev_runner.services.event_routing import (  # noqa: F401 — re-export 포함
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
from app.modules.dev_runner.services.event_sse import (  # noqa: F401 — re-export 포함
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

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # 초
FILE_POLL_TIMEOUT = 5.0
FILE_POLL_INTERVAL = 1.0
MAX_FALLBACK_READ_LINES = 400

# ─── pmessage 수신 헬스 게이지 (in-memory, 5분 슬라이딩 윈도우) ─────────────────
import collections as _collections

_PMSG_WINDOW_SEC = 300  # 5분 슬라이딩 윈도우
_pmsg_timestamps: "collections.deque[float]" = _collections.deque()  # 수신 시각 목록


def _record_pmsg_received() -> None:
    """pmessage 수신 시 호출 — 현재 시각을 슬라이딩 윈도우에 추가"""
    now = time.monotonic()
    _pmsg_timestamps.append(now)
    # 오래된 항목 정리 (>5분)
    while _pmsg_timestamps and now - _pmsg_timestamps[0] > _PMSG_WINDOW_SEC:
        _pmsg_timestamps.popleft()


def get_pmsg_count_last5min() -> int:
    """최근 5분 내 `plan-runner:logs:*` pmessage 수신 건수 반환 (헬스체크용)"""
    if not _pmsg_timestamps:
        return 0
    now = time.monotonic()
    # 윈도우 내 항목만 카운트 (deque는 왼쪽이 가장 오래됨)
    cutoff = now - _PMSG_WINDOW_SEC
    count = sum(1 for t in _pmsg_timestamps if t >= cutoff)
    return count
MAX_FALLBACK_READ_CHARS = 65536
TAIL_STATE_TTL_SEC = 600.0
DEFAULT_DEDUP_WINDOW = 256
COMPLETED_RUNNER_TTL_SEC = 120.0


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
        self._runner_tail_state: dict[str, dict] = {}
        self._completed_runners: dict[str, float] = {}
        self._tail_state_ttl_sec = TAIL_STATE_TTL_SEC
        self._completed_runner_ttl_sec = COMPLETED_RUNNER_TTL_SEC
        self._dedup_window = DEFAULT_DEDUP_WINDOW
        self._file_poll_timeout = FILE_POLL_TIMEOUT
        self._file_poll_interval_sec = FILE_POLL_INTERVAL
        self._file_poll_max_lines = MAX_FALLBACK_READ_LINES
        self._file_poll_max_chars = MAX_FALLBACK_READ_CHARS

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

    def _cleanup_invisible_recent_runners(self) -> None:
        """SSE 연결 초기화 시 RECENT set에서 invisible runner를 제거 + 크기 상한 적용.

        invisible runner(trigger 미설정/비사용자)가 RECENT set을 점령하여
        SSE status 이벤트의 runners 배열에서 visible runner가 누락되는 문제를 방지한다.
        정리 순서: invisible 제거 → 크기 상한(MAX_RECENT_RUNNERS) 적용.
        """
        try:
            recent_ids: list = self._sync.zrange(RECENT_RUNNERS_KEY, 0, -1) or []
            for rid in recent_ids:
                trigger = self._sync.get(f"{RUNNER_KEY_PREFIX}:{rid}:trigger")
                if not is_visible_runner(trigger, rid):
                    self._sync.zrem(RECENT_RUNNERS_KEY, rid)
            # invisible 제거 후 크기 상한: oldest-first로 MAX_RECENT_RUNNERS 초과분 제거
            self._sync.zremrangebyrank(RECENT_RUNNERS_KEY, 0, -(MAX_RECENT_RUNNERS + 1))
        except Exception:
            pass

    # ── /events fallback 상태 관리 ───────────────────────────────────────────

    def _ensure_runtime_state(self) -> None:
        """__new__ 기반 테스트에서도 런타임 상태 필드를 보장한다."""
        if not hasattr(self, "_runner_tail_state"):
            self._runner_tail_state = {}
        if not hasattr(self, "_completed_runners"):
            self._completed_runners = {}
        if not hasattr(self, "_tail_state_ttl_sec"):
            self._tail_state_ttl_sec = TAIL_STATE_TTL_SEC
        if not hasattr(self, "_completed_runner_ttl_sec"):
            self._completed_runner_ttl_sec = COMPLETED_RUNNER_TTL_SEC
        if not hasattr(self, "_dedup_window"):
            self._dedup_window = DEFAULT_DEDUP_WINDOW
        if not hasattr(self, "_file_poll_timeout"):
            self._file_poll_timeout = FILE_POLL_TIMEOUT
        if not hasattr(self, "_file_poll_interval_sec"):
            self._file_poll_interval_sec = FILE_POLL_INTERVAL
        if not hasattr(self, "_file_poll_max_lines"):
            self._file_poll_max_lines = MAX_FALLBACK_READ_LINES
        if not hasattr(self, "_file_poll_max_chars"):
            self._file_poll_max_chars = MAX_FALLBACK_READ_CHARS

    def _get_or_create_tail_state(self, runner_id: str) -> dict:
        self._ensure_runtime_state()
        state = self._runner_tail_state.get(runner_id)
        if state is None:
            state = {
                "path": None,
                "inode": None,
                "offset": 0,
                "recent_fingerprints": deque(maxlen=self._dedup_window),
                "last_seen": time.monotonic(),
            }
            self._runner_tail_state[runner_id] = state
        return state

    def _drop_tail_state(self, runner_id: str) -> None:
        self._ensure_runtime_state()
        self._runner_tail_state.pop(runner_id, None)

    def _mark_runner_completed(self, runner_id: str) -> None:
        self._ensure_runtime_state()
        self._completed_runners[runner_id] = time.monotonic()
        self._drop_tail_state(runner_id)

    def _is_runner_recently_completed(self, runner_id: str) -> bool:
        self._ensure_runtime_state()
        marked_at = self._completed_runners.get(runner_id)
        if marked_at is None:
            return False
        if time.monotonic() - marked_at > self._completed_runner_ttl_sec:
            self._completed_runners.pop(runner_id, None)
            return False
        return True

    def _fingerprint_line(self, runner_id: str, line: str) -> str:
        text = str(line or "")
        raw = f"{runner_id}\x00{text}".encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest()[:16]

    def _is_duplicate_log_line(self, runner_id: str, line: str) -> bool:
        state = self._get_or_create_tail_state(runner_id)
        state["last_seen"] = time.monotonic()
        recent = state.get("recent_fingerprints")
        if not isinstance(recent, deque):
            recent = deque(maxlen=self._dedup_window)
            state["recent_fingerprints"] = recent
        fp = self._fingerprint_line(runner_id, line)
        if fp in recent:
            return True
        recent.append(fp)
        return False

    def _list_visible_active_runner_ids(self) -> list[str]:
        self._ensure_runtime_state()
        try:
            runner_ids = self._sync.smembers(ACTIVE_RUNNERS_KEY) or set()
        except Exception:
            return []

        visible_running_ids: list[str] = []
        for rid in runner_ids:
            runner_id = str(rid)
            payload = build_status_payload(self._sync, runner_id)
            if (
                payload
                and payload.get("visible", False)
                and payload.get("status") == "running"
            ):
                self._completed_runners.pop(runner_id, None)
                visible_running_ids.append(runner_id)
            else:
                self._drop_tail_state(runner_id)
        return visible_running_ids

    def _resolve_runner_log_path(self, runner_id: str) -> Optional[Path]:
        prefix = f"{RUNNER_KEY_PREFIX}:{runner_id}"
        try:
            stream_path_str = self._sync.get(f"{prefix}:stream_log_path")
            if stream_path_str:
                stream_path = Path(stream_path_str)
                if stream_path.exists():
                    return stream_path

            log_path_str = self._sync.get(f"{prefix}:log_file_path")
            if log_path_str:
                log_path = Path(log_path_str)
                if log_path.exists():
                    return log_path
        except Exception:
            pass

        log_dir = Path(config.LOG_DIR)
        if not log_dir.is_absolute():
            log_dir = Path.cwd() / log_dir
        if not log_dir.exists():
            return None

        patterns = [
            str(log_dir / f"plan-runner-stream-{runner_id}-*.log"),
            str(log_dir / f"plan-runner-{runner_id}-*.log"),
        ]
        candidates: list[Path] = []
        for pattern in patterns:
            for matched in glob.glob(pattern):
                path = Path(matched)
                if path.exists():
                    candidates.append(path)
        if not candidates:
            return None
        try:
            return max(candidates, key=lambda p: p.stat().st_mtime)
        except Exception:
            return candidates[-1]

    def _ensure_tail_state_for_path(self, runner_id: str, path: Path) -> Optional[dict]:
        self._ensure_runtime_state()
        try:
            stat = path.stat()
        except Exception:
            self._drop_tail_state(runner_id)
            return None

        state = self._get_or_create_tail_state(runner_id)
        now = time.monotonic()
        path_str = str(path)
        inode_sig = (stat.st_dev, stat.st_ino)
        prev_path = state.get("path")
        prev_inode = state.get("inode")
        prev_offset = int(state.get("offset", 0))
        reset_reason: Optional[str] = None

        if prev_path is None and prev_inode is None:
            # 첫 연결은 offset=0으로 시작해 pub/sub 공백 구간 로그 유실을 방지한다.
            state["path"] = path_str
            state["inode"] = inode_sig
            state["offset"] = 0
        elif prev_path != path_str:
            state["path"] = path_str
            state["inode"] = inode_sig
            state["offset"] = 0
            state["recent_fingerprints"] = deque(maxlen=self._dedup_window)
            reset_reason = "path_changed"
        elif prev_inode != inode_sig:
            state["inode"] = inode_sig
            state["offset"] = 0
            state["recent_fingerprints"] = deque(maxlen=self._dedup_window)
            reset_reason = "rotate"
        elif stat.st_size < prev_offset:
            state["offset"] = 0
            state["recent_fingerprints"] = deque(maxlen=self._dedup_window)
            reset_reason = "truncate"

        state["last_seen"] = now
        if reset_reason:
            logger.debug(
                "[events-fallback] tail offset reset (runner=%s, reason=%s, from=%s, to=%s)",
                runner_id,
                reset_reason,
                prev_offset,
                state.get("offset"),
            )
        return state

    def _cleanup_runner_tail_state(self, visible_runner_ids: set[str]) -> None:
        self._ensure_runtime_state()
        now = time.monotonic()
        for runner_id, state in list(self._runner_tail_state.items()):
            last_seen = float(state.get("last_seen", 0.0))
            if runner_id not in visible_runner_ids:
                self._runner_tail_state.pop(runner_id, None)
                continue
            if now - last_seen > self._tail_state_ttl_sec:
                self._runner_tail_state.pop(runner_id, None)
        for runner_id, marked_at in list(self._completed_runners.items()):
            if runner_id not in visible_runner_ids:
                self._completed_runners.pop(runner_id, None)
                continue
            if now - marked_at > self._completed_runner_ttl_sec:
                self._completed_runners.pop(runner_id, None)

    def _poll_runner_log_delta(self, runner_id: str) -> tuple[list[tuple[str, dict]], int]:
        self._ensure_runtime_state()
        dedup_skipped = 0
        try:
            trigger = self._sync.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger")
        except Exception:
            trigger = None
        if not is_visible_runner(trigger, runner_id):
            self._drop_tail_state(runner_id)
            return [], dedup_skipped
        if self._is_runner_recently_completed(runner_id):
            return [], dedup_skipped

        path = self._resolve_runner_log_path(runner_id)
        if path is None or not path.exists():
            self._drop_tail_state(runner_id)
            return [], dedup_skipped

        state = self._ensure_tail_state_for_path(runner_id, path)
        if state is None:
            return [], dedup_skipped

        max_lines = int(self._file_poll_max_lines)
        max_chars = int(self._file_poll_max_chars)
        offset = int(state.get("offset", 0))
        lines_read = 0
        chars_read = 0
        events: list[tuple[str, dict]] = []
        completed_from_file = False

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                while lines_read < max_lines and chars_read < max_chars:
                    start_pos = handle.tell()
                    raw_line = handle.readline()
                    if raw_line == "":
                        break

                    chars_read += len(raw_line)
                    if chars_read > max_chars and lines_read > 0:
                        handle.seek(start_pos)
                        break

                    line = raw_line.rstrip("\n")
                    if not line:
                        continue
                    lines_read += 1

                    if _is_log_completed_payload(line):
                        status, reason = _parse_log_completed_payload(line)
                        payload = {"runner_id": runner_id, "status": status, "reason": reason}
                        try:
                            error = self._sync.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:error")
                        except Exception:
                            error = None
                        if error:
                            payload["error"] = error
                        events.append(("log_completed", payload))
                        completed_from_file = True
                        break

                    if self._is_duplicate_log_line(runner_id, line):
                        dedup_skipped += 1
                        continue

                    events.append(
                        (
                            "log",
                            {"runner_id": runner_id, "line": _build_log_line_payload(line)},
                        )
                    )

                new_offset = handle.tell()
        except Exception as exc:
            logger.debug("[events-fallback] file poll read failed (runner=%s): %s", runner_id, exc)
            return [], dedup_skipped

        if completed_from_file:
            self._mark_runner_completed(runner_id)
            return events, dedup_skipped

        state["offset"] = int(new_offset)
        state["last_seen"] = time.monotonic()
        if lines_read >= max_lines or chars_read >= max_chars:
            logger.debug(
                "[events-fallback] read cap reached (runner=%s, lines=%s, chars=%s)",
                runner_id,
                lines_read,
                chars_read,
            )
        return events, dedup_skipped

    async def _init_tail_offsets_for_active_runners(self) -> None:
        """SSE 연결 시점에 활성 러너의 tail offset을 현재 파일 EOF로 초기화한다.

        API 재시작 후 SSE 재연결 시 _runner_tail_state가 리셋되어 fallback이
        파일 전체(offset 0)를 재전송하는 문제를 방지한다.
        클라이언트는 catchUp()으로 이미 파일 내용을 로드하므로 서버 fallback은
        이 시점 이후의 신규 라인만 전달하면 된다.
        """
        try:
            runner_ids = self._list_visible_active_runner_ids()
        except Exception as e:
            logger.warning("[events-init-offsets] runner 목록 획득 실패: %s", e)
            return

        for runner_id in runner_ids:
            try:
                path = self._resolve_runner_log_path(runner_id)
                if path is None:
                    continue
                state = self._ensure_tail_state_for_path(runner_id, path)
                if state is None:
                    continue
                try:
                    state["offset"] = path.stat().st_size
                except Exception as e:
                    logger.warning(
                        "[events-init-offsets] stat 실패 (runner=%s, path=%s): %s",
                        runner_id,
                        path,
                        e,
                    )
            except Exception as e:
                logger.warning("[events-init-offsets] runner=%s 처리 중 예외: %s", runner_id, e)

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

        # API 재시작 후 SSE 재연결 시 fallback 중복 재전송 방지: tail offset을 EOF로 초기화
        # (클라이언트 catchUp()이 파일 현재 내용을 로드하므로 서버 fallback은 이후 신규 라인만 담당)
        try:
            await self._init_tail_offsets_for_active_runners()
        except Exception as _e:
            logger.warning("[events-init-offsets] 초기화 중 예외 (스트림 계속): %s", _e)

        # SSE 연결 초기화 시 invisible runner 사전 정리 (RECENT set 오염 방지)
        self._cleanup_invisible_recent_runners()

        # 초기 status 이벤트 1회 즉시 발행
        runners = build_all_runners_status(self._sync)
        stabilized_runners = []
        for payload in runners:
            runner_id = payload.get("runner_id") if isinstance(payload, dict) else None
            if runner_id:
                payload = await stabilize_commit_failed_status_payload(self._sync, runner_id, payload)
            stabilized_runners.append(payload)
        runners = stabilized_runners
        yield sse_format("status", {"runners": runners})

        # 초기 tracking 이벤트
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
        self._ensure_runtime_state()

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
                                        self._drop_tail_state(runner_id)
                                    if payload.get("status") != "running":
                                        self._drop_tail_state(runner_id)
                                    else:
                                        self._completed_runners.pop(runner_id, None)
                        elif event_type == "tracking":
                            payload = build_tracking_payload(self._sync)
                            if payload:
                                yield sse_format("tracking", payload)
                        elif event_type == "plan_changed":
                            payload = build_tracking_payload(self._sync)
                            yield sse_format("plan_changed", payload or {})

                        last_heartbeat = time.monotonic()
                        consecutive_errors = 0

                    # ── 로그 채널 메시지 폴링
                    log_message = await log_pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.25
                    )

                    if log_message and log_message["type"] in ("message", "pmessage"):
                        # pmessage 수신 게이지 기록 (헬스체크용)
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
                            pass  # 빈 데이터 무시
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
                                    self._mark_runner_completed(runner_id)
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
                                    self._completed_runners.pop(runner_id, None)
                                    if self._is_duplicate_log_line(runner_id, str(data)):
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
                            self._cleanup_runner_tail_state(set(visible_runner_ids))
                            fallback_emitted = False
                            for runner_id in visible_runner_ids:
                                fallback_events, dedup_skipped = self._poll_runner_log_delta(runner_id)
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
                    # ── Redis 연결 실패 → 정리 후 재시도
                    logger.warning("[events] Redis 연결 실패: %s: %s", type(redis_err).__name__, redis_err)
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


# ── 모듈 레벨 싱글톤 ─────────────────────────────────────────────────────────
event_service = EventService()

__all__ = ["event_service", "EventService"]
