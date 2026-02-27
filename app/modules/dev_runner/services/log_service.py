"""로그 스트리밍 서비스 - Redis Pub/Sub 기반 실시간 로그"""

import asyncio
import time
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncGenerator, List
import glob

import redis
import redis.asyncio as aioredis

from app.modules.dev_runner.config import config
from app.modules.dev_runner.schemas import LogResponse, RunHistoryItem, RunHistoryResponse, FullLogResponse
from app.modules.dev_runner.services.state import get_state
# Redis 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
LOG_CHANNEL_PREFIX = "plan-runner:logs"
LOG_CHANNEL = "plan-runner:logs"  # 하위호환 — plan_service 등 단일 채널 publish용

HEARTBEAT_INTERVAL = 30  # 초


class LogService:
    """로그 스트리밍 서비스 - Redis Pub/Sub 기반"""

    def __init__(self):
        """Redis 클라이언트 초기화"""
        # 동기 클라이언트 (tail_log_file, _find_current_log 용)
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        # 비동기 클라이언트 (stream_log_file 용 — 이벤트 루프 블로킹 방지)
        self.async_redis = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )

    def _find_current_log(self, runner_id: str) -> Optional[Path]:
        """특정 runner의 stream 로그 파일 (Redis에서 조회)"""
        try:
            # stream 로그 경로 우선 (executor가 직접 기록한 파일)
            log_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
            if log_path and Path(log_path).exists():
                return Path(log_path)
            # fallback: 기존 log_file_path
            log_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")
            if log_path and Path(log_path).exists():
                return Path(log_path)
        except redis.ConnectionError:
            pass
        return None

    def tail_log_file(self, runner_id: str, n_lines: int = 100) -> LogResponse:
        """로그 파일 끝에서 N줄 읽기 (초기 로드용)."""
        log_file = self._find_current_log(runner_id)

        if log_file and log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = deque(f, maxlen=n_lines)
                    if lines:
                        return LogResponse(
                            lines=[line.rstrip('\n') for line in lines],
                            total_lines=len(lines)
                        )
            except Exception as e:
                return LogResponse(
                    lines=[f"Error reading log: {str(e)}"],
                    total_lines=1
                )

        return LogResponse(lines=[], total_lines=0)

    async def stream_log_file(self, runner_id: str) -> AsyncGenerator[str, None]:
        """Redis Pub/Sub 기반 실시간 로그 스트리밍 (SSE 형식)"""
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

        # 초기 연결 이벤트 — EventSource가 MIME type 검증을 통과하도록 보장
        yield "event: connected\ndata: ok\n\n"

        pubsub = None
        last_heartbeat = time.monotonic()
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 5

        while True:
            try:
                if pubsub is None:
                    pubsub = self.async_redis.pubsub()
                    await pubsub.subscribe(log_channel)

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.5
                )
                if message and message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                    last_heartbeat = time.monotonic()
                    consecutive_errors = 0
                else:
                    now = time.monotonic()
                    if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                        yield ": heartbeat\n\n"
                        last_heartbeat = now
                    await asyncio.sleep(0.3)

            except (redis.ConnectionError, aioredis.ConnectionError, ConnectionError, OSError):
                if pubsub:
                    try:
                        await pubsub.unsubscribe(log_channel)
                        await pubsub.aclose()
                    except AttributeError:
                        try:
                            await pubsub.close()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    pubsub = None
                yield "event: redis_disconnected\ndata: Redis not available\n\n"
                last_heartbeat = time.monotonic()
                await asyncio.sleep(5)

            except Exception as e:
                consecutive_errors += 1
                if pubsub:
                    try:
                        await pubsub.unsubscribe(log_channel)
                        await pubsub.aclose()
                    except AttributeError:
                        try:
                            await pubsub.close()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    pubsub = None
                last_heartbeat = time.monotonic()

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    yield "event: stream_error\ndata: Too many consecutive errors, stream stopped\n\n"
                    return

                yield f"data: [Stream error #{consecutive_errors}: {str(e)}]\n\n"
                await asyncio.sleep(5)


    def _get_log_dir(self) -> Path:
        """로그 디렉토리 경로 반환 (config.LOG_DIR 기준, wtools 절대경로로 보정)"""
        log_dir = config.LOG_DIR
        if not log_dir.is_absolute():
            log_dir = config.WTOOLS_BASE_DIR / log_dir
        return log_dir

    def get_run_history(self, limit: int = 20, offset: int = 0) -> RunHistoryResponse:
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
                # runner_id 추출: plan-runner-stream-{8hex}-*.log
                m = re.match(r"plan-runner-stream-([0-9a-f]{8})-", fname)
                if not m:
                    continue
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

                runs[runner_id] = RunHistoryItem(
                    runner_id=runner_id,
                    plan_file=None,
                    engine=None,
                    status="completed",
                    pid=None,
                    start_time=start_time,
                    end_time=None,
                    log_file=str(path),
                    has_log=True,
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
            pattern = str(log_dir / f"plan-runner-stream-{runner_id}-*.log")
            matches = glob.glob(pattern)
            if matches:
                log_file = Path(sorted(matches)[-1])  # 가장 최신 파일

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

    def run_diagnostics(self) -> dict:
        """파이프라인 진단 (1회성) — 4단계 순차 점검"""
        steps = []

        # 1. Redis 연결
        try:
            self.redis_client.ping()
            steps.append({"step": 1, "name": "Redis 연결", "ok": True, "detail": "연결됨"})
        except Exception:
            steps.append({"step": 1, "name": "Redis 연결", "ok": False, "detail": "연결 실패"})
            return {"steps": steps}

        # 2. Listener heartbeat
        hb = self.redis_client.get("plan-runner:listener:heartbeat")
        steps.append({
            "step": 2, "name": "Listener heartbeat", "ok": hb is not None,
            "detail": "활성" if hb else "heartbeat 키 없음 (리스너 꺼짐)"
        })

        # 3. 로그 파일 — 첫 번째 active runner 기준
        log_path = None
        runner_ids = self.redis_client.smembers(ACTIVE_RUNNERS_KEY)
        if runner_ids:
            first_id = next(iter(runner_ids))
            log_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{first_id}:stream_log_path")
            if not log_path:
                log_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{first_id}:log_file_path")

        if log_path and Path(log_path).exists():
            size = Path(log_path).stat().st_size
            steps.append({
                "step": 3, "name": "로그 파일", "ok": True,
                "detail": f"{Path(log_path).name} ({size:,}B)"
            })
        elif log_path:
            steps.append({
                "step": 3, "name": "로그 파일", "ok": False,
                "detail": f"경로 있으나 파일 없음: {log_path}"
            })
        else:
            steps.append({
                "step": 3, "name": "로그 파일", "ok": False,
                "detail": "stream_log_path / log_file_path 키 없음"
            })

        # 4. CLI 프로세스 — active runners 수 기준
        if runner_ids:
            steps.append({"step": 4, "name": "CLI 프로세스", "ok": True, "detail": f"{len(runner_ids)} runner(s) active"})
        else:
            steps.append({
                "step": 4, "name": "CLI 프로세스", "ok": False,
                "detail": "미실행"
            })

        return {"steps": steps}


# 싱글톤 인스턴스
log_service = LogService()

__all__ = ['log_service', 'LogService']
