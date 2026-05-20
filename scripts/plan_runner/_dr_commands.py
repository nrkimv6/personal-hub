"""_dr_commands.py — dev-runner 명령 처리 모듈"""
import json
import logging
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict

import psutil
import redis

from _dr_constants import (
    RUNNER_KEY_PREFIX, RESULTS_KEY, PLAN_FILE_ALL, _LEGACY_ALL,
    LOG_CHANNEL_PREFIX, WORKTREE_BASE_DIR, WTOOLS_BASE_DIR, PROJECT_ROOT,
    RECENT_RUNNERS_TTL, ACTIVE_RUNNERS_KEY,
)
from _dr_merge import _execute_merge_with_lock, _pub_and_log
from _dr_merge_persistence import MergePersistence
from _dr_merge_state import CONFLICT, ERROR, MERGED, QUEUED, RESOLVING, TERMINAL_STATUSES, RetryAction
from _dr_runtime_utils import _publish_with_retry
from _dr_subprocess import _get_fix_engine, _launch_conflict_resolver_process
from _dr_process_utils import _cleanup_process_state, get_plan_git_root
from _dr_stream_cleanup import _do_inline_merge

logger = logging.getLogger(__name__)


def _transition_merge_status(redis_client: redis.Redis, runner_id: str, status: str, *, action: str, message: str | None = None):
    return MergePersistence(redis_client, runner_id).transition(
        status,
        message=message,
        action=action,
    )


