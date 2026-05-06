"""_dr_plan_runner.py — dev-runner plan-runner 프로세스 실행 모듈"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import json
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import IO, Dict, Optional

import psutil
import redis

from _dr_constants import (
    RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, PLAN_FILE_ALL, _LEGACY_ALL,
    LOG_CHANNEL_PREFIX, COMMANDS_KEY, PLAN_RUNNER_PYTHON, PLAN_RUNNER_MODULE_PATH,
    LOG_DIR, PROJECT_ROOT, SUBPROCESS_HEARTBEAT_TTL,
)
from _dr_state import (
    get_running_processes, get_running_log_files, get_stream_threads,
    get_cleanup_done, get_wf_manager,
)
from _dr_subprocess import _ANSI_ESCAPE, _make_plan_runner_env
from _dr_plan_paths import classify_plan_stage, read_plan_status
from _dr_log_framing import MultilineFrameBuffer
from _dr_process_utils import _cleanup_process_state, _is_pid_alive, get_plan_git_root, get_target_project_root, _DummyProcess
from _dr_runner_predicates import _get_process_identity, _hash_process_cmdline
from _dr_runtime_utils import _normalize_exit_reason, _publish_with_retry
from _dr_merge import _handle_post_merge_done, detect_merged_but_not_done, _pub_and_log
from _dr_stream_cleanup import (
    _COMPLETED_EXIT_REASONS,
    _StreamCleanupCtx,
    _build_failure_error_message,
    _determine_merge_requested,
    _do_inline_merge,
    _drain_stdout_log,
    _has_worktree_commits,
    _load_log_tail_lines,
    _pick_error_detail_line,
    _process_error_details,
    _resolve_exit_status,
    _resolve_stop_stage,
    _update_workflow_and_execute_cleanup,
)

logger = logging.getLogger(__name__)

def _register_canonical_alias() -> None:
    """unique loader name으로 import돼도 canonical alias를 최신 모듈로 맞춘다."""
    import sys as _sys

    module = _sys.modules.get(__name__)
    if module is None:
        import inspect as _inspect

        frame = _inspect.currentframe()
        try:
            while frame is not None:
                candidate = frame.f_locals.get("module")
                if getattr(candidate, "__dict__", None) is globals():
                    module = candidate
                    break
                frame = frame.f_back
        finally:
            del frame
    if module is None:
        return

    if __name__ not in _sys.modules:
        _sys.modules[__name__] = module
    if __name__ != "_dr_plan_runner":
        _sys.modules["_dr_plan_runner"] = module


_register_canonical_alias()


def _kill_process_tree(pid: int, timeout: int = 5) -> None:
    """Terminate child processes for a runner PID before killing the runner itself."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
    except psutil.NoSuchProcess:
        logger.debug("process tree cleanup skipped; PID %s no longer exists", pid)
        return
    except (psutil.AccessDenied, psutil.ZombieProcess) as exc:
        logger.debug("process tree cleanup skipped for PID %s: %s", pid, exc)
        return

    for child in children:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.ZombieProcess) as exc:
            logger.debug("child terminate skipped for PID %s: %s", getattr(child, "pid", None), exc)

    if not children:
        return

    try:
        _gone, alive = psutil.wait_procs(children, timeout=timeout)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
        logger.debug("process tree wait skipped for PID %s: %s", pid, exc)
        alive = []

    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.ZombieProcess) as exc:
            logger.debug("child kill skipped for PID %s: %s", getattr(child, "pid", None), exc)

    if alive:
        try:
            psutil.wait_procs(alive, timeout=timeout)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            logger.debug("process tree kill wait skipped for PID %s: %s", pid, exc)


# Lifecycle control lives in `_dr_runner_control` so tests can patch that module
# and observe behavior through the facade imports.
from _dr_runner_control import (  # noqa: E402
    start_plan_runner,
    stop_plan_runner,
    get_status,
    force_stop_plan_runner,
    force_kill_plan_runner,
    _do_start_plan_runner,
    _launch_plan_runner_process,
)

def _ownership_snapshot_dir(project_root: Path = PROJECT_ROOT) -> Path:
    return project_root / "logs" / "dev_runner" / "ownership"


def _normalize_dirty_path(line: str) -> str:
    raw = line[3:].strip() if len(line) >= 3 else line.strip()
    if " -> " in raw:
        raw = raw.split(" -> ", 1)[1].strip()
    return raw.replace("\\", "/").casefold()


def _capture_runner_ownership_snapshot(runner_id: str, project_root: Path) -> dict:
    snapshot_path = _ownership_snapshot_dir(project_root) / f"{runner_id}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "runner_id": runner_id,
        "captured_at": datetime.now().isoformat(),
        "project_root": str(project_root),
        "dirty_files": [],
        "dirty_status_lines": [],
        "owned_files": [],
        "clean_at_start_files": [],
    }

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode == 0:
            dirty_files = []
            dirty_status_lines = []
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                dirty_status_lines.append(line)
                normalized = _normalize_dirty_path(line)
                if normalized:
                    dirty_files.append(normalized)
            payload["dirty_files"] = sorted(dict.fromkeys(dirty_files))
            payload["dirty_status_lines"] = dirty_status_lines
        else:
            payload["capture_error"] = f"git status failed ({result.returncode})"
    except Exception as exc:
        payload["capture_error"] = str(exc)

    try:
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"ownership snapshot write failed (runner_id={runner_id}): {exc}")
    return payload


try:
    from listener_noise_filter import NOISE_BLOCK_MARKERS as _NOISE_BLOCK_MARKERS, is_noise_line as _is_noise_line
except ImportError:
    def _is_noise_line(line): return False
    _NOISE_BLOCK_MARKERS = []



