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

from sqlalchemy import text

import redis
import redis.asyncio as aioredis
from fastapi import HTTPException

from app.config import logger
from app.modules.dev_runner.config import config
from app.modules.dev_runner.services.plan_service import plan_service
from app.modules.dev_runner.services.settings_service import settings_service
from app.modules.dev_runner.services.visibility import is_visible_runner
from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse
from app.modules.dev_runner.services.state import get_state
from app.modules.dev_runner.services.redis_connection import (
    RedisConnection,
    REDIS_HOST, REDIS_PORT, REDIS_DB,
    COMMANDS_KEY, RESULTS_KEY, RUNNER_KEY_PREFIX,
    ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL,
    COMMAND_TIMEOUT, RUNNER_KEY_SUFFIXES,
)
from app.modules.dev_runner.services.runner_state import RunnerState

# re-export: 기존 ~70개 테스트 파일의 from ...executor_service import ACTIVE_RUNNERS_KEY 경로 유지
__all__ = [
    "executor_service", "ExecutorService",
    "ACTIVE_RUNNERS_KEY", "RECENT_RUNNERS_KEY", "RUNNER_KEY_PREFIX",
    "RECENT_RUNNERS_TTL", "RUNNER_KEY_SUFFIXES",
    "COMMANDS_KEY", "RESULTS_KEY", "COMMAND_TIMEOUT",
]


