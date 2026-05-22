"""_dr_process_utils.py ??dev-runner process utility module"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import logging
import os
import re
import sys
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, IO

import redis

from _dr_constants import (
    RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, PLAN_FILE_ALL, _LEGACY_ALL,
    LOG_CHANNEL_PREFIX, MERGE_ACTIVE_STATUSES, WORKTREE_BASE_DIR,
    RECENT_RUNNERS_TTL, RUNNER_KEY_SUFFIXES, PROJECT_ROOT, RECENT_META_TTL,
    OWNERSHIP_SNAPSHOT_DIR, SUBPROCESS_HEARTBEAT_TTL,
    REROUTE_REQUIRED_PATH_KEY, ROOT_DIRTY_CLOSEOUT_STATUS_KEY, ROOT_DIRTY_PATHS_KEY,
    ROOT_DIRTY_STATUS_BLOCKED,
)
from _dr_plan_paths import classify_plan_stage, read_plan_status
from _dr_merge_persistence import MergePersistence
from _dr_merge_state import ERROR, RESIDUE_BLOCKED, RetryAction
from _dr_test_repo_root import read_runner_test_repo_root
from _dr_state import (
    get_running_processes, get_running_log_files, get_stream_threads,
    get_cleanup_done, get_dead_process_first_seen, get_wf_manager,
)
from _dr_log_framing import MultilineFrameBuffer
from _dr_subprocess import _ANSI_ESCAPE
from _dr_runtime_utils import _normalize_exit_reason, _publish_with_retry
from _dr_runner_predicates import (
    _is_user_visible_trigger,
    _is_pre_review_stopped_runner,
    _is_pid_alive,
    _parse_start_elapsed_seconds,
    _is_recent_runner_without_hb,
    _runner_identity_matches,
)

logger = logging.getLogger(__name__)


def _decode_recent_meta_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _build_recent_runner_meta(
    redis_client: redis.Redis,
    runner_id: str,
    *,
    trigger,
    plan_file,
) -> dict:
    meta = {}
    for field, value in (
        ("trigger", trigger),
        ("plan_file", plan_file),
        ("engine", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine")),
        ("execution_count", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:execution_count")),
        ("log_file_path", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")),
        ("stream_log_path", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")),
        ("exit_reason", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason")),
        ("worktree_exists", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_exists")),
        ("branch_exists", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch_exists")),
        ("branch_merged_to_main", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch_merged_to_main")),
        ("metadata_checked_at", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:metadata_checked_at")),
        ("gate_evidence_summary", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:gate_evidence_summary")),
        ("merge_status", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")),
        ("merge_reason", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_reason")),
        ("merge_message", redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_message")),
        (ROOT_DIRTY_CLOSEOUT_STATUS_KEY, redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:{ROOT_DIRTY_CLOSEOUT_STATUS_KEY}")),
        (ROOT_DIRTY_PATHS_KEY, redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:{ROOT_DIRTY_PATHS_KEY}")),
        (REROUTE_REQUIRED_PATH_KEY, redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:{REROUTE_REQUIRED_PATH_KEY}")),
    ):
        if value is not None:
            meta[field] = _decode_recent_meta_value(value)
    if plan_file:
        meta["display_plan_name"] = Path(str(plan_file)).name
    for field in ("accepted_at", "started_at"):
        value = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:{field}")
        if value is not None:
            meta[field] = _decode_recent_meta_value(value)
    return meta


def _register_completed_runner_state(
    redis_client: redis.Redis,
    runner_id: str,
    *,
    trigger,
    plan_file,
) -> None:
    from _dr_constants import RECENT_RUNNERS_KEY

    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
    persist_suffixes = frozenset({"plan_file", "branch", "trigger"})
    for suffix in RUNNER_KEY_SUFFIXES:
        if suffix in persist_suffixes:
            continue
        redis_client.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", RECENT_RUNNERS_TTL)
    redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)

    meta = _build_recent_runner_meta(
        redis_client,
        runner_id,
        trigger=trigger,
        plan_file=plan_file,
    )
    if meta:
        import json as _json

        redis_client.setex(
            f"plan-runner:recent-meta:{runner_id}",
            RECENT_META_TTL,
            _json.dumps(meta, ensure_ascii=False),
        )
        logger.debug(f"[cleanup] saved recent-meta (runner_id={runner_id})")

    if trigger in ("user", "user:all"):
        redis_client.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})
        logger.info(f"[cleanup] registered in RECENT: {runner_id}")


def _parse_trigger_from_runner_log(log_file_path: str | None) -> str | None:
    if not log_file_path:
        return None
    try:
        with open(log_file_path, "r", encoding="utf-8", errors="ignore") as f:
            for _ in range(15):
                line = f.readline()
                if not line:
                    break
                if line.startswith("[TRIGGER] "):
                    return line[len("[TRIGGER] "):].split(" | ", 1)[0].strip() or None
    except (OSError, IOError):
        return None
    return None


def _record_worktree_cleanup_monitor_event(
    *,
    event_type: str,
    branches: list[str],
    runner_id: str | None = None,
    test_source: str | None = None,
    worktree_path: str | None = None,
    repo_root: Path | str | None = None,
) -> None:
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from app.shared.process.worktree_residue_monitor import WorktreeResidueMonitor

        WorktreeResidueMonitor.record_cleanup(
            event_type=event_type,
            branches=branches,
            source="_dr_process_utils",
            runner_id=runner_id,
            test_source=test_source,
            worktree_path=worktree_path,
            repo_root=repo_root,
        )
    except Exception as exc:
        logger.debug("[cleanup] worktree residue monitor record skipped: %s", exc)


def _mark_root_impl_scope_blocked(redis_client: redis.Redis, runner_id: str, message: str) -> None:
    if "root_worktree_impl_scope_blocked" not in (message or ""):
        return
    try:
        MergePersistence(redis_client, runner_id).transition(
            RESIDUE_BLOCKED,
            reason="root_worktree_impl_scope_blocked",
            message=message[:500],
            action=RetryAction.APPROVED_RETRY.value,
        )
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:{ROOT_DIRTY_CLOSEOUT_STATUS_KEY}", ROOT_DIRTY_STATUS_BLOCKED)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:done_post_merge_status", "failed")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:done_post_merge_error", "root_worktree_impl_scope_blocked")
    except Exception:
        logger.debug("[cleanup] root impl scope blocked metadata persist failed", exc_info=True)


def _force_cleanup_test_runner_worktree(runner_id: str, redis_client: redis.Redis) -> bool:
    """test_source가 있는 runner의 worktree/branch를 강제 정리한다."""
    test_source = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:test_source")
    test_source = _decode_recent_meta_value(test_source)
    if not test_source:
        return False

    repo_root = read_runner_test_repo_root(redis_client, runner_id, project_root=PROJECT_ROOT) or PROJECT_ROOT
    worktree_path = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
    worktree_path = _decode_recent_meta_value(worktree_path)
    branch = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch") or f"runner/{runner_id}"
    branch = _decode_recent_meta_value(branch) or f"runner/{runner_id}"

    if not worktree_path:
        worktree_path = str((repo_root / ".worktrees") / runner_id)

    logger.info(
        "[cleanup][test_source=%s] forcing worktree cleanup for runner=%s branch=%s path=%s",
        test_source,
        runner_id,
        branch,
        worktree_path,
    )

    try:
        remove_result = subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(repo_root),
            timeout=15,
        )
        remove_err = (remove_result.stderr or "").strip()
        if remove_result.returncode != 0 and "not a working tree" not in remove_err and "is not a working tree" not in remove_err:
            logger.warning(
                "[cleanup][test_source=%s] worktree remove failed: runner=%s err=%s",
                test_source,
                runner_id,
                remove_err or remove_result.stdout.strip(),
            )
    except Exception as exc:
        logger.warning(
            "[cleanup][test_source=%s] worktree remove exception: runner=%s error=%s",
            test_source,
            runner_id,
            exc,
        )

    try:
        branch_result = subprocess.run(
            ["git", "branch", "-D", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(repo_root),
            timeout=15,
        )
        branch_err = (branch_result.stderr or "").strip()
        if branch_result.returncode != 0 and "not found" not in branch_err:
            logger.warning(
                "[cleanup][test_source=%s] branch delete failed: runner=%s branch=%s err=%s",
                test_source,
                runner_id,
                branch,
                branch_err or branch_result.stdout.strip(),
            )
    except Exception as exc:
        logger.warning(
            "[cleanup][test_source=%s] branch delete exception: runner=%s branch=%s error=%s",
            test_source,
            runner_id,
            branch,
            exc,
        )

    _record_worktree_cleanup_monitor_event(
        event_type="force_cleanup",
        branches=[branch],
        runner_id=runner_id,
        test_source=str(test_source),
        worktree_path=str(worktree_path),
        repo_root=repo_root,
    )

    return True


def _cleanup_runner_ownership_snapshot(runner_id: str) -> None:
    """runner ownership snapshot 단일 truth 파일을 정리한다."""
    try:
        ownership_snapshot = OWNERSHIP_SNAPSHOT_DIR / f"{runner_id}.json"
        if ownership_snapshot.exists():
            ownership_snapshot.unlink()
    except Exception as e:
        logger.debug(f"[cleanup] ownership snapshot cleanup failed (ignoring): {e}")


def _try_v2_merge_fallback(runner_id: str, redis_client: redis.Redis, reason_tag: str) -> bool:
    """v2 merge fallback helper ??detect -> handle pattern."""
    try:
        from _dr_merge import detect_merged_but_not_done as _dmnd, _handle_post_merge_done as _hpmd, _pub_and_log as _pal
        detect_result = _dmnd(runner_id, redis_client)
        if detect_result:
            logger.info(f"[{reason_tag}] v2 merge fallback executing (runner_id={runner_id})")
            try:
                def _pub(msg: str, _rid=runner_id) -> None:
                    _pal(_rid, msg, redis_client, "MERGE-FALLBACK")
                done_result = _hpmd(detect_result["plan_file"], runner_id, _pub, redis_client)
                if isinstance(done_result, dict) and not done_result.get("success", True):
                    reason = str(done_result.get("reason") or done_result.get("status") or "done_post_merge_failed")
                    merge_status = RESIDUE_BLOCKED if reason == "residue_guard" else ERROR
                    quarantine_diff_path = done_result.get("quarantine_diff_path")
                    try:
                        MergePersistence(redis_client, runner_id).transition(
                            merge_status,
                            reason=reason,
                            message=f"{reason_tag} fallback done failed: {reason}",
                            action=RetryAction.APPROVED_RETRY.value,
                        )
                        if quarantine_diff_path:
                            redis_client.set(
                                f"{RUNNER_KEY_PREFIX}:{runner_id}:quarantine_diff_path",
                                str(quarantine_diff_path),
                            )
                    except Exception:
                        pass

                    try:
                        wf_manager = get_wf_manager()
                        if wf_manager:
                            wf = wf_manager.get_by_runner_id(runner_id)
                            if wf:
                                wf_manager.update_status(
                                    wf["id"],
                                    "failed",
                                    error_message=f"{reason_tag} fallback done failed: {reason}"[:500],
                                )
                    except Exception:
                        pass

                    error_message = f"{reason_tag} fallback done failed: {reason}"
                    if quarantine_diff_path and str(quarantine_diff_path) not in error_message:
                        error_message = f"{error_message} [{quarantine_diff_path}]"
                    _pal(runner_id, error_message[:500], redis_client, "MERGE-FALLBACK")
            except Exception as _handle_err:
                logger.warning(f"[{reason_tag}] v2 merge fallback failed (continuing cleanup): {_handle_err}")
            return False
        return False
    except Exception as _det_err:
        logger.debug(f"[{reason_tag}] v2 detect failed (ignoring): {_det_err}")
        return False


def _evict_stale_cleanup_done(max_age: int = 300) -> None:
    """Evict items older than max_age from _cleanup_done"""
    _cleanup_done = get_cleanup_done()
    now = time.time()
    expired = [rid for rid, ts in list(_cleanup_done.items()) if now - ts > max_age]
    if expired:
        logger.debug(f"heartbeat: _cleanup_done evicting {len(expired)}: {expired}")
        for rid in expired:
            _cleanup_done.pop(rid, None)


def _evict_stale_dead_process(max_age: int = 300) -> None:
    """Evict items older than max_age from _dead_process_first_seen"""
    _dead_process_first_seen = get_dead_process_first_seen()
    now = time.time()
    expired = [rid for rid, ts in list(_dead_process_first_seen.items()) if now - ts > max_age]
    if expired:
        logger.debug(f"heartbeat: _dead_process_first_seen evicting {len(expired)}: {expired}")
        for rid in expired:
            _dead_process_first_seen.pop(rid, None)


def get_plan_git_root(plan_file: str) -> Path:
    """Dynamically detect git root of a plan file."""
    try:
        plan_path = Path(plan_file)
        cwd = str(plan_path.parent) if plan_path.parent.is_dir() else str(plan_path.parent.parent)
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=cwd, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception as e:
        logger.warning(f"get_plan_git_root: git rev-parse failed (plan={plan_file}): {e}")
    logger.warning(f"get_plan_git_root: fallback to PROJECT_ROOT (plan={plan_file})")
    return PROJECT_ROOT


def get_target_project_root(plan_file: str) -> Path:
    """plan file의 target project root를 반환 (plans storage root와 분리).

    우선순위:
    1. env PLAN_RUNNER_PROJECT_ROOT
    2. git rev-parse --show-toplevel + .worktrees 감지 시 .worktrees 직전 반환
    3. fallback: PROJECT_ROOT
    """
    env_root = os.environ.get("PLAN_RUNNER_PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()

    try:
        plan_path = Path(plan_file)
        cwd = str(plan_path.parent) if plan_path.parent.is_dir() else str(plan_path.parent.parent)
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=cwd, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            git_root = Path(result.stdout.strip())
            parts = list(git_root.parts)
            if ".worktrees" in parts:
                i = parts.index(".worktrees")
                candidate = Path(*parts[:i])
                if (candidate / ".git").exists():
                    logger.debug(
                        f"get_target_project_root: .worktrees 감지 → {git_root} → {candidate}"
                    )
                    return candidate
            return git_root
    except Exception as e:
        logger.warning(f"get_target_project_root: git rev-parse failed (plan={plan_file}): {e}")

    logger.warning(f"get_target_project_root: fallback to PROJECT_ROOT (plan={plan_file})")
    return PROJECT_ROOT


def _cleanup_process_state(runner_id: str, redis_client: redis.Redis, reason: str = "process_cleanup"):
    """Cleanup global process variables + Redis state (per-runner) + Workflow DB"""
    _running_processes = get_running_processes()
    _running_log_files = get_running_log_files()
    _stream_threads = get_stream_threads()
    _cleanup_done = get_cleanup_done()
    _dead_process_first_seen = get_dead_process_first_seen()
    _wf_manager = get_wf_manager()

    # set cleanup_in_progress flag (TTL 30s)
    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:cleanup_in_progress", "1", ex=30)
    except Exception:
        pass

    # handle pre-review stopped case (reconnect/heartbeat common)
    if reason and reason.startswith(("reconnect_", "heartbeat_", "no_log_file")):
        if _is_pre_review_stopped_runner(runner_id, redis_client):
            reason = "pre_review_stopped"

    # Merge guard: if reason starts with reconnect_* or heartbeat_*, deny cleanup if merge is in progress
    if reason and reason.startswith(("reconnect_", "heartbeat_")):
        try:
            merge_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            if merge_status in MERGE_ACTIVE_STATUSES or merge_status == "approval_required":
                logger.warning(
                    f"[cleanup] denying cleanup for runner {runner_id} (merge in progress) "
                    f"(reason={reason}, merge_status={merge_status})"
                )
                return
        except Exception as _guard_err:
            logger.debug(f"[cleanup] merge guard check failed (ignoring): {_guard_err}")

    # approval_required universal guard: read merge_status early to protect queue position
    _ar_guard_ms = None
    try:
        _raw = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        _ar_guard_ms = _raw.decode("utf-8", errors="replace") if isinstance(_raw, bytes) else (_raw or "")
    except Exception:
        pass

    # release merge turn if process died (skip for approval_required — user must act first)
    _repo_id = None
    if _ar_guard_ms != "approval_required":
        try:
            from merge_queue import release_merge_turn, _get_repo_id
            _repo_id = _get_repo_id(PROJECT_ROOT)
            release_merge_turn(redis_client, runner_id, repo_id=_repo_id)
        except Exception:
            pass
    else:
        logger.warning(
            f"[cleanup] approval_required: preserving merge turn position (runner={runner_id}, reason={reason})"
        )

    # remove from queue (skip for approval_required)
    if _ar_guard_ms != "approval_required":
        try:
            from merge_queue import get_queue_key, _get_repo_id
            if _repo_id is None:
                _repo_id = _get_repo_id(PROJECT_ROOT)
            redis_client.lrem(get_queue_key(_repo_id), 0, runner_id)
        except Exception:
            pass

    _running_processes.pop(runner_id, None)
    _running_log_files.pop(runner_id, None)
    _dead_process_first_seen.pop(runner_id, None)
    _cleanup_done[runner_id] = time.time()
    if runner_id in _stream_threads:
        t = _stream_threads.pop(runner_id)
        if t.is_alive() and t != threading.current_thread():
            t.join(timeout=3)
        elif t == threading.current_thread():
            logger.debug(f"[cleanup] skip self-join (runner_id={runner_id})")

    # Capture state before possible key deletion
    try:
        merge_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        merge_status = _decode_recent_meta_value(merge_status)
        merge_reason = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_reason")
        merge_reason = _decode_recent_meta_value(merge_reason)
        claim_id_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:claim_id")
        if isinstance(claim_id_val, bytes):
            claim_id_val = claim_id_val.decode("utf-8", errors="replace")
        if claim_id_val == "":
            claim_id_val = None
        plan_file_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        plan_file_val = _decode_recent_meta_value(plan_file_val)
        if plan_file_val in (PLAN_FILE_ALL, _LEGACY_ALL):
            plan_file_val = None
        _trigger_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger")
        _trigger_val = _decode_recent_meta_value(_trigger_val)
        if _trigger_val is None:
            _trigger_val = _parse_trigger_from_runner_log(
                redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
                or redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")
            )
        merge_requested = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
        merge_requested = _decode_recent_meta_value(merge_requested)
        test_source_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:test_source")
        test_source_val = _decode_recent_meta_value(test_source_val)
        branch_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")
        branch_val = _decode_recent_meta_value(branch_val)
        worktree_path_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
        worktree_path_val = _decode_recent_meta_value(worktree_path_val)
        root_dirty_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:{ROOT_DIRTY_CLOSEOUT_STATUS_KEY}")
        root_dirty_status = _decode_recent_meta_value(root_dirty_status)
        error_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:error")
        error_val = _decode_recent_meta_value(error_val)
        if isinstance(error_val, str) and "root_worktree_impl_scope_blocked" in error_val:
            _mark_root_impl_scope_blocked(redis_client, runner_id, error_val)
            merge_status = RESIDUE_BLOCKED
            root_dirty_status = ROOT_DIRTY_STATUS_BLOCKED
        force_test_cleanup = bool(test_source_val) and (
            (isinstance(branch_val, str) and branch_val.startswith("runner/t-"))
            or (
                runner_id.startswith("t-")
                and isinstance(worktree_path_val, str)
                and Path(worktree_path_val).name == runner_id
            )
        )
    except Exception as e:
        logger.warning(f"[cleanup] state capture failed (runner_id={runner_id}): {e}")
        merge_status = None
        merge_reason = None
        claim_id_val = None
        plan_file_val = None
        _trigger_val = None
        merge_requested = None
        root_dirty_status = None
        force_test_cleanup = False

    # 1) register stopped runner in RECENT_RUNNERS
    try:
        _register_completed_runner_state(
            redis_client,
            runner_id,
            trigger=_trigger_val,
            plan_file=plan_file_val,
        )
    except Exception as e:
        logger.warning(f"[cleanup] RECENT registration failed (runner_id={runner_id}): {e}")

    # publish completed signal
    try:
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        exit_reason = _normalize_exit_reason(
            redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason")
        )
        _publish_with_retry(redis_client, log_channel, f"__COMPLETED::{exit_reason}__")
    except Exception:
        pass

    # 2) worktree cleanup
    try:
        from worktree_manager import WorktreeManager
        from plan_worktree_helpers import is_plan_in_progress as _is_plan_in_progress
        from plan_worktree_helpers import has_unmerged_commits as _has_unmerged_commits

        test_repo_root = read_runner_test_repo_root(redis_client, runner_id, project_root=PROJECT_ROOT)
        _target_root = test_repo_root or (get_target_project_root(plan_file_val) if plan_file_val else WORKTREE_BASE_DIR.parent)
        _cleanup_worktree_base = _target_root / ".worktrees"

        preserve_test_cleanup = (
            merge_status in {"conflict", "approval_required", "residue_blocked"}
            or merge_reason in {"service_lock", "ownership_guard", "residue_guard", "root_dirty_reroute_required"}
        )
        if force_test_cleanup and not preserve_test_cleanup:
            _force_cleanup_test_runner_worktree(runner_id, redis_client)
            logger.info("[cleanup] test_source runner force-cleaned: %s", runner_id)
        elif force_test_cleanup:
            logger.warning(
                "[cleanup] test_source runner preserved: runner=%s merge_status=%s merge_reason=%s",
                runner_id,
                merge_status,
                merge_reason,
            )
            redis_client.persist(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
        else:
            _preserve_worktree = False
            if plan_file_val and _is_plan_in_progress(plan_file_val):
                _preserve_worktree = True
                logger.info(f"preserving worktree (plan in progress): {runner_id}")
                redis_client.persist(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")

            # unmerged commits protection
            if not _preserve_worktree:
                if plan_file_val:
                    _branch = branch_val or (
                        f"plan/{Path(plan_file_val).stem}"
                        if not runner_id.startswith("t-")
                        else f"runner/{runner_id}"
                    )
                else:
                    _branch = f"runner/{runner_id}"
                if _has_unmerged_commits(_branch, _target_root):
                    _preserve_worktree = True
                    logger.warning(
                        f"[cleanup] preserving worktree (unmerged commits exist): runner={runner_id}, branch={_branch}"
                    )
                    redis_client.persist(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")

            # ?뵶 [fix] merge_requested protection
            if merge_requested == "1":
                _preserve_worktree = True
                logger.warning(f"[_cleanup_process_state] merge_requested=1 -> preserving worktree (runner={runner_id})")
                redis_client.persist(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")

            # approval_required(service_lock) 보호: worktree를 제거하지 않고 사용자 승인 후 retry를 대기한다.
            if merge_status == "approval_required":
                _preserve_worktree = True
                logger.warning(
                    f"[_cleanup_process_state] merge_status=approval_required -> preserving worktree (runner={runner_id})"
                )
                redis_client.persist(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")

            if root_dirty_status in {"reroute_required", "blocked"}:
                _preserve_worktree = True
                logger.warning(
                    f"[_cleanup_process_state] root dirty closeout={root_dirty_status} -> preserving worktree (runner={runner_id})"
                )
                redis_client.persist(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")

            if not _preserve_worktree and merge_status not in ("pending_merge", "conflict", "queued", "approval_required"):
                try:
                    WorktreeManager.remove(
                        runner_id,
                        _cleanup_worktree_base,
                        plan_file=plan_file_val or None,
                        branch=branch_val or None,
                        use_runner_identity=runner_id.startswith("t-"),
                    )
                except Exception as wt_e:
                    logger.warning(f"worktree removal failed (runner_id: {runner_id}): {wt_e}")
            elif not _preserve_worktree and merge_status in ("merging", "testing"):
                try:
                    WorktreeManager.remove(
                        runner_id,
                        _cleanup_worktree_base,
                        plan_file=plan_file_val or None,
                        branch=branch_val or None,
                        use_runner_identity=runner_id.startswith("t-"),
                    )
                    logger.info(f"cleaning up stale intermediate worktree: {runner_id} (merge_status={merge_status})")
                except Exception as wt_e:
                    logger.warning(f"stale worktree cleanup failed (runner_id: {runner_id}): {wt_e}")
    except Exception as e:
        logger.warning(f"[cleanup] error during worktree cleanup (ignoring, runner_id={runner_id}): {e}")

    # Invisible runner final cleanup
    if _trigger_val not in ("user", "user:all"):
        try:
            _ar_preserve_suffixes = frozenset()
            if merge_status == "approval_required":
                _ar_preserve_suffixes = frozenset({
                    "merge_status", "merge_reason", "merge_message",
                    "worktree_path", "branch", "plan_file", "exit_reason",
                })
            if root_dirty_status in {"reroute_required", "blocked"}:
                _ar_preserve_suffixes = _ar_preserve_suffixes | frozenset({
                    "merge_status", "merge_reason", "merge_message",
                    "worktree_path", "branch", "plan_file", "exit_reason",
                    ROOT_DIRTY_CLOSEOUT_STATUS_KEY, ROOT_DIRTY_PATHS_KEY, REROUTE_REQUIRED_PATH_KEY,
                    "done_post_merge_status", "done_post_merge_error", "quarantine_diff_path",
                })
            for _suffix in RUNNER_KEY_SUFFIXES:
                if _suffix in _ar_preserve_suffixes:
                    continue
                redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:{_suffix}")
            logger.debug(f"[cleanup] invisible runner deleting keys: {runner_id} (trigger={_trigger_val!r})")
        except Exception:
            pass

    # Workflow DB updates
    try:
        if _wf_manager:
            wf = _wf_manager.get_by_runner_id(runner_id)
            if wf and wf["status"] in ("running", "merge_pending", "merging"):
                if merge_status == "approval_required":
                    if wf["status"] != "merge_pending":
                        _wf_manager.update_status(
                            wf["id"],
                            "merge_pending",
                            error_message=f"Cleanup preserved approval_required: {reason}",
                        )
                    logger.info(
                        f"[cleanup] workflow {wf['id']} preserved for approval_required (reason: {reason})"
                    )
                else:
                    _wf_manager.update_status(wf["id"], "failed", error_message=f"Cleanup: {reason}")
                    logger.info(f"[cleanup] workflow {wf['id']} -> failed (reason: {reason})")
    except Exception as e:
        logger.warning(f"[cleanup] workflow DB update failed (ignoring): {e}")

    _cleanup_runner_ownership_snapshot(runner_id)

    # ── Claim release (active/queued → released) ──────────────────────
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from app.database import SessionLocal as _ClaimSession
        from app.modules.dev_runner.services.plan_execution_claim_service import (
            get_active_claim_for_plan as _get_active_claim,
            get_active_claim_for_runner as _get_runner_claim,
            release_claim as _release_claim,
        )
        _claim_db = _ClaimSession()
        try:
            _claim = None
            if claim_id_val:
                _claim = type("_ClaimRef", (), {"claim_id": claim_id_val})()
            if _claim is None and plan_file_val:
                _claim = _get_active_claim(_claim_db, plan_file_val)
            if _claim is None:
                _claim = _get_runner_claim(_claim_db, runner_id)
            if _claim:
                _release_claim(_claim_db, _claim.claim_id)
                logger.info(
                    f"[claim] released: claim_id={_claim.claim_id} runner_id={runner_id} "
                    f"plan_file={plan_file_val or '(none)'} merge_status={merge_status or '(none)'} reason={reason}"
                )
        finally:
            _claim_db.close()
    except Exception as _claim_err:
        logger.warning(
            f"[claim] release 실패 (무시, runner_id={runner_id}, plan_file={plan_file_val or '(none)'}, "
            f"claim_id={claim_id_val or '(none)'}, merge_status={merge_status or '(none)'}, reason={reason}): {_claim_err}"
        )
    # ────────────────────────────────────────────────────────────────

    logger.info(f"[cleanup] _cleanup_process_state completed: {runner_id} (reason={reason})")

    # cleanup complete ??clear flag
    try:
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:cleanup_in_progress")
    except Exception:
        pass


class _DummyProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self.returncode: Optional[int] = None

    def poll(self) -> Optional[int]:
        if self.returncode is not None:
            return self.returncode
        if not _is_pid_alive(self.pid):
            self.returncode = -1
        return self.returncode


def _tail_log_and_publish(runner_id: str, log_path: str, redis_client: redis.Redis, replay_from_start: bool = False):
    """Tail log file and publish to Redis log channel"""
    _running_processes = get_running_processes()
    log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    frame_buffer = MultilineFrameBuffer(max_chars=8192)
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            if not replay_from_start:
                f.seek(0, 2)
            while True:
                if runner_id not in _running_processes:
                    break
                line = f.readline()
                if line:
                    stripped = _ANSI_ESCAPE.sub('', line.rstrip('\n'))
                    ready_frames, overflow = frame_buffer.push_line(stripped)
                    for frame in ready_frames:
                        _publish_with_retry(redis_client, log_channel, frame)
                else:
                    proc = _running_processes.get(runner_id)
                    if proc is not None and proc.poll() is not None:
                        time.sleep(0.3)
                        while True:
                            remaining = f.readline()
                            if not remaining:
                                break
                            _stripped = _ANSI_ESCAPE.sub('', remaining.rstrip('\n'))
                            if _stripped:
                                _ready, _overflow = frame_buffer.push_line(_stripped)
                                for _frame in _ready:
                                    _publish_with_retry(redis_client, log_channel, _frame)
                        pending = frame_buffer.flush()
                        if pending:
                            _publish_with_retry(redis_client, log_channel, pending)
                        break
                    time.sleep(0.2)
            pending = frame_buffer.flush()
            if pending:
                _publish_with_retry(redis_client, log_channel, pending)
    except FileNotFoundError:
        logger.warning(f"[tail_log] log file missing: {log_path}")
    except Exception as e:
        logger.error(f"[tail_log] thread error (runner_id={runner_id}): {e}")


def _monitor_pid_until_exit(runner_id: str, pid: int, redis_client: redis.Redis):
    """Monitor PID exit and call cleanup"""
    _running_processes = get_running_processes()
    _cleanup_done = get_cleanup_done()
    _stream_threads = get_stream_threads()
    while True:
        if runner_id not in _running_processes or runner_id in _cleanup_done:
            break
        if not _is_pid_alive(pid):
            proc = _running_processes.get(runner_id)
            if proc is not None and proc.poll() is None:
                logger.info(f"[monitor_pid] runner {runner_id} PID API dead but poll alive -> retrying in 3s")
                time.sleep(3)
                if runner_id not in _running_processes or runner_id in _cleanup_done:
                    break
                if _running_processes.get(runner_id, proc).poll() is None:
                    time.sleep(1)
                    continue
            if runner_id in _cleanup_done:
                break
            logger.info(f"[monitor_pid] runner {runner_id} PID {pid} exit detected -> waiting for tail thread")
            tail_thread = _stream_threads.get(runner_id)
            if tail_thread and tail_thread.is_alive():
                tail_thread.join(timeout=5)
            if runner_id in _cleanup_done:
                break
            logger.info(f"[monitor_pid] runner {runner_id} -> cleanup")
            _try_v2_merge_fallback(runner_id, redis_client, "monitor_pid")
            _cleanup_process_state(runner_id, redis_client, reason="heartbeat_pid_exit")
            break
        time.sleep(1)


def _attach_to_running_process(runner_id: str, pid: int, redis_client: redis.Redis):
    """Attach to existing plan-runner process on listener restart"""
    _running_processes = get_running_processes()
    _running_log_files = get_running_log_files()
    _stream_threads = get_stream_threads()

    log_file_path = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")
    if not log_file_path:
        log_file_path = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
    if not log_file_path or not Path(log_file_path).exists():
        logger.warning(f"[attach] runner {runner_id} log file missing -> cleanup")
        _try_v2_merge_fallback(runner_id, redis_client, "attach_no_log")
        _cleanup_process_state(runner_id, redis_client, reason="no_log_file")
        return

    dummy = _DummyProcess(pid)
    _running_processes[runner_id] = dummy
    _running_log_files[runner_id] = Path(log_file_path)

    tail_thread = threading.Thread(
        target=_tail_log_and_publish,
        args=(runner_id, log_file_path, redis_client, True),
        daemon=True,
    )
    tail_thread.start()
    _stream_threads[runner_id] = tail_thread

    monitor_thread = threading.Thread(
        target=_monitor_pid_until_exit,
        args=(runner_id, pid, redis_client),
        daemon=True,
    )
    monitor_thread.start()

    logger.info(f"[listener] restart detected: runner {runner_id} PID {pid} alive -> re-attached")


def _recover_pending_merge(runner_id: str, redis_client: redis.Redis, merge_status) -> None:
    """Recover pending merge on listener restart"""
    from merge_queue import release_merge_turn, _get_repo_id  # noqa: F401

    logger.info(f"[recover_merge] runner {runner_id} starting merge recovery (merge_status={merge_status})")

    try:
        if merge_status in ("merging", "resolving"):
            try:
                release_merge_turn(redis_client, runner_id, repo_id=_get_repo_id(PROJECT_ROOT))
                logger.info(f"[recover_merge] runner {runner_id} released stale merge lock (merge_status={merge_status})")
            except Exception as _e:
                logger.debug(f"[recover_merge] lock release failed (ignoring): {_e}")
            MergePersistence(redis_client, runner_id).transition(
                "pending_merge",
                reason="listener_restart_recovery",
                message="listener restart recovery queued merge retry",
                action=RetryAction.APPROVED_RETRY.value,
            )
            _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
            if not _mr:
                MergePersistence(redis_client, runner_id).request_merge()

        elif merge_status in ("queued", "pending_merge") or merge_status is None:
            _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
            if not _mr:
                MergePersistence(redis_client, runner_id).request_merge()
        else:
            logger.info(f"[recover_merge] runner {runner_id} merge_status={merge_status} -> no recovery needed")
            return

        from _dr_plan_runner import _do_inline_merge
        _do_inline_merge(runner_id, redis_client)

    except Exception as e:
        logger.warning(f"[recover_pending_merge] runner {runner_id} merge recovery failed: {e}")


def _process_runner_entry(
    runner_id: str,
    pid_str: Optional[str],
    redis_client: redis.Redis,
    *,
    is_orphan: bool = False,
) -> None:
    """Common logic for active runner or orphan key reconnect"""
    _running_processes = get_running_processes()
    _stream_threads = get_stream_threads()
    cleanup_reason = "reconnect_orphan_scan" if is_orphan else "reconnect_orphan"
    label = "orphan" if is_orphan else "runner"
    dead_pid_tag = "reconnect_orphan_dead_pid" if is_orphan else "reconnect_dead_pid"

    if not pid_str:
        try:
            _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
            _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        except Exception:
            _mr, _ms = None, None
        if _ms == "approval_required":
            logger.warning(f"[reconnect] {label} {runner_id} no PID but approval_required -> skip cleanup")
            return
        if _mr or _ms in MERGE_ACTIVE_STATUSES:
            logger.warning(
                f"[reconnect] {label} {runner_id} no PID but merge pending "
                f"(merge_requested={bool(_mr)}, merge_status={_ms}) -> _recover_pending_merge"
            )
            if not (runner_id in _stream_threads and _stream_threads[runner_id].is_alive()):
                t = threading.Thread(
                    target=_recover_pending_merge,
                    args=(runner_id, redis_client, _ms),
                    daemon=True,
                )
                t.start()
        else:
            logger.info(f"[reconnect] {label} {runner_id} no PID -> cleanup")
            if not is_orphan:
                _try_v2_merge_fallback(runner_id, redis_client, "reconnect_no_pid")
            _cleanup_process_state(runner_id, redis_client, reason=cleanup_reason)
        return

    try:
        pid = int(pid_str)
    except ValueError:
        logger.warning(f"[reconnect] {label} {runner_id} invalid PID: {pid_str!r} -> cleanup")
        _cleanup_process_state(runner_id, redis_client, reason=cleanup_reason)
        return

    if not is_orphan and runner_id in _running_processes:
        return

    if _is_pid_alive(pid):
        identity_ok, identity_reason = _runner_identity_matches(redis_client, runner_id, pid)
        if not identity_ok:
            try:
                from _dr_merge import _pub_and_log as _pal
                _pal(
                    runner_id,
                    f"{label} {runner_id} PID {pid} alive but identity check failed "
                    f"({identity_reason}) -> cleanup",
                    redis_client,
                    "RECONNECT",
                )
            except Exception:
                pass
            logger.warning(
                "[reconnect] %s %s PID=%s alive but identity check failed (%s) -> cleanup",
                label,
                runner_id,
                pid,
                identity_reason,
            )
            _cleanup_process_state(runner_id, redis_client, reason=f"reconnect_{identity_reason}")
            return

        try:
            redis_client.set(
                f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat",
                str(time.time()),
                ex=SUBPROCESS_HEARTBEAT_TTL,
            )
        except Exception as hb_err:
            logger.warning(
                "[reconnect] %s %s PID=%s identity=%s but heartbeat republish failed: %s",
                label,
                runner_id,
                pid,
                identity_reason,
                hb_err,
            )
        if is_orphan:
            logger.info(
                "[reconnect] %s %s PID %s alive identity=%s -> re-attached",
                label,
                runner_id,
                pid,
                identity_reason,
            )
        _attach_to_running_process(runner_id, pid, redis_client)
    else:
        try:
            _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
            _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        except Exception:
            _mr, _ms = None, None

        if _ms == "approval_required":
            logger.warning(f"[reconnect] {label} {runner_id} PID {pid} dead but approval_required -> skip cleanup")
            return
        if _mr or _ms in MERGE_ACTIVE_STATUSES:
            logger.warning(
                f"[reconnect] {label} {runner_id} PID {pid} dead but merge pending "
                f"(merge_requested={bool(_mr)}, merge_status={_ms}) -> skip cleanup"
            )
            if not (runner_id in _stream_threads and _stream_threads[runner_id].is_alive()):
                t = threading.Thread(
                    target=_recover_pending_merge,
                    args=(runner_id, redis_client, _ms),
                    daemon=True,
                )
                t.start()
        else:
            logger.info(f"[reconnect] {label} {runner_id} PID {pid} terminated -> cleanup")
            _try_v2_merge_fallback(runner_id, redis_client, dead_pid_tag)
            _cleanup_process_state(runner_id, redis_client, reason=cleanup_reason)


def _reconnect_surviving_runners(redis_client: redis.Redis):
    """Called once on listener start (or restart)"""
    try:
        runner_ids = redis_client.smembers(ACTIVE_RUNNERS_KEY)
    except Exception as e:
        logger.warning(f"[reconnect] active_runners lookup failed: {e}")
        return

    for runner_id in runner_ids:
        _r_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
        if _r_status == "stopped":
            _r_trigger = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger")
            if _is_user_visible_trigger(_r_trigger, runner_id):
                continue
        pid_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
        _process_runner_entry(runner_id, pid_str, redis_client, is_orphan=False)

    try:
        for key in redis_client.scan_iter(f"{RUNNER_KEY_PREFIX}:*:status"):
            prefix = f"{RUNNER_KEY_PREFIX}:"
            suffix = ":status"
            if not (key.startswith(prefix) and key.endswith(suffix)):
                continue
            orphan_id = key[len(prefix):-len(suffix)]
            if not orphan_id or orphan_id in runner_ids:
                continue
            _o_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:status")
            if _o_status == "stopped":
                _o_trigger = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:trigger")
                if _is_user_visible_trigger(_o_trigger, orphan_id):
                    continue
            pid_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:pid")
            _process_runner_entry(orphan_id, pid_str, redis_client, is_orphan=True)
    except Exception as e:
        logger.warning(f"[reconnect] orphan scan failed: {e}")


def _detect_orphan_workflows(redis_client: redis.Redis) -> int:
    """DB<->Redis cross-validation: transition running/merge_pending workflows not in active_runners to failed"""
    _wf_manager = get_wf_manager()
    if _wf_manager is None:
        return 0
    cleaned = 0
    try:
        for status in ("running", "merge_pending"):
            workflows = _wf_manager.list_workflows(status=status)
            for wf in workflows:
                runner_id = wf.get("runner_id")
                if not runner_id or redis_client.sismember(ACTIVE_RUNNERS_KEY, runner_id):
                    continue
                try:
                    _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
                    _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
                except Exception:
                    _mr, _ms = None, None
                if _ms == "approval_required" or _mr or _ms in MERGE_ACTIVE_STATUSES:
                    continue
                _wf_manager.update_status(
                    wf["id"], "failed",
                    error_message="orphan: listener 재시작 시 active_runners에 없음"
                )
                cleaned += 1
    except Exception as e:
        logger.warning(f"[orphan] workflow cross-validation failed: {e}")
    return cleaned


def _cleanup_orphan_plans(redis_client: redis.Redis) -> int:
    """plan file cross-validation: cleanup worktrees/branches without running workflow records"""
    from plan_worktree_helpers import is_worktree_active, has_unmerged_commits
    from worktree_manager import WorktreeManager
    from plan_worktree_helpers import remove_plan_header_fields as _remove_plan_header_fields

    _wf_manager = get_wf_manager()
    if _wf_manager is None:
        return 0
    cleaned_count = 0
    plan_dirs = [
        PROJECT_ROOT / ".worktrees" / "plans" / "docs" / "plan",
        PROJECT_ROOT / "docs" / "plan",
    ]
    existing_plan_dirs = [p for p in plan_dirs if p.is_dir()]
    if not existing_plan_dirs:
        return 0
    try:
        all_workflows = _wf_manager.list_workflows()
        active_statuses = {"running", "merge_pending", "merging"}
        basename_index: dict[str, list[dict]] = {}
        for wf in all_workflows:
            plan_file = wf.get("plan_file")
            if not plan_file:
                continue
            basename = Path(str(plan_file).replace("\\", "/")).name
            basename_index.setdefault(basename, []).append(wf)

        def _workflow_plan_matches(plan_path: Path, workflow_plan_file: str | None) -> bool:
            if not workflow_plan_file:
                return False
            stored = str(workflow_plan_file).replace("\\", "/").strip()
            if not stored or stored in {"ALL", "__ALL_PLANS__"}:
                return False

            candidates = []
            candidates.append(plan_path.as_posix())
            try:
                candidates.append(plan_path.resolve().as_posix())
            except Exception:
                pass
            try:
                candidates.append(plan_path.relative_to(PROJECT_ROOT).as_posix())
            except Exception:
                pass

            for candidate in candidates:
                if stored == candidate or stored.endswith("/" + candidate):
                    return True

            basename = plan_path.name
            related = basename_index.get(basename, [])
            if len(related) == 1 and stored == basename:
                return True
            return False

        for plan_dir in existing_plan_dirs:
            for plan_file in plan_dir.rglob("*.md"):
                try:
                    status = read_plan_status(plan_file)
                except Exception:
                    continue

                stage = classify_plan_stage(status)
                is_impl = status in ("구현중", "구현완료")
                if not is_impl and stage != "pre_review":
                    continue

                active, branch, wt_abs = is_worktree_active(str(plan_file), PROJECT_ROOT)
                if not active or not branch:
                    continue

                matching = [
                    w
                    for w in all_workflows
                    if w.get("status") in active_statuses
                    and _workflow_plan_matches(plan_file, w.get("plan_file"))
                ]
                if not matching:
                    logger.warning(
                        f"[orphan-plan] {plan_file.name}: active worktree는 있으나 Workflow DB에 active 레코드 없음"
                    )
                else:
                    inactive_runners = [
                        w.get("runner_id")
                        for w in matching
                        if w.get("runner_id") and not redis_client.sismember(ACTIVE_RUNNERS_KEY, w.get("runner_id"))
                    ]
                    if not inactive_runners:
                        continue
                    for rid in inactive_runners:
                        logger.warning(
                            f"[orphan-plan] {plan_file.name}: runner {rid}가 active_runners에 없음"
                        )

                try:
                    if not has_unmerged_commits(branch, PROJECT_ROOT):
                        _orphan_base = get_target_project_root(str(plan_file)) / ".worktrees"
                        WorktreeManager.remove("", _orphan_base, plan_file=str(plan_file))
                        _remove_plan_header_fields(str(plan_file))
                        logger.info(f"[orphan-plan] {plan_file.name}: worktree/branch 정리 완료 (branch={branch})")
                        cleaned_count += 1
                    else:
                        logger.warning(f"[orphan-plan] {plan_file.name}: 독자 커밋 존재 — 수동 확인 필요 (branch={branch})")
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"[orphan-plan] plan orphan detection failed: {e}")
    return cleaned_count