def _stream_output(
    process: subprocess.Popen,
    log_handle,
    redis_client: redis.Redis,
    runner_id: str = "",
    stderr_handle: Optional[IO] = None,
):
    """프로세스 stdout을 라인별로 읽어 파일 기록 + Redis publish 동시 수행

    노이즈 필터:
    - xterm.js: Parsing error 블록 → 파일 기록만, publish 억제
    - node-pty AttachConsole failed 스택트레이스 → 파일 기록만, publish 억제
    - 억제된 줄이 있으면 정상 라인 직전에 요약 1줄 publish
    - rate-limiter: 동일 라인 0.5초 내 10회 이상 반복 시 burst 억제
    """
    # 테스트는 `_dr_stream_output.*`를 patch하므로, 구현은 항상 분리 모듈로 위임한다.
    from _dr_stream_output import _stream_output as _impl

    return _impl(
        process,
        log_handle,
        redis_client,
        runner_id,
        stderr_handle=stderr_handle,
    )
    import time
    logger.info(f"[_stream_output] 시작 runner_id={runner_id!r}")
    _running_log_files = get_running_log_files()
    _wf_manager = get_wf_manager()

    # ── Phase 1: 조기 사망 감지 ─────────────────────────────────────────
    _start_time = time.time()
    log_channel_init = f"{LOG_CHANNEL_PREFIX}:{runner_id}" if runner_id else LOG_CHANNEL_PREFIX

    # 진입 시점에서 이미 종료됐는지 즉시 확인
    _initial_poll = process.poll()
    if _initial_poll is not None:
        _elapsed = time.time() - _start_time
        _early_msg = f"[EARLY_EXIT] exit_code={_initial_poll}, elapsed={_elapsed:.1f}s (진입 즉시 감지)"
        logger.warning(f"[_stream_output] {_early_msg} runner_id={runner_id!r}")
        try:
            log_handle.write(_early_msg + "\n")
            log_handle.flush()
        except Exception:
            pass
        try:
            _publish_with_retry(redis_client, log_channel_init, _early_msg)
        except Exception:
            pass

    # stdout readline 루프 진입 전 poll 재확인 (Python 초기화 실패 시 즉시 종료 패턴 방어)
    # 500ms 단일 sleep 금지 → 50ms×10 분할 (pipe buffer 압박 방지)
    if _initial_poll is None:
        for _ in range(10):
            time.sleep(0.05)
            if process.poll() is not None:
                _elapsed = time.time() - _start_time
                _early_msg2 = f"[EARLY_EXIT] exit_code={process.poll()}, elapsed={_elapsed:.1f}s (readline 진입 전 감지)"
                logger.warning(f"[_stream_output] {_early_msg2} runner_id={runner_id!r}")
                try:
                    log_handle.write(_early_msg2 + "\n")
                    log_handle.flush()
                except Exception:
                    pass
                try:
                    _publish_with_retry(redis_client, log_channel_init, _early_msg2)
                except Exception:
                    pass
                break
    # ────────────────────────────────────────────────────────────────────

    suppressed_count = 0
    _last_flushed_pos: int = 0  # 파이프 루프에서 마지막으로 flush한 파일 위치 (drain 중복 방지용)
    # rate-limiter 상태
    last_line = ""
    repeat_count = 0
    repeat_start = 0.0
    BURST_WINDOW = 0.5   # 초
    BURST_LIMIT = 10     # 같은 내용 N회 이상이면 억제
    # 진단 카운터
    _line_count = 0
    publish_ok = 0
    publish_fail = 0
    framer = MultilineFrameBuffer(max_chars=8192)

    # ── Phase 3: stderr 별도 스레드 ──────────────────────────────────────
    _stderr_thread: Optional[threading.Thread] = None

    def _drain_stderr(stderr_fh) -> None:
        """stderr 파이프를 읽어 log_handle에 [STDERR] prefix로 기록"""
        try:
            for _sline in stderr_fh:
                _stripped_s = _sline.rstrip("\n")
                if _stripped_s:
                    _msg = f"[STDERR] {_stripped_s}"
                    try:
                        log_handle.write(_msg + "\n")
                        log_handle.flush()
                    except Exception:
                        pass
                    try:
                        _publish_with_retry(redis_client, log_channel_init, _msg)
                    except Exception:
                        pass
        except Exception as _se:
            logger.debug(f"[_stream_output] stderr drain 중 예외 (무시): {_se}")

    if stderr_handle is not None:
        _stderr_thread = threading.Thread(target=_drain_stderr, args=(stderr_handle,), daemon=True)
        _stderr_thread.start()
    # ────────────────────────────────────────────────────────────────────

    def _publish_frame(frame_text: str) -> None:
        nonlocal suppressed_count, last_line, repeat_count, repeat_start, publish_ok, publish_fail
        if not frame_text:
            return

        now = time.time()
        if frame_text == last_line:
            if now - repeat_start <= BURST_WINDOW:
                repeat_count += 1
            else:
                repeat_count = 1
                repeat_start = now
        else:
            last_line = frame_text
            repeat_count = 1
            repeat_start = now

        if repeat_count > BURST_LIMIT:
            suppressed_count += 1
            return

        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}" if runner_id else LOG_CHANNEL_PREFIX
        if suppressed_count > 0:
            _publish_with_retry(redis_client, log_channel, f"[NOISE] {suppressed_count} lines suppressed")
            suppressed_count = 0

        if _publish_with_retry(redis_client, log_channel, frame_text):
            publish_ok += 1
            return

        publish_fail += 1
        if publish_fail % 100 == 0:
            logger.warning(f"[_stream_output] publish 실패 {publish_fail}건 (runner_id={runner_id!r})")

    try:
        while True:
            line = process.stdout.readline()
            if not line:
                break
            _line_count += 1
            if _line_count in (10, 100, 1000) or (_line_count > 1000 and _line_count % 1000 == 0):
                logger.info(f"[_stream_output] {_line_count}줄 처리됨 runner_id={runner_id!r}")
            stripped = line.rstrip('\n')

            # 1. 파일 기록 (노이즈 포함 전체 보존)
            log_handle.write(line)
            log_handle.flush()
            try:
                _last_flushed_pos = log_handle.tell()
            except Exception:
                pass

            sanitized = _ANSI_ESCAPE.sub('', stripped)

            # 2. 노이즈 필터: 억제 대상이면 카운트 후 skip
            if _is_noise_line(sanitized):
                pending = framer.flush()
                if pending:
                    _publish_frame(pending)
                suppressed_count += 1
                continue

            ready_frames, overflow = framer.push_line(sanitized)
            if overflow:
                logger.warning(
                    f"[_stream_output] 프레임 버퍼 상한(8192 chars) 초과 즉시 flush (runner_id={runner_id!r})"
                )
            for frame in ready_frames:
                _publish_frame(frame)

        # 루프 종료 시 잔여 프레임 flush
        remaining_frame = framer.flush()
        if remaining_frame:
            _publish_frame(remaining_frame)

        # 루프 종료 후 잔여 억제 요약
        if suppressed_count > 0:
            log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}" if runner_id else LOG_CHANNEL_PREFIX
            _publish_with_retry(redis_client, log_channel, f"[NOISE] {suppressed_count} lines suppressed")
            suppressed_count = 0

    except Exception as e:
        logger.error(f"Output streaming error: {e}")
    finally:
        logger.info(f"[_stream_output] 종료: ok={publish_ok} fail={publish_fail} lines={_line_count} runner_id={runner_id!r}")
        # stdout 마커 종료 — extract-plan-log.ps1이 범위를 추출하는 기준점
        try:
            log_handle.write(f"[plan:{runner_id} end]\n")
            log_handle.flush()
        except Exception:
            pass
        try:
            log_handle.flush()
            log_handle.close()
        except Exception:
            pass

        # 프로세스 종료 대기 + 전역 상태 정리
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning(f"[_stream_output] process.wait(10s) 타임아웃 (runner_id={runner_id!r}) → terminate")
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            if process.returncode is None:
                logger.warning(f"[_stream_output] terminate 후 미종료 (runner_id={runner_id!r}) → kill")
                process.kill()
                try:
                    process.wait(timeout=5)
                except Exception:
                    pass
        # ── Phase 3: stderr 스레드 정리 ─────────────────────────────────
        if _stderr_thread is not None:
            _stderr_thread.join(timeout=5)
            if _stderr_thread.is_alive():
                logger.warning(f"[_stream_output] stderr 스레드 join(5s) 타임아웃 (runner_id={runner_id!r}) — 강제 포기")
            # 잔여 stderr drain (스레드가 이미 읽었으므로 대부분 비어있음)
            if stderr_handle is not None:
                try:
                    for _sl in stderr_handle:
                        _msg = f"[STDERR] {_sl.rstrip()}"
                        try:
                            log_handle.write(_msg + "\n")
                        except Exception:
                            pass
                except Exception:
                    pass
        # ────────────────────────────────────────────────────────────────

        exit_code = process.returncode
        _elapsed_total = time.time() - _start_time
        logger.info(f"Output streaming thread finished (exit code: {exit_code})")
        logger.info(f"[_stream_output] finally 분기 시작 (runner_id={runner_id!r}, exit_code={exit_code})")

        # ── Phase 1: lines=0 + 비정상 종료 시 상세 진단 ─────────────────
        if _line_count == 0 and exit_code not in (0, None):
            _diag_parts = [
                f"[DIAG] lines=0, exit_code={exit_code}, elapsed={_elapsed_total:.1f}s",
            ]
            try:
                _vmem = psutil.virtual_memory()
                _diag_parts.append(
                    f"mem_available={_vmem.available // (1024*1024)}MB, "
                    f"mem_total={_vmem.total // (1024*1024)}MB"
                )
            except Exception as _me:
                _diag_parts.append(f"mem_check_failed={_me}")
            try:
                _proc_mem = psutil.Process(process.pid).memory_info()
                _diag_parts.append(f"proc_rss={_proc_mem.rss // (1024*1024)}MB")
            except Exception:
                pass  # NoSuchProcess 등 — subprocess 이미 종료됨
            _diag_parts.append(f"cwd={process.args[0] if hasattr(process, 'args') else 'unknown'}")
            _diag_msg = " | ".join(_diag_parts)
            logger.warning(f"[_stream_output] {_diag_msg} runner_id={runner_id!r}")
            try:
                log_handle.write(_diag_msg + "\n")
                log_handle.flush()
            except Exception:
                pass
            _log_channel_diag = f"{LOG_CHANNEL_PREFIX}:{runner_id}" if runner_id else LOG_CHANNEL_PREFIX
            try:
                _publish_with_retry(redis_client, _log_channel_diag, _diag_msg)
            except Exception:
                pass
        # ────────────────────────────────────────────────────────────────

        # Zone A-E: 헬퍼 함수로 위임 (_dr_stream_cleanup.py)
        log_file_path = _running_log_files.get(runner_id) if runner_id else None
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}" if runner_id else LOG_CHANNEL_PREFIX
        ctx = _StreamCleanupCtx(
            runner_id=runner_id,
            redis_client=redis_client,
            log_channel=log_channel,
            exit_code=exit_code,
            wf_manager=_wf_manager,
        )
        _resolve_exit_status(ctx)
        tail_lines = _drain_stdout_log(ctx, log_file_path, _last_flushed_pos, _publish_frame)
        _process_error_details(ctx, log_file_path, tail_lines)
        merge_requested = _determine_merge_requested(ctx)
        _update_workflow_and_execute_cleanup(ctx, merge_requested)