class ExecutorService:
    """plan-runner CLI 실행 서비스 - Redis 기반 크로스 세션"""

    def __init__(self):
        """Redis 클라이언트 초기화"""
        self.conn = RedisConnection()
        self.redis_client = self.conn.redis_client
        self.async_redis = self.conn.async_redis
        self.state = RunnerState(self.async_redis, self._runner_key,
                                  self._is_pid_alive, self._force_cleanup_state)

    def reconnect(self):
        """환경변수를 반영하여 Redis 클라이언트를 재연결합니다."""
        self.conn.reconnect()
        self.redis_client = self.conn.redis_client
        self.async_redis = self.conn.async_redis
        self.state = RunnerState(self.async_redis, self._runner_key,
                                  self._is_pid_alive, self._force_cleanup_state)

    async def _check_redis_and_listener(self):
        """Redis 연결 + command listener 존재 여부 사전 확인"""
        try:
            await self.async_redis.ping()
        except (redis.ConnectionError, ConnectionRefusedError, OSError):
            raise HTTPException(
                status_code=503,
                detail="Redis에 연결할 수 없습니다. Redis 서버가 실행 중인지 확인하세요."
            )
        heartbeat = await self.async_redis.get("plan-runner:listener:heartbeat")
        if heartbeat is None:
            raise HTTPException(
                status_code=503,
                detail="dev-runner command listener가 실행 중이지 않습니다. 워커를 시작하세요."
            )

    def _fix_orphan_workflows(self, db, rid: str, running: bool, status: str) -> bool:
        """실행 중이 아닌 runner의 DB 워크플로우를 failed로 원자 업데이트. orphan 발견 시 True 반환."""
        if running:
            return False
        try:
            result = db.execute(
                text(
                    "UPDATE workflows SET status='failed', error_message=:msg "
                    "WHERE runner_id=:rid AND status IN ('running', 'merge_pending')"
                ),
                {"msg": f"orphan auto-fix: runner {rid} status={status!r}", "rid": rid},
            )
            db.commit()
            is_orphan = result.rowcount > 0
            if is_orphan:
                logger.warning(
                    f"[dev-runner] orphan workflow 자동 정리: runner {rid} "
                    f"({result.rowcount}건 → failed)"
                )
            return is_orphan
        except Exception as e:
            logger.warning(f"[dev-runner] orphan workflow 자동 정리 실패 (무시): {e}")
            db.rollback()
            return False

    def _runner_key(self, rid: str, suffix: str) -> str:
        return f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}"

    @staticmethod
    def _is_codex_preflight_failure(engine: str | None, fix_engine: str | None, message: str) -> bool:
        """codex 사전검증/가용성 실패 메시지 여부."""
        codex_requested = (engine == "codex") or (fix_engine == "codex")
        if not codex_requested:
            return False

        msg = (message or "").lower()
        # accepted 이후 plan 단계에서 발생하는 runtime 오류는 preflight(422)가 아니다.
        runtime_markers = (
            "model_reasoning_effort",
            "unknown variant",
            "auto_plan_failed",
            "plan_agent_failed",
        )
        if any(marker in msg for marker in runtime_markers):
            return False

        preflight_markers = (
            "preflight",
            "실행파일",
            "인증 실패",
            "authentication",
            "unauthorized",
            "not logged in",
            "token",
            "login",
            "설정 불일치",
        )
        return any(marker in msg for marker in preflight_markers)

    @staticmethod
    def resolve_run_engines(request: RunRequest, settings) -> tuple[str, str]:
        """요청값 > settings 기본값 > claude 규칙으로 engine/fix_engine 해석."""
        def _normalize(value: object) -> str | None:
            if isinstance(value, str):
                normalized = value.strip()
                return normalized or None
            return None

        fallback_engine = _normalize(getattr(settings, "default_engine", None)) or "claude"
        fallback_fix_engine = _normalize(getattr(settings, "default_fix_engine", None)) or "claude"

        resolved_engine = _normalize(request.engine) or fallback_engine
        resolved_fix_engine = _normalize(request.fix_engine) or fallback_fix_engine

        return resolved_engine, resolved_fix_engine

    async def _get_runner_fields(self, rid: str, *fields: str) -> dict:
        result = {}
        for f in fields:
            result[f] = await self.async_redis.get(self._runner_key(rid, f))
        return result

    async def _send_command(self, command: dict, timeout: int = COMMAND_TIMEOUT) -> dict | None:
        """Redis 명령 전송 공통 메서드 — LPUSH + BRPOP + delete + parse 패턴.

        command에 command_id가 없으면 자동 부여.
        타임아웃 시 result_key 삭제 후 None 반환.
        정상 시 JSON 파싱된 dict 반환.
        """
        if "command_id" not in command:
            command = {**command, "command_id": uuid.uuid4().hex[:8]}
        result_key = f"{RESULTS_KEY}:{command['command_id']}"
        await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))
        result = await self.async_redis.brpop(result_key, timeout=timeout)
        await self.async_redis.delete(result_key)
        if result is None:
            return None
        _, raw = result
        return json.loads(raw)

    async def start_dev_runner(self, request: RunRequest) -> RunStatusResponse:
        """plan-runner 실행 시작 - Redis 명령 전송 (비동기, 멀티 runner 지원)"""
        # Redis + listener 사전 확인
        await self._check_redis_and_listener()

        # stale runner 정리 (dead PID 항목을 제거하여 429 방지)
        await self.cleanup_stale_runners()

        # 동시 실행 개수 제한 확인
        count = await self.async_redis.scard(ACTIVE_RUNNERS_KEY)
        settings = settings_service.get()
        if count >= settings.max_concurrent_runners:
            raise HTTPException(
                status_code=429,
                detail=f"최대 {settings.max_concurrent_runners}개 동시 실행 가능 (현재 {count}개)"
            )

        resolved_engine, resolved_fix_engine = self.resolve_run_engines(request, settings)

        # 새 runner_id 생성 (멀티 실행 지원 - 409 체크 없음)
        # test_source가 있으면 TC 추적용 접두사 포함 (t-{source}-{4hex})
        if request.test_source:
            _src = re.sub(r'[^a-zA-Z0-9_]', '', request.test_source)[:20]
            runner_id = f"t-{_src}-{uuid.uuid4().hex[:4]}"
        else:
            runner_id = uuid.uuid4().hex[:8]

        # trigger 판별: test_source 있으면 tc:{name}, 없으면 explicit trigger or "api"
        if request.test_source:
            trigger = f"tc:{request.test_source}"
        else:
            trigger = request.trigger or "api"

        # Redis 명령 생성
        command = {
            "action": "run",
            "runner_id": runner_id,
            "source": "monitor-page-api",
            "trigger": trigger,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(
            f"[dev-runner] Request engine={request.engine}, fix_engine={request.fix_engine} "
            f"-> resolved engine={resolved_engine}, fix_engine={resolved_fix_engine}, runner_id={runner_id}"
        )

        if request.plan_file:
            if "docs/archive/" in request.plan_file.replace("\\", "/"):
                raise HTTPException(status_code=400, detail="archived plan은 실행할 수 없습니다")
            command["plan_file"] = request.plan_file

        command["engine"] = resolved_engine
        command["fix_engine"] = resolved_fix_engine

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

        try:
            result_data = await self._send_command(command)
            if result_data is None:
                await self._cleanup_runner_state(runner_id, reason="start_timeout")
                raise HTTPException(
                    status_code=504,
                    detail="Command timeout - listener may not be responding"
                )

            if not result_data.get("success"):
                message = result_data.get("message", "Failed to start")
                if self._is_codex_preflight_failure(resolved_engine, resolved_fix_engine, message):
                    raise HTTPException(
                        status_code=422,
                        detail=message,
                    )
                raise HTTPException(
                    status_code=500,
                    detail=message,
                )

            # Redis에서 per-runner 상태 조회
            fields = await self._get_runner_fields(runner_id, "pid", "plan_file", "start_time")
            pid = fields["pid"]
            plan_file = fields["plan_file"]
            start_time_str = fields["start_time"]

            return RunStatusResponse(
                running=True,
                runner_id=runner_id,
                engine=resolved_engine,
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

    def _sync_state(self):
        """state를 on-demand 생성하고 async_redis/fn들을 현재 값으로 동기화 (테스트 mock 지원)."""
        if not hasattr(self, 'state') or self.state is None:
            self.state = RunnerState(self.async_redis, self._runner_key,
                                     self._is_pid_alive, self._force_cleanup_state)
        else:
            if self.state.async_redis is not self.async_redis:
                self.state.async_redis = self.async_redis
            self.state._is_pid_alive_fn = self._is_pid_alive
            self.state._force_cleanup_fn = self._force_cleanup_state

    async def _correct_pid_state(
        self, rid: str, status: str, pid_str: str | None, caller: str = ""
    ) -> tuple[bool, str | None]:
        self._sync_state()
        return await self.state._correct_pid_state(rid, status, pid_str, caller)

    async def _force_cleanup_state(self, runner_id: str = ""):
        self._sync_state()
        await self.state._force_cleanup_state(runner_id)

    async def _cleanup_runner_state(self, runner_id: str, reason: str) -> None:
        """timeout/예외/stop 경로 공통 정리 함수."""
        try:
            await self._force_cleanup_state(runner_id)
        except Exception as exc:
            logger.warning(
                "[dev-runner] 상태 정리 실패 (runner_id=%s, reason=%s): %s",
                runner_id,
                reason,
                exc,
            )

    async def _send_force_stop(self, runner_id: str = ""):
        """listener에 force-stop 명령 전송 (_running_processes 변수까지 정리)"""
        try:
            command = {
                "action": "force-stop",
                "runner_id": runner_id,
                "source": "monitor-page-api-reset",
                "timestamp": datetime.now().isoformat(),
            }
            result = await self._send_command(command, timeout=5)
            if result is not None:
                logger.info(f"[dev-runner] force-stop 결과: {result.get('message', '')}")
                return True
            else:
                logger.warning("[dev-runner] force-stop 타임아웃 (listener 무응답)")
                return False
        except Exception as e:
            logger.warning(f"[dev-runner] force-stop 전송 실패: {e}")
            return False

    async def cleanup_stale_runners(self) -> Dict:
        """active_runners + recent_runners 중 stale 항목을 정리 (RunnerState 위임)."""
        self._sync_state()
        return await self.state.cleanup_stale_runners()

    async def _cleanup_stale_runners(self) -> Dict:
        """cleanup_stale_runners 의 내부 alias (테스트 호환용)."""
        return await self.cleanup_stale_runners()

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
            status = await self.async_redis.get(self._runner_key(runner_id, "status"))
            if status != "running":
                # stale 상태 정리: active_runners set에서 제거
                await self.async_redis.srem(ACTIVE_RUNNERS_KEY, runner_id)
                raise HTTPException(status_code=404, detail="Not running")

            # Redis 명령 생성
            command = {
                "action": "stop",
                "runner_id": runner_id,
                "source": "monitor-page-api",
                "timestamp": datetime.now().isoformat(),
            }

            result_data = await self._send_command(command)
            if result_data is None:
                # listener 무응답 → 프로세스가 죽었을 가능성 → 상태 강제 정리
                logger.warning("[dev-runner] listener 무응답, Redis 상태 강제 정리")
                await self._cleanup_runner_state(runner_id, reason="stop_timeout")
                return {"message": "Force cleaned (listener not responding)"}

            if not result_data.get("success"):
                # stop 실패해도 상태 정리
                await self._cleanup_runner_state(runner_id, reason="stop_command_failed")
                return {"message": f"Force cleaned: {result_data.get('message', '')}"}

            return {"message": "Stopped successfully"}

        except redis.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="Redis connection failed - command listener may not be running"
            )
        except json.JSONDecodeError:
            await self._cleanup_runner_state(runner_id, reason="stop_invalid_response")
            return {"message": "Force cleaned (invalid listener response)"}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[dev-runner] stop 실패: {traceback.format_exc()}")
            await self._cleanup_runner_state(runner_id, reason="stop_exception")
            raise HTTPException(status_code=500, detail=f"Failed to stop: {str(e)}")

    async def get_runner_status(self, runner_id: str) -> RunStatusResponse:
        """특정 runner 상태 조회 (per-runner Redis 키 기반)"""
        data = await self._get_runner_fields(runner_id, "status", "pid", "plan_file", "start_time", "engine")
        status = data["status"]
        pid_str = data["pid"]
        plan_file = data["plan_file"]
        start_time_str = data["start_time"]
        engine = data["engine"] or "claude"
        running = status == "running"

        running, pid_str = await self._correct_pid_state(runner_id, status, pid_str, caller="get_runner_status")

        current_cycle_str = await self.async_redis.get(self._runner_key(runner_id, "current_cycle"))
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
                    d = await self._get_runner_fields(rid, "status", "pid", "plan_file", "engine",
                                                      "start_time", "worktree_path", "merge_status",
                                                      "branch", "trigger", "exit_reason")
                    status = d["status"]
                    pid_str = d["pid"]
                    plan_file = d["plan_file"]
                    engine = d["engine"]
                    start_time_str = d["start_time"]
                    worktree_path = d["worktree_path"]
                    merge_status = d["merge_status"]
                    branch = d["branch"]
                    trigger = d["trigger"]
                    exit_reason = d["exit_reason"]
                    if branch is None and worktree_path:
                        branch = f"runner/{rid}"
                    start_time = None
                    if start_time_str:
                        try:
                            start_time = datetime.fromisoformat(start_time_str)
                        except ValueError:
                            pass
                    # PID 기반 양방향 보정: Redis status와 실제 프로세스 상태 불일치 교정
                    running = status == "running"
                    running, pid_str = await self._correct_pid_state(rid, status, pid_str, caller="get_all_runners")

                    # orphan: runner가 실행 중이 아닌데 DB에 running/merge_pending 워크플로우가 있는 경우
                    is_orphan = self._fix_orphan_workflows(db, rid, running, status)
                    # visibility.py 단일 함수로 판별 (화이트리스트 + 이중 방어)
                    is_user = is_visible_runner(trigger, rid)
                    result.append(RunnerListItem(
                        runner_id=rid,
                        running=running,
                        plan_file=plan_file,
                        engine=engine,
                        start_time=start_time,
                        pid=int(pid_str) if pid_str else None,
                        worktree_path=worktree_path,
                        branch=branch,
                        merge_status=merge_status,
                        trigger=trigger,
                        visible=is_user,
                        orphan=is_orphan,
                        exit_reason=exit_reason,
                    ))
                return result
            finally:
                db.close()
        except (redis.ConnectionError, aioredis.ConnectionError):
            return []

    async def dismiss_runner(self, runner_id: str) -> bool:
        self._sync_state()
        return await self.state.dismiss_runner(runner_id)

    def _is_pid_alive(self, pid: int) -> bool:
        return self.state._is_pid_alive(pid)

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

    async def get_merge_status(self, runner_id: str) -> dict | None:
        """runner Redis 키에서 merge_status 조회"""
        try:
            status = await self.async_redis.get(self._runner_key(runner_id, "merge_status"))
            if status is None:
                return None
            return {"runner_id": runner_id, "status": status, "test_passed": None, "fix_attempts": 0, "message": ""}
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

        command = {
            "action": action,
            "runner_id": runner_id,
            "source": "monitor-page-api",
            "timestamp": datetime.now().isoformat(),
        }
        if extra:
            command.update(extra)
        result_data = await self._send_command(command)
        if result_data is None:
            return {"success": False, "message": "Command timeout"}
        return result_data

    async def send_direct_merge_command(self, branch: str, worktree_path: str | None, plan_file: str | None) -> dict:
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
