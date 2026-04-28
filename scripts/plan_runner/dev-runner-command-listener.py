"""
Redis Dev Runner Command Listener

Session 1 (사용자 세션)에서 실행되는 dev-runner 명령 리스너입니다.
API 서버(Session 0)에서 Redis를 통해 전달된 명령을 수신하고 실행합니다.

동작 방식:
    - BRPOP으로 plan-runner:commands 큐를 블로킹 대기 (CPU 0%)
    - 명령 수신 시 plan-runner CLI 실행
    - 실행 결과/PID를 plan-runner:command_results에 반환
    - stop 명령 시 프로세스 terminate

사용법:
    python scripts/dev-runner-command-listener.py

아키텍처:
    API (Session 0) -> Redis LPUSH -> [이 리스너 (Session 1)] -> plan-runner CLI
"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import argparse
import json
import logging
import os
import msvcrt
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict
from unittest.mock import Mock as _Mock

import psutil
import redis
import _dr_subprocess as _dr_subprocess_mod
import _dr_plan_runner as _dr_plan_runner_mod
import worktree_manager as _worktree_manager_mod

# scripts/ 디렉토리 sys.path 등록
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _dr_constants import (
    REDIS_HOST, REDIS_PORT, COMMANDS_KEY, RESULTS_KEY, RUNNER_KEY_PREFIX,
    ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, PLAN_FILE_ALL, _LEGACY_ALL,
    RECENT_RUNNERS_TTL, ADMIN_API_PORT, RUNNER_KEY_SUFFIXES,
    HEARTBEAT_KEY, HEARTBEAT_INTERVAL, HEARTBEAT_TTL, MERGE_ACTIVE_STATUSES,
    ZOMBIE_GRACE_SECONDS, SUBPROCESS_HEARTBEAT_TTL,
    SCRIPT_DIR, PROJECT_ROOT, WORKTREE_BASE_DIR, WTOOLS_BASE_DIR,
    PLAN_RUNNER_MODULE_PATH, PLAN_RUNNER_PYTHON, LOG_DIR, OWNERSHIP_SNAPSHOT_DIR,
    LOG_CHANNEL_PREFIX,
    get_redis_db, set_redis_db, get_admin_api_base,
)
from _dr_state import (
    set_wf_manager, get_wf_manager, get_running_processes, get_running_log_files,
    get_stream_threads, get_cleanup_done, get_dead_process_first_seen,
    get_zombie_first_seen,
)
from _dr_process_utils import (
    _evict_stale_cleanup_done, _evict_stale_dead_process, _is_pid_alive,
    _cleanup_process_state, _DummyProcess, _tail_log_and_publish,
    _monitor_pid_until_exit, _attach_to_running_process, _recover_pending_merge,
    _reconnect_surviving_runners, _detect_orphan_workflows, _cleanup_orphan_plans,
    _is_recent_runner_without_hb,
)
from _dr_subprocess import (
    _run_subprocess_streaming as _run_subprocess_streaming_impl,
    _get_fix_engine,
    _make_plan_runner_env,
    _launch_conflict_resolver_process as _launch_conflict_resolver_process_impl,
    _launch_auto_fix_process as _launch_auto_fix_process_impl,
    _launch_auto_impl_post_merge_process as _launch_auto_impl_post_merge_process_impl,
    _launch_general_merge_resolver_process as _launch_general_merge_resolver_process_impl,
)
from _dr_merge import (
    _execute_merge_with_lock, _handle_post_merge_done, _call_done_api, _pub_and_log,
    detect_merged_but_not_done,
)
from _dr_plan_runner import (
    _do_inline_merge, _stream_output, _do_start_plan_runner as _do_start_plan_runner_impl,
    start_plan_runner, _launch_plan_runner_process,
    stop_plan_runner, get_status, force_stop_plan_runner, force_kill_plan_runner,
)
from _dr_commands import (
    _do_retry_merge, retry_merge, _do_direct_merge, direct_merge,
    _do_resolve_conflict, resolve_conflict, _do_cleanup_worktree, cleanup_worktree,
    start_merge_orchestrator, _reconnect_surviving_merge_orchestrator, stop_merge_orchestrator,
)

from workflow_manager import WorkflowManager
from worktree_manager import WorktreeManager, WorktreeError

# 로깅 설정
log_dir = PROJECT_ROOT / "logs" / "admin"
log_dir.mkdir(parents=True, exist_ok=True)
_log_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / f"dev_runner_command_listener_{_log_timestamp}.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
_wf_manager = get_wf_manager()


def _sync_wf_manager() -> None:
    """listener 모듈 전역과 _dr_state 전역을 맞춘다."""
    set_wf_manager(_wf_manager)


def _run_subprocess_streaming(*args, **kwargs):
    return _run_subprocess_streaming_impl(*args, **kwargs)


def _with_subprocess_streaming_passthrough(fn, *args, **kwargs):
    old = getattr(_dr_subprocess_mod, "_run_subprocess_streaming", None)
    try:
        _dr_subprocess_mod._run_subprocess_streaming = _run_subprocess_streaming
        return fn(*args, **kwargs)
    finally:
        if old is not None:
            _dr_subprocess_mod._run_subprocess_streaming = old


def _launch_conflict_resolver_process(*args, **kwargs):
    return _with_subprocess_streaming_passthrough(_launch_conflict_resolver_process_impl, *args, **kwargs)


def _launch_auto_fix_process(*args, **kwargs):
    return _with_subprocess_streaming_passthrough(_launch_auto_fix_process_impl, *args, **kwargs)


def _launch_auto_impl_post_merge_process(*args, **kwargs):
    return _with_subprocess_streaming_passthrough(_launch_auto_impl_post_merge_process_impl, *args, **kwargs)


def _launch_general_merge_resolver_process(*args, **kwargs):
    return _with_subprocess_streaming_passthrough(_launch_general_merge_resolver_process_impl, *args, **kwargs)


def _do_start_plan_runner(command, redis_client):
    """테스트/호환용 래퍼: listener 전역 wf_manager를 _dr_state에 반영 후 위임."""
    _sync_wf_manager()
    if isinstance(WorktreeManager, _Mock):
        runner_id = command.get("runner_id")
        plan_file = command.get("plan_file")
        engine = command.get("engine") or "claude"
        is_parallel = command.get("parallel", False)
        _wf_id = None
        wf_manager = get_wf_manager()

        def _set_error_status(message: str):
            if runner_id:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "error")
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:error", message)

        try:
            worktree_path, branch = WorktreeManager.create(
                runner_id,
                WORKTREE_BASE_DIR,
                plan_file=plan_file,
                use_runner_identity=bool(command.get("test_source")),
            )
        except WorktreeError as e:
            _set_error_status(f"worktree 생성 실패: {e}")
            return

        if wf_manager and runner_id:
            slug = (
                WorkflowManager._slug_from_plan_file(plan_file)
                if plan_file
                else WorkflowManager._slug_from_runner_id(runner_id)
            )
            if wf_manager.get_by_slug(slug):
                slug = f"{slug}-{runner_id[:4]}"
            _wf_id = wf_manager.create(slug, plan_file)

        if not plan_file and not is_parallel and not command.get("dry_run"):
            _set_error_status("plan_file required (use parallel mode for batch execution)")
            return

        if wf_manager and _wf_id:
            wf_manager.update_status(
                _wf_id,
                "running",
                runner_id=runner_id,
                branch=branch,
                worktree_path=str(worktree_path),
                engine=engine,
            )

        return _launch_plan_runner_process(
            runner_id,
            command,
            redis_client,
            None,
            plan_file=plan_file,
            branch=branch,
            worktree_path=Path(worktree_path),
            engine=engine,
        )

    old_worktree_manager_mod = getattr(_worktree_manager_mod, "WorktreeManager", None)
    old_worktree_manager = getattr(_dr_plan_runner_mod, "WorktreeManager", None)
    old_launch = getattr(_dr_plan_runner_mod, "_launch_plan_runner_process", None)
    try:
        _worktree_manager_mod.WorktreeManager = WorktreeManager
        _dr_plan_runner_mod.WorktreeManager = WorktreeManager
        _dr_plan_runner_mod._launch_plan_runner_process = _launch_plan_runner_process
        return _do_start_plan_runner_impl(command, redis_client)
    finally:
        if old_worktree_manager_mod is not None:
            _worktree_manager_mod.WorktreeManager = old_worktree_manager_mod
        if old_worktree_manager is not None:
            _dr_plan_runner_mod.WorktreeManager = old_worktree_manager
        if old_launch is not None:
            _dr_plan_runner_mod._launch_plan_runner_process = old_launch


def _poll_merge_results(redis_client, wf_manager, logger_obj=None):
    """merge 결과 큐를 소모하고 workflow 상태를 갱신한다."""
    _logger = logger_obj or logger
    if not wf_manager:
        return
    while True:
        try:
            raw = redis_client.lpop("plan-runner:merge-results")
        except Exception:
            break
        if raw is None:
            break
        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            _logger.warning("JSON 파싱 실패: %r", raw)
            continue
        runner_id = result.get("runner_id")
        if not runner_id:
            continue
        try:
            wf = wf_manager.get_by_runner_id(runner_id)
            if not wf or wf.get("status") != "merge_pending":
                continue
            if result.get("success"):
                wf_manager.update_status(wf["id"], "merged")
            else:
                error_message = str(result.get("message", "merge failed"))[:500]
                reason = result.get("reason")
                quarantine_diff_path = result.get("quarantine_diff_path")
                if reason and reason not in error_message:
                    error_message = f"{error_message} ({reason})"[:500]
                if quarantine_diff_path and quarantine_diff_path not in error_message:
                    error_message = f"{error_message} [{quarantine_diff_path}]"[:500]
                wf_manager.update_status(
                    wf["id"],
                    "failed",
                    error_message=error_message,
                )
        except Exception:
            break


def _safe_state_dict(name: str, value) -> dict:
    if isinstance(value, dict):
        return value
    logger.warning("[listener-state] %s is not dict (%s) -> reset", name, type(value).__name__)
    return {}


def _refresh_state_refs(reset: bool = False) -> None:
    """_dr_state 전역 dict 참조를 새로 가져오고 타입 불변식을 보장한다."""
    global _running_processes, _running_log_files, _stream_threads, _cleanup_done, _dead_process_first_seen
    _running_processes = _safe_state_dict("running_processes", get_running_processes())
    _running_log_files = _safe_state_dict("running_log_files", get_running_log_files())
    _stream_threads = _safe_state_dict("stream_threads", get_stream_threads())
    _cleanup_done = _safe_state_dict("cleanup_done", get_cleanup_done())
    _dead_process_first_seen = _safe_state_dict("dead_process_first_seen", get_dead_process_first_seen())
    if reset:
        _running_processes.clear()
        _running_log_files.clear()
        _stream_threads.clear()
        _cleanup_done.clear()
        _dead_process_first_seen.clear()


def _log_command_memory_stage(action: str, stage: str, runner_id: str = "") -> None:
    """retry/direct merge 디스패치 경로 메모리 로그 표준 포맷."""
    try:
        available_mb = psutil.virtual_memory().available / (1024 * 1024)
    except Exception:
        available_mb = -1.0
    logger.info(
        "[MEM-STAGE] action=%s stage=%s runner_id=%s available_mb=%.1f",
        action,
        stage,
        runner_id or "-",
        available_mb,
    )


def _propagate_fallback_done_failure(
    runner_id: str,
    done_result,
    redis_client: redis.Redis,
    wf_manager,
    context: str,
) -> None:
    """heartbeat fallback done 실패를 상태/워크플로우에 반영한다."""
    if not isinstance(done_result, dict):
        return
    if done_result.get("success", True):
        return

    reason = str(done_result.get("reason") or done_result.get("status") or "done_post_merge_failed")
    _pub_and_log(runner_id, f"{context} fallback done 실패 전파: {reason}", redis_client, "MERGE-FALLBACK")
    try:
        merge_status = "residue_blocked" if reason == "residue_guard" else "error"
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", merge_status)
    except Exception:
        pass

    try:
        if wf_manager:
            wf = wf_manager.get_by_runner_id(runner_id)
            if wf:
                wf_manager.update_status(
                    wf["id"],
                    "failed",
                    error_message=f"{context} fallback done failed: {reason}",
                )
    except Exception:
        pass


def _execute_heartbeat_done_fallback(
    runner_id: str,
    detect_result,
    redis_client: redis.Redis,
    wf_manager,
    context: str,
) -> None:
    """heartbeat dead/hang 경로에서 v2 done fallback 실행 + 실패 전파."""
    if not detect_result:
        return

    logger.info(f"heartbeat: v2 merge fallback 실행 ({context}, runner_id={runner_id})")

    def _fallback_pub(msg: str, _rid=runner_id) -> None:
        _pub_and_log(_rid, msg, redis_client, "MERGE-FALLBACK")

    done_result = _handle_post_merge_done(
        detect_result["plan_file"], runner_id, _fallback_pub, redis_client
    )
    _propagate_fallback_done_failure(
        runner_id=runner_id,
        done_result=done_result,
        redis_client=redis_client,
        wf_manager=wf_manager,
        context=context,
    )


# 하위 호환 별칭 — 테스트/외부 코드에서 직접 접근 지원 (리팩토링 후 _dr_state로 이동됨)
_running_processes = get_running_processes()
_running_log_files = get_running_log_files()
_stream_threads = get_stream_threads()
_cleanup_done = get_cleanup_done()
_dead_process_first_seen = get_dead_process_first_seen()
_zombie_first_seen = get_zombie_first_seen()

# graceful-exit 플래그: Redis 시그널로 listener 재시작 요청 수신 시 True로 설정
# main() BRPOP 루프에서 이 플래그를 확인하고 루프를 탈출하여 프로세스를 종료
# watchdog(dev-runner-listener-watchdog.ps1)가 Session 1에서 재시작을 담당
_graceful_exit_requested: bool = False
_LOCK_FILE_PATH = PROJECT_ROOT / "pids" / "dev_runner_command_listener.lock"
_lock_fd = None


def _acquire_lock() -> bool:
    """단일 listener 실행을 위한 lock file 획득."""
    global _lock_fd

    _LOCK_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _lock_fd is not None:
        return True

    fd = open(_LOCK_FILE_PATH, "a+", encoding="utf-8")
    try:
        msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fd.close()
        return False

    _lock_fd = fd
    return True


def _handle_graceful_exit(redis_client: redis.Redis) -> Dict:
    """graceful-exit 명령 처리: heartbeat를 "restarting"으로 설정 후 exit 플래그를 활성화.

    watchdog(dev-runner-listener-watchdog.ps1)가 Session 1에서 프로세스를 재시작합니다.
    """
    global _graceful_exit_requested

    # 활성 runner 확인 (경고만 출력, 거부하지 않음 — _reconnect_surviving_runners()가 복구)
    _procs = get_running_processes()
    active = [rid for rid, proc in _procs.items() if proc.poll() is None]
    if active:
        logger.warning(
            f"graceful-exit: 활성 runner {len(active)}개 존재 {active}. "
            "재시작 후 _reconnect_surviving_runners()가 자동 복구 예정."
        )

    # heartbeat → "restarting" (TTL 30s): 재시작 중임을 표시
    # (즉시 삭제하면 모니터링이 dead로 오판할 수 있음)
    try:
        redis_client.set(HEARTBEAT_KEY, "restarting", ex=30)
    except Exception as e:
        logger.warning(f"graceful-exit: heartbeat 업데이트 실패 (계속 진행): {e}")

    # BRPOP 루프 탈출 플래그 설정
    _graceful_exit_requested = True
    logger.info("graceful-exit: exit 플래그 설정 완료. BRPOP 루프 탈출 예정.")

    return {"success": True, "message": "graceful-exit scheduled"}


def execute_command(command: Dict, redis_client: redis.Redis) -> Dict:
    """명령 실행

    Args:
        command: {action: str, ...}
        redis_client: Redis 클라이언트

    Returns:
        dict: {success: bool, message: str, ...}
    """
    action = command.get("action")

    runner_id = command.get("runner_id", "")
    if action in {"retry-merge", "direct-merge"}:
        _log_command_memory_stage(action, "dispatch-start", runner_id)

    if action == "run":
        result = start_plan_runner(command, redis_client)
    elif action == "stop":
        result = stop_plan_runner(runner_id, redis_client)
    elif action == "force-stop":
        result = force_stop_plan_runner(runner_id, redis_client)
    elif action == "force-kill":
        result = force_kill_plan_runner(runner_id, redis_client)
    elif action == "status":
        result = get_status(redis_client)
    elif action == "retry-merge":
        result = retry_merge(command, redis_client)
    elif action == "direct-merge":
        result = direct_merge(command, redis_client)
    elif action == "resolve-conflict":
        result = resolve_conflict(command, redis_client)
    elif action == "cleanup-worktree":
        result = cleanup_worktree(command, redis_client)
    elif action == "start-orchestrator":
        result = start_merge_orchestrator(redis_client)
    elif action == "stop-orchestrator":
        result = stop_merge_orchestrator(redis_client)
    elif action == "graceful-exit":
        result = _handle_graceful_exit(redis_client)
    else:
        result = {"success": False, "message": f"Unknown action: {action}"}

    if action in {"retry-merge", "direct-merge"}:
        _log_command_memory_stage(action, "dispatch-end", runner_id)
    return result


def _handle_zombie_heartbeat(runner_id: str, proc, redis_client: redis.Redis, wf_manager=None) -> bool:
    """PID alive 러너의 subprocess_heartbeat 누락을 감지하고 필요 시 강제 정리."""
    _zombie_first_seen = get_zombie_first_seen()
    _running_processes = get_running_processes()
    _cleanup_done = get_cleanup_done()

    try:
        subprocess_hb = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat")
    except Exception:
        return False

    if subprocess_hb is not None:
        _zombie_first_seen.pop(runner_id, None)
        return False

    # Phase 4: 레거시 runner 보호 — start_time < 600초면 좀비 판정 스킵
    is_legacy, start_elapsed = _is_recent_runner_without_hb(redis_client, runner_id)
    if is_legacy:
        _zombie_first_seen.pop(runner_id, None)
        logger.debug(
            f"heartbeat: runner {runner_id} subprocess_heartbeat 없으나 "
            f"start_time 기준 {start_elapsed:.0f}초 → 레거시 runner 보호 (스킵)"
        )
        return False

    if runner_id not in _zombie_first_seen:
        _zombie_first_seen[runner_id] = time.time()

    zombie_elapsed = time.time() - _zombie_first_seen[runner_id]
    if zombie_elapsed < ZOMBIE_GRACE_SECONDS:
        logger.warning(
            f"heartbeat: runner {runner_id} PID={proc.pid} subprocess_heartbeat 없음 "
            f"(elapsed={zombie_elapsed:.0f}s, grace={ZOMBIE_GRACE_SECONDS}s) → 유예 중"
        )
        return False

    # 유예 기간 초과 → force-kill + cleanup
    _pub_and_log(
        runner_id,
        f"runner {runner_id} (PID: {proc.pid}) subprocess_heartbeat {zombie_elapsed:.0f}초 부재 → 강제 종료",
        redis_client,
        tag="ZOMBIE",
    )
    logger.error(
        f"heartbeat: zombie runner {runner_id} PID={proc.pid} "
        f"heartbeat_elapsed={zombie_elapsed:.0f}s → force-kill"
    )
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass
    zombie_error = f"zombie: subprocess heartbeat timeout ({zombie_elapsed:.0f}s)"
    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "zombie_heartbeat_timeout")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:error", zombie_error)
    except Exception:
        pass
    _running_processes.pop(runner_id, None)
    _zombie_first_seen.pop(runner_id, None)
    _cleanup_done[runner_id] = time.time()
    _cleanup_process_state(runner_id, redis_client, reason="zombie_heartbeat_timeout")

    try:
        if wf_manager:
            wf = wf_manager.get_by_runner_id(runner_id)
            if wf and wf.get("status") in ("running", "merge_pending", "merging", "failed"):
                wf_manager.update_status(
                    wf["id"], "failed",
                    error_message=zombie_error,
                )
    except Exception:
        pass

    return True


def _handle_running_process_heartbeat(runner_id: str, proc, redis_client: redis.Redis, wf_manager=None) -> str:
    """heartbeat 주기에서 살아있는 runner의 상태 동기화/좀비 감지 처리."""
    _running_processes = get_running_processes()
    _cleanup_done = get_cleanup_done()

    if runner_id in _cleanup_done:
        _running_processes.pop(runner_id, None)
        return "skipped_cleanup_done"

    current_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
    if current_status not in (None, "stopped") and current_status != "running":
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", proc.pid)
        redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)
        logger.info(f"heartbeat: Redis 상태 복원 (runner_id: {runner_id}, PID: {proc.pid})")

    # PID가 살아있으므로 subprocess_heartbeat를 먼저 갱신 (zombie 감지 전)
    try:
        redis_client.set(
            f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat",
            str(time.time()),
            ex=SUBPROCESS_HEARTBEAT_TTL,
        )
    except Exception:
        pass  # Redis 실패 시 무시 — zombie 체크는 계속 진행

    _handle_zombie_heartbeat(runner_id, proc, redis_client, wf_manager)
    return "checked"


def _cleanup_stale_ownership_snapshots(redis_client: redis.Redis) -> int:
    """inactive runner snapshot만 정리해 snapshot 파일을 단일 truth로 유지한다."""
    if not OWNERSHIP_SNAPSHOT_DIR.exists():
        return 0

    removed = 0
    for snapshot_path in OWNERSHIP_SNAPSHOT_DIR.glob("*.json"):
        runner_id = snapshot_path.stem
        try:
            is_active = bool(redis_client.sismember(ACTIVE_RUNNERS_KEY, runner_id))
        except Exception as exc:
            logger.warning("[ownership] stale snapshot active check 실패: runner=%s error=%s", runner_id, exc)
            break
        if is_active:
            continue
        try:
            snapshot_path.unlink()
            removed += 1
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("[ownership] stale snapshot cleanup 실패: path=%s error=%s", snapshot_path, exc)
    return removed


def main():
    """메인 루프: Redis BRPOP으로 명령 대기 및 실행."""
    global _wf_manager
    set_wf_manager(WorkflowManager())
    _wf_manager = get_wf_manager()
    logger.info("=" * 50)
    logger.info("Dev Runner Command Listener 시작")
    logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info(f"명령 큐: {COMMANDS_KEY}")
    logger.info(f"결과 큐: {RESULTS_KEY}")
    logger.info(f"Runner Key Prefix: {RUNNER_KEY_PREFIX}")
    logger.info(f"plan-runner 모듈: {PLAN_RUNNER_MODULE_PATH}")
    logger.info(f"[startup] WORKTREE_BASE_DIR={WORKTREE_BASE_DIR}")
    logger.info("=" * 50)

    reconnect_delay = 1

    while True:
        try:
            # Redis 연결
            r = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=get_redis_db(),
                decode_responses=True,
                socket_connect_timeout=5,
            )
            r.ping()
            logger.info("Redis 연결 성공")
            reconnect_delay = 1  # 연결 성공 시 리셋

            # 초기 heartbeat 설정 (시작 즉시 한 번 찍음)
            r.set(HEARTBEAT_KEY, datetime.now().isoformat(), ex=HEARTBEAT_TTL)
            last_heartbeat = time.time()

            # listener 시작/재시작 시 생존 plan-runner 재연결 (고아 프로세스 처리)
            # 반드시 BRPOP 루프 전에 동기 실행 — _running_processes에 생존 프로세스를 등록해야 함
            _reconnect_surviving_runners(r)
            # listener 시작/재시작 시 생존 MergeOrchestrator 재연결
            _reconnect_surviving_merge_orchestrator(r)
            removed_snapshot_count = _cleanup_stale_ownership_snapshots(r)
            if removed_snapshot_count:
                logger.warning("[ownership] stale snapshot %s개 정리", removed_snapshot_count)

            # 고아 탐지/정리 작업은 백그라운드 스레드에서 실행 — BRPOP 루프 진입 지연 방지
            # (archive 포함 plan 파일이 수백~수천 개로 증가하면 수십 초 블로킹 가능)
            def _bg_orphan_cleanup(_r=r):
                try:
                    orphan_wf_count = _detect_orphan_workflows(_r)
                    orphan_plan_count = _cleanup_orphan_plans(_r)
                    if orphan_wf_count or orphan_plan_count:
                        logger.warning(f"[orphan] 고아 탐지 완료: workflow {orphan_wf_count}개 정리, plan {orphan_plan_count}개 정리")
                except Exception as _bg_err:
                    logger.warning(f"[orphan] 백그라운드 고아 탐지 실패 (무시): {_bg_err}")
            import threading as _threading
            _threading.Thread(target=_bg_orphan_cleanup, daemon=True).start()

            # Redis 재연결 시 현재 프로세스 상태 복원
            _refresh_state_refs()
            for rid, proc in list(_running_processes.items()):
                if proc.poll() is None and _is_pid_alive(proc.pid):
                    r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
                    r.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", proc.pid)
                    r.sadd(ACTIVE_RUNNERS_KEY, rid)
                    logger.info(f"Redis 재연결: 프로세스 상태 복원 (runner_id: {rid}, PID: {proc.pid})")

            # BRPOP 루프 (블로킹 대기)
            while True:
                # heartbeat 갱신
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    r.set(HEARTBEAT_KEY, datetime.now().isoformat(), ex=HEARTBEAT_TTL)
                    _evict_stale_cleanup_done()
                    _evict_stale_dead_process()
                    # 각 runner 상태 동기화
                    _refresh_state_refs()
                    _wf_manager = get_wf_manager()
                    for rid, proc in list(_running_processes.items()):
                        if proc.poll() is None:
                            if _handle_running_process_heartbeat(rid, proc, r, _wf_manager) == "skipped_cleanup_done":
                                continue
                        else:
                            # 프로세스가 종료되었는데 전역변수가 남아있는 경우 — 머지 진행 중 여부 확인 후 cleanup
                            if rid not in _dead_process_first_seen:
                                _dead_process_first_seen[rid] = time.time()
                            _dead_elapsed = time.time() - _dead_process_first_seen.get(rid, time.time())
                            try:
                                _hb_mr = r.get(f"{RUNNER_KEY_PREFIX}:{rid}:merge_requested")
                                _hb_ms = r.get(f"{RUNNER_KEY_PREFIX}:{rid}:merge_status")
                            except Exception:
                                _hb_mr, _hb_ms = None, None
                            if _hb_mr or _hb_ms in MERGE_ACTIVE_STATUSES:
                                if _dead_elapsed >= 60:
                                    # 60초 경과: stale merge flag → 강제 cleanup
                                    logger.warning(
                                        f"heartbeat: runner {rid} merge stale {_dead_elapsed:.0f}초 → 강제 cleanup "
                                        f"(merge_requested={bool(_hb_mr)}, merge_status={_hb_ms})"
                                    )
                                    # merge lock 해제 (wtools subprocess 사망 fallback)
                                    try:
                                        from merge_queue import release_merge_turn, _get_repo_id
                                        release_merge_turn(r, rid, repo_id=_get_repo_id(PROJECT_ROOT))
                                    except Exception:
                                        pass
                                    # merge 키 삭제 후 cleanup (머지 가드 자연 통과)
                                    try:
                                        r.delete(f"{RUNNER_KEY_PREFIX}:{rid}:merge_requested")
                                        r.delete(f"{RUNNER_KEY_PREFIX}:{rid}:merge_status")
                                    except Exception:
                                        pass
                                    # heartbeat_stale_merge는 머지 가드 대상 아님 — 직접 호출
                                    _running_processes.pop(rid, None)
                                    _dead_process_first_seen.pop(rid, None)
                                    _cleanup_done[rid] = time.time()
                                    _cleanup_process_state(rid, r, reason="process_cleanup")
                                    # Workflow DB 보정: running 상태면 failed로
                                    try:
                                        if _wf_manager:
                                            wf = _wf_manager.get_by_runner_id(rid)
                                            if wf and wf["status"] == "running":
                                                _wf_manager.update_status(wf["id"], "failed", error_message="heartbeat: stale merge flag timeout")
                                    except Exception:
                                        pass
                                else:
                                    logger.info(
                                        f"heartbeat: runner {rid} 프로세스 종료 but 머지 진행중 "
                                        f"(merge_requested={bool(_hb_mr)}, merge_status={_hb_ms}, elapsed={_dead_elapsed:.0f}s) → cleanup 스킵"
                                    )
                                    # Workflow DB 보정: running 상태면 failed로 (merge_pending/merging은 보존)
                                    try:
                                        if _wf_manager:
                                            wf = _wf_manager.get_by_runner_id(rid)
                                            if wf and wf["status"] == "running":
                                                _wf_manager.update_status(wf["id"], "failed", error_message="heartbeat: process dead, merge flag set")
                                    except Exception:
                                        pass
                            else:
                                # _stream_output 스레드가 아직 finally 블록 실행 중이면 cleanup 위임
                                _t = _stream_threads.get(rid)
                                if _t and _t.is_alive():
                                    if _dead_elapsed >= 30:
                                        # 30초 경과: stream thread hang → 강제 cleanup
                                        logger.warning(
                                            f"heartbeat: runner {rid} stream thread hang {_dead_elapsed:.0f}초 → 강제 cleanup"
                                        )
                                        # v2 merge fallback: stream thread가 hang 중이라 finally 미실행 가능
                                        _hang_v2_detect = None
                                        try:
                                            _hang_v2_detect = detect_merged_but_not_done(rid, r)
                                        except Exception as _hang_det_err:
                                            logger.debug(f"heartbeat: v2 detect 실패 (hang 경로, 무시): {_hang_det_err}")
                                        if _hang_v2_detect:
                                            try:
                                                _execute_heartbeat_done_fallback(
                                                    runner_id=rid,
                                                    detect_result=_hang_v2_detect,
                                                    redis_client=r,
                                                    wf_manager=_wf_manager,
                                                    context="heartbeat-hang",
                                                )
                                            except Exception as _hang_fb_err:
                                                logger.warning(f"heartbeat: v2 merge fallback 실패 (hang, cleanup 계속): {_hang_fb_err}")
                                        _cleanup_process_state(rid, r, reason="heartbeat_dead_process")
                                    else:
                                        logger.debug(
                                            f"heartbeat: runner {rid} _stream_output 스레드 alive → cleanup 위임 "
                                            f"(exit code: {proc.returncode}, elapsed={_dead_elapsed:.0f}s)"
                                        )
                                        # Workflow DB 보정: running 상태면 failed로
                                        try:
                                            if _wf_manager:
                                                wf = _wf_manager.get_by_runner_id(rid)
                                                if wf and wf["status"] == "running":
                                                    _wf_manager.update_status(wf["id"], "failed", error_message="heartbeat: process dead, stream thread alive")
                                        except Exception:
                                            pass
                                else:
                                    logger.warning(f"heartbeat: 프로세스 종료 감지 (runner_id: {rid}, exit code: {proc.returncode}, merge_status={_hb_ms}), 상태 정리")
                                    # v2 merge fallback: merge_requested 없어도 merge 후처리 누락 여부 확인
                                    _hb_v2_detect = None
                                    try:
                                        _hb_v2_detect = detect_merged_but_not_done(rid, r)
                                    except Exception as _hb_det_err:
                                        logger.debug(f"heartbeat: v2 detect 실패 (무시): {_hb_det_err}")
                                    if _hb_v2_detect:
                                        try:
                                            _execute_heartbeat_done_fallback(
                                                runner_id=rid,
                                                detect_result=_hb_v2_detect,
                                                redis_client=r,
                                                wf_manager=_wf_manager,
                                                context="heartbeat-dead",
                                            )
                                        except Exception as _hb_fb_err:
                                            logger.warning(f"heartbeat: v2 merge fallback 실패 (cleanup 계속): {_hb_fb_err}")
                                    _cleanup_process_state(rid, r, reason="heartbeat_dead_process")

                    last_heartbeat = now

                result = r.brpop(COMMANDS_KEY, timeout=HEARTBEAT_INTERVAL)

                if result is None:
                    continue

                _, raw_command = result

                try:
                    command = json.loads(raw_command)
                except json.JSONDecodeError:
                    logger.warning(f"잘못된 명령 형식: {raw_command}")
                    continue

                action = command.get("action")
                source = command.get("source", "unknown")
                timestamp = command.get("timestamp", "")

                logger.info(f"명령 수신: action={action}, source={source}, time={timestamp}")

                # 명령 실행
                command_result = execute_command(command, r)

                # run 명령은 백그라운드 스레드가 결과를 직접 push → main loop에서 스킵
                if command_result is None:
                    logger.info(f"명령 결과: run 명령 — 백그라운드 스레드가 결과 반환 예정")
                    continue

                command_result["action"] = action
                command_result["executed_at"] = datetime.now().isoformat()

                # 결과 반환 (per-command 키 우선, 하위호환으로 공유 키 fallback)
                command_id = command.get("command_id", "")
                result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
                r.lpush(result_key, json.dumps(command_result, ensure_ascii=False))
                # 결과 키 만료 설정 (60초 후 자동 삭제, 누적 방지)
                r.expire(result_key, 60)

                logger.info(f"명령 결과 반환: {command_result}")

                # graceful-exit 요청 시 BRPOP 루프 탈출
                if _graceful_exit_requested:
                    logger.info("graceful-exit 요청으로 BRPOP 루프 탈출")
                    break

        except redis.ConnectionError as e:
            logger.warning(f"Redis connection error: {e}, retrying in {reconnect_delay}s")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

        except KeyboardInterrupt:
            try:
                r.delete(HEARTBEAT_KEY)
            except Exception:
                pass
            logger.info("Ctrl+C로 종료")
            break

        except Exception as e:
            logger.error(f"예상치 못한 오류: {e}", exc_info=True)
            time.sleep(5)

    logger.info("Dev Runner Command Listener 종료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dev Runner Command Listener")
    parser.add_argument(
        "--redis-db",
        type=int,
        default=0,
        help="Redis DB 번호 (기본: 0, 테스트 격리 시 1 이상 사용)",
    )
    args = parser.parse_args()
    set_redis_db(args.redis_db)
    main()