def _do_start_plan_runner(command: Dict, redis_client: redis.Redis):
    """plan-runner CLI 실행 (백그라운드 스레드에서 호출 — worktree 생성 포함)"""
    from worktree_manager import WorktreeManager, WorktreeError, ensure_main_branch
    from workflow_manager import WorkflowManager
    from _dr_plan_paths import (
        classify_plan_stage,
        is_reserved_plan_status,
        read_plan_status,
        resolve_plan_target,
    )
    from plan_worktree_helpers import (
        is_plan_archived,
        is_worktree_active,
        write_plan_worktree_info as _write_plan_worktree_info,
        remove_plan_header_fields as _remove_plan_header_fields,
    )
    from _dr_constants import PROJECT_ROOT as _PR

    runner_id = command.get("runner_id")
    _wf_id: Optional[int] = None
    _wf_manager = get_wf_manager()
    _wf_marked_running = False

    def _set_error_status(message: str):
        """실패 시 per-runner 상태를 Redis에 기록 + 라이브 로그 채널에 publish"""
        if runner_id:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "error")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:error", message)
            logger.error(f"[_do_start_plan_runner] 실패 상태 기록 (runner_id: {runner_id}): {message}")
            if not _publish_with_retry(redis_client, f"{LOG_CHANNEL_PREFIX}:{runner_id}", f"[ERROR] {message}"):
                pub_err = "publish retry failed"
                logger.warning(f"[_set_error_status] publish 실패 (무시): {pub_err}")
            # Workflow 실패 상태 업데이트
            if _wf_manager and _wf_id:
                try:
                    _wf_manager.update_status(_wf_id, "failed", error_message=message)
                except Exception as wf_err:
                    logger.warning(f"[_set_error_status] workflow update 실패 (무시): {wf_err}")

    # 명령어 구성
    plan_file = command.get("plan_file")

    # archive 경로 방어: archive된 plan은 실행 거부
    if plan_file:
        try:
            _path_resolution = resolve_plan_target(plan_file, purpose="archive")
            _status = read_plan_status(plan_file)
            _plan_stage = classify_plan_stage(_status)
            logger.info(
                "[_do_start_plan_runner] plan rule resolved: plan=%s rule=%s target=%s kind=%s plan_stage=%s",
                plan_file,
                _path_resolution.rule_id,
                _path_resolution.target,
                _path_resolution.target_kind,
                _plan_stage,
            )
            if is_reserved_plan_status(_status):
                _set_error_status(f"예약대기 plan은 실행할 수 없습니다: {plan_file}")
                return
        except Exception as _path_err:
            logger.debug(f"[_do_start_plan_runner] plan rule 해석 실패 (무시): {_path_err}")
        if is_plan_archived(plan_file):
            _set_error_status(f"archived plan은 실행할 수 없습니다: {plan_file}")
            return

    # plan 파일의 git root 결정 (wtools 등 외부 레포 지원)
    plan_project_root = get_target_project_root(plan_file) if plan_file else _PR
    plan_worktree_base = plan_project_root / ".worktrees"
    if plan_project_root != _PR:
        logger.info(f"외부 레포 plan 감지: project_root={plan_project_root}")

    # worktree 생성 또는 재사용 (시간이 걸릴 수 있음)
    try:
        ensure_main_branch(plan_project_root)
        _reused_worktree = False
        if plan_file:
            _active, existing_branch, existing_wt_abs = is_worktree_active(plan_file, plan_project_root)
            if _active:
                    worktree_path = Path(existing_wt_abs)
                    branch = existing_branch
                    _reused_worktree = True
                    try:
                        worktree_rel = str(worktree_path.relative_to(plan_project_root)).replace("\\", "/")
                    except ValueError:
                        worktree_rel = str(worktree_path)
                    if not _write_plan_worktree_info(plan_file, branch, worktree_rel, owner=plan_file):
                        _set_error_status(f"plan worktree header 기록 실패: {plan_file}")
                        return
                    logger.info(f"기존 워크트리 재사용: {worktree_path} (branch: {branch})")
            else:
                    # 경로 없음 또는 worktree 검증 실패 → plan 헤더에서 필드 제거 후 신규 생성
                    _remove_plan_header_fields(plan_file)
                    logger.info(f"워크트리 없음 또는 검증 실패, 신규 생성: plan={plan_file}")
        if not _reused_worktree:
            worktree_path, branch = WorktreeManager.create(
                runner_id,
                plan_worktree_base,
                plan_file=plan_file,
                use_runner_identity=bool(command.get("test_source")),
            )
            # Phase 4: plan 헤더에 branch/worktree 기록 (수동 /implement와 동일 패턴)
            if plan_file:
                worktree_rel = str(worktree_path.relative_to(plan_project_root)).replace("\\", "/")
                if not _write_plan_worktree_info(plan_file, branch, worktree_rel, owner=plan_file):
                    _set_error_status(f"plan worktree header 기록 실패: {plan_file}")
                    return
    except WorktreeError as e:
        logger.error(f"worktree 생성 실패 (runner_id: {runner_id}): {e}")
        _set_error_status(f"worktree 생성 실패: {e}")
        return

    # Workflow 레코드 생성
    if _wf_manager and runner_id:
        try:
            slug = (
                WorkflowManager._slug_from_plan_file(plan_file)
                if plan_file
                else WorkflowManager._slug_from_runner_id(runner_id)
            )
            # slug 중복 방지: 이미 존재하면 runner_id prefix 추가
            if _wf_manager.get_by_slug(slug):
                slug = f"{slug}-{runner_id[:4]}"
            _wf_id = _wf_manager.create(slug, plan_file)
        except Exception as wf_err:
            logger.warning(f"[_do_start_plan_runner] workflow create 실패 (무시): {wf_err}")

    engine = command.get("engine")
    fix_engine = command.get("fix_engine")
    is_parallel = command.get("parallel", False)
    if not plan_file and not is_parallel and not command.get("dry_run"):
        _set_error_status("plan_file required (use parallel mode for batch execution)")
        return

    _normalized_plan_key = WorkflowManager._normalize_plan_key(plan_file)
    command["plan_key"] = _normalized_plan_key
    if _wf_manager and _wf_id:
        try:
            started_at_iso, execution_count = _wf_manager.mark_running_with_execution_count(
                _wf_id,
                runner_id,
                branch,
                str(worktree_path),
                engine or "claude",
            )
            command["started_at"] = started_at_iso
            command["execution_count"] = execution_count
            _wf_marked_running = True
        except Exception as wf_err:
            logger.warning(f"[_do_start_plan_runner] workflow running+count update 실패 (fallback): {wf_err}")
            command.setdefault("started_at", datetime.now().isoformat())
            command.setdefault("execution_count", "unknown")
    else:
        command.setdefault("started_at", datetime.now().isoformat())
        command.setdefault("execution_count", "unknown")

    result = _launch_plan_runner_process(
        command,
        redis_client,
        runner_id,
        worktree_path,
        plan_file,
        engine,
        fix_engine=fix_engine,
        branch=branch,
        project_root=plan_project_root,
    )
    if not result.get("success"):
        _set_error_status(result.get("message", "Unknown error"))
    else:
        # Workflow running 상태 업데이트
        if _wf_manager and _wf_id and not _wf_marked_running:
            try:
                _wf_manager.update_status(
                    _wf_id, "running",
                    runner_id=runner_id,
                    branch=branch,
                    worktree_path=str(worktree_path),
                    engine=engine or "claude",
                )
            except Exception as wf_err:
                logger.warning(f"[_do_start_plan_runner] workflow running update 실패 (무시): {wf_err}")


