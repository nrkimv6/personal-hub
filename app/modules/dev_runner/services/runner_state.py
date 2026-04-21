"""Runner ?곹깭 愿由???PID 寃利? stale cleanup, force cleanup, dismiss"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

from app.config import logger

# 紐⑤뱢 ?꾩슜 logger (?뚯뒪?몄뿉??caplog濡?罹≪쿂 媛??
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
from app.modules.dev_runner.services.visibility import is_visible_runner

# stopped user ?щ꼫 蹂댁〈 怨꾩빟: dismiss ?꾧퉴吏 ???ㅻ뱾? TTL ?놁씠 ?곴뎄 蹂댁〈
_PERSIST_SUFFIXES = frozenset({"plan_file", "branch", "trigger"})


class RunnerState:
    """Runner Redis ?곹깭 愿由?(PID 蹂댁젙, stale/force cleanup, dismiss)."""

    def __init__(self, async_redis, runner_key_fn, is_pid_alive_fn=None, force_cleanup_fn=None):
        """async_redis: aioredis ?대씪?댁뼵?? runner_key_fn: (rid, suffix) -> str ?⑥닔."""
        self.async_redis = async_redis
        self._runner_key = runner_key_fn
        self._is_pid_alive_fn = is_pid_alive_fn or self._is_pid_alive
        self._force_cleanup_fn = force_cleanup_fn or self._force_cleanup_state

    def _is_pid_alive(self, pid: int) -> bool:
        """PID媛 ?ㅼ젣濡??댁븘?덈뒗吏 ?뺤씤 (Windows: GetExitCodeProcess濡?寃利?"""
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
        """PID 湲곕컲 ?묐갑??蹂댁젙 怨듯넻 硫붿꽌??

        Bug 2: status="running" ?몃뜲 PID dead ??_force_cleanup_state ?몄텧 + (False, None)
        Bug 1: status??running" ?몃뜲 PID alive ??Redis 蹂듭썝 + (True, pid_str)
        completed 媛?? status="completed" + PID alive ???ㅻ낫??諛⑹?, 洹몃?濡?諛섑솚
        """
        if not pid_str:
            return (status == "running", pid_str)
        running = status == "running"
        try:
            pid_int = int(pid_str)
            pid_alive = self._is_pid_alive_fn(pid_int)  # noqa: E501 (injected or default)
            if running and not pid_alive:
                logger.warning(
                    f"[dev-runner] {caller}: runner {rid} PID {pid_str} 醫낅즺????stale ?뺣━"
                )
                await self._force_cleanup_fn(rid)
                return (False, None)
            elif not running and pid_alive:
                if status == "completed":
                    return (running, pid_str)
                logger.warning(
                    f"[dev-runner] {caller}: runner {rid} PID {pid_str} alive but status={status!r} ??蹂듭썝"
                )
                await self.async_redis.set(self._runner_key(rid, "status"), "running")
                await self.async_redis.sadd(ACTIVE_RUNNERS_KEY, rid)
                return (True, pid_str)
            return (running, pid_str)
        except (ValueError, Exception) as e:
            logger.debug(
                f"[dev-runner] {caller}: PID 蹂댁젙 ?ㅽ뙣 (臾댁떆, rid={rid}): {e}"
            )
            return (running, pid_str)

    async def _force_cleanup_state(self, runner_id: str = ""):
        """Redis ?곹깭 媛뺤젣 ?뺣━ (listener 臾댁쓳????fallback)

        醫낅즺??runner??利됱떆 ??젣?섏? ?딄퀬 RECENT_RUNNERS_KEY??蹂댁〈?섏뿬
        ?ㅻⅨ ?대씪?댁뼵?몄뿉?쒕룄 ??쓣 蹂듭썝?????덈룄濡??쒕떎.

        諛⑹뼱 濡쒖쭅: status ?ㅺ? ?녿뒗 runner (listener媛 ?대? ?뺣━ ?꾨즺)??RECENT???깅줉?섏? ?딅뒗??
        ?대? ?듯빐 listener cleanup ??API cleanup??以묐났 ?몄텧????plan_file=None ?좊졊 ???앹꽦??諛⑹?.
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
                # invisible runner(trigger 誘몄꽕??鍮꾩궗?⑹옄)??RECENT???깅줉?섏? ?딄퀬 ??利됱떆 ??젣
                trigger = await self.async_redis.get(self._runner_key(runner_id, "trigger"))
                if not is_visible_runner(trigger, runner_id):
                    _module_logger.debug(
                        f"[dev-runner] invisible runner ??RECENT ?ㅽ궢, ????젣: {runner_id} (trigger={trigger!r})"
                    )
                    pipe = self.async_redis.pipeline()
                    for key_suffix in RUNNER_KEY_SUFFIXES:
                        pipe.delete(self._runner_key(runner_id, key_suffix))
                    pipe.srem(ACTIVE_RUNNERS_KEY, runner_id)
                    await pipe.execute()
                    plan_service.invalidate_plans_cache()
                    return
                pipe = self.async_redis.pipeline()
                for key_suffix in RUNNER_KEY_SUFFIXES:
                    if key_suffix in _PERSIST_SUFFIXES:
                        # dismiss ?꾧퉴吏 ?곴뎄 蹂댁〈: plan_file/branch/trigger??TTL ?ㅼ젙 ????
                        pipe.persist(self._runner_key(runner_id, key_suffix))
                    else:
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
                    # invisible runner(trigger 誘몄꽕??鍮꾩궗?⑹옄)??RECENT???깅줉?섏? ?딄퀬 ??利됱떆 ??젣
                    trigger = await self.async_redis.get(self._runner_key(rid, "trigger"))
                    if not is_visible_runner(trigger, rid):
                        _module_logger.debug(
                            f"[dev-runner] invisible runner(諛곗튂) ??RECENT ?ㅽ궢, ????젣: {rid} (trigger={trigger!r})"
                        )
                        pipe = self.async_redis.pipeline()
                        for key_suffix in RUNNER_KEY_SUFFIXES:
                            pipe.delete(self._runner_key(rid, key_suffix))
                        pipe.srem(ACTIVE_RUNNERS_KEY, rid)
                        await pipe.execute()
                        continue
                    pipe = self.async_redis.pipeline()
                    for key_suffix in RUNNER_KEY_SUFFIXES:
                        if key_suffix in _PERSIST_SUFFIXES:
                            pipe.persist(self._runner_key(rid, key_suffix))
                        else:
                            pipe.expire(self._runner_key(rid, key_suffix), RECENT_RUNNERS_TTL)
                    pipe.zadd(RECENT_RUNNERS_KEY, {rid: stop_ts})
                    await pipe.execute()
                await self.async_redis.delete(ACTIVE_RUNNERS_KEY)
                plan_service.invalidate_plans_cache()
        except Exception:
            pass

    async def cleanup_stale_runners(self) -> Dict:
        """active_runners + recent_runners 以?stale ??ぉ???뺣━.

        Returns:
            {
                "cleaned_active": int,
                "cleaned_recent": int,
                "preserved_recent": int,
                "bugs": int,
                "total": int,
            }
        """
        cleaned_active = 0
        cleaned_recent = 0
        preserved_recent = 0
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
                _module_logger.warning(f"[dev-runner] stale active runner 諛쒓껄: {rid} ???뺣━ ?쒖옉")
                await self._force_cleanup_state(rid)
                cleaned_active_ids.add(rid)
                cleaned_active += 1

        try:
            recent_entries = await self.async_redis.zrange(
                RECENT_RUNNERS_KEY,
                0,
                -1,
                withscores=True,
            )
        except Exception:
            recent_entries = []

        now = datetime.now()
        cutoff_ts = time.time() - RECENT_RUNNERS_TTL
        GRACE_SECONDS = 600

        for rid, recent_score in recent_entries:
            if rid in cleaned_active_ids:
                continue
            status = await self.async_redis.get(self._runner_key(rid, "status"))
            if status == "stopped":
                trigger = await self.async_redis.get(self._runner_key(rid, "trigger"))
                plan_file = await self.async_redis.get(self._runner_key(rid, "plan_file"))
                reason = "file_lost"  # 湲곕낯媛? ?뚯씪 ?놁쓬
                if plan_file:
                    try:
                        source_path = Path(plan_file)
                        if source_path.exists():
                            preserved_recent += 1
                            continue
                        target = resolve_plan_target(plan_file, purpose="archive")
                        if Path(target.target).exists():
                            reason = "history_archived" if target.target_kind == "history" else "archived"
                    except PathRuleError:
                        pass

                if reason == "archived":
                    preserved_recent += 1
                    continue

                if reason == "file_lost" and recent_score >= cutoff_ts:
                    preserved_recent += 1
                    continue

                if is_visible_runner(trigger, rid):
                    # user/user:all trigger: dismiss ?꾧퉴吏 cleanup-stale濡???젣?섏? ?딅뒗??
                    preserved_recent += 1
                    continue
                # TTL 珥덇낵 + archived/file_lost recent 留??뺣━
                if reason == "file_lost":
                    bugs += 1
                    logger.warning(f"[dev-runner] cleanup: runner {rid} plan ?뚯씪 ?뚯떎 (file_lost)")
                for key_suffix in RUNNER_KEY_SUFFIXES:
                    await self.async_redis.delete(self._runner_key(rid, key_suffix))
                await self.async_redis.zrem(RECENT_RUNNERS_KEY, rid)
                cleaned_recent += 1
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
                    # 洹쒖튃 ?댁꽍 ?ㅽ뙣 寃쎈줈??蹂댁닔?곸쑝濡?file_lost 痍④툒
                    reason = "file_lost"
            else:
                reason = "file_lost"

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
                logger.warning(f"[dev-runner] cleanup: runner {rid} plan ?뚯씪 ?뚯떎 (file_lost)")

        total = cleaned_active + cleaned_recent
        if total:
            logger.info(
                "[dev-runner] cleanup_stale_runners: active=%s, recent=%s, preserved=%s, bugs=%s",
                cleaned_active,
                cleaned_recent,
                preserved_recent,
                bugs,
            )

        return {
            "cleaned_active": cleaned_active,
            "cleaned_recent": cleaned_recent,
            "preserved_recent": preserved_recent,
            "bugs": bugs,
            "total": total,
        }

    async def dismiss_runner(self, runner_id: str) -> bool:
        """??hard delete ?꾩슜 寃쎈줈: RECENT? per-runner ?ㅻ? 利됱떆 ??젣?쒕떎."""
        try:
            await self.async_redis.zrem(RECENT_RUNNERS_KEY, runner_id)
            for key_suffix in RUNNER_KEY_SUFFIXES:
                await self.async_redis.delete(self._runner_key(runner_id, key_suffix))
            await self.async_redis.srem(ACTIVE_RUNNERS_KEY, runner_id)
            return True
        except Exception:
            return False

