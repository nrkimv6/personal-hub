"""subprocess 실행 서비스 - Redis 기반 크로스 세션 실행"""

import json
import os
import re
import signal
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict

import redis
import redis.asyncio as aioredis
from fastapi import HTTPException

from app.config import logger
from app.modules.dev_runner.config import config
from app.modules.dev_runner.services.settings_service import settings_service
from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse
from app.modules.dev_runner.services.state import get_state

# Redis 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = int(os.environ.get("PLAN_RUNNER_REDIS_DB", "0"))
COMMANDS_KEY = "plan-runner:commands"
RESULTS_KEY = "plan-runner:command_results"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"  # sorted set: score=종료 timestamp
RECENT_RUNNERS_TTL = 3600  # 1시간 (초) — cleanup 후 분석용 보관 (변경: 86400→3600)
COMMAND_TIMEOUT = 30  # 명령 결과 대기 타임아웃 (초) — worktree 생성 시간 고려
# per-runner 키 suffix 전체 목록 (listener와 공유되는 단일 진실 원천)
# scripts/dev-runner-command-listener.py도 동일 상수를 별도 정의하여 참조
RUNNER_KEY_SUFFIXES = (
    "status", "pid", "plan_file", "start_time", "log_file_path", "stream_log_path",
    "engine", "fix_engine", "worktree_path", "branch", "merge_status", "merge_requested",
    "current_cycle", "quota_stopped", "error", "restart_after_merge", "test_source",
)