def start_plan_runner(command: Dict, redis_client: redis.Redis) -> Dict:
    """plan-runner CLI 실행 시작 — 즉시 accepted 반환, worktree+프로세스는 백그라운드"""
    _running_processes = get_running_processes()

    runner_id = command.get("runner_id")
    if not runner_id:
        return {"success": False, "message": "runner_id required"}

    plan_file_req = command.get("plan_file")
    if plan_file_req and plan_file_req not in (PLAN_FILE_ALL, _LEGACY_ALL):
        try:
            from _dr_plan_paths import is_reserved_plan_status, read_plan_status

            plan_status = read_plan_status(plan_file_req)
            if is_reserved_plan_status(plan_status):
                message = f"예약대기 plan은 실행할 수 없습니다: {plan_file_req}"
                logger.info("[start_plan_runner] reserved plan blocked before accepted: %s", plan_file_req)
                return {
                    "success": False,
                    "reason": "reserved_status",
                    "status": plan_status,
                    "message": message,
                    "runner_id": runner_id,
                    "action": "run",
                    "executed_at": datetime.now().isoformat(),
                }
        except Exception as status_err:
            logger.warning("[start_plan_runner] reserved status preflight failed: %s", status_err)

    # 동일 runner_id로 이미 실행 중이면 에러 (stale 프로세스 자동 정리 포함)
    redis_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
    redis_pid_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
    if redis_status == "running" and redis_pid_str:
        try:
            redis_pid = int(redis_pid_str)
            if _is_pid_alive(redis_pid):
                logger.warning(f"[start_plan_runner] 중복 실행 감지: Redis status=running, PID={redis_pid} 살아있음 — 시작 거부")
                return {"success": False, "message": f"Already running (PID: {redis_pid}) — detected via Redis"}
        except (ValueError, TypeError):
            pass

    proc = _running_processes.get(runner_id)
    if proc and proc.poll() is None:
        if not _is_pid_alive(proc.pid):
            logger.warning(f"Stale process detected (PID: {proc.pid}), cleaning up")
            _cleanup_process_state(runner_id, redis_client)
        else:
            return {
                "success": False,
                "message": f"Already running (PID: {proc.pid})"
            }
    elif proc and proc.poll() is not None:
        logger.info(f"Previous process ended (exit code: {proc.returncode}), cleaning up")
        _cleanup_process_state(runner_id, redis_client)

    # ── DB claim preflight: queued/active claim이 있으면 충돌 거부 ────────
    if plan_file_req and plan_file_req not in (PLAN_FILE_ALL, _LEGACY_ALL):
        try:
            import sys as _sys_pf
            _pr_pf = str(Path(__file__).resolve().parent.parent.parent)
            if _pr_pf not in _sys_pf.path:
                _sys_pf.path.insert(0, _pr_pf)
            from app.database import SessionLocal as _PfSession
            from app.modules.dev_runner.services.plan_execution_claim_service import (
                get_active_claim_for_plan as _get_active_pf,
            )
            _pf_db = _PfSession()
            try:
                _existing_claim = _get_active_pf(_pf_db, plan_file_req)
            finally:
                _pf_db.close()
            if _existing_claim and _existing_claim.runner_id and _existing_claim.runner_id != runner_id:
                logger.info(
                    f"[start_plan_runner] DB claim 충돌: plan={plan_file_req} "
                    f"claim_id={_existing_claim.claim_id} state={_existing_claim.state} "
                    f"claim_runner={_existing_claim.runner_id}"
                )
                return {
                    "success": False,
                    "reason": "claim_conflict",
                    "message": (
                        f"plan이 이미 실행 점유 중입니다 "
                        f"(claim_id={_existing_claim.claim_id} state={_existing_claim.state})"
                    ),
                    "claim_id": _existing_claim.claim_id,
                    "claim_state": _existing_claim.state,
                    "runner_id": runner_id,
                    "action": "run",
                    "executed_at": datetime.now().isoformat(),
                }
        except Exception as _pf_claim_err:
            logger.debug(f"[start_plan_runner] DB claim preflight 실패 (무시): {_pf_claim_err}")
    # ────────────────────────────────────────────────────────────────

    # plan_file 기준 기존 워커 감지 (재실행 시 attach — runner_id는 달라도 같은 plan 실행 중)
    if plan_file_req and plan_file_req not in (PLAN_FILE_ALL, _LEGACY_ALL):
        from _dr_constants import RESULTS_KEY as _RESULTS_KEY_EARLY
        _command_id_early = command.get("command_id", "")
        _result_key_early = f"{_RESULTS_KEY_EARLY}:{_command_id_early}" if _command_id_early else _RESULTS_KEY_EARLY
        try:
            _existing_runners = redis_client.smembers(ACTIVE_RUNNERS_KEY) or set()
        except Exception:
            _existing_runners = set()

        for _rid_raw in _existing_runners:
            _rid = _rid_raw if isinstance(_rid_raw, str) else _rid_raw.decode("utf-8", errors="replace")
            if _rid == runner_id:
                continue  # 자기 자신 스킵

            # cleanup 진행 중 확인 → 동일 plan이면 "정리 중" 응답
            _cleanup_flag = redis_client.get(f"{RUNNER_KEY_PREFIX}:{_rid}:cleanup_in_progress")
            _cleanup_flag_str = _cleanup_flag if isinstance(_cleanup_flag, str) else (_cleanup_flag.decode("utf-8") if _cleanup_flag else None)
            _existing_pf_raw = redis_client.get(f"{RUNNER_KEY_PREFIX}:{_rid}:plan_file")
            _existing_pf = _existing_pf_raw if isinstance(_existing_pf_raw, str) else (_existing_pf_raw.decode("utf-8") if _existing_pf_raw else None)
            if _cleanup_flag_str == "1" and _existing_pf == plan_file_req:
                logger.info(f"[start_plan_runner] 동일 plan cleanup 진행 중 (rid={_rid}, plan={plan_file_req})")
                _cleanup_resp = {
                    "success": False,
                    "message": f"이전 실행 정리 중 (runner_id: {_rid}) — 잠시 후 재시도하세요",
                    "runner_id": runner_id,
                    "action": "run",
                    "executed_at": datetime.now().isoformat(),
                }
                redis_client.lpush(_result_key_early, json.dumps(_cleanup_resp, ensure_ascii=False))
                redis_client.expire(_result_key_early, 60)
                return None

            # plan_file 불일치이면 스킵
            if _existing_pf != plan_file_req:
                continue

            # PID alive 확인 → attach
            _pid_raw = redis_client.get(f"{RUNNER_KEY_PREFIX}:{_rid}:pid")
            if not _pid_raw:
                continue
            try:
                _existing_pid = int(_pid_raw if isinstance(_pid_raw, str) else _pid_raw.decode("utf-8"))
            except (ValueError, TypeError):
                continue

            if _is_pid_alive(_existing_pid):
                logger.info(f"[start_plan_runner] 동일 plan 기존 워커 → attach (rid={_rid}, pid={_existing_pid}, plan={plan_file_req})")
                _attached_resp = {
                    "success": True,
                    "status": "attached",
                    "runner_id": _rid,
                    "message": "기존 워커에 연결됨",
                    "action": "run",
                    "executed_at": datetime.now().isoformat(),
                }
                redis_client.lpush(_result_key_early, json.dumps(_attached_resp, ensure_ascii=False))
                redis_client.expire(_result_key_early, 60)
                return None

    # 즉시 "accepted" 결과를 per-command result key에 push → API 타임아웃 방지
    from _dr_constants import RESULTS_KEY
    command_id = command.get("command_id", "")
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    accepted = {
        "success": True,
        "message": "accepted",
        "runner_id": runner_id,
        "action": "run",
        "executed_at": datetime.now().isoformat(),
    }
    redis_client.lpush(result_key, json.dumps(accepted, ensure_ascii=False))
    redis_client.expire(result_key, 60)
    logger.info(f"[start_plan_runner] accepted 응답 즉시 반환 (runner_id: {runner_id})")

    # 관측 메타: accepted 시점 타임스탬프 + 처리 경로 + trigger 조기 저장
    # trigger는 _launch_plan_runner_process에서도 덮어쓰지만, worktree 생성 실패 등으로
    # 프로세스 spawn에 실패해도 trigger가 관측 가능하도록 accepted 시점에 미리 저장한다.
    try:
        _accepted_at_ts = accepted["executed_at"]
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:accepted_at", _accepted_at_ts)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:accepted_source", "listener")
        _trigger_early = command.get("trigger", "unknown")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", _trigger_early)
    except Exception as _meta_err:
        logger.warning(f"[start_plan_runner] accepted 메타 저장 실패 (무시): {_meta_err}")

    # 백그라운드 스레드에서 worktree 생성 + 프로세스 시작
    thread = threading.Thread(
        target=_do_start_plan_runner,
        args=(command, redis_client),
        daemon=True,
    )
    thread.start()

    return None  # sentinel: main loop에서 결과 push 스킵 (이미 위에서 push)


