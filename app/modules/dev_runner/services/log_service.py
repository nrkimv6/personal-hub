"""로그 스트리밍 서비스 - Redis Pub/Sub 기반 실시간 로그"""

import asyncio
import hashlib
import json
import logging
import os
import time
import re

logger = logging.getLogger(__name__)
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncGenerator, List
import glob

import redis
import redis.asyncio as aioredis

from app.modules.dev_runner.config import config
from app.modules.dev_runner.services.completion_reason import (
    is_log_completed_payload,
    is_merge_completed_payload,
    parse_log_completed_payload,
    parse_merge_completed_payload,
)
from app.shared.redis.client import RedisClient
from app.modules.dev_runner.services.sse_helpers import (
    safe_close_pubsub,
    MAX_SSE_FRAME_CHARS,
    _is_multiline_frame_enabled,
    _normalize_newlines,
    _format_sse_data,
    _is_frame_start,
    _PollFrameBuffer,
)
from app.modules.dev_runner.schemas import LogResponse, RunHistoryItem, RunHistoryResponse, FullLogResponse
from app.modules.dev_runner.services.state import get_state
from app.modules.dev_runner.services.visibility import is_visible_runner
from app.modules.dev_runner.services.log_file_resolver import LogFileResolver
# Redis 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
LOG_CHANNEL_PREFIX = "plan-runner:logs"
SYSTEM_LOG_CHANNEL = "plan-runner:system"  # 전역 시스템 알림용, per-runner 로그 채널과 구분

HEARTBEAT_INTERVAL = 30  # 초
FILE_POLL_TIMEOUT = 5.0  # pub/sub 미수신 N초 후 파일 폴링 전환 (테스트에서 patch 가능)
_ANSI_ESCAPE_RE = re.compile(r"\033\[[0-9;]*m")


