"""_dr_stream_cleanup.py — _stream_output finally 블록 리팩토링용 헬퍼 모듈"""
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis

from _dr_constants import (
    COMMANDS_KEY,
    LOG_CHANNEL_PREFIX,
    PLAN_FILE_ALL,
    RUNNER_KEY_PREFIX,
    _LEGACY_ALL,
)
from _dr_merge import _execute_merge_with_lock, _pub_and_log
from _dr_plan_paths import classify_plan_stage, read_plan_status
from _dr_process_utils import _cleanup_process_state
from _dr_subprocess import _ANSI_ESCAPE
from _dr_log_framing import MultilineFrameBuffer
from _dr_runtime_utils import _normalize_exit_reason, _publish_with_retry

logger = logging.getLogger(__name__)

# _dr_plan_runner.py에서 이동된 상수
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


def _build_failure_error_message(
    exit_code: Optional[int],
    exit_reason: str,
    stop_stage: Optional[str],
    detail: Optional[str],
) -> str:
    parts = [f"exit_code={exit_code}", f"exit_reason={exit_reason}"]
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
    # merge_requested 플래그 삭제 (중복 진입 방지)
    try:
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
    except Exception:
        pass

    _execute_merge_with_lock(runner_id, redis_client, action_name="inline-merge")

    # restart_after_merge 플래그 감지 → main 추가 사이클 트리거
    try:
        _flag = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge")
        if _flag:
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
                return
            if plan_file and plan_file not in (PLAN_FILE_ALL, _LEGACY_ALL):
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
    except redis.ConnectionError:
        logger.warning(
            f"[_do_inline_merge] restart_after_merge 감지 중 Redis 연결 실패 (무시)"
        )
    except Exception as _re:
        logger.warning(
            f"[_do_inline_merge] restart_after_merge 처리 실패 (무시): {_re}"
        )

    _cleanup_process_state(runner_id, redis_client)


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


def _determine_merge_requested(ctx: _StreamCleanupCtx) -> bool:
    """merge_requested 여부를 판정"""
    merge_requested = False
    flag = None
    if ctx.runner_id:
        try:
            flag = ctx.redis_client.get(
                f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:merge_requested"
            )
            if flag:
                if ctx.exit_code == 0:
                    if ctx.completed_for_flow:
                        merge_requested = True
                    else:
                        _pub_and_log(
                            ctx.runner_id,
                            f"[_stream_output] merge_requested 있지만 exit_reason={ctx.exit_reason}, stop_stage={ctx.stop_stage} → merge 스킵",
                            ctx.redis_client,
                            "CLEANUP",
                        )
                else:
                    # exit_code != 0: worktree 커밋 유무로 merge 여부 결정
                    branch_for_check = ctx.redis_client.get(
                        f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:branch"
                    )
                    if isinstance(branch_for_check, bytes):
                        branch_for_check = branch_for_check.decode("utf-8")
                    if branch_for_check:
                        try:
                            from _dr_constants import PROJECT_ROOT as _PR

                            log_proc = subprocess.run(
                                [
                                    "git",
                                    "log",
                                    f"main..{branch_for_check}",
                                    "--oneline",
                                ],
                                capture_output=True,
                                text=True,
                                cwd=str(_PR),
                                timeout=15,
                            )
                            commit_count = len(
                                [
                                    l
                                    for l in log_proc.stdout.splitlines()
                                    if l.strip()
                                ]
                            )
                            if commit_count > 0:
                                merge_requested = True
                                logger.info(
                                    f"[_stream_output] exit_code={ctx.exit_code}이지만 worktree 커밋 {commit_count}개 존재 "
                                    f"(runner_id={ctx.runner_id}, branch={branch_for_check}) — merge 시도"
                                )
                            else:
                                logger.info(
                                    f"[_stream_output] exit_code={ctx.exit_code}, worktree 커밋 없음 "
                                    f"(runner_id={ctx.runner_id}, branch={branch_for_check}) — merge 스킵"
                                )
                        except Exception as _git_err:
                            logger.warning(
                                f"[_stream_output] git log 커밋 수 확인 실패: {_git_err} — merge 스킵"
                            )
                    else:
                        logger.info(
                            f"[_stream_output] exit_code={ctx.exit_code}, branch 키 없음 — merge 스킵"
                        )
        except Exception as e:
            logger.warning(
                f"[_stream_output] merge_requested 플래그 조회 실패 (runner_id={ctx.runner_id}): {e}"
            )

    if merge_requested and ctx.stop_stage == "pre_review":
        merge_requested = False
        try:
            ctx.redis_client.delete(
                f"{RUNNER_KEY_PREFIX}:{ctx.runner_id}:merge_requested"
            )
        except Exception:
            pass
        _pub_and_log(
            ctx.runner_id,
            "[_stream_output] stop_stage=pre_review → inline merge 차단",
            ctx.redis_client,
            "CLEANUP",
        )

    # 로그 출력
    if flag:
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