def _launch_plan_runner_process(
    command: Dict,
    redis_client: redis.Redis,
    runner_id: str,
    worktree_path: Path,
    plan_file: str,
    engine: str,
    fix_engine: str = None,
    branch: str = "",
    project_root: Path = None,
) -> Dict:
    """plan-runner CLI 프로세스 실행 (worktree 생성 이후 호출)"""
    from _dr_constants import PROJECT_ROOT as _PR
    if project_root is None:
        project_root = _PR
    if fix_engine is None:
        fix_engine = command.get("fix_engine")

    _running_processes = get_running_processes()
    _running_log_files = get_running_log_files()
    _stream_threads = get_stream_threads()

    cmd = [
        str(PLAN_RUNNER_PYTHON),
        "-m",
        "plan_runner",
        "run",
    ]

    if plan_file:
        cmd.extend(["--plan-file", plan_file])
    if engine:
        cmd.extend(["--engine", engine])
    if fix_engine:
        cmd.extend(["--fix-engine", fix_engine])

    # 옵션 추가
    if command.get("max_cycles") is not None:
        cmd.extend(["--max-cycles", str(command["max_cycles"])])

    if command.get("max_tokens") is not None:
        cmd.extend(["--max-tokens", str(command["max_tokens"])])

    if command.get("until"):
        cmd.extend(["--until", command["until"]])

    if command.get("dry_run"):
        cmd.append("--dry-run")

    if command.get("parallel"):
        cmd.append("--parallel")

    if command.get("projects"):
        cmd.extend(["--projects", command["projects"]])

    if command.get("extra_plan_dirs"):
        cmd.extend(["--extra-plan-dirs", command["extra_plan_dirs"]])

    if command.get("ignored_plans"):
        cmd.extend(["--ignored-plans", command["ignored_plans"]])

    # fused 세션 인자 추가 (--worktree 이전 위치 — 순서 spec: --engine 직후 ~ --worktree 직전)
    if command.get("session_id"):
        cmd.extend(["--session-id", str(command["session_id"])])
    if command.get("fused_session"):
        cmd.append("--fused-session")

    if command.get("worktree") or worktree_path:
        cmd.append("--worktree")

    logger.info(
        "[session] runner_id=%s session_id=%s fused=%s",
        runner_id,
        command.get("session_id", ""),
        command.get("fused_session", False),
    )

    # 로그 파일 생성
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"plan-runner-{runner_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

    try:
        # subprocess 실행 및 stdout을 PIPE로 받아 스레드에서 파일+Redis 동시 기록
        log_handle = open(log_file, "w", encoding="utf-8")
        started_at_text = command.get("started_at") or datetime.now().isoformat()
        execution_count_text = command.get("execution_count")
        if execution_count_text is None:
            execution_count_text = "unknown"
        plan_key_text = command.get("plan_key") or (plan_file or PLAN_FILE_ALL)

        log_handle.write(
            f"[TRIGGER] {command.get('trigger', 'unknown')} | plan={plan_file} | "
            f"engine={engine} | fix_engine={fix_engine} | runner_id={runner_id}\n"
        )
        run_meta_line = (
            f"[RUN_META] started_at={started_at_text} | "
            f"execution_count={execution_count_text} | plan_key={plan_key_text}"
        )
        log_handle.write(run_meta_line + "\n")

        # ── Phase 2: [ENV] 헤더 — 사후 분석용 환경/메모리 정보 ──────────
        try:
            _vmem_hdr = psutil.virtual_memory()
            _env_line = (
                f"[ENV] available_memory={_vmem_hdr.available // (1024*1024)}MB, "
                f"total_memory={_vmem_hdr.total // (1024*1024)}MB, "
                f"python={str(PLAN_RUNNER_PYTHON)}"
            )
        except Exception as _vmem_err:
            _env_line = f"[ENV] mem_check_failed={_vmem_err}, python={str(PLAN_RUNNER_PYTHON)}"
        log_handle.write(_env_line + "\n")
        log_handle.flush()
        # ────────────────────────────────────────────────────────────────

        _publish_with_retry(redis_client, f"{LOG_CHANNEL_PREFIX}:{runner_id}", run_meta_line)

        import os
        import re as _re
        env = _make_plan_runner_env(
            runner_id,
            profile_env_key=command.get("profile_env_key"),
            profile_config_dir=command.get("profile_config_dir"),
            profile_extra_env=command.get("profile_extra_env"),
            PLAN_RUNNER_WORK_DIR=str(worktree_path),
            PLAN_RUNNER_WORKTREE_PATH=str(worktree_path),
            PLAN_RUNNER_PROJECT_ROOT=str(project_root),
        )
        # 로그 prefix 식별자: plan명(날짜 제거, 첫 2단어) + runner_id 앞 4자
        _plan_basename = os.path.splitext(os.path.basename(plan_file or ""))[0]
        _plan_basename = _re.sub(r'^\d{4}-\d{2}-\d{2}[_-]', '', _plan_basename)
        _plan_parts = _plan_basename.replace('_', '-').split('-')
        _plan_short = '-'.join(_plan_parts[:2]) if len(_plan_parts) >= 2 else _plan_parts[0]
        env["PLAN_RUNNER_NAME"] = f"PLAN-RUNNER#{_plan_short}@{runner_id[:4]}"
        env["TEST_DB_DIR"] = str(worktree_path / "data")
        if branch:
            env["PLAN_RUNNER_BRANCH"] = branch

        # ── Phase 2: 메모리 사전 검증 ────────────────────────────────────
        _log_ch_pre = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        try:
            _pre_vmem = psutil.virtual_memory()
            _avail_mb = _pre_vmem.available // (1024 * 1024)
            if _avail_mb < 300:
                _reject_msg = f"메모리 부족으로 plan-runner 실행 거부 (가용: {_avail_mb}MB < 300MB)"
                logger.error(f"[_launch_plan_runner_process] {_reject_msg}")
                try:
                    log_handle.write(f"[REJECT] {_reject_msg}\n")
                    log_handle.flush()
                except Exception:
                    pass
                _publish_with_retry(redis_client, _log_ch_pre, f"[REJECT] {_reject_msg}")
                try:
                    log_handle.close()
                except Exception:
                    pass
                return {"success": False, "message": _reject_msg}
            elif _avail_mb < 500:
                _warn_msg = f"[WARN] 가용 메모리 낮음 ({_avail_mb}MB < 500MB) — 실행 계속"
                logger.warning(f"[_launch_plan_runner_process] {_warn_msg}")
                try:
                    log_handle.write(_warn_msg + "\n")
                    log_handle.flush()
                except Exception:
                    pass
        except Exception as _mem_chk_err:
            logger.warning(f"[_launch_plan_runner_process] 메모리 확인 실패 (무시): {_mem_chk_err}")
        # ────────────────────────────────────────────────────────────────

        ownership_snapshot = _capture_runner_ownership_snapshot(runner_id, project_root)
        capture_error = ownership_snapshot.get("capture_error") if isinstance(ownership_snapshot, dict) else None
        if capture_error:
            _warn_msg = f"[WARN] ownership snapshot capture failed — 실행은 계속 ({capture_error})"
            logger.warning(f"[_launch_plan_runner_process] {_warn_msg}")
            try:
                log_handle.write(_warn_msg + "\n")
                log_handle.flush()
            except Exception:
                pass
            _publish_with_retry(redis_client, _log_ch_pre, _warn_msg)

        process = subprocess.Popen(
            cmd,
            cwd=str(PLAN_RUNNER_MODULE_PATH),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        _running_processes[runner_id] = process
        _running_log_files[runner_id] = log_file

        # stdout 마커 — extract-plan-log.ps1이 범위를 추출하는 기준점
        try:
            log_handle.write(f"[plan:{runner_id} start]\n")
            log_handle.flush()
        except Exception:
            pass

        # 별도 스레드에서 stdout 을 파일 + Redis publish (stderr는 별도 파이프로 분리)
        thread = threading.Thread(
            target=_stream_output,
            args=(process, log_handle, redis_client, runner_id),
            kwargs={"stderr_handle": process.stderr},
            daemon=True,
        )
        thread.start()
        _stream_threads[runner_id] = thread

        # Redis에 상태 저장 (per-runner 키)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path", str(log_file))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path", str(log_file))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", process.pid)
        try:
            identity = _get_process_identity(process.pid, fallback_cmdline=cmd)
            if identity is None:
                identity = {
                    "pid_create_time": "",
                    "process_cmdline_hash": _hash_process_cmdline(cmd),
                }
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid_create_time", identity["pid_create_time"])
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:process_cmdline_hash", identity["process_cmdline_hash"])
        except Exception as identity_err:
            logger.warning(
                "_launch_plan_runner_process: process identity 저장 실패 "
                "(runner_id=%s, pid=%s, reason=%s)",
                runner_id,
                process.pid,
                identity_err,
            )
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file or PLAN_FILE_ALL)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch or f"runner/{runner_id}")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", started_at_text)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:execution_count", str(execution_count_text))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        # 초기 heartbeat — subprocess 루프 진입 전 좀비 오판 방지
        try:
            _hb_val = str(time.time())
            _hb_key = f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat"
            redis_client.set(_hb_key, _hb_val, ex=SUBPROCESS_HEARTBEAT_TTL)
            # Problem A 디버깅: SET 직후 GET 확인 — 불일치 시 Redis 경로/연결 의심
            _hb_check = redis_client.get(_hb_key)
            if _hb_check is None:
                try:
                    _hb_ttl = redis_client.ttl(_hb_key)
                    _hb_exists = redis_client.exists(_hb_key)
                    _hb_db = getattr(getattr(redis_client, "connection_pool", None), "connection_kwargs", {}).get("db", "unknown")
                except Exception:
                    _hb_ttl, _hb_exists, _hb_db = "unknown", "unknown", "unknown"
                logger.error(
                    f"_launch_plan_runner_process: 초기 heartbeat SET 직후 GET=None — "
                    f"Redis 경로 불일치 의심 "
                    f"(runner_id={runner_id}, key={_hb_key}, db={_hb_db}, ttl={_hb_ttl}, exists={_hb_exists})"
                )
        except Exception:
            logger.warning(f"_launch_plan_runner_process: 초기 heartbeat 저장 실패 (runner_id={runner_id})")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", command.get("engine", "claude"))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:fix_engine", command.get("fix_engine", "claude"))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", str(worktree_path))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:claim_id", command.get("claim_id", ""))
        # profile 정보 Redis에 저장 — merge/fix 후속 단계에서 복원용
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:profile", command.get("profile", ""))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:profile_env_key", command.get("profile_env_key") or "")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:profile_config_dir", command.get("profile_config_dir") or "")
        import json as _json
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:profile_extra_env", _json.dumps(command.get("profile_extra_env") or {}))
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:quota_stopped")
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:stop_stage")
        redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)
        trigger = command.get("trigger", "unknown")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", trigger)
        # 관측 메타: 실제 프로세스 spawn 성공 시점 저장 (accepted_at <= started_at 계약)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:started_at", datetime.now().isoformat())

        logger.info(f"plan-runner started (PID: {process.pid}, log: {log_file})")

        # ── Claim activate: queued → active ──────────────────────────────
        if plan_file:
            try:
                import sys as _sys_claim
                _pr_str = str(PROJECT_ROOT)
                if _pr_str not in _sys_claim.path:
                    _sys_claim.path.insert(0, _pr_str)
                from app.database import SessionLocal as _ClaimSession
                from app.modules.dev_runner.services.plan_execution_claim_service import (
                    get_active_claim_for_plan as _get_active_claim,
                    activate_claim as _activate_claim,
                )
                _claim_db = _ClaimSession()
                try:
                    _claim_id = command.get("claim_id")
                    _claim = None
                    if _claim_id:
                        _claim = _activate_claim(
                            _claim_db,
                            _claim_id,
                            runner_id=runner_id,
                            pid=process.pid,
                            branch=branch or f"runner/{runner_id}",
                            worktree_path=str(worktree_path),
                        )
                        logger.info(
                            f"[claim] activated: claim_id={_claim.claim_id} "
                            f"runner_id={runner_id} pid={process.pid}"
                        )
                    else:
                        _claim = _get_active_claim(_claim_db, plan_file)
                        if _claim and _claim.state == "queued":
                            _activate_claim(
                                _claim_db,
                                _claim.claim_id,
                                runner_id=runner_id,
                                pid=process.pid,
                                branch=branch or f"runner/{runner_id}",
                                worktree_path=str(worktree_path),
                            )
                            logger.info(
                                f"[claim] activated: claim_id={_claim.claim_id} "
                                f"runner_id={runner_id} pid={process.pid}"
                            )
                finally:
                    _claim_db.close()
            except Exception as _claim_err:
                logger.warning(f"[claim] activate_claim 실패 (무시): {_claim_err}")
        # ────────────────────────────────────────────────────────────────

        return {
            "success": True,
            "message": "plan-runner started",
            "pid": process.pid,
            "log_file": str(log_file),
        }

    except Exception as e:
        logger.error(f"Failed to start plan-runner: {e}")
        return {
            "success": False,
            "message": f"Failed to start: {str(e)}"
        }


