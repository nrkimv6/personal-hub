"""subprocess 실행 서비스 - Redis 기반 크로스 세션 실행"""

import json
import re
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
from app.core.config import PROJECT_ROOT
from app.modules.dev_runner.config import config
from app.modules.dev_runner.services.plan_service import plan_service
from app.modules.claude_worker.services.profile_store import (
    get_selected as get_selected_profile,
    get_by_name as get_profile_by_name,
    SUPPORTED_ENGINES as PROFILE_SUPPORTED_ENGINES,
)
from app.modules.claude_worker.services.profile_env import ENGINE_ENV_KEYS
from app.modules.dev_runner.services.plan_path_resolver import is_archive_or_history_path
from app.modules.dev_runner.services.settings_service import settings_service
from app.modules.dev_runner.services.visibility import is_visible_runner
from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse
from app.modules.dev_runner.services.state import get_state
from app.modules.dev_runner.services.redis_connection import (
    RedisConnection,
    REDIS_HOST, REDIS_PORT, REDIS_DB,
    COMMANDS_KEY, RESULTS_KEY, RUNNER_KEY_PREFIX,
    ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL, MAX_RECENT_RUNNERS,
    COMMAND_TIMEOUT, RUNNER_KEY_SUFFIXES,
    SESSION_ID_KEY_PREFIX,
)
from app.modules.dev_runner.services.runner_state import RunnerState
from app.modules.dev_runner.services.merge_service import MergeService

