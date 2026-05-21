"""_dr_merge.py — dev-runner merge 실행 헬퍼 모듈"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import base64
import functools
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import redis

from _dr_constants import (
    RUNNER_KEY_PREFIX, PLAN_FILE_ALL, _LEGACY_ALL, LOG_CHANNEL_PREFIX,
    PLAN_RUNNER_PYTHON, PLAN_RUNNER_MODULE_PATH, OWNERSHIP_SNAPSHOT_DIR, get_redis_db, get_admin_api_base,
    REROUTE_REQUIRED_PATH_KEY,
    ROOT_DIRTY_CLOSEOUT_STATUS_KEY,
    ROOT_DIRTY_PATHS_KEY,
    ROOT_DIRTY_STATUS_BLOCKED,
    ROOT_DIRTY_STATUS_CLEAN,
    ROOT_DIRTY_STATUS_REROUTE_REQUIRED,
)
from _dr_merge_persistence import MergePersistence
from _dr_merge_state import (
    ACTIVE_STATUSES,
    APPROVAL_REQUIRED,
    CONFLICT,
    ERROR,
    FIXING,
    MERGED,
    MERGING,
    QUEUED,
    RESIDUE_BLOCKED,
    RESOLVING,
    TERMINAL_STATUSES,
    TEST_FAILED,
    RetryAction,
)
from _dr_plan_paths import classify_plan_stage, read_plan_status
from _dr_runtime_utils import _publish_with_retry
from _dr_subprocess import _get_fix_engine, _launch_conflict_resolver_process, _launch_auto_impl_post_merge_process, _launch_general_merge_resolver_process, PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_MERGE_LOCK_TIMEOUT_SECONDS = 86400
_INLINE_MERGE_PRESERVE_STATUSES = TERMINAL_STATUSES


def _transition_action(action_name: str) -> str:
    if action_name == RetryAction.APPROVED_RETRY.value:
        return RetryAction.APPROVED_RETRY.value
    if action_name == "retry-merge":
        return RetryAction.RETRY_MERGE.value
    if action_name == "direct-merge":
        return RetryAction.DIRECT_MERGE.value
    return action_name or RetryAction.INLINE_MERGE.value


def _transition_merge_status(
    runner_id: str,
    redis_client: redis.Redis,
    to_status: str,
    *,
    reason: str | None = None,
    message: str | None = None,
    action_name: str = "inline-merge",
):
    return MergePersistence(redis_client, runner_id).transition(
        to_status,
        reason=reason,
        message=message,
        action=_transition_action(action_name),
    )


def _get_merge_lock_timeout_seconds() -> int:
    raw = os.environ.get("MERGE_TEST_LOCK_TIMEOUT")
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning("Invalid MERGE_TEST_LOCK_TIMEOUT=%r; using default %s", raw, DEFAULT_MERGE_LOCK_TIMEOUT_SECONDS)
    return DEFAULT_MERGE_LOCK_TIMEOUT_SECONDS


def _decode_redis_value(val) -> str:
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8", errors="replace")
        except Exception:
            return str(val)
    return "" if val is None else str(val)


def _plan_runner_source_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(PLAN_RUNNER_MODULE_PATH),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _preserve_terminal_inline_merge_state(
    runner_id: str,
    redis_client: redis.Redis,
    action_name: str,
    pub_fn,
) -> Optional[dict]:
    """Return an existing terminal merge state instead of re-entering inline merge."""
    if action_name != "inline-merge":
        return None

    persistence = MergePersistence(redis_client, runner_id)
    try:
        state = persistence.read()
    except Exception:
        state = None

    if state is None or state.merge_status not in _INLINE_MERGE_PRESERVE_STATUSES:
        return None

    try:
        persistence.clear_request()
    except Exception:
        pass

    pub_fn(
        "terminal merge_status 보존 → inline merge 차단 "
        f"(merge_status={state.merge_status}, reason={state.merge_reason or state.merge_status})"
    )
    return {
        "success": False,
        "message": state.merge_message or state.merge_status,
        "merge_status": state.merge_status,
        "action": action_name,
        "reason": state.merge_reason or state.merge_status,
    }


def _normalize_ownership_key(path: Path, project_root: Path) -> Optional[str]:
    try:
        rel = path.resolve(strict=False).relative_to(project_root.resolve(strict=False))
    except Exception:
        return None
    return str(rel).replace("\\", "/").casefold()


def _status_line_relpath(line: str) -> str:
    raw = line[3:].strip() if len(line) >= 3 else line.strip()
    if " -> " in raw:
        raw = raw.split(" -> ", 1)[1].strip()
    return raw.replace("\\", "/")


def _is_root_checkout(project_root: Path) -> bool:
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if common.returncode != 0 or not common.stdout.strip():
            return False
        common_git_dir = Path(common.stdout.strip())
        if not common_git_dir.is_absolute():
            common_git_dir = project_root / common_git_dir
        return common_git_dir.resolve(strict=False).parent == project_root.resolve(strict=False)
    except Exception:
        return False


def _is_mirror_surface_path(relpath: str) -> bool:
    normalized = relpath.replace("\\", "/")
    return normalized.startswith((".agents/", ".agent/", ".claude/", ".gemini/"))


def _is_allowed_root_operator_path(relpath: str) -> bool:
    normalized = relpath.replace("\\", "/")
    if normalized in {"AGENTS.md", "CLAUDE.md", "MANUAL_TASKS.md", "CHANGELOG.md", ".gitignore"}:
        return True
    return normalized.startswith(("docs/archive/", "docs/plan/"))


def _is_implementation_scope_path(relpath: str) -> bool:
    return not _is_mirror_surface_path(relpath) and not _is_allowed_root_operator_path(relpath)


def _load_runner_ownership_payload(runner_id: str) -> Optional[tuple[Path, dict]]:
    snapshot_path = OWNERSHIP_SNAPSHOT_DIR / f"{runner_id}.json"
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("[ownership] snapshot read failed: runner=%s error=%s", runner_id, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("[ownership] snapshot payload invalid: runner=%s type=%s", runner_id, type(payload).__name__)
        return None
    return snapshot_path, payload


def _resolve_snapshot_project_root(payload: dict) -> Path:
    raw = payload.get("project_root")
    if isinstance(raw, str) and raw.strip():
        return Path(raw)
    return PROJECT_ROOT


def _collect_post_merge_owned_paths(plan_file: str, project_root: Path) -> list[Path]:
    from app.modules.dev_runner.services.archive_service import resolve_archive_target_or_raise
    from app.modules.dev_runner.services.plan_path_helpers import resolve_plans_ledger_paths

    plan_path = Path(plan_file)
    today = datetime.now().date()
    candidates: list[Path] = [plan_path]
    archive_path: Optional[Path] = None

    try:
        archive_path = resolve_archive_target_or_raise(plan_file)
        candidates.append(archive_path)
    except Exception as exc:
        logger.debug("[ownership] archive target resolve skipped: plan=%s error=%s", plan_file, exc)

    todo_path = plan_path.parent / f"{plan_path.stem}_todo.md"
    candidates.append(todo_path)
    if archive_path is not None:
        candidates.append(archive_path.parent / todo_path.name)

    ledger_paths = resolve_plans_ledger_paths(project_root, today=today)
    candidates.extend(
        [
            ledger_paths.todo_path,
            ledger_paths.done_path,
            ledger_paths.done_history_path,
            project_root / "MANUAL_TASKS.md",
        ]
    )
    return candidates


def _register_post_merge_owned_files(runner_id: str, plan_file: str) -> None:
    loaded = _load_runner_ownership_payload(runner_id)
    if not loaded:
        return

    snapshot_path, payload = loaded
    project_root = _resolve_snapshot_project_root(payload)
    dirty_files = {
        str(item).replace("\\", "/").casefold()
        for item in payload.get("dirty_files", [])
        if isinstance(item, str) and item.strip()
    }
    owned_files = {
        str(item).replace("\\", "/").casefold()
        for item in payload.get("owned_files", [])
        if isinstance(item, str) and item.strip()
    }
    clean_at_start_files = {
        str(item).replace("\\", "/").casefold()
        for item in payload.get("clean_at_start_files", [])
        if isinstance(item, str) and item.strip()
    }

    for candidate in _collect_post_merge_owned_paths(plan_file, project_root):
        key = _normalize_ownership_key(candidate, project_root)
        if not key:
            continue
        owned_files.add(key)
        if key not in dirty_files:
            clean_at_start_files.add(key)

    payload["owned_files"] = sorted(owned_files)
    payload["clean_at_start_files"] = sorted(clean_at_start_files)
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _collect_git_status_entries(project_root: Path) -> list[dict]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git status failed ({result.returncode})")

    entries: list[dict] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        relpath = _status_line_relpath(line)
        key = relpath.casefold()
        if not key:
            continue
        entries.append(
            {
                "line": line,
                "relpath": relpath,
                "key": key,
                "untracked": line.startswith("??"),
            }
        )
    return entries


def _write_post_merge_residue_diff(
    runner_id: str,
    stray_entries: list[dict],
    project_root: Path,
) -> str:
    residue_dir = project_root / "logs" / "dev_runner" / "residue"
    residue_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    diff_path = residue_dir / f"{runner_id}-{timestamp}.diff"

    tracked_paths = [entry["relpath"] for entry in stray_entries if not entry.get("untracked")]
    lines: list[str] = [
        f"# runner_id: {runner_id}",
        f"# captured_at: {datetime.now().isoformat()}",
        "# stray_status:",
    ]
    lines.extend(str(entry["line"]) for entry in stray_entries)
    lines.append("")

    if tracked_paths:
        diff_proc = subprocess.run(
            ["git", "diff", "--binary", "--", *tracked_paths],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        lines.append("# tracked_diff:")
        lines.append(diff_proc.stdout if diff_proc.returncode == 0 else f"# git diff failed ({diff_proc.returncode})")
    else:
        lines.append("# tracked_diff:")
        lines.append("# no tracked residue")

    untracked_paths = [entry["relpath"] for entry in stray_entries if entry.get("untracked")]
    if untracked_paths:
        lines.append("")
        lines.append("# untracked_paths:")
        lines.extend(untracked_paths)

    diff_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(diff_path)


def _write_reroute_required_evidence(
    runner_id: str,
    affected_entries: list[dict],
    project_root: Path,
    *,
    quarantine_diff_path: str | None = None,
) -> str:
    evidence_dir = project_root / "logs" / "dev_runner" / "reroute_required"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_runner = re.sub(r"[^A-Za-z0-9_.-]+", "_", runner_id)[:80] or "runner"
    evidence_path = evidence_dir / f"{safe_runner}-{timestamp}.md"
    rescue_name = f"codex/root-dirty-rescue-{datetime.now().strftime('%Y%m%d')}"
    affected_paths = [str(entry["relpath"]) for entry in affected_entries]

    lines = [
        "# root dirty reroute required",
        "",
        f"- runner_id: `{runner_id}`",
        f"- captured_at: `{datetime.now().isoformat()}`",
        f"- root: `{project_root}`",
        f"- root_dirty_closeout_status: `{ROOT_DIRTY_STATUS_REROUTE_REQUIRED}`",
        f"- recommended_rescue_branch: `{rescue_name}`",
        f"- recommended_rescue_worktree: `.worktrees/{rescue_name.replace('/', '-')}`",
    ]
    if quarantine_diff_path:
        lines.append(f"- quarantine_diff_path: `{quarantine_diff_path}`")
    lines.extend(["", "## affected paths", ""])
    lines.extend(f"- `{path}`" for path in affected_paths)
    lines.extend(
        [
            "",
            "## operator note",
            "",
            "`root_worktree_impl_scope_blocked` is not a successful closeout. Move these changes into the owning impl worktree or a named rescue worktree, then verify the root checkout is clean.",
        ]
    )
    evidence_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(evidence_path)


def _remove_untracked_residue_path(project_root: Path, relpath: str) -> None:
    target = (project_root / relpath).resolve(strict=False)
    root = project_root.resolve(strict=False)
    try:
        target.relative_to(root)
    except Exception as exc:
        raise RuntimeError(f"residue path escaped project root: {relpath}") from exc

    if not target.exists():
        return
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def _restore_post_merge_residue(stray_entries: list[dict], project_root: Path) -> None:
    tracked_paths = [entry["relpath"] for entry in stray_entries if not entry.get("untracked")]
    if tracked_paths:
        restore_proc = subprocess.run(
            ["git", "restore", "--source=HEAD", "--worktree", "--", *tracked_paths],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if restore_proc.returncode != 0:
            raise RuntimeError(f"git restore failed ({restore_proc.returncode})")

    for entry in stray_entries:
        if entry.get("untracked"):
            _remove_untracked_residue_path(project_root, str(entry["relpath"]))


def _check_post_merge_residue(runner_id: str, pub_fn) -> dict:
    loaded = _load_runner_ownership_payload(runner_id)
    if not loaded:
        pub_fn("ownership snapshot 없음 — residue guard skip")
        return {"success": True, "status": "snapshot_missing"}

    _, payload = loaded
    capture_error = payload.get("capture_error")
    if capture_error:
        pub_fn(f"ownership snapshot 경고 — residue guard skip ({capture_error})")
        return {"success": True, "status": "snapshot_capture_failed"}

    project_root = _resolve_snapshot_project_root(payload)
    dirty_files = {
        str(item).replace("\\", "/").casefold()
        for item in payload.get("dirty_files", [])
        if isinstance(item, str) and item.strip()
    }
    owned_files = {
        str(item).replace("\\", "/").casefold()
        for item in payload.get("owned_files", [])
        if isinstance(item, str) and item.strip()
    }
    allowed_files = dirty_files | owned_files

    entries = _collect_git_status_entries(project_root)
    if _is_root_checkout(project_root):
        root_impl_entries = [
            entry for entry in entries
            if _is_implementation_scope_path(str(entry["relpath"]))
        ]
        if root_impl_entries:
            quarantine_diff_path = _write_post_merge_residue_diff(runner_id, root_impl_entries, project_root)
            reroute_required_path = _write_reroute_required_evidence(
                runner_id,
                root_impl_entries,
                project_root,
                quarantine_diff_path=quarantine_diff_path,
            )
            affected_paths = [str(entry["relpath"]) for entry in root_impl_entries]
            pub_fn(
                "root implementation dirty 감지: "
                f"{len(affected_paths)}건 reroute_required, evidence={reroute_required_path}"
            )
            return {
                "success": False,
                "status": "reroute_required",
                "reason": "root_dirty_reroute_required",
                "message": "root implementation dirty requires reroute before closeout",
                "quarantine_diff_path": quarantine_diff_path,
                REROUTE_REQUIRED_PATH_KEY: reroute_required_path,
                ROOT_DIRTY_CLOSEOUT_STATUS_KEY: ROOT_DIRTY_STATUS_REROUTE_REQUIRED,
                ROOT_DIRTY_PATHS_KEY: affected_paths,
                "stray_files": affected_paths,
            }

    stray_entries = [entry for entry in entries if entry["key"] not in allowed_files]
    if not stray_entries:
        return {"success": True, "status": "clean", ROOT_DIRTY_CLOSEOUT_STATUS_KEY: ROOT_DIRTY_STATUS_CLEAN}

    quarantine_diff_path = _write_post_merge_residue_diff(runner_id, stray_entries, project_root)
    _restore_post_merge_residue(stray_entries, project_root)

    stray_paths = [str(entry["relpath"]) for entry in stray_entries]
    pub_fn(
        f"post-merge residue 감지: {len(stray_paths)}건 차단, quarantine={quarantine_diff_path}"
    )
    return {
        "success": False,
        "status": "residue_blocked",
        "reason": "residue_guard",
        "message": "post-merge residue detected and restored",
        "quarantine_diff_path": quarantine_diff_path,
        "stray_files": stray_paths,
    }


def _persist_merge_result_metadata(runner_id: str, redis_client: redis.Redis, result: dict) -> None:
    MergePersistence(redis_client, runner_id).persist_result_metadata(result)


def is_done_completed(runner_id: str, redis_client: redis.Redis) -> bool:
    """plan-runner가 이미 done을 완료했는지 확인 (이중 done 방지).

    plan-runner loop의 auto-done 성공 후 설정되는 플래그를 확인한다.
    (fix: v2-pipeline-transition-safety Phase 2)
    """
    try:
        val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:done_completed")
        return val == "1"
    except Exception:
        return False


def _is_pre_review_stopped(runner_id: str, redis_client: redis.Redis, plan_file: str | None = None) -> bool:
    """stop_stage 또는 plan 상태를 기준으로 pre_review stopped 여부 판단."""
    try:
        stop_stage = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage")
        if stop_stage == "pre_review":
            return True
        if stop_stage == "post_review":
            return False
    except Exception:
        pass

    if not plan_file or plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
        return False
    try:
        status = read_plan_status(plan_file)
        return classify_plan_stage(status) == "pre_review"
    except Exception:
        return False


def detect_merged_but_not_done(runner_id: str, redis_client: redis.Redis) -> Optional[dict]:
    """v2 merge 성공 후 후처리(done/archive/cleanup)가 누락된 runner를 감지한다.

    v2 파이프라인에서 handle_merge_stage()가 merge 성공 후 plan-runner 프로세스가 죽으면
    dev-runner가 후처리를 놓치는 버그의 fallback 감지 함수.

    감지 경로:
    1. Redis merge_status == "merged" (v2에서 세팅 시)
    2. git log에서 branch merge commit이 main에 존재
    3. 활성 plan 경로에 파일이 잔존하고 상태가 머지대기/통합테스트중

    Args:
        runner_id: plan-runner ID
        redis_client: Redis 클라이언트

    Returns:
        감지 시 {"plan_file": str, "branch": str}, 미감지 시 None
    """
    from plan_worktree_helpers import is_plan_archived, resolve_active_plan_file

    # done_completed 플래그 확인 — plan-runner가 이미 done 완료 시 fallback 불필요
    # (fix: v2-pipeline-transition-safety Phase 2)
    if is_done_completed(runner_id, redis_client):
        logger.debug(f"[detect_merged] runner {runner_id}: done_completed=1 → 스킵")
        return None

    try:
        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        branch = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")
    except Exception as e:
        logger.debug(f"[detect_merged] runner {runner_id}: Redis 조회 실패 (무시) — {e}")
        return None

    # plan_file 없음 또는 ALL 모드이면 스킵
    if not plan_file or plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
        logger.debug(f"[detect_merged] runner {runner_id}: plan_file 없음 또는 ALL → 스킵")
        return None

    resolved_plan = resolve_active_plan_file(plan_file, project_root=PROJECT_ROOT)
    effective_plan_file = str(resolved_plan) if resolved_plan else plan_file

    # pre-review stopped는 fallback 대상에서 제외
    if _is_pre_review_stopped(runner_id, redis_client, effective_plan_file):
        logger.info(f"[detect_merged] runner {runner_id}: stop_stage=pre_review → fallback 스킵")
        return None

    # 이미 archive됐으면 중복 방지
    try:
        if is_plan_archived(effective_plan_file):
            logger.debug(f"[detect_merged] runner {runner_id}: plan이 이미 archive됨 → 스킵")
            return None
    except Exception:
        pass

    # plan 파일이 존재하고 상태가 머지대기/통합테스트중인지 확인
    plan_path = Path(effective_plan_file)
    if not plan_path.exists():
        logger.info(
            f"[detect_merged] runner {runner_id}: 활성 plan 파일 미발견 "
            f"(input={plan_file}, resolved={effective_plan_file})"
        )
        return None

    try:
        head = plan_path.read_text(encoding="utf-8", errors="replace")[:2000]
        if not re.search(r">\s*상태:\s*(머지대기|통합테스트중)", head):
            logger.debug(f"[detect_merged] runner {runner_id}: plan 상태가 머지대기/통합테스트중 아님 → 스킵")
            return None
    except Exception as e:
        logger.debug(f"[detect_merged] runner {runner_id}: plan 상태 확인 실패 (무시) — {e}")
        return None

    # 감지 경로 1: Redis merge_status == "merged"
    redis_merged = False
    try:
        ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        if ms == "merged":
            redis_merged = True
            logger.info(f"[detect_merged] runner {runner_id}: Redis merge_status=merged 감지")
    except Exception:
        pass

    # 감지 경로 2: git log에서 branch merge commit이 main에 존재
    git_merged = False
    if branch:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--merges",
                 f"--grep=Merge branch '{branch}'", "main", "-1"],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                git_merged = True
                logger.info(f"[detect_merged] runner {runner_id}: git log merge commit 감지 (branch={branch})")
            else:
                # grep 패턴 대안: --grep="plan/{branch-tail}"
                branch_tail = branch.split("/")[-1] if "/" in branch else branch
                result2 = subprocess.run(
                    ["git", "log", "--oneline", "--merges",
                     f"--grep={branch_tail}", "main", "-3"],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
                )
                if result2.returncode == 0 and result2.stdout.strip():
                    git_merged = True
                    logger.info(
                        f"[detect_merged] runner {runner_id}: git log merge commit 감지 (branch_tail={branch_tail})"
                    )
        except Exception as e:
            logger.debug(f"[detect_merged] runner {runner_id}: git log 확인 실패 (무시) — {e}")

    if redis_merged or git_merged:
        logger.info(
            f"[detect_merged] runner {runner_id}: merge 후 후처리 누락 감지 "
            f"(redis_merged={redis_merged}, git_merged={git_merged}, plan={effective_plan_file})"
        )
        return {"plan_file": effective_plan_file, "branch": branch or ""}

    logger.debug(
        f"[detect_merged] runner {runner_id}: merge 감지 안됨 "
        f"(redis_merged={redis_merged}, git_merged={git_merged})"
    )
    return None


def _pub_and_log(runner_id: str, msg: str, redis_client: redis.Redis, tag: str = "MERGE") -> None:
    """Pub/Sub + Redis list + stream_log_path 파일에 통합 기록하는 헬퍼.

    Args:
        runner_id: plan-runner ID
        msg: 기록할 메시지 (태그 미포함)
        redis_client: Redis 클라이언트
        tag: 로그 태그 (기본값: MERGE)
    """
    tagged = f"[{tag}] {msg}"
    logger.info(tagged)
    log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    log_list_key = f"plan-runner:logs:list:{runner_id}"
    _publish_with_retry(redis_client, log_channel, tagged)
    try:
        redis_client.rpush(log_list_key, tagged)
        redis_client.expire(log_list_key, 86400)
    except Exception:
        pass
    # stream_log_path → fallback: log_file_path 파일에 append
    try:
        log_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
        if not log_path_str:
            log_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")
        if log_path_str:
            log_path = Path(log_path_str)
            if log_path.exists():
                with open(str(log_path), "a", encoding="utf-8") as _f:
                    _f.write(tagged + "\n")
    except Exception as _e:
        logger.debug(f"[_pub_and_log] 파일 기록 실패 (무시): {_e}")


def _build_merge_completed_sentinel(result: dict) -> str:
    """merge 결과를 merge-log 종료 sentinel payload로 정규화한다."""
    return MergePersistence.build_completed_sentinel(result)


def _publish_merge_completed_sentinel(runner_id: str, redis_client: redis.Redis, result: dict) -> None:
    """terminal merge sentinel만 merge-log 채널에 1회 publish한다."""
    MergePersistence(redis_client, runner_id).publish_completed_sentinel(result)


def _extract_post_merge_done_failure(done_result) -> tuple[bool, str]:
    """post-merge done 결과에서 실패 여부/사유를 추출한다."""
    if not isinstance(done_result, dict):
        return False, ""
    if done_result.get("success", True):
        return False, ""
    reason = done_result.get("reason") or done_result.get("status") or "done_post_merge_failed"
    return True, str(reason)


def _compose_merge_result_with_done(
    runner_id: str,
    redis_client: redis.Redis,
    action_name: str,
    base_message: str,
    done_result,
    pub_fn,
) -> dict:
    """merge 성공 결과에 post-merge done 결과를 반영한다."""
    failed, reason = _extract_post_merge_done_failure(done_result)
    if failed:
        merge_status = RESIDUE_BLOCKED if reason in {"residue_guard", "root_dirty_reroute_required"} else ERROR
        pub_fn(f"post-merge done 실패 전파: {reason}")
        _transition_merge_status(
            runner_id,
            redis_client,
            merge_status,
            reason=reason,
            message=f"{base_message}; post-merge done failed: {reason}",
            action_name=action_name,
        )
        result = {
            "success": False,
            "message": f"{base_message}; post-merge done failed: {reason}",
            "merge_status": merge_status,
            "action": action_name,
            "reason": reason,
        }
    else:
        result = {
            "success": True,
            "message": base_message,
            "merge_status": MERGED,
            "action": action_name,
        }

    if isinstance(done_result, dict):
        result["post_merge_done"] = done_result
        if done_result.get("quarantine_diff_path"):
            result["quarantine_diff_path"] = done_result["quarantine_diff_path"]
        for key in (ROOT_DIRTY_CLOSEOUT_STATUS_KEY, ROOT_DIRTY_PATHS_KEY, REROUTE_REQUIRED_PATH_KEY):
            if done_result.get(key):
                result[key] = done_result[key]
    return result


def _handle_merge_success(runner_id: str, redis_client: redis.Redis, plan_file, pub_fn, action_name: str = "inline-merge") -> dict:
    residue_result = _check_post_merge_residue(runner_id, pub_fn)
    if not residue_result.get("success", True):
        failure_reason = str(residue_result.get("reason") or "residue_guard")
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:done_post_merge_status", "skipped_residue")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:done_post_merge_error", failure_reason)
            if residue_result.get("quarantine_diff_path"):
                redis_client.set(
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:quarantine_diff_path",
                    residue_result["quarantine_diff_path"],
                )
            for key in (ROOT_DIRTY_CLOSEOUT_STATUS_KEY, ROOT_DIRTY_PATHS_KEY, REROUTE_REQUIRED_PATH_KEY):
                if residue_result.get(key):
                    value = residue_result[key]
                    if isinstance(value, (list, tuple, set)):
                        value = json.dumps(list(value), ensure_ascii=False)
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:{key}", str(value))
        except Exception:
            pass
        return _compose_merge_result_with_done(
            runner_id=runner_id,
            redis_client=redis_client,
            action_name=action_name,
            base_message="merge blocked by residue",
            done_result={
                "success": False,
                "status": "skipped_residue",
                "reason": failure_reason,
                "message": str(residue_result.get("message") or "post-merge residue detected"),
                "quarantine_diff_path": residue_result.get("quarantine_diff_path"),
                ROOT_DIRTY_CLOSEOUT_STATUS_KEY: residue_result.get(ROOT_DIRTY_CLOSEOUT_STATUS_KEY),
                ROOT_DIRTY_PATHS_KEY: residue_result.get(ROOT_DIRTY_PATHS_KEY),
                REROUTE_REQUIRED_PATH_KEY: residue_result.get(REROUTE_REQUIRED_PATH_KEY),
            },
            pub_fn=pub_fn,
        )
    try:
        _transition_merge_status(runner_id, redis_client, MERGED, message="merged", action_name=action_name)
    except Exception:
        pass
    pub_fn("merge 성공 (exit_code=0)")
    done_result = _handle_post_merge_done(plan_file, runner_id, pub_fn, redis_client)
    closeout_result = _check_post_merge_residue(runner_id, pub_fn)
    if not closeout_result.get("success", True):
        failure_reason = str(closeout_result.get("reason") or "residue_guard")
        done_payload = {
            "success": False,
            "status": "skipped_residue",
            "reason": failure_reason,
            "message": str(closeout_result.get("message") or "post-merge closeout residue detected"),
            "quarantine_diff_path": closeout_result.get("quarantine_diff_path"),
            ROOT_DIRTY_CLOSEOUT_STATUS_KEY: closeout_result.get(ROOT_DIRTY_CLOSEOUT_STATUS_KEY),
            ROOT_DIRTY_PATHS_KEY: closeout_result.get(ROOT_DIRTY_PATHS_KEY),
            REROUTE_REQUIRED_PATH_KEY: closeout_result.get(REROUTE_REQUIRED_PATH_KEY),
            "previous_post_merge_done": done_result,
        }
        return _compose_merge_result_with_done(
            runner_id=runner_id,
            redis_client=redis_client,
            action_name=action_name,
            base_message="merged but closeout blocked",
            done_result=done_payload,
            pub_fn=pub_fn,
        )
    result = _compose_merge_result_with_done(
        runner_id=runner_id,
        redis_client=redis_client,
        action_name=action_name,
        base_message="merged",
        done_result=done_result,
        pub_fn=pub_fn,
    )
    result["post_merge_loss_check"] = _run_post_merge_loss_check(runner_id, redis_client, plan_file, pub_fn)
    return result


def _handle_test_failed(runner_id: str, redis_client: redis.Redis, plan_file, pub_fn, action_name: str = "inline-merge", _test_fix_attempt: int = 0) -> dict:
    if _test_fix_attempt >= 2 or not plan_file:
        if _test_fix_attempt >= 2:
            pub_fn(f"auto-impl-post-merge 재시도 한도(2회) 초과 — test_failed 상태 유지")
        try:
            _transition_merge_status(runner_id, redis_client, TEST_FAILED, message="test_failed", action_name=action_name)
        except Exception:
            pass
        pub_fn(f"post-merge 테스트 실패 (exit_code=2)")
        return {"success": False, "message": "test_failed", "merge_status": TEST_FAILED, "action": action_name}
    else:
        try:
            _transition_merge_status(runner_id, redis_client, FIXING, action_name=action_name)
        except Exception:
            pass
        pub_fn("post-merge 테스트 실패 — auto-impl-post-merge 자동 실행")
        engine = _get_fix_engine(redis_client, runner_id)
        _fix_result = _launch_auto_impl_post_merge_process(
            runner_id=runner_id,
            plan_file=plan_file,
            redis_client=redis_client,
            pub_fn=pub_fn,
            engine=engine,
        )
    if _fix_result["success"]:
        pub_fn("auto-impl-post-merge 성공 — merge 완료")
        residue_result = _check_post_merge_residue(runner_id, pub_fn)
        if not residue_result.get("success", True):
            failure_reason = str(residue_result.get("reason") or "residue_guard")
            return _compose_merge_result_with_done(
                runner_id=runner_id,
                redis_client=redis_client,
                action_name=action_name,
                base_message="test fixed but residue blocked",
                done_result={
                    "success": False,
                    "status": "skipped_residue",
                    "reason": failure_reason,
                    "message": str(residue_result.get("message") or "post-merge residue detected"),
                    "quarantine_diff_path": residue_result.get("quarantine_diff_path"),
                    ROOT_DIRTY_CLOSEOUT_STATUS_KEY: residue_result.get(ROOT_DIRTY_CLOSEOUT_STATUS_KEY),
                    ROOT_DIRTY_PATHS_KEY: residue_result.get(ROOT_DIRTY_PATHS_KEY),
                    REROUTE_REQUIRED_PATH_KEY: residue_result.get(REROUTE_REQUIRED_PATH_KEY),
                },
                pub_fn=pub_fn,
            )
        try:
            _transition_merge_status(runner_id, redis_client, MERGED, message="merged", action_name=action_name)
        except Exception:
            pass
        done_result = _handle_post_merge_done(plan_file, runner_id, pub_fn, redis_client)
        return _compose_merge_result_with_done(
            runner_id=runner_id,
            redis_client=redis_client,
            action_name=action_name,
            base_message="test fixed and merged",
            done_result=done_result,
            pub_fn=pub_fn,
        )
    else:
        pub_fn(f"auto-impl-post-merge 실패: {_fix_result['message']}")
        try:
            _transition_merge_status(runner_id, redis_client, TEST_FAILED, message="test_failed", action_name=action_name)
        except Exception:
            pass
        return {"success": False, "message": "test_failed", "merge_status": TEST_FAILED, "action": action_name}


def _handle_conflict(runner_id: str, redis_client: redis.Redis, plan_file, pub_fn, action_name: str = "inline-merge", branch_str: str = "") -> dict:
    try:
        _transition_merge_status(runner_id, redis_client, RESOLVING, action_name=action_name)
    except Exception:
        pass
    pub_fn(f"merge 충돌 (exit_code=3) — conflict resolver 자동 실행")
    engine = _get_fix_engine(redis_client, runner_id)
    worktree_path_str = ""
    try:
        worktree_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path") or ""
    except Exception:
        pass
    _resolve_result = _launch_conflict_resolver_process(
        runner_id=runner_id,
        branch=branch_str or "",
        worktree_path=Path(worktree_path_str) if worktree_path_str else PROJECT_ROOT / ".worktrees" / runner_id,
        redis_client=redis_client,
        pub_fn=pub_fn,
        engine=engine,
        needs_remerge=True,
    )
    _resolve_merge_status = str(_resolve_result.get("merge_status") or "").strip().lower()
    if _resolve_result["success"] and _resolve_merge_status in ("", "merged"):
        pub_fn(f"conflict resolver 성공 — {_resolve_result['message']}")
        try:
            _transition_merge_status(runner_id, redis_client, MERGED, message="merged", action_name=action_name)
        except Exception:
            pass
        done_result = _handle_post_merge_done(plan_file, runner_id, pub_fn, redis_client)
        return _compose_merge_result_with_done(
            runner_id=runner_id,
            redis_client=redis_client,
            action_name=action_name,
            base_message=_resolve_result["message"],
            done_result=done_result,
            pub_fn=pub_fn,
        )
    if _resolve_merge_status == "conflict" or _resolve_result.get("conflict"):
        pub_fn(f"conflict resolver 중단: {_resolve_result['message']}")
        try:
            _transition_merge_status(runner_id, redis_client, CONFLICT, message=_resolve_result["message"], action_name=action_name)
        except Exception:
            pass
        return {
            "success": False,
            "message": _resolve_result["message"],
            "conflict": True,
            "merge_status": CONFLICT,
            "action": action_name,
        }

    pub_fn(f"conflict resolver 실패: {_resolve_result['message']}")
    try:
        _transition_merge_status(runner_id, redis_client, ERROR, message=_resolve_result["message"], action_name=action_name)
    except Exception:
        pass
    return {
        "success": False,
        "message": _resolve_result["message"],
        "merge_status": ERROR,
        "action": action_name,
    }


def _handle_general_error(runner_id: str, redis_client: redis.Redis, plan_file, pub_fn, action_name: str = "inline-merge", exit_code: int = 1, error_msg: str = "", branch_str: str = "") -> dict:
    try:
        _transition_merge_status(runner_id, redis_client, ERROR, message=error_msg or f"exit_code={exit_code}", action_name=action_name)
    except Exception:
        pass
    pub_fn(f"merge 실패 (exit_code={exit_code}) — general resolver 실행")
    engine = _get_fix_engine(redis_client, runner_id)
    _general_result = _launch_general_merge_resolver_process(
        runner_id=runner_id,
        branch=branch_str or "",
        error_msg=f"exit_code={exit_code}",
        redis_client=redis_client,
        pub_fn=pub_fn,
        engine=engine,
    )
    if _general_result["success"]:
        pub_fn("general resolver 성공 — merge 완료")
        try:
            _transition_merge_status(runner_id, redis_client, MERGED, message="general resolver merged", action_name=action_name)
        except Exception:
            pass
        return {"success": True, "message": "general resolver merged", "merge_status": MERGED, "action": action_name}
    else:
        pub_fn(f"general resolver 실패: {_general_result['message']}")
        return {"success": False, "message": f"exit_code={exit_code}", "merge_status": ERROR, "action": action_name}


def _handle_approval_required(
    runner_id: str,
    redis_client: redis.Redis,
    plan_file,
    pub_fn,
    action_name: str = "inline-merge",
) -> dict:
    """service_lock 같은 precheck에서 승인 대기(approval_required)로 중단된 merge 결과를 보존한다.

    plan-runner(post-merge)가 이미 Redis에 merge_status/merge_reason/merge_message를 기록하므로,
    dev-runner는 일반 resolver로 넘기지 않고 해당 값을 그대로 반환한다.

    중요: 이것은 코드 결함이 아니라 런타임 안전성 게이트다.
    service_lock은 NSSM 서비스로 실행 중인 파일을 덮어쓰는 위험을 차단하기 위한 precheck로,
    자동 수정(auto-fix/conflict-resolver)으로 해결할 수 있는 문제가 아니다.
    사람이 "지금 서비스가 영향받아도 됨"을 명시적으로 판단하고 승인해야 한다.
    """
    pub_fn("merge 승인 필요 감지 (approval_required) — 자동 resolver 스킵, worktree 보존")
    try:
        message = _decode_redis_value(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_message")) or "approval_required"
        reason = _decode_redis_value(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_reason")) or "approval_required"
    except Exception:
        message = "approval_required"
        reason = "approval_required"

    # service_lock인 경우 auto-fix 미실행 사유를 명시적으로 로깅한다.
    if reason == "service_lock":
        pub_fn(
            "auto-fix skipped: service_lock is a runtime-safety gate, not a code defect — "
            "코드 결함 아님, 사람 판단 필요 (NSSM 서비스 실행 중인 파일 덮어쓰기 위험)"
        )

    try:
        _transition_merge_status(
            runner_id,
            redis_client,
            APPROVAL_REQUIRED,
            reason=reason,
            message=message,
            action_name=action_name,
        )
    except Exception:
        pass

    return {
        "success": False,
        "message": message,
        "merge_status": APPROVAL_REQUIRED,
        "action": action_name,
        "reason": reason,
    }


# dispatch table: exit_code → handler
# handler signature: (runner_id, redis_client, plan_file, pub_fn, action_name, **kwargs) -> dict
_EXIT_CODE_HANDLERS = {
    0: _handle_merge_success,
    2: _handle_test_failed,  # 테스트 실패 → auto-fix 대상 (코드 결함)
    3: _handle_conflict,     # merge 충돌 → conflict resolver 대상 (코드 결함)
    5: _handle_approval_required,  # service_lock precheck 승인 대기 — 런타임 안전성 게이트, auto-fix 대상 아님
}


def _write_pre_merge_snapshot(runner_id: str, branch: str, project_root: Path, pub_fn) -> Optional[str]:
    if not branch:
        return None

    snapshot_dir = project_root / "logs" / "dev_runner" / "merge_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_runner = re.sub(r"[^A-Za-z0-9_.-]+", "_", runner_id)[:80] or "runner"
    snapshot_path = snapshot_dir / f"{safe_runner}-{timestamp}.md"

    commands = [
        ("commit_log", ["git", "log", "--oneline", f"main..{branch}"]),
        ("name_status", ["git", "diff", "--name-status", f"main...{branch}"]),
    ]
    sections: list[tuple[str, str]] = []
    for label, cmd in commands:
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        stdout = proc.stdout if isinstance(proc.stdout, str) else ""
        stderr = proc.stderr if isinstance(proc.stderr, str) else ""
        if proc.returncode != 0:
            raise RuntimeError(f"pre-merge snapshot {label} failed ({proc.returncode}): {stderr.strip()}")
        sections.append((label, stdout.strip() or "(empty)"))

    lines = [
        f"# pre-merge snapshot: {runner_id}",
        f"- captured_at: {datetime.now().isoformat()}",
        f"- branch: {branch}",
        f"- base: main",
        "",
    ]
    for label, body in sections:
        lines.extend([f"## {label}", "", "```", body, "```", ""])

    snapshot_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    pub_fn(f"pre-merge snapshot 저장: {snapshot_path}")
    return str(snapshot_path)


def _check_stale_merge_gate(
    runner_id: str,
    redis_client: redis.Redis,
    branch: str,
    pub_fn,
    action_name: str = "inline-merge",
) -> tuple[Optional[dict], Optional[str]]:
    if not branch:
        pub_fn("merge branch 없음 — stale merge gate/snapshot skip")
        return None, None

    from plan_worktree_helpers import classify_merge_risk, get_branch_divergence

    behind, ahead = get_branch_divergence(branch, PROJECT_ROOT)
    risk = classify_merge_risk(behind, ahead)
    message = (
        f"stale merge gate: risk={risk}, behind={behind}, ahead={ahead}, branch={branch}; "
        "cause=branch divergence/mirror diff risk, not Redis state loss; rebuild a clean branch before retry"
    )
    pub_fn(message)
    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stale_merge_risk", risk)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stale_merge_behind", "" if behind is None else str(behind))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stale_merge_ahead", "" if ahead is None else str(ahead))
    except Exception:
        pass

    if risk == "WARN":
        pub_fn("stale merge WARN — 수동 확인 필요 로그를 남기고 merge를 계속 진행")

    allow_override = os.environ.get("DEV_RUNNER_ALLOW_STALE_MERGE") == "1"
    if risk == "BLOCK" and not allow_override:
        reason = "stale_merge_blocked"
        transition = _transition_merge_status(
            runner_id,
            redis_client,
            ERROR,
            reason=reason,
            message=message,
            action_name=action_name,
        )
        if not transition.allowed:
            state = MergePersistence(redis_client, runner_id).read()
            return {
                "success": False,
                "message": state.merge_message or state.merge_status or transition.reason,
                "merge_status": state.merge_status or transition.from_status,
                "action": action_name,
                "reason": state.merge_reason or state.merge_status or transition.reason,
                "stale_merge": {"risk": risk, "behind": behind, "ahead": ahead, "branch": branch},
            }, None
        return {
            "success": False,
            "message": message,
            "merge_status": ERROR,
            "action": action_name,
            "reason": reason,
            "stale_merge": {"risk": risk, "behind": behind, "ahead": ahead, "branch": branch},
        }, None

    if risk == "BLOCK":
        approver = os.environ.get("DEV_RUNNER_STALE_MERGE_APPROVER", "").strip() or "unknown"
        override_reason = os.environ.get("DEV_RUNNER_STALE_MERGE_REASON", "").strip() or "not provided"
        pub_fn(
            "stale merge BLOCK override 사용: "
            f"approver={approver}, reason={override_reason}, at={datetime.now().isoformat()}"
        )

    try:
        snapshot_path = _write_pre_merge_snapshot(runner_id, branch, PROJECT_ROOT, pub_fn)
        if snapshot_path:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_snapshot_path", snapshot_path)
    except Exception as exc:
        reason = "pre_merge_snapshot_failed"
        snapshot_message = f"{reason}: {exc}"
        pub_fn(snapshot_message)
        transition = _transition_merge_status(
            runner_id,
            redis_client,
            ERROR,
            reason=reason,
            message=snapshot_message,
            action_name=action_name,
        )
        if not transition.allowed:
            state = MergePersistence(redis_client, runner_id).read()
            return {
                "success": False,
                "message": state.merge_message or state.merge_status or transition.reason,
                "merge_status": state.merge_status or transition.from_status,
                "action": action_name,
                "reason": state.merge_reason or state.merge_status or transition.reason,
            }, None
        return {
            "success": False,
            "message": snapshot_message,
            "merge_status": ERROR,
            "action": "inline-merge",
            "reason": reason,
        }, None

    return None, snapshot_path


def _run_post_merge_loss_check(runner_id: str, redis_client: redis.Redis, plan_file, pub_fn) -> dict:
    snapshot_path = ""
    try:
        snapshot_path = _decode_redis_value(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_snapshot_path"))
    except Exception:
        snapshot_path = ""

    checks: list[str] = []
    if snapshot_path:
        checks.append("snapshot_exists" if Path(snapshot_path).exists() else "snapshot_missing")
    else:
        checks.append("snapshot_not_recorded")

    if plan_file:
        plan_path = Path(str(plan_file))
        checks.append("active_plan_absent_after_done" if not plan_path.exists() else "active_plan_still_present")

    pub_fn(f"post-merge loss checklist: {', '.join(checks)}")
    return {"checks": checks, "snapshot_path": snapshot_path or None}


def _execute_merge_with_lock(runner_id: str, redis_client: redis.Redis, action_name: str = "inline-merge", _test_fix_attempt: int = 0) -> dict:
    """lock acquire → plan-runner post-merge subprocess → exit code 분기 → merge-results push 공통 헬퍼.

    _do_inline_merge, _do_retry_merge에서 공유하는 lock+subprocess+결과 패턴을 통합한다.

    exit code 규약: 0=merged, 1=error, 2=test_failed, 3=conflict, 5=approval_required(service_lock)

    Args:
        _test_fix_attempt: exit_code=2 자동 복구 시도 횟수 (무한루프 방지, 최대 2회)

    Returns:
        dict: {"success": bool, "message": str, "merge_status": str, "action": action_name}
    """
    from merge_queue import acquire_merge_turn, release_merge_turn, _get_repo_id

    def _pub(msg: str) -> None:
        _pub_and_log(runner_id, msg, redis_client, "MERGE")

    branch_str = None
    plan_file = None
    lock_acquired = False
    result = {"success": False, "message": "unknown error", "merge_status": ERROR, "action": action_name}

    try:
        try:
            branch_str = _decode_redis_value(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")).strip() or None
            plan_file = _decode_redis_value(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")).strip() or None
            if plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
                plan_file = None
        except Exception:
            pass

        preserved_result = _preserve_terminal_inline_merge_state(runner_id, redis_client, action_name, _pub)
        if preserved_result is not None:
            result = preserved_result
            return result

        # 1. merge_status = "queued" + lock 대기
        try:
            transition = _transition_merge_status(runner_id, redis_client, QUEUED, action_name=action_name)
            if not transition.allowed:
                state = MergePersistence(redis_client, runner_id).read()
                _pub(f"{transition.reason} — 기존 merge_status 보존")
                result = {
                    "success": False,
                    "message": state.merge_message or state.merge_status or transition.reason,
                    "merge_status": state.merge_status or transition.from_status,
                    "action": action_name,
                    "reason": state.merge_reason or state.merge_status or transition.reason,
                }
                return result
        except Exception:
            pass
        _pub("merge lock 대기 중...")

        lock_timeout = _get_merge_lock_timeout_seconds()
        lock_acquired = acquire_merge_turn(redis_client, runner_id, repo_id=_get_repo_id(PROJECT_ROOT), timeout=lock_timeout)
        if not lock_acquired:
            _pub(f"merge lock 획득 실패 (timeout={lock_timeout}s) — merge 중단")
            try:
                _transition_merge_status(runner_id, redis_client, ERROR, message=f"merge lock 획득 실패 (timeout={lock_timeout}s)", action_name=action_name)
            except Exception:
                pass
            result["message"] = f"merge lock 획득 실패 (timeout={lock_timeout}s)"
            result["merge_status"] = ERROR
            return result

        gate_result, snapshot_path = _check_stale_merge_gate(runner_id, redis_client, branch_str or "", _pub, action_name=action_name)
        if gate_result is not None:
            gate_result["action"] = action_name
            result = gate_result
            return result

        # 2. lock 획득 후 merge_status = "merging"
        try:
            _transition_merge_status(runner_id, redis_client, MERGING, action_name=action_name)
        except Exception:
            pass
        _pub("merge lock 획득 완료 — plan-runner post-merge 실행 중...")
        source_commit = _plan_runner_source_commit()
        _pub(f"plan-runner source: path={PLAN_RUNNER_MODULE_PATH}, expected_commit={source_commit}")
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:runtime_source_root", str(PLAN_RUNNER_MODULE_PATH))
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:runtime_source_commit", source_commit)
        except Exception:
            pass

        # 3. subprocess로 plan-runner post-merge 호출
        proc = subprocess.run(
            [str(PLAN_RUNNER_PYTHON), "-m", "plan_runner", "post-merge",
             "--runner-id", runner_id,
             "--redis-db", str(get_redis_db()),
             "--project-dir", str(PROJECT_ROOT)],
            cwd=str(PLAN_RUNNER_MODULE_PATH),
        )
        exit_code = proc.returncode

        # 4. exit code dispatch table 분기
        handler = _EXIT_CODE_HANDLERS.get(exit_code)
        if handler is None:
            # else branch: general error handler
            result = _handle_general_error(
                runner_id, redis_client, plan_file, _pub,
                action_name=action_name, exit_code=exit_code,
                error_msg=f"exit_code={exit_code}", branch_str=branch_str or "",
            )
        elif exit_code == 2:
            result = _handle_test_failed(
                runner_id, redis_client, plan_file, _pub,
                action_name=action_name, _test_fix_attempt=_test_fix_attempt,
            )
        elif exit_code == 3:
            result = _handle_conflict(
                runner_id, redis_client, plan_file, _pub,
                action_name=action_name, branch_str=branch_str or "",
            )
        else:
            result = handler(runner_id, redis_client, plan_file, _pub, action_name)
        if snapshot_path and isinstance(result, dict):
            result.setdefault("snapshot_path", snapshot_path)

    except Exception as e:
        logger.error(f"[_execute_merge_with_lock] 예외 발생 (runner_id={runner_id}, action={action_name}): {e}")
        try:
            _transition_merge_status(runner_id, redis_client, ERROR, message=str(e), action_name=action_name)
        except Exception:
            pass
        result = {"success": False, "message": str(e), "merge_status": ERROR, "action": action_name}

    finally:
        _persist_merge_result_metadata(runner_id, redis_client, result)
        if lock_acquired:
            try:
                release_merge_turn(redis_client, runner_id, repo_id=_get_repo_id(PROJECT_ROOT))
            except Exception:
                pass
        # merge-results Redis list에 결과 push (merge history API 연동)
        MergePersistence(redis_client, runner_id).push_result_history(
            branch=branch_str,
            plan_file=plan_file,
            result=result,
        )
        # terminal merge sentinel은 normal log와 분리해 merge-log 채널에만 1회 publish한다.
        _publish_merge_completed_sentinel(runner_id, redis_client, result)

    return result


def _handle_post_merge_done(plan_file: str, runner_id: str, pub_fn, redis_client) -> dict:
    """머지 성공 후 done flow를 실행한다.

    plan_file에서 branch/worktree 헤더 필드를 제거하고,
    완료율을 체크하여 100%이면 done API를 호출하고,
    미완료 태스크가 있으면 main 추가 사이클을 예약한다.

    Args:
        plan_file: plan 파일 절대 경로 (None 또는 ALL 모드이면 스킵)
        runner_id: 로깅용 runner ID
        pub_fn: 로그 publish 함수 (msg: str) -> None
        redis_client: Redis 클라이언트
    """
    from plan_worktree_helpers import (
        remove_plan_header_fields as _remove_plan_header_fields,
        get_plan_completion as _get_plan_completion,
        is_fix_plan as _is_fix_plan,
        has_phase_r as _has_phase_r,
        has_undefended_paths as _has_undefended_paths,
    )
    if not plan_file or plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
        pub_fn("plan_file 없음(--all 모드) — done 스킵")
        return {"success": True, "status": "skipped_no_plan", "reason": "no_plan_file"}
    try:
        if redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status") == "residue_blocked":
            pub_fn("merge_status=residue_blocked 감지 — done/restart 스킵")
            return {"success": False, "status": "skipped_residue", "reason": "residue_guard"}
    except Exception:
        pass

    # plan 파일 존재 확인 — 이미 archive됨 (fix: v2-pipeline-transition-safety Phase 2)
    if not Path(plan_file).exists():
        pub_fn("plan 이미 처리됨 (파일 없음) — done 스킵")
        logger.info(f"[_handle_post_merge_done] plan 파일 없음, 이미 처리된 것으로 판단: {plan_file}")
        return {"success": True, "status": "skipped_missing_plan", "reason": "missing_plan_file"}

    # pre-review stopped는 done/restart 후처리 금지
    if _is_pre_review_stopped(runner_id, redis_client, plan_file):
        pub_fn("stop_stage=pre_review 감지 — post-merge done/restart 스킵")
        logger.info(f"[_handle_post_merge_done] pre_review stopped guard: runner={runner_id}, plan={plan_file}")
        return {"success": True, "status": "skipped_pre_review", "reason": "pre_review_stopped"}

    # plan 상태 확인 — "완료"이면 이미 done 처리됨
    try:
        _head = Path(plan_file).read_text(encoding="utf-8", errors="replace")[:2000]
        if re.search(r">\s*상태:\s*완료", _head):
            pub_fn("plan 이미 완료 상태 — done 스킵")
            return {"success": True, "status": "skipped_already_done", "reason": "already_done"}
    except Exception:
        pass

    # plan 헤더에서 branch/worktree 필드 제거 — 잔존 시 auto-done 에이전트가 /done 2.5단계에서 차단됨
    _remove_plan_header_fields(plan_file)

    # fallback 경로: plan 상태가 머지대기/통합테스트중이면 구현완료로 전이
    # (v2 handle_merge_stage에서 run_loop 상태 전이가 실행 안 됐을 때 보완)
    try:
        plan_text = Path(plan_file).read_text(encoding="utf-8", errors="replace")
        if re.search(r">\s*상태:\s*(머지대기|통합테스트중)", plan_text[:2000]):
            # fix plan 사전 검증: Phase R 부재/미방어 확인 (branch/worktree는 merge 직후이므로 면제)
            if _is_fix_plan(plan_file, plan_text):
                if not _has_phase_r(plan_text):
                    pub_fn("fix plan 사전 검증 실패 — 구현완료 전이 보류: Phase R 섹션 필수")
                    logger.warning(f"[_handle_post_merge_done] fix plan Phase R 부재, 구현완료 전이 스킵: {plan_file}")
                elif _has_undefended_paths(plan_text):
                    pub_fn("fix plan 사전 검증 실패 — 구현완료 전이 보류: Phase R에 미방어 경로 잔존")
                    logger.warning(f"[_handle_post_merge_done] fix plan Phase R 미방어 잔존, 구현완료 전이 스킵: {plan_file}")
                else:
                    updated = re.sub(
                        r"(>\s*상태:\s*)(머지대기|통합테스트중)",
                        r"\g<1>구현완료",
                        plan_text[:2000],
                    ) + plan_text[2000:]
                    Path(plan_file).write_text(updated, encoding="utf-8")
                    pub_fn("plan 상태 → 구현완료 전이 (fallback)")
                    logger.info(f"[_handle_post_merge_done] plan 상태 구현완료 전이: {plan_file}")
            else:
                updated = re.sub(
                    r"(>\s*상태:\s*)(머지대기|통합테스트중)",
                    r"\g<1>구현완료",
                    plan_text[:2000],
                ) + plan_text[2000:]
                Path(plan_file).write_text(updated, encoding="utf-8")
                pub_fn("plan 상태 → 구현완료 전이 (fallback)")
                logger.info(f"[_handle_post_merge_done] plan 상태 구현완료 전이: {plan_file}")
    except Exception as _st_err:
        logger.debug(f"[_handle_post_merge_done] plan 상태 전이 실패 (무시): {_st_err}")

    # 자동 done 분기: 완료율 체크 → done API 호출 or main 추가 사이클 예약
    done_count, total_count = _get_plan_completion(plan_file)
    if total_count > 0 and done_count == total_count:
        pub_fn(f"완료율 100% ({done_count}/{total_count}) — 자동 done 처리 시작")
        try:
            _register_post_merge_owned_files(runner_id, plan_file)
        except Exception as exc:
            logger.warning("[_handle_post_merge_done] ownership owned-files register 실패: runner=%s error=%s", runner_id, exc)
        done_result = _call_done_api(plan_file, runner_id, pub_fn)
        if done_result.get("success"):
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:done_post_merge_status", "success")
            except Exception:
                pass
            return {"success": True, "status": "done_called", "done_count": done_count, "total_count": total_count}

        failure_reason = str(done_result.get("reason") or "done_api_failed")
        if failure_reason == "residue_guard":
            error_key = "residue_guard"
        elif failure_reason == "ownership_guard":
            error_key = "ownership_guard"
        else:
            error_key = "done_api_failed"
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:done_post_merge_status", "failed")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:done_post_merge_error", error_key)
            if error_key != "residue_guard":
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge", "1")
        except Exception:
            pass
        if error_key == "residue_guard":
            pub_fn(f"자동 done 실패 ({failure_reason}) — residue 차단으로 추가 사이클 미예약")
        else:
            pub_fn(f"자동 done 실패 ({failure_reason}) — main 추가 사이클 예약")
        return {
            "success": False,
            "status": "done_failed",
            "reason": error_key,
            "message": str(done_result.get("message") or failure_reason),
            "done_count": done_count,
            "total_count": total_count,
        }

    pub_fn(f"미완료 태스크 있음 ({done_count}/{total_count}) — main 추가 사이클 예약")
    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge", "1")
    except Exception:
        pass
    return {"success": True, "status": "restart_scheduled", "done_count": done_count, "total_count": total_count}


def _call_done_api(plan_file: str, runner_id: str, pub_fn) -> dict:
    """plan_file 경로에 대해 Admin API /plans/{encoded_path}/done 를 호출한다.

    Args:
        plan_file: plan 파일 절대 경로
        runner_id: 로깅용 runner ID
        pub_fn: 로그 publish 함수 (msg: str) -> None

    Returns:
        {"success": bool, "reason": str|None, "message": str}
    """
    try:
        encoded = base64.urlsafe_b64encode(plan_file.encode("utf-8")).decode("ascii").rstrip("=")
        url = f"{get_admin_api_base()}/plans/{encoded}/done"
        headers = {"X-Plan-Runner-Id": runner_id} if runner_id else None
        resp = requests.post(url, timeout=60, headers=headers)
        if resp.status_code != 200:
            pub_fn(f"done API 실패 (status={resp.status_code}) — 수동 처리 필요")
            logger.warning(f"[_call_done_api] done API 실패: runner={runner_id}, status={resp.status_code}, url={url}")
            return {"success": False, "reason": "http_error", "message": f"done API failed with status={resp.status_code}"}

        try:
            payload = resp.json()
        except ValueError as parse_err:
            pub_fn("done API 응답 파싱 실패 — 수동 처리 필요")
            logger.warning(
                "[_call_done_api] done API 응답 파싱 실패: runner=%s, url=%s, error=%s",
                runner_id,
                url,
                parse_err,
            )
            return {"success": False, "reason": "invalid_json", "message": "done API returned invalid JSON"}

        if not isinstance(payload, dict):
            pub_fn("done API 응답 형식 오류 — 수동 처리 필요")
            logger.warning(
                "[_call_done_api] done API 응답 형식 오류: runner=%s, url=%s, type=%s",
                runner_id,
                url,
                type(payload).__name__,
            )
            return {"success": False, "reason": "invalid_payload", "message": "done API returned non-dict payload"}

        if payload.get("success") is False:
            reason = str(payload.get("reason") or "done_api_failed")
            message = str(payload.get("message") or reason)
            pub_fn(f"done API 실패 (success=false): {message} — 수동 처리 필요")
            logger.warning(
                "[_call_done_api] done API success=false: runner=%s, url=%s, reason=%s",
                runner_id,
                url,
                message,
            )
            return {"success": False, "reason": reason, "message": message}

        return {"success": True, "reason": None, "message": str(payload.get("message") or "")}
    except requests.exceptions.RequestException as e:
        pub_fn(f"done API 연결 실패: {e} — 수동 처리 필요")
        logger.warning(f"[_call_done_api] done API 연결 실패: runner={runner_id}, error={e}")
        return {"success": False, "reason": "request_exception", "message": str(e)}