def stop_plan_runner(runner_id: str, redis_client: redis.Redis) -> Dict:
    """plan-runner 프로세스 종료"""
    _running_processes = get_running_processes()
    proc = _running_processes.get(runner_id)
    if not proc or proc.poll() is not None:
        return {"success": False, "message": "Not running"}

    try:
        logger.info(f"Stopping plan-runner (runner_id: {runner_id}, PID: {proc.pid})...")

        # Windows: terminate() 호출
        _kill_process_tree(proc.pid)
        proc.terminate()

        # 5초 대기
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # 강제 종료
            _kill_process_tree(proc.pid)
            proc.kill()
            proc.wait()

        logger.info(f"plan-runner stopped (runner_id: {runner_id})")

        # 스트리밍 스레드 + Redis 상태 정리
        _cleanup_process_state(runner_id, redis_client)

        return {
            "success": True,
            "message": "Stopped successfully"
        }

    except Exception as e:
        logger.error(f"Failed to stop plan-runner: {e}")
        return {
            "success": False,
            "message": f"Failed to stop: {str(e)}"
        }


def get_status(redis_client: redis.Redis) -> Dict:
    """현재 실행 상태 조회 (모든 runner 요약)"""
    _running_processes = get_running_processes()
    _running_log_files = get_running_log_files()
    running_runners = []
    stale_runners = []
    for rid, proc in list(_running_processes.items()):
        if proc.poll() is None:
            log_file = _running_log_files.get(rid)
            running_runners.append({
                "runner_id": rid,
                "pid": proc.pid,
                "log_file": str(log_file) if log_file else None,
            })
        else:
            stale_runners.append(rid)

    # stale 정리
    for rid in stale_runners:
        try:
            from merge_queue import get_queue_key, _get_repo_id
            redis_client.lrem(get_queue_key(_get_repo_id(PROJECT_ROOT)), 0, rid)
        except Exception:
            pass
        _cleanup_process_state(rid, redis_client)

    return {
        "success": True,
        "running": len(running_runners) > 0,
        "runners": running_runners,
        "pid": running_runners[0]["pid"] if running_runners else None,
        "log_file": running_runners[0]["log_file"] if running_runners else None,
    }