# re-export: 기존 ~70개 테스트 파일의 from ...executor_service import ACTIVE_RUNNERS_KEY 경로 유지
__all__ = [
    "executor_service", "ExecutorService",
    "MergeService",
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
        self.merge = MergeService(self.async_redis, self._runner_key, self._send_command)

    def reconnect(self):
        """환경변수를 반영하여 Redis 클라이언트를 재연결합니다."""
        self.conn.reconnect()
        self.redis_client = self.conn.redis_client
        self.async_redis = self.conn.async_redis
        self.state = RunnerState(self.async_redis, self._runner_key,
                                  self._is_pid_alive, self._force_cleanup_state)
        self.merge = MergeService(self.async_redis, self._runner_key, self._send_command)

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

    @staticmethod
    def _resolve_profile(engine: str, profile_name: str | None) -> dict:
        """engine + profile_name으로 profile env 정보 resolve.

        Args:
            engine: 실행 엔진 이름
            profile_name: 프로필 이름 (None → 전역 선택 프로필)

        Returns:
            profile 관련 env dict:
              {"profile": str, "profile_env_key": str|None,
               "profile_config_dir": str|None, "profile_extra_env": dict}
            engine이 PROFILE_SUPPORTED_ENGINES에 없으면 빈 dict 반환

        Raises:
            ValueError: profile_name 지정 시 해당 프로필이 없으면 전파
        """
        if engine not in PROFILE_SUPPORTED_ENGINES:
            logger.warning(
                f"[profile] engine={engine!r}는 프로필 미지원 (지원: {sorted(PROFILE_SUPPORTED_ENGINES)}), 스킵"
            )
            return {}

        if profile_name:
            profile = get_profile_by_name(engine, profile_name)
        else:
            profile = get_selected_profile(engine)

        env_key = ENGINE_ENV_KEYS.get(engine)  # e.g. "CLAUDE_CONFIG_DIR" or None
        return {
            "profile": profile.name,
            "profile_env_key": env_key,
            "profile_config_dir": profile.config_dir,
            "profile_extra_env": profile.extra_env or {},
        }

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
        max_concurrent_runners = getattr(settings, "max_concurrent_runners", config.MAX_CONCURRENT_RUNNERS)
        if count >= max_concurrent_runners:
            raise HTTPException(
                status_code=429,
                detail=f"최대 {max_concurrent_runners}개 동시 실행 가능 (현재 {count}개)"
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

        # session_id: 유효한 UUID면 사용, 없거나 잘못된 형식이면 자동 발급
        raw_session_id = (request.session_id or "").strip()
        if raw_session_id:
            try:
                uuid.UUID(raw_session_id)
                session_id = raw_session_id
            except ValueError:
                logger.warning(f"[session] invalid session_id format={raw_session_id!r}, issuing new UUID")
                session_id = str(uuid.uuid4())
        else:
            session_id = str(uuid.uuid4())

        # plan_records에 claude_session_id 저장 (plan_file 기반 조회)
        if request.plan_file:
            try:
                from app.database import SessionLocal
                from app.modules.dev_runner.services.plan_record_service import PlanRecordService
                _db = SessionLocal()
                try:
                    _svc = PlanRecordService(_db)
                    _record = _svc.get_or_create(request.plan_file)
                    _svc.update_claude_session_id(_record.id, session_id)
                finally:
                    _db.close()
            except Exception as _e:
                logger.warning(f"[session] plan_record claude_session_id 저장 실패: {_e}")

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
            if is_archive_or_history_path(request.plan_file):
                raise HTTPException(status_code=400, detail="archived plan은 실행할 수 없습니다")
            command["plan_file"] = request.plan_file

        command["engine"] = resolved_engine
        command["fix_engine"] = resolved_fix_engine

        # profile resolve — ValueError → 400 (프로필 미존재)
        try:
            profile_data = self._resolve_profile(resolved_engine, request.profile)
            command.update(profile_data)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

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

        # fused 세션 ID 주입
        command["session_id"] = session_id
        if request.fused_session:
            command["fused_session"] = True

        logger.info(
            f"[session] runner_id={runner_id} session_id={session_id} fused={request.fused_session}"
        )

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
            # session_id를 Redis에 저장 (TTL 24h)
            await self.async_redis.set(
                f"{SESSION_ID_KEY_PREFIX}{runner_id}", session_id, ex=86400
            )

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

            # 기존 워커에 attach된 경우 → 기존 runner_id로 상태 반환
            if result_data.get("status") == "attached":
                existing_id = result_data["runner_id"]
                fields = await self._get_runner_fields(existing_id, "pid", "plan_file", "start_time", "execution_count", "engine")
                existing_pid = fields.get("pid")
                existing_start_time_str = fields.get("start_time")
                existing_engine = fields.get("engine") or resolved_engine
                existing_exec_count_raw = fields.get("execution_count")
                existing_exec_count = None
                if existing_exec_count_raw is not None:
                    try:
                        existing_exec_count = int(existing_exec_count_raw)
                    except (TypeError, ValueError):
                        existing_exec_count = None
                # 같은 runner_id로 중복 start 시 기존 session_id 재사용 (정책: 세션 연속성 유지)
                existing_session_id = await self.async_redis.get(f"{SESSION_ID_KEY_PREFIX}{existing_id}")
                if not existing_session_id:
                    logger.warning(
                        f"[session] attached runner_id={existing_id} session_id not found in Redis, issuing new UUID"
                    )
                    existing_session_id = str(uuid.uuid4())
                return RunStatusResponse(
                    running=True,
                    runner_id=existing_id,
                    attached=True,
                    engine=existing_engine,
                    pid=int(existing_pid) if existing_pid else None,
                    plan_file=fields.get("plan_file") or request.plan_file,
                    start_time=datetime.fromisoformat(existing_start_time_str) if existing_start_time_str else None,
                    current_cycle=0,
                    execution_count=existing_exec_count,
                    listener_alive=True,
                    redis_connected=True,
                    session_id=existing_session_id,
                )

            # Redis에서 per-runner 상태 조회
            fields = await self._get_runner_fields(runner_id, "pid", "plan_file", "start_time", "execution_count")
            pid = fields["pid"]
            plan_file = fields["plan_file"]
            start_time_str = fields["start_time"]
            execution_count_raw = fields["execution_count"]
            execution_count = None
            if execution_count_raw is not None:
                try:
                    execution_count = int(execution_count_raw)
                except (TypeError, ValueError):
                    execution_count = None

            return RunStatusResponse(
                running=True,
                runner_id=runner_id,
                engine=resolved_engine,
                pid=int(pid) if pid else None,
                plan_file=plan_file or request.plan_file,
                start_time=datetime.fromisoformat(start_time_str) if start_time_str else None,
                current_cycle=0,
                execution_count=execution_count,
                listener_alive=True,
                redis_connected=True,
                session_id=session_id,
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

    def _sync_merge(self):
        """merge를 on-demand 생성하고 async_redis/fn들을 현재 값으로 동기화 (테스트 mock 지원)."""
        if not hasattr(self, "merge") or self.merge is None:
            self.merge = MergeService(self.async_redis, self._runner_key, self._send_command)
        else:
            if self.merge.async_redis is not self.async_redis:
                self.merge.async_redis = self.async_redis
            self.merge._runner_key = self._runner_key
            self.merge._send_command = self._send_command

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
        data = await self._get_runner_fields(
            runner_id, "status", "pid", "plan_file", "start_time", "engine", "execution_count"
        )
        status = data["status"]
        pid_str = data["pid"]
        plan_file = data["plan_file"]
        start_time_str = data["start_time"]
        engine = data["engine"] or "claude"
        execution_count_raw = data["execution_count"]
        running = status == "running"

        running, pid_str = await self._correct_pid_state(runner_id, status, pid_str, caller="get_runner_status")

        current_cycle_str = await self.async_redis.get(self._runner_key(runner_id, "current_cycle"))
        current_cycle = int(current_cycle_str) if current_cycle_str is not None else None
        execution_count = None
        if execution_count_raw is not None:
            try:
                execution_count = int(execution_count_raw)
            except (TypeError, ValueError):
                execution_count = None

        # session_id 조회: 없으면 None (기존 runner 하위 호환)
        session_id = await self.async_redis.get(f"{SESSION_ID_KEY_PREFIX}{runner_id}")

        return RunStatusResponse(
            runner_id=runner_id,
            running=running,
            engine=engine,
            pid=int(pid_str) if pid_str else None,
            plan_file=plan_file,
            start_time=datetime.fromisoformat(start_time_str) if start_time_str else None,
            current_cycle=current_cycle,
            execution_count=execution_count,
            listener_alive=True,
            redis_connected=True,
            session_id=session_id,
        )

    async def get_all_runners(self) -> list:
        """활성 runner + 최근 종료 runner 목록 조회 (탭 복원 지원)"""
        from app.modules.dev_runner.schemas import RunnerListItem
        try:
            # TTL 만료 recent runner 정리: trigger=user/user:all는 dismiss 전까지 보존
            cutoff_ts = time.time() - RECENT_RUNNERS_TTL
            expired_entries = await self.async_redis.zrangebyscore(RECENT_RUNNERS_KEY, "-inf", cutoff_ts)
            for rid in expired_entries:
                trigger = await self.async_redis.get(self._runner_key(rid, "trigger"))
                if is_visible_runner(trigger, rid):
                    # user/user:all: 만료되어도 dismiss 전까지 보존
                    continue
                await self.async_redis.zrem(RECENT_RUNNERS_KEY, rid)
            # sorted set 크기 상한: invisible 정리 후 oldest-first로 MAX_RECENT_RUNNERS 초과분 제거
            await self.async_redis.zremrangebyrank(RECENT_RUNNERS_KEY, 0, -(MAX_RECENT_RUNNERS + 1))

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
                                                      "start_time", "execution_count", "worktree_path", "merge_status",
                                                      "branch", "trigger", "exit_reason", "stop_stage", "error")
                    status = d["status"]
                    pid_str = d["pid"]
                    plan_file = d["plan_file"]
                    engine = d["engine"]
                    start_time_str = d["start_time"]
                    execution_count_raw = d["execution_count"]
                    worktree_path = d["worktree_path"]
                    merge_status = d["merge_status"]
                    branch = d["branch"]
                    trigger = d["trigger"]
                    # trigger 미존재 시 recent-meta fallback (cleanup 후 타이밍 이슈 방어)
                    if trigger is None:
                        try:
                            _recent_meta_raw = await self.async_redis.get(f"plan-runner:recent-meta:{rid}")
                            if _recent_meta_raw:
                                import json as _json
                                _recent_meta = _json.loads(_recent_meta_raw)
                                trigger = _recent_meta.get("trigger")
                        except Exception:
                            pass
                    exit_reason = d["exit_reason"]
                    stop_stage = d["stop_stage"]
                    error = d["error"]
                    if branch is None and worktree_path:
                        branch = f"runner/{rid}"
                    start_time = None
                    if start_time_str:
                        try:
                            start_time = datetime.fromisoformat(start_time_str)
                        except ValueError:
                            pass
                    execution_count = None
                    if execution_count_raw is not None:
                        try:
                            execution_count = int(execution_count_raw)
                        except (TypeError, ValueError):
                            execution_count = None
                    # PID 기반 양방향 보정: Redis status와 실제 프로세스 상태 불일치 교정
                    running = status == "running"
                    running, pid_str = await self._correct_pid_state(rid, status, pid_str, caller="get_all_runners")

                    # orphan: runner가 실행 중이 아닌데 DB에 running/merge_pending 워크플로우가 있는 경우
                    is_orphan = self._fix_orphan_workflows(db, rid, running, status)
                    # visibility.py 단일 함수로 판별 (화이트리스트 + 이중 방어)
                    is_user = is_visible_runner(trigger, rid)
                    # plan_file 소실 시 worktree_path/branch에서 fallback 이름 추출
                    display_plan_name: str | None = None
                    if not plan_file:
                        if worktree_path:
                            display_plan_name = Path(worktree_path).name
                        elif branch:
                            display_plan_name = branch.split("/")[-1] if "/" in branch else branch
                    result.append(RunnerListItem(
                        runner_id=rid,
                        running=running,
                        plan_file=plan_file,
                        engine=engine,
                        start_time=start_time,
                        execution_count=execution_count,
                        pid=int(pid_str) if pid_str else None,
                        worktree_path=worktree_path,
                        branch=branch,
                        merge_status=merge_status,
                        trigger=trigger,
                        visible=is_user,
                        orphan=is_orphan,
                        exit_reason=exit_reason,
                        stop_stage=stop_stage,
                        error=error,
                        display_plan_name=display_plan_name,
                    ))
                return result
            finally:
                db.close()
        except (redis.ConnectionError, aioredis.ConnectionError):
            raise

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


    # ------------------------------------------------------------------
    # Merge 위임 래퍼 (deprecation shim) — 실제 구현은 self.merge (MergeService)
    # 기존 호출자(라우트, 테스트) 호환 유지용
    # ------------------------------------------------------------------

    async def get_merge_queue(self) -> list:
        """[deprecated shim] → self.merge.get_merge_queue()"""
        self._sync_merge()
        return await self.merge.get_merge_queue()

    async def get_merge_queue_length(self) -> int:
        """[deprecated shim] → self.merge.get_merge_queue_length()"""
        self._sync_merge()
        return await self.merge.get_merge_queue_length()

    async def get_merge_status(self, runner_id: str) -> dict | None:
        """[deprecated shim] → self.merge.get_merge_status()"""
        self._sync_merge()
        return await self.merge.get_merge_status(runner_id)

    async def get_merge_history(self, limit: int = 50) -> list:
        """[deprecated shim] → self.merge.get_merge_history()"""
        self._sync_merge()
        return await self.merge.get_merge_history(limit)

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
        """[deprecated shim] → self.merge.send_direct_merge_command()"""
        self._sync_merge()
        return await self.merge.send_direct_merge_command(branch, worktree_path, plan_file)

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
        """command-listener에 graceful-exit 시그널을 보내 재시작합니다.

        Session 0(SYSTEM)에서 직접 subprocess를 spawn하지 않고,
        Redis LPUSH로 graceful-exit 명령을 전달합니다.
        dev-runner-command-listener가 명령을 수신하면 clean exit하고,
        Session 1에서 실행 중인 watchdog가 자동으로 재시작합니다.

        1. Redis LPUSH로 graceful-exit 명령 전송
        2. heartbeat가 "restarting"으로 변경될 때까지 대기 (최대 5초)
        3. heartbeat가 정상 ISO 타임스탬프로 복구될 때까지 대기 (최대 15초)
        """
        HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
        baseline_heartbeat = self.redis_client.get(HEARTBEAT_KEY)
        command_id = uuid.uuid4().hex[:8]
        result_key = f"{RESULTS_KEY}:{command_id}"

        try:
            self.redis_client.lpush(
                COMMANDS_KEY,
                json.dumps({
                    "command_id": command_id,
                    "action": "graceful-exit",
                    "source": "restart-listener-api",
                    "timestamp": datetime.now().isoformat(),
                }),
            )
            result = self.redis_client.brpop(result_key, timeout=10)
        finally:
            try:
                self.redis_client.delete(result_key)
            except Exception:
                pass

        if result is None:
            return {"success": False, "message": "listener graceful-exit 명령 결과를 10초 내 받지 못했습니다."}

        _key, raw_result = result
        try:
            command_result = json.loads(raw_result)
        except (TypeError, json.JSONDecodeError):
            return {"success": False, "message": f"listener graceful-exit 결과 파싱 실패: {raw_result!r}"}

        if not command_result.get("success", False):
            return {
                "success": False,
                "message": str(command_result.get("message") or "listener graceful-exit failed"),
            }

        # 단계 1: heartbeat → "restarting" 또는 baseline에서 변경 대기 (최대 5초)
        saw_restarting = False
        saw_transition = False
        deadline = time.time() + 5
        while time.time() < deadline:
            hb = self.redis_client.get(HEARTBEAT_KEY)
            hb_str = hb.decode() if isinstance(hb, bytes) else (hb or "")
            if hb_str == "restarting":
                saw_restarting = True
                saw_transition = True
                break
            if hb_str and hb_str != baseline_heartbeat:
                saw_transition = True
                break
            time.sleep(0.5)

        # 단계 2: heartbeat → 정상 ISO 타임스탬프 복구 대기 (최대 15초)
        # restarting을 놓친 케이스도 허용하되, command_result 성공 후 fresh heartbeat가 확인되면 성공으로 본다.
        deadline = time.time() + 15
        while time.time() < deadline:
            hb = self.redis_client.get(HEARTBEAT_KEY)
            hb_str = hb.decode() if isinstance(hb, bytes) else (hb or "")
            if hb_str and hb_str != "restarting":
                if saw_transition or hb_str != baseline_heartbeat:
                    return {"success": True, "message": "listener restarted"}
            time.sleep(0.5)

        if saw_restarting:
            return {
                "success": False,
                "message": "listener restart signaled but heartbeat did not recover within 15s",
            }

        # 일부 실환경에서는 restarting 마커를 매우 짧게 지나가므로,
        # graceful-exit 명령이 처리되었고 listener heartbeat가 계속 살아 있으면 성공으로 간주한다.
        current_heartbeat = self.redis_client.get(HEARTBEAT_KEY)
        current_hb_str = current_heartbeat.decode() if isinstance(current_heartbeat, bytes) else (current_heartbeat or "")
        if current_hb_str:
            return {"success": True, "message": "listener restarted"}

        return {"success": False, "message": "listener heartbeat not recovered within 15s after graceful-exit"}


# 싱글톤 인스턴스
executor_service = ExecutorService()