def _is_service_lock_approval_required(redis_client: redis.Redis, runner_id: str) -> bool:
    merge_status = _redis_text(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status"))
    merge_reason = _redis_text(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_reason"))
    return merge_status == "approval_required" and merge_reason == "service_lock"


def _set_service_lock_approved_flag(redis_client: redis.Redis, runner_id: str) -> str:
    key = f"{RUNNER_KEY_PREFIX}:{runner_id}:service_lock_approved"
    redis_client.set(key, "true", ex=RECENT_RUNNERS_TTL)
    return key


def _clear_service_lock_approved_flag(redis_client: redis.Redis, runner_id: str) -> None:
    try:
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:service_lock_approved")
    except Exception:
        pass


def _redis_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _refresh_runner_ownership_snapshot(
    runner_id: str,
    worktree_path: str | Path | None = None,
    *,
    action: str,
) -> dict:
    """Refresh ownership snapshot before a merge action uses the worktree."""
    try:
        from _dr_plan_runner import _capture_runner_ownership_snapshot

        project_root = Path(worktree_path).resolve() if worktree_path else PROJECT_ROOT
        if not (project_root / ".git").exists():
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    cwd=str(project_root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    project_root = Path(result.stdout.strip()).resolve()
            except Exception:
                pass
        payload = _capture_runner_ownership_snapshot(runner_id, project_root)
        payload["action"] = action
        return payload
    except Exception as exc:
        logger.warning("[%s] ownership snapshot refresh failed: %s", action, exc)
        return {"runner_id": runner_id, "action": action, "capture_error": str(exc)}


def _log_memory_stage(
    action: str,
    stage: str,
    runner_id: str = "",
    redis_client: redis.Redis | None = None,
) -> None:
    """retry/direct merge 경로의 메모리 단계 로그를 표준화한다."""
    try:
        available_mb = psutil.virtual_memory().available / (1024 * 1024)
    except Exception:
        available_mb = -1.0

    message = (
        f"[MEM-STAGE] action={action} stage={stage} "
        f"runner_id={runner_id or '-'} available_mb={available_mb:.1f}"
    )
    logger.info(message)
    if redis_client and runner_id:
        try:
            _pub_and_log(runner_id, message, redis_client, "MEMORY")
        except Exception:
            pass


def _do_retry_merge(runner_id: str, redis_client: redis.Redis, command_id: str, command: Dict = None) -> None:
    """retry-merge 실제 작업 (백그라운드 스레드에서 실행).

    Redis 키 재발급 전처리 → pre_merge_gate + auto_commit_stage → _execute_merge_with_lock()에 위임.
    """
    import sys as _sys
    from _dr_constants import PLAN_RUNNER_MODULE_PATH
    _plan_runner_path = str(PLAN_RUNNER_MODULE_PATH)
    if _plan_runner_path not in _sys.path:
        _sys.path.insert(0, _plan_runner_path)
    from plan_runner.core.stages import pre_merge_gate, auto_commit_stage  # noqa: E402

    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY

    def _pub(msg: str) -> None:
        _pub_and_log(runner_id, msg, redis_client, "MERGE")

    result = {"success": False, "message": "unknown error", "action": "retry-merge"}
    approved_service_lock = bool((command or {}).get("approve_service_lock"))
    flag_written = False
    try:
        _log_memory_stage("retry-merge", "start", runner_id, redis_client)
        if _is_service_lock_approval_required(redis_client, runner_id) and not approved_service_lock:
            result = {
                "success": False,
                "message": "service_lock approval required",
                "merge_status": "approval_required",
                "reason": "service_lock",
                "action": "retry-merge",
            }
            return
        if approved_service_lock:
            _set_service_lock_approved_flag(redis_client, runner_id)
            flag_written = True
            _pub("[RETRY-MERGE] service_lock 승인 플래그 설정 (one-shot)")
        # Redis 키 만료 시 command payload로 재발급
        worktree_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
        if not worktree_path_str and command:
            _wt = command.get("worktree_path")
            _pf = command.get("plan_file")
            _br = command.get("branch")
            if _wt:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", _wt, ex=3600)
                if _pf:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", _pf, ex=3600)
                if _br:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", _br, ex=3600)
                worktree_path_str = _wt
                _pub(f"[RETRY-MERGE] Redis 키 재발급: worktree={_wt}, plan={_pf}, branch={_br}")
        if not worktree_path_str:
            result = {"success": False, "message": f"worktree_path not found for runner {runner_id}", "action": "retry-merge"}
            return

        # pre_merge_gate + auto_commit_stage (최대 3회 재시도)
        gate_ok, gate_msg = pre_merge_gate(PROJECT_ROOT)
        if not gate_ok:
            if "다른 머지" in gate_msg or "lock" in gate_msg.lower():
                # 이미 lock이 잡혀있는 경우 — 진행 허용
                _pub(f"[RETRY-MERGE] pre_merge_gate: lock already held, proceeding ({gate_msg})")
            elif "dirty" in gate_msg or "git dirty" in gate_msg:
                # dirty 상태 → auto_commit_stage 최대 3회 재시도
                _pub(f"[RETRY-MERGE] pre_merge_gate dirty 감지 — auto_commit_stage 시도: {gate_msg}")
                committed = False
                for attempt in range(1, 4):
                    if auto_commit_stage(PROJECT_ROOT, f"chore: pre-merge safety commit (retry-merge attempt {attempt})"):
                        _pub(f"[RETRY-MERGE] auto_commit_stage 성공 (attempt {attempt})")
                        committed = True
                        break
                    # 이미 clean이면 auto_commit_stage가 False 반환 → gate 재확인
                    gate_ok2, gate_msg2 = pre_merge_gate(PROJECT_ROOT)
                    if gate_ok2:
                        _pub(f"[RETRY-MERGE] pre_merge_gate 재확인 통과 (attempt {attempt})")
                        committed = True
                        break
                    _pub(f"[RETRY-MERGE] auto_commit_stage attempt {attempt} 실패: {gate_msg2}")
                if not committed:
                    # 3회 모두 실패
                    _pub(f"[RETRY-MERGE] pre_merge_gate 3회 실패 — merge 중단: {gate_msg}")
                    try:
                        _transition_merge_status(
                            redis_client,
                            runner_id,
                            ERROR,
                            action="retry-merge",
                            message=f"pre_merge_gate 3회 실패: {gate_msg}",
                        )
                    except Exception:
                        pass
                    result = {"success": False, "message": f"pre_merge_gate 3회 실패: {gate_msg}", "merge_status": ERROR, "action": "retry-merge"}
                    return
            else:
                # main 브랜치가 아님 등 — gate 실패 그대로 전달하되 진행 (merge_to_main이 자체 처리)
                _pub(f"[RETRY-MERGE] pre_merge_gate 경고: {gate_msg} — 계속 진행")
        else:
            _pub(f"[RETRY-MERGE] pre_merge_gate 통과 — merge 진행")

        # lock + subprocess + 결과 처리는 공통 헬퍼에 위임
        _log_memory_stage("retry-merge", "mid", runner_id, redis_client)
        _refresh_runner_ownership_snapshot(runner_id, worktree_path_str, action="retry-merge")
        action_name = RetryAction.APPROVED_RETRY.value if approved_service_lock else "retry-merge"
        merge_result = _execute_merge_with_lock(runner_id, redis_client, action_name=action_name)
        result = merge_result

    except Exception as e:
        logger.error(f"[_do_retry_merge] 실패: {e}")
        result = {"success": False, "message": str(e), "action": "retry-merge"}

    finally:
        if flag_written:
            _clear_service_lock_approved_flag(redis_client, runner_id)
        _log_memory_stage("retry-merge", "end", runner_id, redis_client)
        _cleanup_process_state(runner_id, redis_client)
        redis_client.lpush(result_key, json.dumps(result, ensure_ascii=False))
        redis_client.expire(result_key, 60)


def retry_merge(command: Dict, redis_client: redis.Redis) -> None:
    """머지 충돌 후 재머지 시도 — 즉시 accepted 반환, 실제 작업은 백그라운드 스레드"""
    runner_id = command.get("runner_id", "")
    command_id = command.get("command_id", "")
    if not runner_id:
        return {"success": False, "message": "runner_id required"}
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    accepted = {
        "success": True,
        "message": "accepted",
        "runner_id": runner_id,
        "action": "retry-merge",
        "executed_at": datetime.now().isoformat(),
    }
    redis_client.lpush(result_key, json.dumps(accepted, ensure_ascii=False))
    redis_client.expire(result_key, 60)
    logger.info(f"[retry_merge] accepted 응답 즉시 반환 (runner_id: {runner_id})")
    thread = threading.Thread(
        target=_do_retry_merge,
        args=(runner_id, redis_client, command_id, command),
        daemon=False,
    )
    thread.start()
    return None


def _do_direct_merge(branch: str, worktree_path_str, plan_file, redis_client: redis.Redis, command_id: str, approve_service_lock: bool = False) -> None:
    """direct-merge 실제 작업 (백그라운드 스레드에서 실행) — 임시 runner_id로 _do_inline_merge 호출"""
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    from uuid import uuid4

    runner_id = f"dm-{uuid4().hex[:8]}"
    result = {"success": False, "message": "unknown error", "action": "direct-merge", "runner_id": runner_id}
    logger.info(f"[direct_merge] _do_direct_merge 스레드 진입: runner_id={runner_id}, branch={branch}, worktree={worktree_path_str}")
    _log_memory_stage("direct-merge", "start", runner_id, redis_client)
    flag_written = False

    try:
        # worktree_path 결정
        if worktree_path_str:
            worktree_path = Path(worktree_path_str).resolve()
        else:
            # branch 이름으로 추론 (runner/{id} → runner_{id} 변환)
            branch_slug = branch.replace("/", "_")
            worktree_path = WORKTREE_BASE_DIR / branch_slug
            if not worktree_path.is_dir():
                # git worktree list --porcelain 으로 branch 매칭 (monitor-page + wtools 모두 스캔)
                worktree_path_str = None
                _scan_roots = [PROJECT_ROOT, WTOOLS_BASE_DIR]
                for _scan_root in _scan_roots:
                    proc = subprocess.run(
                        ["git", "worktree", "list", "--porcelain"],
                        capture_output=True, text=True, cwd=str(_scan_root)
                    )
                    lines = proc.stdout.splitlines()
                    i = 0
                    while i < len(lines):
                        if lines[i].startswith("worktree "):
                            wt_path = lines[i][len("worktree "):]
                            branch_line = lines[i + 2] if i + 2 < len(lines) else ""
                            if f"branch refs/heads/{branch}" in branch_line:
                                worktree_path_str = wt_path
                                break
                        i += 1
                    if worktree_path_str:
                        break
                if worktree_path_str:
                    worktree_path = Path(worktree_path_str)
                else:
                    logger.error(f"[direct_merge] worktree not found for branch: {branch}")
                    result = {"success": False, "message": f"worktree not found for branch: {branch}", "action": "direct-merge", "runner_id": runner_id}
                    return

        if not worktree_path.is_dir():
            logger.error(f"[direct_merge] worktree dir not found: {worktree_path} (원본: {worktree_path_str})")
            result = {"success": False, "message": f"worktree dir not found: {worktree_path}", "action": "direct-merge", "runner_id": runner_id}
            return

        # 최소 Redis 키 세팅
        now_iso = datetime.now().isoformat()
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", str(worktree_path))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", now_iso)
        _transition_merge_status(redis_client, runner_id, QUEUED, action="direct-merge")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        if plan_file:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
        if approve_service_lock:
            _set_service_lock_approved_flag(redis_client, runner_id)
            flag_written = True
        # TTL 설정 (24시간)
        for suffix in ("status", "worktree_path", "branch", "start_time", "merge_status", "plan_file", "trigger"):
            redis_client.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", RECENT_RUNNERS_TTL)
        # SSE가 감지하도록 active_runners 등록
        redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        logger.info(f"[direct_merge] 임시 runner {runner_id} 생성, branch={branch}, worktree={worktree_path}")

        # _do_inline_merge 호출 (lock+cleanup+로그 발행 포함)
        _log_memory_stage("direct-merge", "mid", runner_id, redis_client)
        _refresh_runner_ownership_snapshot(runner_id, worktree_path, action="direct-merge")
        _do_inline_merge(runner_id, redis_client)

        # 머지 결과 읽기
        final_status = _redis_text(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")) or "unknown"
        reason = _redis_text(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_reason"))
        quarantine_diff_path = _redis_text(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:quarantine_diff_path"))
        success = final_status == "merged"
        result = {
            "success": success,
            "message": f"direct-merge 완료: {final_status}",
            "merge_status": final_status,
            "action": "direct-merge",
            "runner_id": runner_id,
        }
        if reason:
            result["reason"] = reason
        if quarantine_diff_path:
            result["quarantine_diff_path"] = quarantine_diff_path

    except Exception as e:
        import traceback
        logger.error(f"[direct_merge] 실패: {e}\n{traceback.format_exc()}")
        result = {"success": False, "message": str(e), "action": "direct-merge", "runner_id": runner_id}
    finally:
        if flag_written:
            _clear_service_lock_approved_flag(redis_client, runner_id)
        _log_memory_stage("direct-merge", "end", runner_id, redis_client)
        # merge_status Redis 키 보장 (스레드 실패 시에도 상태 추적 가능)
        try:
            current_ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            current_text = _redis_text(current_ms) or ""
            if current_text and current_text not in TERMINAL_STATUSES:
                final_ms = ERROR if not result.get("success") else current_text
                _transition_merge_status(redis_client, runner_id, final_ms, action="direct-merge")
                redis_client.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", RECENT_RUNNERS_TTL)
        except Exception:
            pass
        # SSE 채널에 최종 결과 publish
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        status_msg = result.get("message", "unknown")
        _publish_with_retry(redis_client, log_channel, f"[MERGE] direct-merge 최종 결과: {status_msg}")
        redis_client.lpush(result_key, json.dumps(result, ensure_ascii=False))
        redis_client.expire(result_key, 60)


def direct_merge(command: Dict, redis_client: redis.Redis) -> None:
    """branch/worktree 기반 직접 머지 — 러너 없이 머지 재시도. 즉시 accepted 반환, 실제 작업은 백그라운드 스레드"""
    branch = command.get("branch", "")
    if not branch:
        return {"success": False, "message": "branch required"}

    worktree_path = command.get("worktree_path")
    plan_file = command.get("plan_file")
    command_id = command.get("command_id", "")
    approve_service_lock = bool(command.get("approve_service_lock"))

    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    accepted = {
        "success": True,
        "message": "accepted",
        "branch": branch,
        "action": "direct-merge",
        "executed_at": datetime.now().isoformat(),
    }
    redis_client.lpush(result_key, json.dumps(accepted, ensure_ascii=False))
    redis_client.expire(result_key, 60)
    logger.info(f"[direct_merge] accepted 응답 즉시 반환 (branch: {branch})")
    thread = threading.Thread(
        target=_do_direct_merge,
        args=(branch, worktree_path, plan_file, redis_client, command_id, approve_service_lock),
        daemon=False,
    )
    thread.start()
    return None


def _do_resolve_conflict(runner_id: str, redis_client: redis.Redis, command_id: str) -> None:
    """resolve-conflict 실제 작업 (백그라운드 스레드에서 실행)."""
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    try:
        if _is_service_lock_approval_required(redis_client, runner_id):
            result = {
                "success": False,
                "message": (
                    "service_lock은 conflict가 아니라 런타임 안전성 게이트이므로 resolve-conflict 대상이 아닙니다. "
                    "NSSM 서비스로 실행 중인 파일을 덮어쓰는 위험을 차단하는 precheck입니다. "
                    "서비스 다운타임을 허용하는 경우 retry-merge에 approve_service_lock=true를 설정하여 승인하세요."
                ),
                "merge_status": "approval_required",
                "reason": "service_lock",
                "action": "resolve-conflict",
            }
            redis_client.lpush(result_key, json.dumps(result, ensure_ascii=False))
            redis_client.expire(result_key, 60)
            return
        worktree_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
        if not worktree_path_str:
            result = {"success": False, "message": f"worktree_path not found for runner {runner_id}"}
            redis_client.lpush(result_key, json.dumps(result, ensure_ascii=False))
            redis_client.expire(result_key, 60)
            return

        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        if plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
            plan_file = None

        # branch 계산
        branch_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")
        if branch_str:
            branch = branch_str
        elif plan_file:
            branch = f"plan/{Path(plan_file).stem}"
        else:
            branch = f"runner/{runner_id}"

        _transition_merge_status(redis_client, runner_id, RESOLVING, action="resolve-conflict")

        resolve_result = _launch_conflict_resolver_process(
            runner_id, branch, Path(worktree_path_str), redis_client,
            engine=_get_fix_engine(redis_client, runner_id)
        )

        if resolve_result["success"]:
            _transition_merge_status(redis_client, runner_id, MERGED, action="resolve-conflict", message="충돌 자동 해결 완료")
            result = {"success": True, "message": "충돌 자동 해결 완료", "action": "resolve-conflict"}
        else:
            _transition_merge_status(redis_client, runner_id, CONFLICT, action="resolve-conflict", message=resolve_result["message"])
            result = {"success": False, "message": resolve_result["message"], "action": "resolve-conflict"}
    except Exception as e:
        logger.error(f"[resolve_conflict] 실패: {e}")
        result = {"success": False, "message": str(e), "action": "resolve-conflict"}
    redis_client.lpush(result_key, json.dumps(result, ensure_ascii=False))
    redis_client.expire(result_key, 60)


def resolve_conflict(command: Dict, redis_client: redis.Redis) -> None:
    """충돌 자동 해결 — 즉시 accepted 반환, 실제 작업은 백그라운드 스레드"""
    runner_id = command.get("runner_id", "")
    command_id = command.get("command_id", "")
    if not runner_id:
        return {"success": False, "message": "runner_id required"}
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    accepted = {
        "success": True,
        "message": "accepted",
        "runner_id": runner_id,
        "action": "resolve-conflict",
        "executed_at": datetime.now().isoformat(),
    }
    redis_client.lpush(result_key, json.dumps(accepted, ensure_ascii=False))
    redis_client.expire(result_key, 60)
    logger.info(f"[resolve_conflict] accepted 응답 즉시 반환 (runner_id: {runner_id})")
    thread = threading.Thread(
        target=_do_resolve_conflict,
        args=(runner_id, redis_client, command_id),
        daemon=False,
    )
    thread.start()
    return None


def _do_cleanup_worktree(runner_id: str, redis_client: redis.Redis, command_id: str) -> None:
    """cleanup-worktree 실제 작업 (백그라운드 스레드에서 실행)"""
    from worktree_manager import WorktreeManager
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    try:
        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        if plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
            plan_file = None
        _cw_base = (get_plan_git_root(plan_file) / ".worktrees") if plan_file else WORKTREE_BASE_DIR
        WorktreeManager.remove(runner_id, _cw_base, plan_file=plan_file or None)
        redis_client.delete(
            f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status",
        )
        logger.info(f"[cleanup_worktree] 정리 완료: {runner_id}")
        result = {"success": True, "message": f"worktree {runner_id} 정리 완료", "action": "cleanup-worktree"}
    except Exception as e:
        logger.error(f"[cleanup_worktree] 실패: {e}")
        result = {"success": False, "message": str(e), "action": "cleanup-worktree"}
    redis_client.lpush(result_key, json.dumps(result, ensure_ascii=False))
    redis_client.expire(result_key, 60)


def cleanup_worktree(command: Dict, redis_client: redis.Redis) -> None:
    """worktree 수동 정리 — 즉시 accepted 반환, 실제 작업은 백그라운드 스레드"""
    runner_id = command.get("runner_id", "")
    command_id = command.get("command_id", "")
    if not runner_id:
        return {"success": False, "message": "runner_id required"}
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    accepted = {
        "success": True,
        "message": "accepted",
        "runner_id": runner_id,
        "action": "cleanup-worktree",
        "executed_at": datetime.now().isoformat(),
    }
    redis_client.lpush(result_key, json.dumps(accepted, ensure_ascii=False))
    redis_client.expire(result_key, 60)
    logger.info(f"[cleanup_worktree] accepted 응답 즉시 반환 (runner_id: {runner_id})")
    thread = threading.Thread(
        target=_do_cleanup_worktree,
        args=(runner_id, redis_client, command_id),
        daemon=False,
    )
    thread.start()
    return None


# [DEPRECATED] start_merge_orchestrator — 인라인 merge(_do_inline_merge)로 대체됨
def start_merge_orchestrator(redis_client: redis.Redis) -> Dict:
    """[DEPRECATED] merge 로직이 _stream_output finally 블록으로 인라인화됨."""
    return {"success": False, "message": "Deprecated: merge is now handled inline in _stream_output"}


def _reconnect_surviving_merge_orchestrator(redis_client: redis.Redis):
    """[DEPRECATED] MergeOrchestrator 제거됨 — 아무것도 하지 않음."""
    pass


def stop_merge_orchestrator(redis_client: redis.Redis) -> Dict:
    """[DEPRECATED] MergeOrchestrator 제거됨 — 인라인 merge로 대체. 호환성 유지용."""
    return {"success": False, "message": "Deprecated: MergeOrchestrator removed, merge is now inline"}
