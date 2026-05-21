"""_dr_stream_cleanup.py — _stream_output finally 블록 리팩토링용 헬퍼 모듈"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis

from _dr_constants import (
    COMMANDS_KEY,
    DEV_RUNNER_PG_MIRROR_ENABLED_DEFAULT,
    DEV_RUNNER_PG_MIRROR_ENABLED_ENV,
    LOG_CHANNEL_PREFIX,
    PLAN_FILE_ALL,
    REROUTE_REQUIRED_PATH_KEY,
    ROOT_DIRTY_CLOSEOUT_STATUS_KEY,
    ROOT_DIRTY_PATHS_KEY,
    ROOT_DIRTY_STATUS_BLOCKED,
    ROOT_DIRTY_STATUS_REROUTE_REQUIRED,
    RUNNER_KEY_PREFIX,
    _LEGACY_ALL,
)
from _dr_merge_persistence import MergePersistence
from _dr_merge_state import MERGED, RESIDUE_BLOCKED, MergeCleanupAction, TERMINAL_STATUSES, should_enter_inline_merge
from _dr_merge import _execute_merge_with_lock, _handle_post_merge_done, detect_merged_but_not_done, _pub_and_log
from _dr_plan_paths import classify_plan_stage, read_plan_status
from _dr_process_utils import _cleanup_process_state, _cleanup_runner_ownership_snapshot
from _dr_subprocess import _ANSI_ESCAPE
from _dr_log_framing import MultilineFrameBuffer
from _dr_runtime_utils import _normalize_exit_reason, _publish_with_retry

logger = logging.getLogger(__name__)

# _dr_plan_runner.py에서 이동된 상수
_COMPLETED_EXIT_REASONS = {"completed"}  # 정상 완료로 처리되는 exit_reason 집합
_DEFAULT_DETECT_MERGED_BUT_NOT_DONE = detect_merged_but_not_done
_DEFAULT_HANDLE_POST_MERGE_DONE = _handle_post_merge_done
_DEFAULT_CLEANUP_PROCESS_STATE = _cleanup_process_state
_INLINE_MERGE_PRESERVE_STATUSES = TERMINAL_STATUSES
_ERROR_DETAIL_NOISE_PREFIXES = (
    "[NOISE]",
    ": heartbeat",
)
_ERROR_DETAIL_HINTS = (
    "error",
    "failed",
    "failure",
    "traceback",
    "exception",
    "timeout",
    "fatal",
    "exit code",
    "enoent",
    "winerror",
    "commit_scope=",
    "failed_projects=",
    "dirty_files=",
    "state transition commit",
    "상태 전이 커밋",
)

try:
    from listener_noise_filter import (
        NOISE_BLOCK_MARKERS as _NOISE_BLOCK_MARKERS,
    )
    from listener_noise_filter import is_noise_line as _is_noise_line
except ImportError:

    def _is_noise_line(line):
        return False

    _NOISE_BLOCK_MARKERS = []


def _resolve_hook(name: str, default):
    import sys as _sys

    current = globals().get(name, default)
    if current is not default:
        return current

    for _mod_name, _mod in list(_sys.modules.items()):
        if not _mod_name.startswith("_dr_plan_runner"):
            continue
        other = getattr(_mod, name, default)
        if other is not default:
            return other

    return default


@dataclass
class _StreamCleanupCtx:
    """_stream_output cleanup 과정의 공유 상태를 담는 컨텍스트"""

    runner_id: str
    redis_client: redis.Redis
    log_channel: str
    exit_code: Optional[int] = None
    exit_reason: str = "completed"
    stop_stage: Optional[str] = None
    completed_for_flow: bool = False
    wf_manager: Any = None
    suppressed_count: int = 0
    failure_message: Optional[str] = None


@dataclass
class MergeCleanupDecision:
    action: MergeCleanupAction
    reason: str
    log_message: str = ""


def _build_failure_error_message(
    exit_code: Optional[int],
    exit_reason: str,
    stop_stage: Optional[str],
    detail: Optional[str],
    lines_count: int = -1,
) -> str:
    parts = [f"exit_code={exit_code}", f"exit_reason={exit_reason}"]
    if lines_count == 0:
        parts.append(f"subprocess 즉시 종료 (exit_code={exit_code})")
    if stop_stage:
        parts.append(f"stop_stage={stop_stage}")
    if detail:
        parts.append(f"detail={detail}")
    return "; ".join(parts)


def _load_log_tail_lines(
    log_file_path: Optional[Path], max_lines: int = 120
) -> List[str]:
    if not log_file_path:
        return []
    try:
        with open(
            str(log_file_path), "r", encoding="utf-8", errors="replace"
        ) as handle:
            lines = handle.readlines()
            return [line.rstrip("\n") for line in lines[-max_lines:]]
    except Exception:
        return []


def _pick_error_detail_line(lines: List[str]) -> Optional[str]:
    if not lines:
        return None
    for line in reversed(lines):
        text = (line or "").strip()
        if not text:
            continue
        lower = text.lower()
        if any(
            lower.startswith(prefix.lower())
            for prefix in _ERROR_DETAIL_NOISE_PREFIXES
        ):
            continue
        if any(marker in lower for marker in _NOISE_BLOCK_MARKERS):
            continue
        if _is_noise_line(text):
            continue
        if any(hint in lower for hint in _ERROR_DETAIL_HINTS):
            return text[:400]

    # 힌트 라인이 없으면 마지막 유의미 라인이라도 보존
    for line in reversed(lines):
        text = (line or "").strip()
        if not text:
            continue
        lower = text.lower()
        if any(
            lower.startswith(prefix.lower())
            for prefix in _ERROR_DETAIL_NOISE_PREFIXES
        ):
            continue
        if any(marker in lower for marker in _NOISE_BLOCK_MARKERS):
            continue
        if _is_noise_line(text):
            continue
        return text[:400]
    return None


def _resolve_stop_stage(
    runner_id: str, redis_client: redis.Redis, exit_reason: str
) -> Optional[str]:
    """exit_reason=stopped인 경우 pre/post review 단계 판별 및 Redis 기록."""
    if not runner_id:
        return None
    key = f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage"
    if exit_reason != "stopped":
        try:
            redis_client.delete(key)
        except Exception:
            pass
        return None

    try:
        existing = redis_client.get(key)
        if existing:
            return existing.decode("utf-8") if isinstance(existing, bytes) else existing
    except Exception:
        existing = None

    stage = "unknown"
    try:
        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        if isinstance(plan_file, bytes):
            plan_file = plan_file.decode("utf-8")
        if plan_file and plan_file not in (PLAN_FILE_ALL, _LEGACY_ALL):
            status = read_plan_status(plan_file)
            classified = classify_plan_stage(status)
            if classified in ("pre_review", "post_review"):
                stage = classified
    except Exception as stage_err:
        logger.debug(
            f"[_stream_output] stop_stage 판별 실패 (runner_id={runner_id!r}): {stage_err}"
        )

    try:
        redis_client.set(key, stage)
    except Exception:
        pass
    return stage


def _do_inline_merge(runner_id: str, redis_client: redis.Redis) -> None:
    """merge_requested 플래그가 있을 때 _stream_output finally에서 호출되는 인라인 merge 함수.

    _execute_merge_with_lock()으로 공통 로직을 위임하고, cleanup만 처리한다.
    """
    _cleanup_process_state_fn = _resolve_hook(
        "_cleanup_process_state", _DEFAULT_CLEANUP_PROCESS_STATE
    )

    # merge_requested 플래그 삭제 (중복 진입 방지)
    try:
        MergePersistence(redis_client, runner_id).clear_request()
    except Exception:
        pass

    merge_result = _execute_merge_with_lock(runner_id, redis_client, action_name="inline-merge")

    # restart_after_merge 플래그 감지 → main 추가 사이클 트리거
    try:
        residue_blocked = (
            isinstance(merge_result, dict)
            and merge_result.get("merge_status") == "residue_blocked"
        )
        reroute_required = (
            isinstance(merge_result, dict)
            and merge_result.get(ROOT_DIRTY_CLOSEOUT_STATUS_KEY) == ROOT_DIRTY_STATUS_REROUTE_REQUIRED
        )
        if residue_blocked or reroute_required:
            redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge")
        else:
            _flag = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge")
            post_merge_done = merge_result.get("post_merge_done") if isinstance(merge_result, dict) else {}
            if _flag and isinstance(post_merge_done, dict) and post_merge_done.get("status") == "restart_scheduled":
                redis_client.delete(
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge"
                )
                plan_file = redis_client.get(
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file"
                )
                if isinstance(plan_file, bytes):
                    plan_file = plan_file.decode("utf-8")
                engine = (
                    redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine")
                    or "claude"
                )
                if isinstance(engine, bytes):
                    engine = engine.decode("utf-8")
                fix_engine = (
                    redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:fix_engine")
                    or "claude"
                )
                if isinstance(fix_engine, bytes):
                    fix_engine = fix_engine.decode("utf-8")
                trigger = redis_client.get(
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger"
                )
                if isinstance(trigger, bytes):
                    trigger = trigger.decode("utf-8")
                log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
                try:
                    redis_client.publish(
                        log_channel,
                        f"main 추가 사이클 시작 (plan={plan_file}, engine={engine}, fix_engine={fix_engine})",
                    )
                except Exception:
                    pass
                if not trigger:
                    logger.warning(
                        f"[_do_inline_merge] trigger 소실 — restart_after_merge 스킵: {runner_id}"
                    )
                elif plan_file and plan_file not in (PLAN_FILE_ALL, _LEGACY_ALL):
                    import uuid as _uuid

                    new_runner_id = _uuid.uuid4().hex[:8]
                    command = {
                        "action": "run",
                        "runner_id": new_runner_id,
                        "plan_file": plan_file,
                        "engine": engine,
                        "fix_engine": fix_engine,
                        "trigger": trigger,
                    }
                    redis_client.lpush(
                        COMMANDS_KEY, json.dumps(command, ensure_ascii=False)
                    )
                    _pub_and_log(
                        runner_id,
                        f"[_do_inline_merge] main 추가 사이클 큐잉: runner={new_runner_id}, plan={plan_file}",
                        redis_client,
                        "MERGE",
                    )
                    _cleanup_runner_ownership_snapshot(runner_id)
    except redis.ConnectionError:
        logger.warning(
            f"[_do_inline_merge] restart_after_merge 감지 중 Redis 연결 실패 (무시)"
        )
    except Exception as _re:
        logger.warning(
            f"[_do_inline_merge] restart_after_merge 처리 실패 (무시): {_re}"
        )

    _cleanup_process_state_fn(runner_id, redis_client)


def _resolve_exit_status(ctx: _StreamCleanupCtx) -> None:
    """exit_reason, stop_stage, completed_for_flow를 결정하여 ctx 업데이트"""
    if ctx.runner_id:
        try:
            val = ctx.redis_client.get(
                f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:exit_reason"
            )
            if isinstance(val, bytes):
                val = val.decode("utf-8")
            ctx.exit_reason = _normalize_exit_reason(val)
        except Exception as _er:
            logger.warning(
                f"[_stream_output] exit_reason 조회 실패 (runner_id={ctx.runner_id!r}): {_er}"
            )
            ctx.exit_reason = "error"

    ctx.stop_stage = (
        _resolve_stop_stage(ctx.runner_id, ctx.redis_client, ctx.exit_reason)
        if ctx.runner_id
        else None
    )
    ctx.completed_for_flow = ctx.exit_reason in _COMPLETED_EXIT_REASONS


def _drain_stdout_log(
    ctx: _StreamCleanupCtx,
    log_file_path: Optional[Path],
    last_flushed_pos: int,
    publish_cb: Any,
) -> List[str]:
    """파이프 종료 후 파일에 남은 로그 drain 및 tail_lines_buf 반환"""
    tail_lines_for_detail: List[str] = []
    if log_file_path and ctx.runner_id:
        try:
            with open(
                str(log_file_path), "r", encoding="utf-8", errors="replace"
            ) as _drain_f:
                _drain_f.seek(0, 2)
                end_pos = _drain_f.tell()
                if last_flushed_pos >= end_pos:
                    pass
                else:
                    start_pos = max(last_flushed_pos, end_pos - 8192)
                    _drain_f.seek(start_pos)
                    tail_lines = _drain_f.readlines()
                    drain_framer = MultilineFrameBuffer(max_chars=8192)
                    for _tail_line in tail_lines[-50:]:
                        _stripped = _tail_line.rstrip("\n")
                        if _stripped:
                            _cleaned = _ANSI_ESCAPE.sub("", _stripped)
                            tail_lines_for_detail.append(_cleaned)
                            if _is_noise_line(_cleaned):
                                _pending = drain_framer.flush()
                                if _pending:
                                    publish_cb(_pending)
                                ctx.suppressed_count += 1
                                continue
                            _ready_frames, _overflow = drain_framer.push_line(
                                _cleaned
                            )
                            if _overflow:
                                logger.warning(
                                    f"[_stream_output] drain 프레임 버퍼 상한 초과 즉시 flush (runner_id={ctx.runner_id!r})"
                                )
                            for _frame in _ready_frames:
                                publish_cb(_frame)
                    _drain_tail = drain_framer.flush()
                    if _drain_tail:
                        publish_cb(_drain_tail)
        except Exception as _drain_err:
            logger.debug(f"[_stream_output] stdout drain 실패 (무시): {_drain_err}")

    if ctx.suppressed_count > 0:
        _publish_with_retry(
            ctx.redis_client,
            ctx.log_channel,
            f"[NOISE] {ctx.suppressed_count} lines suppressed",
        )
        ctx.suppressed_count = 0

    return tail_lines_for_detail


def _process_error_details(
    ctx: _StreamCleanupCtx,
    log_file_path: Optional[Path],
    tail_lines_buf: List[str],
) -> None:
    """에러 상세 추출 및 Redis/Log 채널 발행"""
    error_detail = _pick_error_detail_line(_load_log_tail_lines(log_file_path))
    if not error_detail:
        error_detail = _pick_error_detail_line(tail_lines_buf)

    ctx.failure_message = _build_failure_error_message(
        exit_code=ctx.exit_code,
        exit_reason=ctx.exit_reason,
        stop_stage=ctx.stop_stage,
        detail=error_detail,
    )

    if ctx.runner_id and not ctx.completed_for_flow:
        try:
            error_message = (
                ctx.failure_message
                if ctx.exit_reason == "commit_failed"
                else (error_detail or ctx.failure_message)
            )
            ctx.redis_client.set(
                f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:error", error_message
            )
            if "root_worktree_impl_scope_blocked" in error_message:
                MergePersistence(ctx.redis_client, ctx.runner_id).transition(
                    RESIDUE_BLOCKED,
                    reason="root_worktree_impl_scope_blocked",
                    message=error_message[:500],
                    action="approved-retry",
                )
                ctx.redis_client.set(
                    f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:{ROOT_DIRTY_CLOSEOUT_STATUS_KEY}",
                    ROOT_DIRTY_STATUS_BLOCKED,
                )
            if error_detail:
                _publish_with_retry(
                    ctx.redis_client, ctx.log_channel, f"[ERROR] {error_detail}"
                )
            else:
                _publish_with_retry(
                    ctx.redis_client,
                    ctx.log_channel,
                    f"[ERROR] {ctx.failure_message}",
                )
        except Exception as _error_save_err:
            logger.debug(
                f"[_stream_output] error detail 저장 실패 (무시): {_error_save_err}"
            )


def _decode_redis_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _mirror_terminal_state_to_db(ctx: _StreamCleanupCtx, merge_requested: bool) -> None:
    """Best-effort Postgres mirror for cleanup terminal evidence."""
    if not ctx.runner_id:
        return
    import os

    if os.environ.get(DEV_RUNNER_PG_MIRROR_ENABLED_ENV, DEV_RUNNER_PG_MIRROR_ENABLED_DEFAULT) in {"0", "false", "False"}:
        return

    try:
        from app.database import SessionLocal
        from app.modules.dev_runner.services.dev_runner_state_repository import upsert_runner_state

        prefix = f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}"
        plan_file = _decode_redis_text(ctx.redis_client.get(f"{prefix}:plan_file")) or PLAN_FILE_ALL
        branch = _decode_redis_text(ctx.redis_client.get(f"{prefix}:branch")) or None
        worktree_path = _decode_redis_text(ctx.redis_client.get(f"{prefix}:worktree_path")) or None
        start_time = _decode_redis_text(ctx.redis_client.get(f"{prefix}:start_time"))
        merge_status = _decode_redis_text(ctx.redis_client.get(f"{prefix}:merge_status")) or None
        status = "머지대기" if merge_requested else "stopped"
        if merge_status == "merging":
            status = "통합테스트중"

        started_at = None
        if start_time:
            try:
                from datetime import datetime as _datetime

                started_at = _datetime.fromisoformat(start_time)
            except ValueError:
                started_at = None

        db = SessionLocal()
        try:
            upsert_runner_state(
                db,
                {
                    "runner_id": ctx.runner_id,
                    "plan_file": plan_file,
                    "project": "monitor-page",
                    "status": status,
                    "started_at": started_at,
                    "branch": branch,
                    "worktree_path": worktree_path,
                    "exit_reason": ctx.exit_reason,
                    "merge_requested": bool(merge_requested),
                    "completed_at": None if merge_requested else datetime.now(),
                    "metadata": {
                        "merge_status": merge_status,
                        "stop_stage": ctx.stop_stage,
                        "failure_message": ctx.failure_message,
                    },
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as exc:
        logger.warning("[dev-runner] Postgres runner mirror failed; Redis cleanup continues: %s", exc)


def _project_root() -> Path:
    from _dr_constants import PROJECT_ROOT as root
    return Path(root)


def _resolve_plan_path(plan_file: str | None) -> Path | None:
    if not plan_file or plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
        return None
    path = Path(plan_file)
    if not path.is_absolute():
        path = _project_root() / path
    return path


def _read_runner_plan_file(runner_id: str, redis_client) -> str:
    plan_file = _decode_redis_text(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")).strip()
    if plan_file:
        return plan_file
    try:
        recent_raw = redis_client.get(f"plan-runner:recent-meta:{runner_id}")
        recent_text = _decode_redis_text(recent_raw)
        if recent_text:
            recent = json.loads(recent_text)
            return str(recent.get("plan_file") or "").strip()
    except Exception:
        pass
    return ""


def _read_plan_header_evidence(plan_file: str | None) -> tuple[str, str]:
    plan_path = _resolve_plan_path(plan_file)
    if not plan_path or not plan_path.exists():
        return "", ""
    try:
        branch = ""
        worktree = ""
        for line in plan_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("> branch:"):
                branch = line.split(":", 1)[1].strip()
            elif line.startswith("> worktree:"):
                worktree = line.split(":", 1)[1].strip()
            if branch and worktree:
                break
        return branch, worktree
    except Exception as exc:
        logger.debug(f"[_has_worktree_commits] plan header 읽기 실패: {exc}")
        return "", ""


def _resolve_worktree_path(worktree_path: str | None) -> Path | None:
    if not worktree_path:
        return None
    path = Path(worktree_path)
    if not path.is_absolute():
        path = _project_root() / path
    return path


def _git_log_has_commits(refspec: str, cwd: Path) -> tuple[bool, int]:
    log_proc = subprocess.run(
        ["git", "log", refspec, "--oneline"],
        capture_output=True, text=True, cwd=str(cwd), timeout=15,
    )
    commit_count = len([line for line in log_proc.stdout.splitlines() if line.strip()])
    return commit_count > 0, commit_count


def _get_worktree_head_branch(worktree_path: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, cwd=str(worktree_path), timeout=15,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _is_post_merge_phase_header(header: str) -> bool:
    normalized = header.strip().lower()
    return bool(re.search(r"\b(?:phase\s+)?(?:t4|t5|z)\b", normalized))


def _remaining_leaf_summary(plan_file: str | None) -> dict[str, int]:
    summary = {"impl": 0, "post_merge": 0, "total": 0}
    plan_path = _resolve_plan_path(plan_file)
    if not plan_path or not plan_path.exists():
        return summary
    current_phase = ""
    checkbox_re = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(?:[-*]\s+)?\[\s\]")
    phase_re = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
    try:
        for line in plan_path.read_text(encoding="utf-8", errors="replace").splitlines():
            phase_match = phase_re.match(line)
            if phase_match:
                current_phase = phase_match.group(1)
                continue
            if not checkbox_re.match(line):
                continue
            key = "post_merge" if _is_post_merge_phase_header(current_phase) else "impl"
            summary[key] += 1
            summary["total"] += 1
    except Exception as exc:
        logger.debug(f"[_remaining_leaf_summary] plan 읽기 실패: {exc}")
    return summary


def _completed_residual_state(runner_id: str, redis_client) -> tuple[str, dict[str, int], str]:
    plan_file = _read_runner_plan_file(runner_id, redis_client)
    summary = _remaining_leaf_summary(plan_file)
    if summary["total"] == 0:
        return "none", summary, plan_file
    if summary["impl"] == 0 and summary["post_merge"] > 0:
        return "post_merge_only", summary, plan_file
    return "impl_remaining", summary, plan_file


def _publish_merge_evidence_missing(runner_id: str, redis_client, plan_file: str, branch_key: str, worktree_path: str) -> None:
    msg = (
        "MERGE-EVIDENCE-MISSING "
        f"runner_id={runner_id}, plan_file={plan_file or '(none)'}, "
        f"branch_key={branch_key or '(none)'}, worktree_path={worktree_path or '(none)'}"
    )
    try:
        _pub_and_log(runner_id, msg, redis_client, "CLEANUP")
    except Exception:
        logger.warning(msg)


def _has_worktree_commits(runner_id: str, redis_client) -> bool:
    """워크트리 브랜치에 main 대비 커밋이 있으면 True를 반환한다.

    - branch Redis 키가 없으면 plan header/worktree HEAD 순으로 fallback한다.
    - git log 실행 실패 시 False 반환 (안전 기본값 — merge 스킵)
    """
    try:
        branch = _decode_redis_text(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")).strip()
        worktree_path = _decode_redis_text(redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")).strip()
        plan_file = _read_runner_plan_file(runner_id, redis_client)
        evidence_source = "redis" if branch else ""
        if not branch:
            header_branch, header_worktree = _read_plan_header_evidence(plan_file)
            if header_branch:
                branch = header_branch
                evidence_source = "plan_header"
                try:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch)
                except Exception:
                    pass
            if not worktree_path and header_worktree:
                worktree_path = header_worktree
                try:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", worktree_path)
                except Exception:
                    pass
        if branch:
            has_commits, commit_count = _git_log_has_commits(f"main..{branch}", _project_root())
            logger.info(
                f"[_has_worktree_commits] evidence_source={evidence_source or 'redis'} "
                f"(runner_id={runner_id}, branch={branch}, commits={commit_count}) → {has_commits}"
            )
            return has_commits

        resolved_worktree = _resolve_worktree_path(worktree_path)
        if resolved_worktree and resolved_worktree.exists():
            head_branch = _get_worktree_head_branch(resolved_worktree)
            if head_branch:
                try:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", head_branch)
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", str(resolved_worktree))
                except Exception:
                    pass
                has_commits, commit_count = _git_log_has_commits("main..HEAD", resolved_worktree)
                logger.info(
                    f"[_has_worktree_commits] evidence_source=worktree_head "
                    f"(runner_id={runner_id}, branch={head_branch}, worktree={resolved_worktree}, commits={commit_count}) → {has_commits}"
                )
                return has_commits

        _publish_merge_evidence_missing(runner_id, redis_client, plan_file, branch, worktree_path)
        if not branch:
            logger.info(
                f"[_has_worktree_commits] branch/worktree evidence 없음 (runner_id={runner_id}) → False"
            )
            return False
    except Exception as e:
        logger.warning(f"[_has_worktree_commits] git log 확인 실패: {e} → False")
        return False


def _get_merge_status(redis_client, runner_id: str) -> str:
    if not runner_id:
        return ""
    try:
        return MergePersistence(redis_client, runner_id).read().merge_status
    except Exception:
        return ""


def _get_merge_reason(redis_client, runner_id: str) -> str:
    if not runner_id:
        return ""
    try:
        return MergePersistence(redis_client, runner_id).read().merge_reason
    except Exception:
        return ""


def _ensure_terminal_merge_reason(redis_client, runner_id: str, merge_status: str) -> str:
    reason = _get_merge_reason(redis_client, runner_id)
    if reason:
        return reason
    reason = "unknown_merge_error" if merge_status == ERROR else merge_status
    try:
        MergePersistence(redis_client, runner_id).transition(
            merge_status,
            reason=reason,
            message=f"terminal merge_status={merge_status} without reason",
            action="cleanup-terminal-reason-fill",
        )
    except Exception:
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_reason", reason)
        except Exception:
            pass
    return reason


def _preserve_terminal_merge_state_if_needed(ctx: _StreamCleanupCtx, *, flag_present: bool) -> bool:
    """Return True when cleanup must not re-enter inline merge.

    Some merge statuses are terminal user-action states. A leftover
    merge_requested flag from the completed subprocess is lower priority than
    those terminal states and must not trigger another stale-gated merge.
    """
    merge_status = _get_merge_status(ctx.redis_client, ctx.runner_id)
    if merge_status not in _INLINE_MERGE_PRESERVE_STATUSES:
        return False
    merge_reason = _ensure_terminal_merge_reason(ctx.redis_client, ctx.runner_id, merge_status)

    if flag_present:
        try:
            MergePersistence(ctx.redis_client, ctx.runner_id).clear_request()
        except Exception:
            pass

    _pub_and_log(
        ctx.runner_id,
        "[_stream_output] terminal merge_status 보존 → inline merge 차단 "
        f"(merge_status={merge_status}, merge_reason={merge_reason or '(none)'}, exit_code={ctx.exit_code}, "
        f"exit_reason={ctx.exit_reason}, stop_stage={ctx.stop_stage})",
        ctx.redis_client,
        "CLEANUP",
    )
    return True


def _persist_fallback_gate_evidence_summary(
    ctx: _StreamCleanupCtx,
    detect_result: dict,
    done_result: dict,
) -> None:
    if not ctx.runner_id or not isinstance(done_result, dict):
        return
    try:
        merge_status = _get_merge_status(ctx.redis_client, ctx.runner_id) or MERGED
        MergePersistence(ctx.redis_client, ctx.runner_id).persist_result_metadata(
            {
                "success": bool(done_result.get("success", True)),
                "merge_status": merge_status,
                "message": done_result.get("message") or f"fallback done status={done_result.get('status', 'unknown')}",
                "reason": done_result.get("reason") or done_result.get("status"),
                "quarantine_diff_path": detect_result.get("quarantine_diff_path"),
                ROOT_DIRTY_CLOSEOUT_STATUS_KEY: done_result.get(ROOT_DIRTY_CLOSEOUT_STATUS_KEY),
                ROOT_DIRTY_PATHS_KEY: done_result.get(ROOT_DIRTY_PATHS_KEY),
                REROUTE_REQUIRED_PATH_KEY: done_result.get(REROUTE_REQUIRED_PATH_KEY),
                "snapshot_path": detect_result.get("snapshot_path"),
                "post_merge_done": done_result,
            }
        )
    except Exception:
        logger.debug("[_stream_output] fallback gate evidence persist failed", exc_info=True)


def decide_cleanup_action(
    state,
    exit_code: Optional[int],
    exit_reason: str,
    stop_stage: Optional[str],
    completed_for_flow: bool,
    has_worktree_commits: bool,
) -> MergeCleanupDecision:
    if state.merge_status == MERGED:
        return MergeCleanupDecision(
            MergeCleanupAction.FALLBACK_DONE,
            "merged_not_done_check",
            "merge_status=merged uses post-merge fallback detection",
        )
    if state.merge_status in TERMINAL_STATUSES:
        return MergeCleanupDecision(
            MergeCleanupAction.BLOCKED_TERMINAL,
            state.merge_status,
            f"terminal merge_status={state.merge_status} blocks inline merge",
        )
    if stop_stage == "pre_review":
        return MergeCleanupDecision(MergeCleanupAction.SKIP, "pre_review", "pre_review stop blocks inline merge")
    if should_enter_inline_merge(state.merge_status, state.merge_requested, exit_code, stop_stage):
        if exit_code == 0 and not completed_for_flow:
            return MergeCleanupDecision(MergeCleanupAction.SKIP, "not_completed_for_flow")
        if exit_code == 0 or has_worktree_commits:
            return MergeCleanupDecision(MergeCleanupAction.INLINE_MERGE, "merge_requested")
    if exit_code == 0 and completed_for_flow and has_worktree_commits:
        return MergeCleanupDecision(MergeCleanupAction.INLINE_MERGE, "completed_with_commits")
    return MergeCleanupDecision(MergeCleanupAction.SKIP, "no_merge_requested")


def _determine_merge_requested(ctx: _StreamCleanupCtx) -> bool:
    """merge_requested 여부를 판정"""
    merge_requested = False
    flag = None
    decision = MergeCleanupDecision(MergeCleanupAction.SKIP, "no_runner")
    if ctx.runner_id:
        try:
            persistence = MergePersistence(ctx.redis_client, ctx.runner_id)
            state = persistence.read()
            flag = "1" if state.merge_requested else None
            if state.merge_status in _INLINE_MERGE_PRESERVE_STATUSES:
                if _preserve_terminal_merge_state_if_needed(ctx, flag_present=state.merge_requested):
                    decision = MergeCleanupDecision(
                        MergeCleanupAction.BLOCKED_TERMINAL,
                        state.merge_status,
                        f"terminal merge_status={state.merge_status} blocks inline merge",
                    )
                    return False

            has_commits = False
            if state.merge_requested and ctx.exit_code != 0:
                has_commits = _has_worktree_commits(ctx.runner_id, ctx.redis_client)
            elif not state.merge_requested and ctx.exit_code == 0 and ctx.completed_for_flow:
                has_commits = _has_worktree_commits(ctx.runner_id, ctx.redis_client)

            decision = decide_cleanup_action(
                state,
                ctx.exit_code,
                ctx.exit_reason,
                ctx.stop_stage,
                ctx.completed_for_flow,
                has_commits,
            )

            if decision.action == MergeCleanupAction.BLOCKED_TERMINAL:
                _preserve_terminal_merge_state_if_needed(ctx, flag_present=state.merge_requested)
                return False
            if decision.action == MergeCleanupAction.INLINE_MERGE:
                merge_requested = True
                if not state.merge_requested and has_commits:
                    _pub_and_log(
                        ctx.runner_id,
                        "[_stream_output] merge_requested 플래그 없음 + exit_code=0 + completed + 워크트리 커밋 있음 → merge",
                        ctx.redis_client,
                        "CLEANUP",
                    )
            elif state.merge_requested:
                if ctx.exit_code == 0:
                    if not ctx.completed_for_flow:
                        _pub_and_log(
                            ctx.runner_id,
                            f"[_stream_output] merge_requested 있지만 exit_reason={ctx.exit_reason}, stop_stage={ctx.stop_stage} → merge 스킵",
                            ctx.redis_client,
                            "CLEANUP",
                        )
                else:
                    if not has_commits:
                        logger.info(
                            f"[_stream_output] exit_code={ctx.exit_code}, worktree 커밋 없음 "
                            f"(runner_id={ctx.runner_id}) — merge 스킵"
                        )
        except Exception as e:
            logger.warning(
                f"[_stream_output] merge_requested 플래그 조회 실패 (runner_id={ctx.runner_id}): {e}"
            )

    if merge_requested and ctx.stop_stage == "pre_review":
        merge_requested = False
        try:
            MergePersistence(ctx.redis_client, ctx.runner_id).clear_request()
        except Exception:
            pass
        _pub_and_log(
            ctx.runner_id,
            f"[_stream_output] stop_stage=pre_review → inline merge 차단 ({decision.reason})",
            ctx.redis_client,
            "CLEANUP",
        )

    # 로그 출력 — flag 있음 또는 flag 없이 worktree 커밋 감지로 merge 결정된 경우 CLEANUP 채널에 출력
    if flag or merge_requested:
        _pub_and_log(
            ctx.runner_id,
            f"[_stream_output] merge 분기 판정: _merge_requested={merge_requested}, exit_code={ctx.exit_code}, exit_reason={ctx.exit_reason}, stop_stage={ctx.stop_stage}",
            ctx.redis_client,
            "CLEANUP",
        )
    else:
        logger.debug(
            f"[_stream_output] merge 분기 판정: _merge_requested={merge_requested}, exit_code={ctx.exit_code}, exit_reason={ctx.exit_reason}, stop_stage={ctx.stop_stage}"
        )

    return merge_requested


def _update_workflow_status(ctx: _StreamCleanupCtx, merge_requested: bool) -> bool:
    """Update workflow state and return the effective cleanup action flag."""
    if ctx.wf_manager and ctx.runner_id:
        try:
            wf = ctx.wf_manager.get_by_runner_id(ctx.runner_id)
            if wf:
                merge_status = _get_merge_status(ctx.redis_client, ctx.runner_id)
                terminal_merge_status = merge_status if merge_status in TERMINAL_STATUSES else ""
                if merge_status == "approval_required":
                    if wf.get("status") != "merge_pending":
                        ctx.wf_manager.update_status(
                            wf["id"],
                            "merge_pending",
                            error_message=ctx.failure_message,
                        )
                    _pub_and_log(
                        ctx.runner_id,
                        "[_stream_output] approval_required 보존 → workflow failed 전이 차단",
                        ctx.redis_client,
                        "CLEANUP",
                    )
                    return False
                if ctx.exit_code == 0:
                    if merge_requested:
                        _pub_and_log(
                            ctx.runner_id,
                            "[_stream_output] merge_requested 플래그 감지 → merge 흐름 진입",
                            ctx.redis_client,
                            "CLEANUP",
                        )
                        ctx.wf_manager.update_status(wf["id"], "merge_pending")
                    else:
                        if ctx.completed_for_flow:
                            residual_state, residual_summary, residual_plan = _completed_residual_state(
                                ctx.runner_id, ctx.redis_client
                            )
                            if residual_state == "post_merge_only":
                                if terminal_merge_status:
                                    merge_reason = _ensure_terminal_merge_reason(ctx.redis_client, ctx.runner_id, terminal_merge_status)
                                    message = (
                                        "blocked_post_merge_error: "
                                        f"terminal_merge_status={terminal_merge_status}, "
                                        f"merge_reason={merge_reason}, "
                                        f"remaining_post_merge={residual_summary['post_merge']}, "
                                        f"plan={residual_plan}"
                                    )
                                    _pub_and_log(ctx.runner_id, f"[_stream_output] {message}", ctx.redis_client, "CLEANUP")
                                    ctx.wf_manager.update_status(wf["id"], "failed", error_message=message)
                                else:
                                    merge_requested = True
                                    _pub_and_log(
                                        ctx.runner_id,
                                        "[_stream_output] completed 직전 post-merge-only 잔여 감지 "
                                        f"(plan={residual_plan}, remaining_post_merge={residual_summary['post_merge']}) → merge_pending",
                                        ctx.redis_client,
                                        "CLEANUP",
                                    )
                                    ctx.wf_manager.update_status(wf["id"], "merge_pending")
                            elif residual_state == "impl_remaining":
                                message = (
                                    "completed_with_remaining_tasks: "
                                    f"plan={residual_plan}, remaining_impl={residual_summary['impl']}, "
                                    f"remaining_post_merge={residual_summary['post_merge']}"
                                )
                                _pub_and_log(ctx.runner_id, f"[_stream_output] {message}", ctx.redis_client, "CLEANUP")
                                ctx.wf_manager.update_status(
                                    wf["id"], "failed", error_message=message
                                )
                            else:
                                _pub_and_log(
                                    ctx.runner_id,
                                    f"[_stream_output] merge_requested 플래그 없음 + exit_reason={ctx.exit_reason}, stop_stage={ctx.stop_stage} → completed 처리",
                                    ctx.redis_client,
                                    "CLEANUP",
                                )
                                ctx.wf_manager.update_status(wf["id"], "completed")
                        else:
                            _pub_and_log(
                                ctx.runner_id,
                                f"[_stream_output] exit_code=0이지만 exit_reason={ctx.exit_reason}, stop_stage={ctx.stop_stage} → failed 처리",
                                ctx.redis_client,
                                "CLEANUP",
                            )
                            ctx.wf_manager.update_status(
                                wf["id"], "failed", error_message=ctx.failure_message
                            )
                elif ctx.exit_code is not None and ctx.exit_code != 0:
                    ctx.wf_manager.update_status(
                        wf["id"], "failed", error_message=ctx.failure_message
                    )
                else:
                    logger.warning(
                        f"[_stream_output] exit_code=None → workflow {wf['id']} failed 처리"
                    )
                    ctx.wf_manager.update_status(
                        wf["id"], "failed", error_message=ctx.failure_message
                    )
        except Exception as wf_err:
            logger.warning(f"[_stream_output] workflow update 실패 (무시): {wf_err}")

    return merge_requested


def _execute_cleanup_action(
    ctx: _StreamCleanupCtx,
    merge_requested: bool,
    *,
    detect_merged_but_not_done,
    handle_post_merge_done_fn,
    cleanup_process_state_fn,
) -> None:
    """Dispatch the cleanup action selected by decision/workflow evaluation."""
    if merge_requested:
        if _preserve_terminal_merge_state_if_needed(ctx, flag_present=True):
            merge_requested = False

    if not merge_requested and _preserve_terminal_merge_state_if_needed(ctx, flag_present=False):
        cleanup_process_state_fn(ctx.runner_id, ctx.redis_client)
        return

    if merge_requested:
        # merge 흐름 — cleanup은 merge 완료/실패 후 _do_inline_merge 내부에서 호출
        _do_inline_merge(ctx.runner_id, ctx.redis_client)
    else:
        # v2 merge fallback: merge_requested 플래그 없이도 "이미 머지됐지만 done 처리가 안 된" 상태를 감지하는 안전장치
        _v2_detect = None
        if ctx.runner_id:
            try:
                _v2_detect = detect_merged_but_not_done(ctx.runner_id, ctx.redis_client)
            except Exception as _det_err:
                logger.debug(f"[_stream_output] v2 detect 실패 (무시): {_det_err}")
        if _v2_detect:
            logger.info(
                f"[_stream_output] v2 merge 후처리 fallback 실행: "
                f"runner_id={ctx.runner_id}, plan={_v2_detect['plan_file']}"
            )
            try:
                def _pub_fallback(msg: str) -> None:
                    _pub_and_log(ctx.runner_id, msg, ctx.redis_client, "MERGE-FALLBACK")

                _done_result = handle_post_merge_done_fn(
                    _v2_detect["plan_file"], ctx.runner_id, _pub_fallback, ctx.redis_client
                )
                _persist_fallback_gate_evidence_summary(ctx, _v2_detect, _done_result)
                if ctx.wf_manager and ctx.runner_id:
                    try:
                        _wf = ctx.wf_manager.get_by_runner_id(ctx.runner_id)
                        if _wf:
                            if not _done_result.get("success", True):
                                _reason = _done_result.get("reason", "done_post_merge_failed")
                                ctx.wf_manager.update_status(
                                    _wf["id"],
                                    "failed",
                                    error_message=f"Fallback done failed: {_reason}",
                                )
                            elif ctx.completed_for_flow:
                                ctx.wf_manager.update_status(_wf["id"], "completed")
                            else:
                                ctx.wf_manager.update_status(
                                    _wf["id"], "failed", error_message=ctx.failure_message
                                )
                    except Exception as _wf_err:
                        logger.debug(
                            f"[_stream_output] fallback workflow update 실패 (무시): {_wf_err}"
                        )
            except Exception as _fallback_err:
                logger.warning(
                    f"[_stream_output] v2 merge fallback 실패 (cleanup은 계속): "
                    f"runner_id={ctx.runner_id}, error={_fallback_err}"
                )
        cleanup_process_state_fn(ctx.runner_id, ctx.redis_client)


def _update_workflow_and_execute_cleanup(
    ctx: _StreamCleanupCtx, merge_requested: bool
) -> None:
    """Workflow 상태 업데이트(구역 D) 및 merge/fallback 실행(구역 E)"""
    _detect_merged_but_not_done = _resolve_hook(
        "detect_merged_but_not_done", _DEFAULT_DETECT_MERGED_BUT_NOT_DONE
    )
    _handle_post_merge_done_fn = _resolve_hook(
        "_handle_post_merge_done", _DEFAULT_HANDLE_POST_MERGE_DONE
    )
    _cleanup_process_state_fn = _resolve_hook(
        "_cleanup_process_state", _DEFAULT_CLEANUP_PROCESS_STATE
    )

    merge_requested = _update_workflow_status(ctx, merge_requested)
    _mirror_terminal_state_to_db(ctx, merge_requested)
    _execute_cleanup_action(
        ctx,
        merge_requested,
        detect_merged_but_not_done=_detect_merged_but_not_done,
        handle_post_merge_done_fn=_handle_post_merge_done_fn,
        cleanup_process_state_fn=_cleanup_process_state_fn,
    )