def force_stop_plan_runner(runner_id: str, redis_client: redis.Redis) -> Dict:
    """강제 종료 - kill 및 전역 상태 초기화 (리셋용)"""
    _running_processes = get_running_processes()
    if runner_id:
        proc = _running_processes.get(runner_id)
        pid = proc.pid if proc else None
        if proc:
            try:
                _kill_process_tree(proc.pid)
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        _cleanup_process_state(runner_id, redis_client)
        msg = f"Force stopped runner {runner_id} (PID: {pid})" if pid else f"Force cleaned runner {runner_id} (no process)"
    else:
        # 모든 runner 강제 종료
        pids = []
        for rid, proc in list(_running_processes.items()):
            if proc:
                pids.append(proc.pid)
                try:
                    _kill_process_tree(proc.pid)
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
            _cleanup_process_state(rid, redis_client)
        msg = f"Force stopped all runners (PIDs: {pids})" if pids else "Force cleaned (no processes)"

    logger.info(msg)
    return {"success": True, "message": msg}


def force_kill_plan_runner(runner_id: str, redis_client: redis.Redis) -> Dict:
    """강제 종료 (SIGKILL) — graceful stop과 달리 즉시 프로세스 사망."""
    _running_processes = get_running_processes()
    if not runner_id:
        return {"success": False, "message": "runner_id required"}

    proc = _running_processes.get(runner_id)
    pid_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
    pid = None

    # subprocess.Popen 인 경우
    if proc and hasattr(proc, "kill") and not isinstance(proc, _DummyProcess):
        pid = proc.pid
        try:
            _kill_process_tree(proc.pid)
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        # _DummyProcess 또는 proc 없음 → Redis PID로 직접 SIGKILL
        if pid_str:
            try:
                pid = int(pid_str)
                _kill_process_tree(pid)
                import ctypes
                PROCESS_TERMINATE = 0x0001
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 1)
                    ctypes.windll.kernel32.CloseHandle(handle)
            except Exception as e:
                logger.warning(f"[force_kill] PID {pid} 직접 종료 실패: {e}")

    _cleanup_process_state(runner_id, redis_client)
    msg = f"Force killed runner {runner_id} (PID: {pid})" if pid else f"Force killed runner {runner_id} (no PID)"
    logger.info(msg)
    return {"success": True, "message": msg}
