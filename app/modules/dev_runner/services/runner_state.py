"""Runner 상태 관리 — PID 검증, stale cleanup, force cleanup, dismiss"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

from app.config import logger

# 모듈 전용 logger (테스트에서 caplog로 캡처 가능)
_module_logger = logging.getLogger("app.modules.dev_runner.services.executor_service")
from app.modules.dev_runner.services.plan_path_resolver import (
    PathRuleError,
    resolve_plan_target,
)
from app.modules.dev_runner.services.plan_service import plan_service
from app.modules.dev_runner.services.redis_connection import (
    ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL,
    RUNNER_KEY_PREFIX, RUNNER_KEY_SUFFIXES,
)


class RunnerState:
    """Runner Redis 상태 관리 (PID 보정, stale/force cleanup, dismiss)."""

    def __init__(self, async_redis, runner_key_fn, is_pid_alive_fn=None, force_cleanup_fn=None):
        """async_redis: aioredis 클라이언트, runner_key_fn: (rid, suffix) -> str 함수."""
        self.async_redis = async_redis
        self._runner_key = runner_key_fn
        self._is_pid_alive_fn = is_pid_alive_fn or self._is_pid_alive
        self._force_cleanup_fn = force_cleanup_fn or self._force_cleanup_state

    def _is_pid_alive(self, pid: int) -> bool:
        """PID가 실제로 살아있는지 확인 (Windows: GetExitCodeProcess로 검증)"""
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            STILL_ACTIVE = 259
            exit_code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return exit_code.value == STILL_ACTIVE
        except Exception:
            return False

    async def _correct_pid_state(
        self, rid: str, status: str, pid_str: str | None, caller: str = ""
    ) -> tuple[bool, str | None]:
        """PID 기반 양방향 보정 공통 메서드.

        Bug 2: status="running" 인데 PID dead → _force_cleanup_state 호출 + (False, None)
        Bug 1: status≠"running" 인데 PID alive → Redis 복원 + (True, pid_str)
        completed 가드: status="completed" + PID alive → 오보정 방지, 그대로 반환
        """
        if not pid_str:
            return (status == "running", pid_str)
        running = status == "running"
        try:
            pid_int = int(pid_str)
            pid_alive = self._is_pid_alive_fn(pid_int)  # noqa: E501 (injected or default)
            if running and not pid_alive:
                logger.warning(
                    f"[dev-runner] {caller}: runner {rid} PID {pid_str} 종료됨 → stale 정리"
                )
                await self._force_cleanup_fn(rid)
                return (False, None)
            elif not running and pid_alive:
                if status == "completed":
                    return (running, pid_str)
                logger.warning(
                    f"[dev-runner] {caller}: runner {rid} PID {pid_str} alive but status={status!r} → 복원"
                )
                await self.async_redis.set(self._runner_key(rid, "status"), "running")
                await self.async_redis.sadd(ACTIVE_RUNNERS_KEY, rid)
                return (True, pid_str)
            return (running, pid_str)
        except (ValueError, Exception) as e:
            logger.debug(
                f"[dev-runner] {caller}: PID 보정 실패 (무시, rid={rid}): {e}"
            )
            return (running, pid_str)

    async def _force_cleanup_state(self, runner_id: str = ""):
        """Redis 상태 강제 정리 (listener 무응답 시 fallback)

        종료된 runner는 즉시 삭제하지 않고 RECENT_RUNNERS_KEY에 보존하여
        다른 클라이언트에서도 탭을 복원할 수 있도록 한다.

        방어 로직: status 키가 없는 runner (listener가 이미 정리 완료)는 RECENT에 등록하지 않는다.
        이를 통해 listener cleanup 후 API cleanup이 중복 호출될 때 plan_file=None 유령 탭 생성을 방지.
        """
        try:
            if runner_id:
                _module_logger.info(f"[dev-runner] force_cleanup_state 시작: {runner_id}")
                existing_status = await self.async_redis.get(self._runner_key(runner_id, "status"))
                if existing_status is None:
                    _module_logger.debug(f"[dev-runner] status 키 없음: {runner_id} — RECENT 등록 스킵")
                    await self.async_redis.srem(ACTIVE_RUNNERS_KEY, runner_id)
                    return
                await self.async_redis.set(self._runner_key(runner_id, "status"), "stopped")
                pipe = self.async_redis.pipeline()
                for key_suffix in RUNNER_KEY_SUFFIXES:
                    pipe.expire(self._runner_key(runner_id, key_suffix), RECENT_RUNNERS_TTL)
                pipe.srem(ACTIVE_RUNNERS_KEY, runner_id)
                pipe.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})
                await pipe.execute()
                plan_service.invalidate_plans_cache()
                _module_logger.info(f"[dev-runner] force_cleanup_state 완료: {runner_id} RECENT 이동")
            else:
                runner_ids = await self.async_redis.smembers(ACTIVE_RUNNERS_KEY)
                stop_ts = time.time()
                for rid in runner_ids:
                    existing_status = await self.async_redis.get(self._runner_key(rid, "status"))
                    if existing_status is None:
                        await self.async_redis.srem(ACTIVE_RUNNERS_KEY, rid)
                        continue
                    await self.async_redis.set(self._runner_key(rid, "status"), "stopped")
                    pipe = self.async_redis.pipeline()
                    for key_suffix in RUNNER_KEY_SUFFIXES:
                        pipe.expire(self._runner_key(rid, key_suffix), RECENT_RUNNERS_TTL)
                    pipe.zadd(RECENT_RUNNERS_KEY, {rid: stop_ts})
                    await pipe.execute()
                await self.async_redis.delete(ACTIVE_RUNNERS_KEY)
                plan_service.invalidate_plans_cache()
        except Exception:
            pass

    async def cleanup_stale_runners(self) -> Dict:
        """active_runners + recent_runners 중 stale 항목을 정리.

        Returns:
            {"cleaned_active": int, "cleaned_recent": int, "bugs": int, "total": int}
        """
        cleaned_active = 0
        cleaned_recent = 0
        bugs = 0
        cleaned_active_ids: set = set()

        try:
            runner_ids = await self.async_redis.smembers(ACTIVE_RUNNERS_KEY)
        except Exception:
            runner_ids = set()

        for rid in runner_ids:
            pid_str = await self.async_redis.get(self._runner_key(rid, "pid"))
            should_clean = False
            if not pid_str:
                should_clean = True
            else:
                try:
                    pid = int(pid_str)
                    if not self._is_pid_alive_fn(pid):
                        should_clean = True
                except ValueError:
                    should_clean = True

            if should_clean:
                _module_logger.warning(f"[dev-runner] stale active runner 발견: {rid} — 정리 시작")
                await self._force_cleanup_state(rid)
                cleaned_active_ids.add(rid)
                cleaned_active += 1

        try:
            recent_ids = await self.async_redis.zrange(RECENT_RUNNERS_KEY, 0, -1)
        except Exception:
            recent_ids = []

        now = datetime.now()
        GRACE_SECONDS = 600

        for rid in recent_ids:
            if rid in cleaned_active_ids:
                continue
            plan_file = await self.async_redis.get(self._runner_key(rid, "plan_file"))

            if plan_file and Path(plan_file).exists():
                continue

            reason = None
            if plan_file:
                try:
                    target = resolve_plan_target(plan_file, purpose="archive")
                    if Path(target.target).exists():
                        reason = "archived"
                    else:
                        reason = "file_lost"
                except PathRuleError:
                    # 규칙 해석 실패 경로는 보수적으로 file_lost 취급
                    reason = "file_lost"
            else:
                reason = "file_lost"

            status = await self.async_redis.get(self._runner_key(rid, "status"))
            start_time_str = await self.async_redis.get(self._runner_key(rid, "start_time"))

            if status == "running" and reason == "file_lost":
                if start_time_str:
                    try:
                        start_time = datetime.fromisoformat(start_time_str)
                        elapsed = (now - start_time).total_seconds()
                        if elapsed < GRACE_SECONDS:
                            continue
                    except ValueError:
                        pass

            for key_suffix in RUNNER_KEY_SUFFIXES:
                await self.async_redis.delete(self._runner_key(rid, key_suffix))
            await self.async_redis.zrem(RECENT_RUNNERS_KEY, rid)
            await self.async_redis.srem(ACTIVE_RUNNERS_KEY, rid)
            cleaned_recent += 1

            if reason == "file_lost":
                bugs += 1
                logger.warning(f"[dev-runner] cleanup: runner {rid} plan 파일 소실 (file_lost)")

        total = cleaned_active + cleaned_recent
        if total:
            logger.info(f"[dev-runner] cleanup_stale_runners: active={cleaned_active}, recent={cleaned_recent}, bugs={bugs}")

        return {
            "cleaned_active": cleaned_active,
            "cleaned_recent": cleaned_recent,
            "bugs": bugs,
            "total": total,
        }

    async def dismiss_runner(self, runner_id: str) -> bool:
        """종료된 runner를 탭에서 제거 (RECENT_RUNNERS_KEY에서 삭제 + per-runner 키 즉시 삭제)"""
        try:
            await self.async_redis.zrem(RECENT_RUNNERS_KEY, runner_id)
            for key_suffix in RUNNER_KEY_SUFFIXES:
                await self.async_redis.delete(self._runner_key(runner_id, key_suffix))
            await self.async_redis.srem(ACTIVE_RUNNERS_KEY, runner_id)
            return True
        except Exception:
            return False