class ExecutorService:
    """plan-runner CLI 실행 서비스 - Redis 기반 크로스 세션"""

    def __init__(self):
        """Redis 클라이언트 초기화"""
        self.reconnect()

    def reconnect(self):
        """환경변수를 반영하여 Redis 클라이언트를 재연결합니다."""
        # 상수 재갱신 (테스트에서 os.environ 변경 시 반영을 위함)
        global REDIS_DB
        REDIS_DB = int(os.environ.get("PLAN_RUNNER_REDIS_DB", "0"))

        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
        )
        # 비동기 클라이언트 (brpop 등 블로킹 호출용)
        self.async_redis = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=COMMAND_TIMEOUT + 5,  # BRPOP 무한 대기 방지
        )
        logger.info(f"[executor-service] Redis 재연결 완료 (db={REDIS_DB})")

    async def _check_redis_and_listener(self):
        """Redis 연결 + command listener 존재 여부 사전 확인"""
        try:
            await self.async_redis.ping()
        except (redis.ConnectionError, ConnectionRefusedError, OSError):
            raise HTTPException(
                status_code=503,
                detail="Redis에 연결할 수 없습니다. Redis 서버가 실행 중인지 확인하세요."
            )

        # listener 프로세스 존재 확인: listener가 주기적으로 갱신하는 heartbeat 키 체크
        heartbeat = await self.async_redis.get("plan-runner:listener:heartbeat")
        if heartbeat is None:
            raise HTTPException(
                status_code=503,
                detail="dev-runner command listener가 실행 중이지 않습니다. 워커를 시작하세요."
            )

    async def _cleanup_stale_runners(self) -> int:
        """active_runners 중 PID가 없거나 죽어있는 stale 항목을 정리.

        listener 재연결 실패 등으로 고아 상태가 된 runner를 제거하여
        start_dev_runner()의 429 에러를 방지한다.

        Returns:
            정리된 stale runner 수
        """
        try:
            runner_ids = await self.async_redis.smembers(ACTIVE_RUNNERS_KEY)
        except Exception:
            return 0

        cleaned = 0
        for rid in runner_ids:
            pid_str = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:pid")
            if not pid_str:
                # PID 정보 없음 → stale
                await self._force_cleanup_state(rid)
                cleaned += 1
                continue
            try:
                pid = int(pid_str)
            except ValueError:
                await self._force_cleanup_state(rid)
                cleaned += 1
                continue
            if not self._is_pid_alive(pid):
                await self._force_cleanup_state(rid)
                cleaned += 1

        if cleaned:
            logger.info(f"[dev-runner] stale 정리: {cleaned}개 제거")
        return cleaned

    async def cleanup_stale_runners(self) -> Dict:
        """active_runners + recent_runners 중 stale 항목 일괄 정리 (API 엔드포인트용).

        Phase 1: ACTIVE_RUNNERS_KEY 순회 → PID 죽은 runner → _force_cleanup_state → cleaned_active 카운트
        Phase 2: RECENT_RUNNERS_KEY 순회 → plan_file 없거나 파일시스템에 없는 경우 → 정리 → cleaned_recent 카운트
                  단, Phase 1에서 이미 정리한 ID는 스킵 (cleaned_active_ids 세트로 판별)

        Returns:
            {"cleaned_active": int, "cleaned_recent": int, "bugs": int}
        """
        cleaned_active = 0
        cleaned_recent = 0
        bugs = 0
        cleaned_active_ids: set = set()

        try:
            # Phase 1: active runners 정리 (dead PID)
            try:
                runner_ids = await self.async_redis.smembers(ACTIVE_RUNNERS_KEY)
            except Exception:
                runner_ids = []

            for rid in runner_ids:
                pid_str = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:pid")
                should_clean = False
                if not pid_str:
                    should_clean = True
                else:
                    try:
                        pid = int(pid_str)
                        if not self._is_pid_alive(pid):
                            should_clean = True
                    except ValueError:
                        should_clean = True
                if should_clean:
                    await self._force_cleanup_state(rid)
                    cleaned_active_ids.add(rid)
                    cleaned_active += 1

            # Phase 2: recent runners 정리 (stale 항목)
            try:
                recent_ids = await self.async_redis.zrange(RECENT_RUNNERS_KEY, 0, -1)
            except Exception:
                recent_ids = []

            for rid in recent_ids:
                plan_file = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file")
                if plan_file and Path(plan_file).exists():
                    continue
                # plan_file 없거나 파일시스템에 없는 경우 → 정리 대상
                status = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:status")
                if status == "running":
                    # 아직 실행 중인 runner는 건드리지 않음
                    bugs += 1
                    continue
                await self.async_redis.zrem(RECENT_RUNNERS_KEY, rid)
                for key_suffix in RUNNER_KEY_SUFFIXES:
                    await self.async_redis.delete(f"{RUNNER_KEY_PREFIX}:{rid}:{key_suffix}")
                cleaned_recent += 1

        except Exception:
            logger.error(f"[dev-runner] cleanup_stale_runners 실패: {traceback.format_exc()}")

        if cleaned_active or cleaned_recent:
            logger.info(f"[dev-runner] cleanup_stale_runners: active={cleaned_active}, recent={cleaned_recent}, bugs={bugs}")

        return {"cleaned_active": cleaned_active, "cleaned_recent": cleaned_recent, "bugs": bugs}

    async def start_dev_runner(self, request: RunRequest) -> RunStatusResponse:
        """plan-runner 실행 시작 - Redis 명령 전송 (비동기, 멀티 runner 지원)"""
        # Redis + listener 사전 확인
        await self._check_redis_and_listener()

        # stale runner 정리 (dead PID 항목을 제거하여 429 방지)
        await self._cleanup_stale_runners()

        # 동시 실행 개수 제한 확인
        count = await self.async_redis.scard(ACTIVE_RUNNERS_KEY)
        settings = settings_service.get()
        if count >= settings.max_concurrent_runners:
            raise HTTPException(
                status_code=429,
                detail=f"최대 {settings.max_concurrent_runners}개 동시 실행 가능 (현재 {count}개)"
            )

        # 새 runner_id 생성 (멀티 실행 지원 - 409 체크 없음)
        # test_source가 있으면 TC 추적용 접두사 포함 (t-{source}-{4hex})
        if request.test_source:
            _src = re.sub(r'[^a-zA-Z0-9_]', '', request.test_source)[:20]
            runner_id = f"t-{_src}-{uuid.uuid4().hex[:4]}"
        else:
            runner_id = uuid.uuid4().hex[:8]

        # per-command 결과 키 (레이스 컨디션 방지)
        command_id = uuid.uuid4().hex[:8]

        # Redis 명령 생성
        command = {
            "action": "run",
            "runner_id": runner_id,
            "command_id": command_id,
            "source": "monitor-page-api",
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(f"[dev-runner] Request engine: {request.engine}, runner_id: {runner_id}")

        if request.plan_file:
            if "docs/archive/" in request.plan_file.replace("\\", "/"):
                raise HTTPException(status_code=400, detail="archived plan은 실행할 수 없습니다")
            command["plan_file"] = request.plan_file

        if request.engine:
            command["engine"] = request.engine

        if request.fix_engine:
            command["fix_engine"] = request.fix_engine

        # 옵션 추가
        if request.max_cycles is not None:
            command["max_cycles"] = request.max_cycles

        if request.max_tokens is not None:
            command["max_tokens"] = request.max_tokens

        if request.until:
            command["until"] = request.until

        if request.dry_run:
            command["dry_run"] = True

        if request.skip_plan:
            command["skip_plan"] = True

        if request.parallel:
            command["parallel"] = True

        if request.projects:
            command["projects"] = request.projects

        if request.worktree:
            command["worktree"] = True

        if request.pipeline:
            command["pipeline"] = request.pipeline

        if request.test_source:
            command["test_source"] = request.test_source

        # registered_paths에서 wtools 외부 경로 추출 (asyncio.to_thread로 이벤트 루프 블로킹 방지)
        if request.parallel:
            import asyncio
            from app.modules.dev_runner.services.plan_service import plan_service
            extra_dirs = await asyncio.to_thread(plan_service.get_extra_plan_dirs)
            if extra_dirs:
                command["extra_plan_dirs"] = ",".join(extra_dirs)
            ignored_paths = await asyncio.to_thread(plan_service.get_ignored_plan_paths)
            if ignored_paths:
                command["ignored_plans"] = ",".join(ignored_paths)

        result_key = f"{RESULTS_KEY}:{command_id}"

        try:
            # Redis LPUSH - 명령 전송
            await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))

            # BRPOP으로 결과 대기 (per-command 키, 레이스 컨디션 방지)
            result = await self.async_redis.brpop(result_key, timeout=COMMAND_TIMEOUT)

            if result is None:
                # cleanup
                await self.async_redis.delete(result_key)
                await self._force_cleanup_state(runner_id)
                raise HTTPException(
                    status_code=504,
                    detail="Command timeout - listener may not be responding"
                )

            _, raw_result = result
            await self.async_redis.delete(result_key)
            result_data = json.loads(raw_result)

            if not result_data.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail=result_data.get("message", "Failed to start")
                )

            # Redis에서 per-runner 상태 조회
            pid = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
            plan_file = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
            start_time_str = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time")

            return RunStatusResponse(
                running=True,
                runner_id=runner_id,
                engine=request.engine,
                pid=int(pid) if pid else None,
                plan_file=plan_file or request.plan_file,
                start_time=datetime.fromisoformat(start_time_str) if start_time_str else None,
                current_cycle=0,
                listener_alive=True,
                redis_connected=True,
            )

        except redis.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="Redis connection failed - command listener may not be running"
            )
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Invalid response from listener: {str(e)}"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[dev-runner] start 실패: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to start: {str(e)}")

    async def _force_cleanup_state(self, runner_id: str = ""):
        """Redis 상태 강제 정리 (listener 무응답 시 fallback)

        종료된 runner는 즉시 삭제하지 않고 RECENT_RUNNERS_KEY에 보존하여
        다른 클라이언트에서도 탭을 복원할 수 있도록 한다.

        방어 로직: status 키가 없는 runner (listener가 이미 정리 완료)는 RECENT에 등록하지 않는다.
        이를 통해 listener cleanup 후 API cleanup이 중복 호출될 때 plan_file=None 유령 탭 생성을 방지.
        """
        try:
            if runner_id:
                existing_status = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
                if existing_status is None:
                    # listener가 이미 cleanup 완료 (키 삭제됨) → RECENT 등록 스킵
                    await self.async_redis.srem(ACTIVE_RUNNERS_KEY, runner_id)
                    return
                await self.async_redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
                pipe = self.async_redis.pipeline()
                for key_suffix in RUNNER_KEY_SUFFIXES:
                    full_key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{key_suffix}"
                    pipe.expire(full_key, RECENT_RUNNERS_TTL)
                pipe.srem(ACTIVE_RUNNERS_KEY, runner_id)
                pipe.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})
                await pipe.execute()
            else:
                runner_ids = await self.async_redis.smembers(ACTIVE_RUNNERS_KEY)
                stop_ts = time.time()
                for rid in runner_ids:
                    existing_status = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:status")
                    if existing_status is None:
                        # listener가 이미 cleanup 완료 → RECENT 등록 스킵, ACTIVE만 정리
                        await self.async_redis.srem(ACTIVE_RUNNERS_KEY, rid)
                        continue
                    await self.async_redis.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
                    pipe = self.async_redis.pipeline()
                    for key_suffix in RUNNER_KEY_SUFFIXES:
                        full_key = f"{RUNNER_KEY_PREFIX}:{rid}:{key_suffix}"
                        pipe.expire(full_key, RECENT_RUNNERS_TTL)
                    pipe.zadd(RECENT_RUNNERS_KEY, {rid: stop_ts})
                    await pipe.execute()
                await self.async_redis.delete(ACTIVE_RUNNERS_KEY)
        except Exception:
            pass

    async def _send_force_stop(self, runner_id: str = ""):
        """listener에 force-stop 명령 전송 (_running_processes 변수까지 정리)"""
        try:
            command_id = uuid.uuid4().hex[:8]
            command = {
                "action": "force-stop",
                "runner_id": runner_id,
                "command_id": command_id,
                "source": "monitor-page-api-reset",
                "timestamp": datetime.now().isoformat(),
            }
            result_key = f"{RESULTS_KEY}:{command_id}"
            await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))
            # 결과 대기 (짧은 타임아웃)
            result = await self.async_redis.brpop(result_key, timeout=5)
            await self.async_redis.delete(result_key)
            if result:
                _, raw = result
                data = json.loads(raw)
                logger.info(f"[dev-runner] force-stop 결과: {data.get('message', '')}")
                return True
            else:
                logger.warning("[dev-runner] force-stop 타임아웃 (listener 무응답)")
                return False
        except Exception as e:
            logger.warning(f"[dev-runner] force-stop 전송 실패: {e}")
            return False

    async def reset_running_state(self, full_reset: bool = False) -> Dict:
        """RUNNING 상태 강제 초기화 - Redis 정리만 수행"""
        try:
            # 0. listener에 force-stop 전송 (메모리 내 _running_processes 정리)
            await self._send_force_stop()

            # 1. Redis 상태 정리 (모든 runner)
            await self._force_cleanup_state()
            logger.info("[dev-runner] Redis 상태 정리 완료")

            return {"success": True, "reset_count": 0, "full_reset": full_reset}

        except Exception as e:
            logger.error(f"[dev-runner] reset_running_state 실패: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to reset state: {str(e)}")

    async def stop_dev_runner(self, runner_id: str) -> Dict:
        """plan-runner 실행 중지 - Redis 명령 전송 (비동기)"""
        try:
            # Redis 사전 확인 (ping만 — listener는 stop 시에는 없을 수도 있음)
            try:
                await self.async_redis.ping()
            except (redis.ConnectionError, ConnectionRefusedError, OSError):
                raise HTTPException(
                    status_code=503,
                    detail="Redis에 연결할 수 없습니다."
                )

            # Redis를 통해 해당 runner 상태 확인
            status = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
            if status != "running":
                # stale 상태 정리: active_runners set에서 제거
                await self.async_redis.srem(ACTIVE_RUNNERS_KEY, runner_id)
                raise HTTPException(status_code=404, detail="Not running")

            # per-command 결과 키
            command_id = uuid.uuid4().hex[:8]

            # Redis 명령 생성
            command = {
                "action": "stop",
                "runner_id": runner_id,
                "command_id": command_id,
                "source": "monitor-page-api",
                "timestamp": datetime.now().isoformat(),
            }
            result_key = f"{RESULTS_KEY}:{command_id}"

            # Redis LPUSH - 명령 전송
            await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))

            # BRPOP으로 결과 대기 (per-command 키)
            result = await self.async_redis.brpop(result_key, timeout=COMMAND_TIMEOUT)

            if result is None:
                # listener 무응답 → 프로세스가 죽었을 가능성 → 상태 강제 정리
                logger.warning("[dev-runner] listener 무응답, Redis 상태 강제 정리")
                await self.async_redis.delete(result_key)
                await self._force_cleanup_state(runner_id)
                return {"message": "Force cleaned (listener not responding)"}

            _, raw_result = result
            await self.async_redis.delete(result_key)
            result_data = json.loads(raw_result)

            if not result_data.get("success"):
                # stop 실패해도 상태 정리
                await self._force_cleanup_state(runner_id)
                return {"message": f"Force cleaned: {result_data.get('message', '')}"}

            return {"message": "Stopped successfully"}

        except redis.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="Redis connection failed - command listener may not be running"
            )
        except json.JSONDecodeError:
            await self._force_cleanup_state(runner_id)
            return {"message": "Force cleaned (invalid listener response)"}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[dev-runner] stop 실패: {traceback.format_exc()}")
            await self._force_cleanup_state(runner_id)
            raise HTTPException(status_code=500, detail=f"Failed to stop: {str(e)}")

    async def get_runner_status(self, runner_id: str) -> RunStatusResponse:
        """특정 runner 상태 조회 (per-runner Redis 키 기반)"""
        status = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
        pid_str = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
        plan_file = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        start_time_str = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time")
        engine = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine") or "claude"
        running = status == "running"

        # PID stale 감지
        if running and pid_str and not self._is_pid_alive(int(pid_str)):
            logger.warning(f"[dev-runner] runner {runner_id} PID {pid_str} 종료됨 → stale 정리")
            await self._force_cleanup_state(runner_id)
            running = False
            pid_str = None

        current_cycle_str = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:current_cycle")
        current_cycle = int(current_cycle_str) if current_cycle_str is not None else None

        return RunStatusResponse(
            runner_id=runner_id,
            running=running,
            engine=engine,
            pid=int(pid_str) if pid_str else None,
            plan_file=plan_file,
            start_time=datetime.fromisoformat(start_time_str) if start_time_str else None,
            current_cycle=current_cycle,
            listener_alive=True,
            redis_connected=True,
        )

    async def get_all_runners(self) -> list:
        """활성 runner + 최근 종료 runner 목록 조회 (탭 복원 지원)"""
        from app.modules.dev_runner.schemas import RunnerListItem
        try:
            # 24시간 이상 된 최근 종료 runner 자동 정리
            cutoff_ts = time.time() - RECENT_RUNNERS_TTL
            await self.async_redis.zremrangebyscore(RECENT_RUNNERS_KEY, "-inf", cutoff_ts)

            # ACTIVE_RUNNERS_KEY + RECENT_RUNNERS_KEY 합집합으로 runner 목록 구성
            active_ids = await self.async_redis.smembers(ACTIVE_RUNNERS_KEY)
            recent_ids_with_scores = await self.async_redis.zrange(RECENT_RUNNERS_KEY, 0, -1)
            all_ids = set(active_ids) | set(recent_ids_with_scores)

            # orphan 판별을 위한 DB 세션
            from app.database import SessionLocal
            from app.models.workflow import Workflow
            db = SessionLocal()
            try:
                result = []
                for rid in all_ids:
                    status = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:status")
                    pid_str = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:pid")
                    plan_file = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file")
                    engine = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:engine")
                    start_time_str = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:start_time")
                    worktree_path = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:worktree_path")
                    merge_status = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:merge_status")
                    branch = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:branch")
                    if branch is None and worktree_path:
                        branch = f"runner/{rid}"
                    start_time = None
                    if start_time_str:
                        try:
                            start_time = datetime.fromisoformat(start_time_str)
                        except ValueError:
                            pass
                    # orphan: runner가 실행 중이 아닌데 DB에 running/merge_pending 워크플로우가 있는 경우
                    is_orphan = False
                    if status != "running":
                        orphan_wf = db.query(Workflow).filter(
                            Workflow.runner_id == rid,
                            Workflow.status.in_(["running", "merge_pending"])
                        ).first()
                        if orphan_wf:
                            is_orphan = True
                    result.append(RunnerListItem(
                        runner_id=rid,
                        running=status == "running",
                        plan_file=plan_file,
                        engine=engine,
                        start_time=start_time,
                        pid=int(pid_str) if pid_str else None,
                        worktree_path=worktree_path,
                        branch=branch,
                        merge_status=merge_status,
                        orphan=is_orphan,
                    ))
                return result
            finally:
                db.close()
        except (redis.ConnectionError, aioredis.ConnectionError):
            return []

    async def dismiss_runner(self, runner_id: str) -> bool:
        """종료된 runner를 탭에서 제거 (RECENT_RUNNERS_KEY에서 삭제 + per-runner 키 즉시 삭제)"""
        try:
            # RECENT_RUNNERS_KEY에서 제거
            await self.async_redis.zrem(RECENT_RUNNERS_KEY, runner_id)
            # per-runner 키 즉시 삭제
            for key_suffix in RUNNER_KEY_SUFFIXES:
                await self.async_redis.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:{key_suffix}")
            # ACTIVE_RUNNERS_KEY에서도 제거 (혹시 남아있다면)
            await self.async_redis.srem(ACTIVE_RUNNERS_KEY, runner_id)
            return True
        except Exception:
            return False

    def _is_pid_alive(self, pid: int) -> bool:
        """PID가 실제로 살아있는지 확인 (Windows: GetExitCodeProcess로 검증)"""
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            # OpenProcess는 종료된 프로세스도 핸들을 반환할 수 있으므로
            # GetExitCodeProcess로 실제 생존 여부 확인
            STILL_ACTIVE = 259
            exit_code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return exit_code.value == STILL_ACTIVE
        except Exception:
            return False

    async def get_process_status(self) -> RunStatusResponse:
        """프로세스 상태 조회 - 하위호환 (첫 번째 active runner 반환)"""
        try:
            # Redis 연결 확인
            try:
                await self.async_redis.ping()
            except (redis.ConnectionError, aioredis.ConnectionError, ConnectionRefusedError, OSError):
                return RunStatusResponse(running=False, listener_alive=False, redis_connected=False, pid=None, plan_file=None)

            heartbeat = await self.async_redis.get("plan-runner:listener:heartbeat")
            listener_alive = heartbeat is not None

            runner_ids = await self.async_redis.smembers(ACTIVE_RUNNERS_KEY)
            if runner_ids:
                first_id = next(iter(runner_ids))
                r = await self.get_runner_status(first_id)
                r.listener_alive = listener_alive
                return r

            # 실행 중인 runner 없음
            return RunStatusResponse(running=False, engine="claude", listener_alive=listener_alive, redis_connected=True, pid=None, plan_file=None)

        except (redis.ConnectionError, aioredis.ConnectionError):
            return RunStatusResponse(running=False, listener_alive=False, redis_connected=False, pid=None, plan_file=None)
        except Exception as e:
            logger.error(f"[dev-runner] status 조회 실패: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


    async def enqueue_merge(self, branch: str, plan_file: str = "", project: str = "monitor-page", worktree_path: str = "") -> dict:
        """[DEPRECATED] merge는 이제 _stream_output finally 블록에서 인라인으로 처리됨.

        이 메서드는 호환성 유지용으로 보존되지만 실제 merge 큐에 투입하지 않는다.
        merge_requested 플래그를 직접 설정하여 runner 완료 시 자동 merge가 트리거되게 한다.
        """
        return {"runner_id": "deprecated", "queued": False, "message": "enqueue_merge is deprecated. Use merge_requested flag on runner instead."}

    async def get_merge_queue(self) -> list:
        """merge 대기 큐 조회 → plan-runner:merge-wait-queue (merge lock 대기 중인 runner 목록)"""
        try:
            raw_items = await self.async_redis.lrange("plan-runner:merge-wait-queue", 0, -1)
            result = []
            for rid in raw_items:
                # runner별 Redis 키에서 상세 정보 조회
                plan_file = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file") or ""
                branch = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:branch") or ""
                worktree_path = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:worktree_path") or ""
                start_time_str = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:start_time") or ""
                result.append({
                    "runner_id": rid,
                    "branch": branch,
                    "plan_file": plan_file,
                    "project": "monitor-page",
                    "status": "waiting",
                    "timestamp": start_time_str,
                    "worktree_path": worktree_path,
                })
            return result
        except Exception:
            return []

    async def get_merge_status(self, runner_id: str) -> dict | None:
        """Redis merge:{runner_id}:status 조회"""
        try:
            status = await self.async_redis.get(f"plan-runner:merge:{runner_id}:status")
            if status is None:
                return None
            return {"runner_id": runner_id, "status": status, "fix_attempts": 0, "message": ""}
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

    async def send_runner_command(self, runner_id: str, action: str, extra: dict | None = None) -> dict:
        """runner에 명령 전송 (retry-merge, cleanup-worktree 등)

        extra: 추가 payload — command dict에 병합되어 Redis에 전송됨 (retry-merge Redis 키 재발급 등에 활용)
        """
        try:
            await self.async_redis.ping()
        except (redis.ConnectionError, ConnectionRefusedError, OSError):
            raise HTTPException(status_code=503, detail="Redis에 연결할 수 없습니다.")

        command_id = uuid.uuid4().hex[:8]
        command = {
            "action": action,
            "runner_id": runner_id,
            "command_id": command_id,
            "source": "monitor-page-api",
            "timestamp": datetime.now().isoformat(),
        }
        if extra:
            command.update(extra)
        result_key = f"{RESULTS_KEY}:{command_id}"
        await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))
        result = await self.async_redis.brpop(result_key, timeout=COMMAND_TIMEOUT)
        if result is None:
            await self.async_redis.delete(result_key)
            return {"success": False, "message": "Command timeout"}
        _, raw = result
        await self.async_redis.delete(result_key)
        return json.loads(raw)

    async def send_direct_merge_command(self, branch: str, worktree_path: str | None, plan_file: str | None) -> dict:
        """direct-merge 명령 전송 — runner_id 없이 branch/worktree만으로 머지 실행"""
        try:
            await self.async_redis.ping()
        except (redis.ConnectionError, ConnectionRefusedError, OSError):
            raise HTTPException(status_code=503, detail="Redis에 연결할 수 없습니다.")

        command_id = uuid.uuid4().hex[:8]
        command = {
            "action": "direct-merge",
            "branch": branch,
            "worktree_path": worktree_path,
            "plan_file": plan_file,
            "command_id": command_id,
            "source": "monitor-page-api",
            "timestamp": datetime.now().isoformat(),
        }
        result_key = f"{RESULTS_KEY}:{command_id}"
        await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))
        result = await self.async_redis.brpop(result_key, timeout=COMMAND_TIMEOUT)
        if result is None:
            await self.async_redis.delete(result_key)
            return {"success": False, "message": "Command timeout"}
        _, raw = result
        await self.async_redis.delete(result_key)
        return json.loads(raw)

    async def stop_all_runners(self) -> dict:
        """모든 active runner 일괄 중지 - asyncio.gather 병렬 호출"""
        import asyncio

        runners = await self.get_all_runners()
        runner_ids = [r.runner_id for r in runners if r.running]

        if not runner_ids:
            return {"stopped": 0}

        async def _stop_one(runner_id: str):
            try:
                await self.stop_dev_runner(runner_id)
                return True
            except Exception as e:
                logger.warning(f"[dev-runner] stop_all: runner {runner_id} 중지 실패: {e}")
                return False

        results = await asyncio.gather(*[_stop_one(rid) for rid in runner_ids], return_exceptions=False)
        stopped = sum(1 for r in results if r)
        return {"stopped": stopped}

    def restart_listener(self) -> dict:
        """command-listener 프로세스를 재시작합니다.

        1. Redis에서 기존 PID 조회 → 존재 시 SIGTERM 전송
        2. 새 listener 프로세스 spawn
        3. 최대 10초 동안 heartbeat 키 감지 대기
        """
        LISTENER_SCRIPT = Path(__file__).parent.parent.parent.parent / "scripts" / "dev-runner-command-listener.py"
        HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
        PID_KEY = "plan-runner:listener:pid"

        # 기존 PID 종료
        old_pid_str = self.redis_client.get(PID_KEY)
        if old_pid_str:
            try:
                old_pid = int(old_pid_str)
                if sys.platform == "win32":
                    os.kill(old_pid, signal.SIGTERM)
                else:
                    os.kill(old_pid, signal.SIGTERM)
                self.redis_client.delete(PID_KEY)
            except (ProcessLookupError, PermissionError):
                pass
            time.sleep(1)

        # 새 프로세스 spawn
        python_exe = sys.executable
        proc = subprocess.Popen(
            [python_exe, str(LISTENER_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # heartbeat 감지 대기 (최대 10초)
        deadline = time.time() + 10
        while time.time() < deadline:
            hb = self.redis_client.get(HEARTBEAT_KEY)
            if hb:
                return {"success": True, "new_pid": proc.pid, "message": "listener restarted"}
            time.sleep(0.5)

        return {"success": False, "new_pid": proc.pid, "message": "heartbeat not detected within 10s"}


# 싱글톤 인스턴스
executor_service = ExecutorService()

__all__ = ['executor_service', 'ExecutorService', 'ACTIVE_RUNNERS_KEY', 'RECENT_RUNNERS_KEY', 'RUNNER_KEY_PREFIX', 'RECENT_RUNNERS_TTL', 'RUNNER_KEY_SUFFIXES']