class LogService:
    """로그 스트리밍 서비스 - Redis Pub/Sub 기반"""

    def __init__(self):
        """Redis 클라이언트 초기화 (ConnectionPool 기반)"""
        # 동기 클라이언트 (tail_log_file, _find_current_log 용)
        sync_client = RedisClient.get_sync_client()
        self.redis_client = sync_client if sync_client is not None else redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=5,
        )
        # 비동기 클라이언트 (stream_log_file 용 — ConnectionPool로 연결 수 제한)
        self._async_pool = aioredis.ConnectionPool(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
            socket_connect_timeout=5, max_connections=50,
        )
        self.async_redis = aioredis.Redis(connection_pool=self._async_pool)
        self.resolver = LogFileResolver(config, self.redis_client)

    # 레거시 파일명(runner_id 없음) pseudo_id → Path 역매핑 캐시 (resolver와 공유)
    _legacy_map: dict[str, "Path"] = {}

    def _sync_resolver(self) -> None:
        """resolver 지연 초기화 + redis_client 교체 동기화 (테스트 __new__ 경로 지원)."""
        resolver = getattr(self, "resolver", None)
        redis_client = getattr(self, "redis_client", None)
        if resolver is None or not isinstance(resolver, LogFileResolver):
            self.resolver = LogFileResolver(config, redis_client)
        elif getattr(resolver, "_redis_client", None) is not redis_client:
            self.resolver = LogFileResolver(config, redis_client)
        # 레거시 pseudo_id 캐시는 LogService/Resolver 간 공유 유지
        self.resolver._legacy_map = self._legacy_map

    def _find_current_log(self, runner_id: str) -> Optional[Path]:
        """[shim] → self.resolver.find_current_log()"""
        self._sync_resolver()
        resolved = self.resolver.find_current_log(runner_id)
        if resolved is not None:
            return resolved

        # 호환 fallback: 테스트에서 _get_log_dir patch한 경로까지 포함해 파일시스템 재탐색
        if runner_id.startswith("lg-"):
            return None
        log_dir = self._get_log_dir()
        if log_dir.exists():
            for pattern in [
                f"plan-runner-stream-{runner_id}-*.log",
                f"plan-runner-{runner_id}-*.log",
            ]:
                matches = list(log_dir.glob(pattern))
                if matches:
                    return max(matches, key=lambda p: p.stat().st_mtime)
        return None

    def _resolve_legacy_log(self, runner_id: str) -> Optional[Path]:
        """[shim] → self.resolver.resolve_legacy_log()"""
        self._sync_resolver()
        # 호환: LogService 클래스 캐시 우선 (기존 테스트 계약)
        if runner_id in self._legacy_map:
            return self._legacy_map[runner_id]

        log_dir = self._get_log_dir()
        if not log_dir.exists():
            return None

        for log_path in log_dir.glob("plan-runner-stream-*.log"):
            m = re.match(r"plan-runner-stream-(\d{8}_\d{6})\.log$", log_path.name)
            if not m:
                continue
            ts = m.group(1)
            pseudo_id = f"lg-{hashlib.md5(ts.encode()).hexdigest()[:5]}"
            self._legacy_map[pseudo_id] = log_path
        return self._legacy_map.get(runner_id)

    def tail_log_file(self, runner_id: str, n_lines: int = 100) -> LogResponse:
        """로그 파일 끝에서 N줄 읽기 (초기 로드용)."""
        log_file = self._find_current_log(runner_id)

        # Phase 2 fallback: lg- 접두사 pseudo runner_id → 레거시 파일 탐색
        if log_file is None and runner_id.startswith("lg-"):
            log_file = self._resolve_legacy_log(runner_id)

        if log_file and log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    all_lines = f.readlines()
                total = len(all_lines)
                sliced = all_lines[-n_lines:] if total > n_lines else all_lines
                from_line = max(0, total - n_lines)
                if sliced:
                    return LogResponse(
                        lines=[line.rstrip('\n') for line in sliced],
                        total_lines=len(sliced),
                        from_line=from_line,
                    )
            except Exception as e:
                return LogResponse(
                    lines=[f"Error reading log: {str(e)}"],
                    total_lines=1
                )

        # fallback: Redis list에서 merge 로그 히스토리 조회 (dm-* runner 등 로그 파일 없는 경우)
        logger.warning(f"[tail_log_file] runner {runner_id}: 로그 파일 미탐지 → Redis list fallback")
        try:
            log_list_key = f"plan-runner:logs:list:{runner_id}"
            logs = self.redis_client.lrange(log_list_key, -n_lines, -1)
            if logs:
                return LogResponse(lines=logs, total_lines=len(logs))
        except Exception:
            pass

        return LogResponse(lines=[], total_lines=0)

    async def _stream_sse_loop(
        self,
        channel: str,
        completion_checker,
        completion_parser,
        *,
        multiline_frame: bool = True,
    ) -> AsyncGenerator[str, None]:
        """공통 Redis Pub/Sub SSE 루프 — pubsub 생성·completion·heartbeat·에러 처리.

        파일 폴링 fallback 없는 순수 pubsub 스트리밍.
        stream_merge_log 등 단순 채널 구독에 사용한다.
        """
        pubsub = None
        was_disconnected = False
        last_heartbeat = time.monotonic()
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 5

        try:
            while True:
                try:
                    if pubsub is None:
                        pubsub = self.async_redis.pubsub()
                        await pubsub.subscribe(channel)
                        if was_disconnected:
                            yield "event: connected\ndata: ok\n\n"
                            was_disconnected = False

                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.5
                    )
                    if message and message["type"] == "message":
                        data = message["data"]
                        if completion_checker(data):
                            _, reason = completion_parser(data)
                            yield f"event: completed\ndata: {reason}\n\n"
                            return
                        if multiline_frame:
                            yield _format_sse_data(_ANSI_ESCAPE_RE.sub("", data))
                        else:
                            yield f"data: {data}\n\n"
                        last_heartbeat = time.monotonic()
                        consecutive_errors = 0
                    else:
                        now = time.monotonic()
                        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                            yield ": heartbeat\n\n"
                            last_heartbeat = now
                        await asyncio.sleep(0.3)

                except (redis.ConnectionError, aioredis.ConnectionError, ConnectionError, OSError):
                    await safe_close_pubsub(pubsub)
                    pubsub = None
                    was_disconnected = True
                    yield "event: redis_disconnected\ndata: Redis not available\n\n"
                    last_heartbeat = time.monotonic()
                    await asyncio.sleep(5)

                except Exception as e:
                    consecutive_errors += 1
                    await safe_close_pubsub(pubsub)
                    pubsub = None
                    last_heartbeat = time.monotonic()

                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        yield "event: stream_error\ndata: Too many consecutive errors, stream stopped\n\n"
                        return

                    yield f"data: [Stream error #{consecutive_errors}: {str(e)}]\n\n"
                    await asyncio.sleep(5)
        finally:
            await safe_close_pubsub(pubsub)

    async def stream_log_file(self, runner_id: str, since_line: int = 0) -> AsyncGenerator[str, None]:
        """Redis Pub/Sub 기반 실시간 로그 스트리밍 (SSE 형식)"""
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        logger.info(f"[SSE] stream_log_file 시작: channel={log_channel}")
        multiline_frame_enabled = _is_multiline_frame_enabled()

        # 초기 Redis 연결 확인
        try:
            await self.async_redis.ping()
        except Exception:
            yield "event: error\ndata: Redis 연결 불가\n\n"
            return

        # 초기 연결 이벤트 — EventSource가 MIME type 검증을 통과하도록 보장
        yield "event: connected\ndata: ok\n\n"

        # since_line > 0 이면 파일에서 해당 줄 이후 내용을 먼저 전송 (gap 해소)
        _file_pos_init = 0
        if since_line > 0:
            gap_file = self._find_current_log(runner_id)
            if gap_file and gap_file.exists():
                try:
                    with open(gap_file, "r", encoding="utf-8", errors="replace") as gf:
                        gap_lines = gf.readlines()
                        _file_pos_init = gf.tell()
                    buffered = gap_lines[since_line:]
                    if multiline_frame_enabled:
                        gap_framer = _PollFrameBuffer()
                        for bl in buffered:
                            stripped = _ANSI_ESCAPE_RE.sub("", bl.rstrip("\n"))
                            if not stripped:
                                continue
                            ready_frames, overflow = gap_framer.push_line(stripped)
                            if overflow:
                                logger.warning(f"[SSE] gap fill 프레임 상한 초과 (runner={runner_id})")
                            for frame in ready_frames:
                                yield _format_sse_data(frame)
                        pending_gap = gap_framer.flush()
                        if pending_gap:
                            yield _format_sse_data(pending_gap)
                    else:
                        for bl in buffered:
                            stripped = _ANSI_ESCAPE_RE.sub("", bl.rstrip("\n"))
                            if stripped:
                                yield f"data: {stripped}\n\n"
                except Exception as ge:
                    logger.debug(f"[SSE] since_line gap fill 실패: {ge}")

        pubsub = None
        was_disconnected = False
        last_heartbeat = time.monotonic()
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 5
        # Phase 0: 첫 메시지 수신 진단
        _first_msg_logged = False
        # Phase 2: 파일 폴링 fallback
        _no_msg_since = time.monotonic()
        _file_pos = _file_pos_init
        _poll_chunk_buffer = ""
        _poll_framer = _PollFrameBuffer()

        try:
            while True:
                try:
                    if pubsub is None:
                        pubsub = self.async_redis.pubsub()
                        await pubsub.subscribe(log_channel)
                        if was_disconnected:
                            yield "event: connected\ndata: ok\n\n"
                            was_disconnected = False

                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.5
                    )
                    if message and message["type"] == "message":
                        if not _first_msg_logged:
                            logger.info(f"[SSE] 첫 메시지 수신: channel={log_channel}")
                            _first_msg_logged = True
                        _no_msg_since = time.monotonic()
                        data = message["data"]
                        if is_log_completed_payload(data):
                            _, reason = parse_log_completed_payload(data)
                            yield f"event: completed\ndata: {reason}\n\n"
                            return
                        if multiline_frame_enabled:
                            yield _format_sse_data(_ANSI_ESCAPE_RE.sub("", data))
                        else:
                            yield f"data: {data}\n\n"
                        last_heartbeat = time.monotonic()
                        consecutive_errors = 0
                    else:
                        now = time.monotonic()
                        # Phase 2: pub/sub 메시지 없을 때 파일 폴링 fallback
                        if now - _no_msg_since >= FILE_POLL_TIMEOUT:
                            log_file = self._find_current_log(runner_id)
                            if log_file and log_file.exists():
                                if _file_pos == 0:
                                    # since_line=0: 파일 폴링 첫 진입 시 EOF seek으로 초기화 (기존 내용 중복 재전송 방지)
                                    try:
                                        with open(log_file, "r", encoding="utf-8", errors="replace") as _f_init:
                                            _f_init.seek(0, 2)  # SEEK_END
                                            _file_pos = _f_init.tell()
                                    except Exception:
                                        pass
                                    logger.warning(
                                        "[SSE][FALLBACK] %s",
                                        json.dumps({"event": "fallback_mode", "channel": log_channel, "runner_id": runner_id}),
                                    )
                                    # R4: 클라이언트에 fallback_mode 이벤트 전송 (개발 모드용 배지)
                                    yield "event: fallback_mode\ndata: file polling active\n\n"
                                try:
                                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                                        f.seek(_file_pos)
                                        new_lines = f.read()
                                        new_pos = f.tell()
                                    if new_lines:
                                        if multiline_frame_enabled:
                                            _poll_chunk_buffer += _normalize_newlines(new_lines)
                                            parts = _poll_chunk_buffer.split("\n")
                                            _poll_chunk_buffer = parts.pop() if parts else ""
                                            for poll_line in parts:
                                                stripped_line = _ANSI_ESCAPE_RE.sub("", poll_line.rstrip("\n"))
                                                if not stripped_line:
                                                    continue
                                                ready_frames, overflow = _poll_framer.push_line(stripped_line)
                                                if overflow:
                                                    logger.warning(
                                                        f"[SSE] 파일 폴링 프레임 상한 초과 즉시 flush (runner={runner_id})"
                                                    )
                                                for frame in ready_frames:
                                                    yield _format_sse_data(frame)
                                            pending_poll = _poll_framer.flush()
                                            if pending_poll:
                                                yield _format_sse_data(pending_poll)
                                        else:
                                            for poll_line in new_lines.splitlines():
                                                stripped_line = poll_line.strip()
                                                if stripped_line:
                                                    yield f"data: {stripped_line}\n\n"
                                        _file_pos = new_pos
                                        last_heartbeat = time.monotonic()
                                except Exception as fe:
                                    logger.debug(f"[SSE] 파일 폴링 실패: {fe}")
                        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                            yield ": heartbeat\n\n"
                            last_heartbeat = now
                        await asyncio.sleep(0.3)

                except (redis.ConnectionError, aioredis.ConnectionError, ConnectionError, OSError) as _conn_err:
                    logger.error(
                        "[SSE][CONN_ERROR] %s",
                        json.dumps({"event": "pubsub_disconnected", "channel": log_channel, "runner_id": runner_id, "error": str(_conn_err)}),
                    )
                    await safe_close_pubsub(pubsub)
                    pubsub = None
                    was_disconnected = True
                    yield "event: redis_disconnected\ndata: Redis not available\n\n"
                    last_heartbeat = time.monotonic()
                    await asyncio.sleep(5)

                except Exception as e:
                    consecutive_errors += 1
                    await safe_close_pubsub(pubsub)
                    pubsub = None
                    last_heartbeat = time.monotonic()

                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        yield "event: stream_error\ndata: Too many consecutive errors, stream stopped\n\n"
                        return

                    yield f"data: [Stream error #{consecutive_errors}: {str(e)}]\n\n"
                    await asyncio.sleep(5)
        finally:
            await safe_close_pubsub(pubsub)


    async def stream_merge_log(self, runner_id: str) -> AsyncGenerator[str, None]:
        """Redis Pub/Sub 기반 머지 로그 SSE 스트리밍 (_stream_sse_loop thin wrapper)"""
        log_channel = f"plan-runner:merge-log:{runner_id}"
        yield "event: connected\ndata: ok\n\n"
        async for event in self._stream_sse_loop(
            log_channel,
            is_merge_completed_payload,
            parse_merge_completed_payload,
            multiline_frame=True,
        ):
            yield event

    def _get_log_dir(self) -> Path:
        """[shim] → self.resolver.get_log_dir()"""
        self._sync_resolver()
        return self.resolver.get_log_dir()

    @staticmethod
    def _parse_meta_from_log(log_file_path: str, scan_lines: int = 15) -> dict:
        """[shim] → LogFileResolver.parse_meta_from_log()"""
        return LogFileResolver.parse_meta_from_log(log_file_path, scan_lines)

    @staticmethod
    def _parse_trigger_from_log(log_file_path: str) -> Optional[str]:
        """[shim] → LogFileResolver.parse_trigger_from_log()"""
        return LogFileResolver.parse_trigger_from_log(log_file_path)

    def get_run_history(self, limit: int = 20, offset: int = 0, visible_only: bool = False) -> RunHistoryResponse:
        """실행 이력 조회: Redis active_runners + 로그 파일 스캔 병합, start_time DESC 정렬"""
        runs: dict[str, RunHistoryItem] = {}

        # 1. Redis active_runners에서 현재 실행 중인 runner 수집
        try:
            runner_ids = self.redis_client.smembers(ACTIVE_RUNNERS_KEY) or set()
            for runner_id in runner_ids:
                prefix = f"{RUNNER_KEY_PREFIX}:{runner_id}"
                plan_file = self.redis_client.get(f"{prefix}:plan_file")
                engine = self.redis_client.get(f"{prefix}:engine") or "claude"
                pid_str = self.redis_client.get(f"{prefix}:pid")
                start_time_str = self.redis_client.get(f"{prefix}:start_time")
                stream_log = self.redis_client.get(f"{prefix}:stream_log_path")
                log_file_path = stream_log or self.redis_client.get(f"{prefix}:log_file_path")
                worktree_path = self.redis_client.get(f"{prefix}:worktree_path")
                merge_status = self.redis_client.get(f"{prefix}:merge_status")
                trigger = self.redis_client.get(f"{prefix}:trigger")

                start_time = None
                if start_time_str:
                    try:
                        start_time = datetime.fromisoformat(start_time_str)
                    except ValueError:
                        pass

                pid = None
                if pid_str:
                    try:
                        pid = int(pid_str)
                    except ValueError:
                        pass

                has_log = bool(log_file_path and Path(log_file_path).exists())
                branch = f"runner/{runner_id}" if worktree_path else None
                if trigger is None and log_file_path:
                    trigger = self._parse_trigger_from_log(log_file_path)
                if visible_only and not is_visible_runner(trigger, runner_id):
                    continue
                # execution_count: Redis에서 우선 조회
                execution_count = None
                ec_raw = self.redis_client.get(f"{prefix}:execution_count")
                if ec_raw is not None:
                    try:
                        execution_count = int(ec_raw)
                    except (ValueError, TypeError):
                        pass
                runs[runner_id] = RunHistoryItem(
                    runner_id=runner_id,
                    plan_file=plan_file,
                    engine=engine,
                    status="running",
                    pid=pid,
                    start_time=start_time,
                    end_time=None,
                    log_file=log_file_path,
                    has_log=has_log,
                    worktree_path=worktree_path,
                    branch=branch,
                    merge_status=merge_status,
                    trigger=trigger,
                    execution_count=execution_count,
                )
        except redis.ConnectionError:
            pass

        # 2. 로그 파일 스캔 — 종료된 runner 포함
        log_dir = self._get_log_dir()
        if log_dir.exists():
            # stream log 파일 패턴: plan-runner-stream-{runner_id}-YYYYMMDD*.log
            pattern = str(log_dir / "plan-runner-stream-*.log")
            for log_path in glob.glob(pattern):
                path = Path(log_path)
                fname = path.name
                # runner_id 추출: 신규 형식 plan-runner-stream-{8hex}-*.log
                m = re.match(r"plan-runner-stream-([0-9a-f]{8})-", fname)
                if not m:
                    # 레거시 형식 plan-runner-stream-{timestamp}.log
                    m2 = re.match(r"plan-runner-stream-(\d{8}_\d{6})\.log$", fname)
                    if not m2:
                        continue
                    ts = m2.group(1)
                    runner_id = f"lg-{hashlib.md5(ts.encode()).hexdigest()[:5]}"
                    self._legacy_map[runner_id] = path
                else:
                    runner_id = m.group(1)

                # 이미 Redis에서 수집한 running runner면 log_file만 보정
                if runner_id in runs:
                    if not runs[runner_id].log_file:
                        runs[runner_id].log_file = str(path)
                        runs[runner_id].has_log = path.exists()
                    continue

                # 파일 수정 시간을 start_time 대용으로 사용
                try:
                    mtime = path.stat().st_mtime
                    start_time = datetime.fromtimestamp(mtime)
                except OSError:
                    start_time = None

                file_meta = self._parse_meta_from_log(str(path))
                file_trigger = file_meta.get("trigger")
                file_plan = file_meta.get("plan")
                file_started_at = file_meta.get("started_at")
                file_execution_count = file_meta.get("execution_count")
                if visible_only and not is_visible_runner(file_trigger, runner_id):
                    continue
                # RUN_META.started_at 우선, 없으면 mtime fallback
                if file_started_at:
                    try:
                        start_time = datetime.fromisoformat(file_started_at)
                    except (ValueError, TypeError):
                        pass
                runs[runner_id] = RunHistoryItem(
                    runner_id=runner_id,
                    plan_file=file_plan,  # 로그에서 파싱된 plan 경로 (Redis 소실 시 fallback)
                    engine=None,
                    status="completed",
                    pid=None,
                    start_time=start_time,
                    end_time=None,
                    log_file=str(path),
                    has_log=True,
                    trigger=file_trigger,
                    execution_count=file_execution_count,
                )

        # 3. start_time DESC 정렬
        sorted_runs = sorted(
            runs.values(),
            key=lambda r: r.start_time or datetime.min,
            reverse=True,
        )

        total = len(sorted_runs)
        paginated = sorted_runs[offset: offset + limit]

        return RunHistoryResponse(runs=paginated, total=total)

    def get_full_log(self, runner_id: str, offset: int = 0, limit: int = 500) -> FullLogResponse:
        """종료된 Runner 전체 로그 조회 (offset/limit 청크 로드)"""
        # 1. Redis에서 로그 파일 경로 조회
        log_file = self._find_current_log(runner_id)

        # 2. Redis에 없으면 파일 스캔으로 fallback
        if log_file is None:
            log_dir = self._get_log_dir()
            if runner_id.startswith("lg-"):
                # 레거시 pseudo runner_id → _legacy_map 또는 전체 스캔
                log_file = self._resolve_legacy_log(runner_id)
            else:
                pattern = str(log_dir / f"plan-runner-stream-{runner_id}-*.log")
                matches = glob.glob(pattern)
                if matches:
                    log_file = Path(sorted(matches, key=lambda p: Path(p).stat().st_mtime)[-1])

        if log_file is None or not log_file.exists():
            return FullLogResponse(lines=[], total_lines=0, offset=offset, has_more=False)

        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()

            total_lines = len(all_lines)
            chunk = all_lines[offset: offset + limit]
            has_more = (offset + limit) < total_lines

            return FullLogResponse(
                lines=[line.rstrip('\n') for line in chunk],
                total_lines=total_lines,
                offset=offset,
                has_more=has_more,
            )
        except Exception as e:
            return FullLogResponse(
                lines=[f"Error reading log: {str(e)}"],
                total_lines=1,
                offset=0,
                has_more=False,
            )

    def publish_log(self, tag: str, message: str) -> None:
        """Redis pub/sub으로 로그 publish (LogViewer에 실시간 표시).

        plan_service._publish_log()와 동일 로직 — 외부 서비스에서 호출용 공개 인터페이스.
        Redis 미연결 시 조용히 무시한다.
        """
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            self.redis_client.publish(SYSTEM_LOG_CHANNEL, f"[{ts}] [{tag}] {message}")
        except Exception:
            pass  # Redis 미연결 시 무시

    def get_system_log(self, lines: int = 200) -> LogResponse:
        """Listener 시스템 로그 tail 조회 (가장 최신 plan-runner-*.log 파일)"""
        log_dir = self._get_log_dir()
        if not log_dir.exists():
            return LogResponse(lines=[], total_lines=0)

        # plan-runner-stream-* 제외, listener 자체 로그만 선택
        pattern = str(log_dir / "plan-runner-*.log")
        all_files = [
            p for p in glob.glob(pattern)
            if "stream" not in Path(p).name
        ]

        if not all_files:
            return LogResponse(lines=[], total_lines=0)

        # 가장 최신 파일 선택 (수정 시간 기준)
        latest = max(all_files, key=lambda p: Path(p).stat().st_mtime)

        try:
            with open(latest, "r", encoding="utf-8", errors="ignore") as f:
                tail = deque(f, maxlen=lines)
            result = [line.rstrip('\n') for line in tail]
            return LogResponse(lines=result, total_lines=len(result))
        except Exception as e:
            return LogResponse(lines=[f"Error reading system log: {str(e)}"], total_lines=1)



# 싱글톤 인스턴스
log_service = LogService()


def publish_log(tag: str, message: str) -> None:
    """모듈 레벨 publish_log 헬퍼 — log_service 싱글톤에 위임."""
    log_service.publish_log(tag, message)


__all__ = ['log_service', 'LogService', 'publish_log']
