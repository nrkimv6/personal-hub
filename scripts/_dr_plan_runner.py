"""_dr_plan_runner.py — dev-runner plan-runner 프로세스 실행 모듈"""
import json
import logging
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import redis

from _dr_constants import (
    RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, PLAN_FILE_ALL, _LEGACY_ALL,
    LOG_CHANNEL_PREFIX, COMMANDS_KEY, PLAN_RUNNER_PYTHON, PLAN_RUNNER_MODULE_PATH,
    LOG_DIR,
)
from _dr_state import (
    get_running_processes, get_running_log_files, get_stream_threads,
    get_cleanup_done, get_wf_manager,
)
from _dr_subprocess import _ANSI_ESCAPE, _make_plan_runner_env
from _dr_process_utils import _cleanup_process_state, _is_pid_alive, get_plan_git_root, _DummyProcess
from _dr_merge import _execute_merge_with_lock, _handle_post_merge_done

logger = logging.getLogger(__name__)

try:
    from listener_noise_filter import NOISE_BLOCK_MARKERS as _NOISE_BLOCK_MARKERS, is_noise_line as _is_noise_line
except ImportError:
    def _is_noise_line(line): return False
    _NOISE_BLOCK_MARKERS = []


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
            redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge")
            plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
            engine = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine") or "claude"
            log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
            try:
                redis_client.publish(log_channel, f"main 추가 사이클 시작 (plan={plan_file}, engine={engine})")
            except Exception:
                pass
            if plan_file and plan_file not in (PLAN_FILE_ALL, _LEGACY_ALL):
                import uuid as _uuid
                new_runner_id = _uuid.uuid4().hex[:8]
                command = {
                    "action": "run",
                    "runner_id": new_runner_id,
                    "plan_file": plan_file,
                    "engine": engine,
                }
                redis_client.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))
                logger.info(f"[_do_inline_merge] main 추가 사이클 큐잉: runner={new_runner_id}, plan={plan_file}")
    except redis.ConnectionError:
        logger.warning(f"[_do_inline_merge] restart_after_merge 감지 중 Redis 연결 실패 (무시)")
    except Exception as _re:
        logger.warning(f"[_do_inline_merge] restart_after_merge 처리 실패 (무시): {_re}")

    _cleanup_process_state(runner_id, redis_client)


def _stream_output(process: subprocess.Popen, log_handle, redis_client: redis.Redis, runner_id: str = ""):
    """프로세스 stdout을 라인별로 읽어 파일 기록 + Redis publish 동시 수행

    노이즈 필터:
    - xterm.js: Parsing error 블록 → 파일 기록만, publish 억제
    - node-pty AttachConsole failed 스택트레이스 → 파일 기록만, publish 억제
    - 억제된 줄이 있으면 정상 라인 직전에 요약 1줄 publish
    - rate-limiter: 동일 라인 0.5초 내 10회 이상 반복 시 burst 억제
    """
    import time
    _running_log_files = get_running_log_files()
    _wf_manager = get_wf_manager()

    suppressed_count = 0
    _last_flushed_pos: int = 0  # 파이프 루프에서 마지막으로 flush한 파일 위치 (drain 중복 방지용)
    # rate-limiter 상태
    last_line = ""
    repeat_count = 0
    repeat_start = 0.0
    BURST_WINDOW = 0.5   # 초
    BURST_LIMIT = 10     # 같은 내용 N회 이상이면 억제

    try:
        for line in process.stdout:
            stripped = line.rstrip('\n')

            # 1. 파일 기록 (노이즈 포함 전체 보존)
            log_handle.write(line)
            log_handle.flush()
            try:
                _last_flushed_pos = log_handle.tell()
            except Exception:
                pass

            # 2. 노이즈 필터: 억제 대상이면 카운트 후 skip
            if _is_noise_line(stripped):
                suppressed_count += 1
                continue

            # 3. rate-limiter: 동일 내용 burst 감지
            now = time.time()
            if stripped == last_line:
                if now - repeat_start <= BURST_WINDOW:
                    repeat_count += 1
                else:
                    repeat_count = 1
                    repeat_start = now
            else:
                last_line = stripped
                repeat_count = 1
                repeat_start = now

            if repeat_count > BURST_LIMIT:
                suppressed_count += 1
                continue

            log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}" if runner_id else LOG_CHANNEL_PREFIX

            # 4. 직전 억제 요약 먼저 publish
            if suppressed_count > 0:
                try:
                    redis_client.publish(log_channel, f"[NOISE] {suppressed_count} lines suppressed")
                except redis.ConnectionError:
                    pass
                suppressed_count = 0

            # 5. 정상 라인 publish (ANSI 이스케이프 코드 제거)
            try:
                redis_client.publish(log_channel, _ANSI_ESCAPE.sub('', stripped))
            except redis.ConnectionError:
                pass  # Redis 끊겨도 파일 기록은 계속

        # 루프 종료 후 잔여 억제 요약
        if suppressed_count > 0:
            log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}" if runner_id else LOG_CHANNEL_PREFIX
            try:
                redis_client.publish(log_channel, f"[NOISE] {suppressed_count} lines suppressed")
            except redis.ConnectionError:
                pass

    except Exception as e:
        logger.error(f"Output streaming error: {e}")
    finally:
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
        exit_code = process.returncode
        logger.info(f"Output streaming thread finished (exit code: {exit_code})")
        logger.info(f"[_stream_output] finally 분기 시작 (runner_id={runner_id!r}, exit_code={exit_code})")

        # stdout 버퍼 drain: 파이프 루프 종료 후 파일에 추가된 미발행 라인만 publish
        log_file_path = _running_log_files.get(runner_id) if runner_id else None
        if log_file_path and runner_id:
            log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
            try:
                with open(str(log_file_path), "r", encoding="utf-8", errors="replace") as _drain_f:
                    _drain_f.seek(0, 2)
                    end_pos = _drain_f.tell()
                    if _last_flushed_pos >= end_pos:
                        pass  # 이미 모두 발행됨 → drain 전체 skip
                    else:
                        start_pos = max(_last_flushed_pos, end_pos - 8192)
                        _drain_f.seek(start_pos)
                        tail_lines = _drain_f.readlines()
                        for _tail_line in tail_lines[-50:]:
                            _stripped = _tail_line.rstrip('\n')
                            if _stripped:
                                try:
                                    redis_client.publish(log_channel, _ANSI_ESCAPE.sub('', _stripped))
                                except redis.ConnectionError:
                                    pass
            except Exception as _drain_err:
                logger.debug(f"[_stream_output] stdout drain 실패 (무시): {_drain_err}")

        # merge_requested 플래그 확인 (1회) — exit_code != 0이어도 worktree 커밋이 있으면 merge 시도
        _merge_requested = False
        if runner_id:
            try:
                _flag = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
                if _flag:
                    if exit_code == 0:
                        _merge_requested = True
                    else:
                        # exit_code != 0: worktree 커밋 유무로 merge 여부 결정
                        _branch_for_check = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")
                        if _branch_for_check:
                            try:
                                from _dr_constants import PROJECT_ROOT as _PR
                                _log_proc = subprocess.run(
                                    ["git", "log", f"main..{_branch_for_check}", "--oneline"],
                                    capture_output=True, text=True, cwd=str(_PR), timeout=15,
                                )
                                _commit_count = len([l for l in _log_proc.stdout.splitlines() if l.strip()])
                                if _commit_count > 0:
                                    _merge_requested = True
                                    logger.info(
                                        f"[_stream_output] exit_code={exit_code}이지만 worktree 커밋 {_commit_count}개 존재 "
                                        f"(runner_id={runner_id}, branch={_branch_for_check}) — merge 시도"
                                    )
                                else:
                                    logger.info(
                                        f"[_stream_output] exit_code={exit_code}, worktree 커밋 없음 "
                                        f"(runner_id={runner_id}, branch={_branch_for_check}) — merge 스킵"
                                    )
                            except Exception as _git_err:
                                logger.warning(f"[_stream_output] git log 커밋 수 확인 실패: {_git_err} — merge 스킵")
                        else:
                            logger.info(f"[_stream_output] exit_code={exit_code}, branch 키 없음 — merge 스킵")
            except Exception as e:
                logger.warning(f"[_stream_output] merge_requested 플래그 조회 실패 (runner_id={runner_id}): {e}")
        logger.info(
            f"[_stream_output] merge 분기 판정: _merge_requested={_merge_requested}, "
            f"exit_code={exit_code} (runner_id={runner_id})"
        )

        # Workflow 상태 업데이트
        if _wf_manager and runner_id:
            try:
                wf = _wf_manager.get_by_runner_id(runner_id)
                if wf:
                    if exit_code == 0:
                        if _merge_requested:
                            logger.info(f"[_stream_output] merge_requested 플래그 감지 (runner_id={runner_id}) → merge 흐름 진입")
                            _wf_manager.update_status(wf["id"], "merge_pending")
                        else:
                            logger.info(f"[_stream_output] merge_requested 플래그 없음 (runner_id={runner_id}) → completed 처리")
                            _wf_manager.update_status(wf["id"], "completed")
                    elif exit_code is not None and exit_code != 0:
                        _wf_manager.update_status(
                            wf["id"], "failed",
                            error_message=f"Process exited with code {exit_code}",
                        )
                    else:
                        logger.warning(f"[_stream_output] exit_code=None → workflow {wf['id']} failed 처리")
                        _wf_manager.update_status(
                            wf["id"], "failed",
                            error_message="Process terminated unexpectedly (exit_code=None)",
                        )
            except Exception as wf_err:
                logger.warning(f"[_stream_output] workflow update 실패 (무시): {wf_err}")

        if _merge_requested:
            # merge 흐름 — cleanup은 merge 완료/실패 후 _do_inline_merge 내부에서 호출
            _do_inline_merge(runner_id, redis_client)
        else:
            _cleanup_process_state(runner_id, redis_client)


def _do_start_plan_runner(command: Dict, redis_client: redis.Redis):
    """plan-runner CLI 실행 (백그라운드 스레드에서 호출 — worktree 생성 포함)"""
    from worktree_manager import WorktreeManager, WorktreeError, ensure_main_branch
    from workflow_manager import WorkflowManager
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

    def _set_error_status(message: str):
        """실패 시 per-runner 상태를 Redis에 기록 + 라이브 로그 채널에 publish"""
        if runner_id:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "error")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:error", message)
            logger.error(f"[_do_start_plan_runner] 실패 상태 기록 (runner_id: {runner_id}): {message}")
            try:
                redis_client.publish(f"{LOG_CHANNEL_PREFIX}:{runner_id}", f"[ERROR] {message}")
            except Exception as pub_err:
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
        if is_plan_archived(plan_file):
            _set_error_status(f"archived plan은 실행할 수 없습니다: {plan_file}")
            return

    # plan 파일의 git root 결정 (wtools 등 외부 레포 지원)
    plan_project_root = get_plan_git_root(plan_file) if plan_file else _PR
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
                    logger.info(f"기존 워크트리 재사용: {worktree_path} (branch: {branch})")
            else:
                    # 경로 없음 또는 worktree 검증 실패 → plan 헤더에서 필드 제거 후 신규 생성
                    _remove_plan_header_fields(plan_file)
                    logger.info(f"워크트리 없음 또는 검증 실패, 신규 생성: plan={plan_file}")
        if not _reused_worktree:
            worktree_path, branch = WorktreeManager.create(runner_id, plan_worktree_base, plan_file=plan_file)
            # Phase 4: plan 헤더에 branch/worktree 기록 (수동 /implement와 동일 패턴)
            if plan_file:
                worktree_rel = str(worktree_path.relative_to(plan_project_root)).replace("\\", "/")
                _write_plan_worktree_info(plan_file, branch, worktree_rel)
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
    is_parallel = command.get("parallel", False)
    if not plan_file and not is_parallel:
        _set_error_status("plan_file required (use parallel mode for batch execution)")
        return

    result = _launch_plan_runner_process(command, redis_client, runner_id, worktree_path, plan_file, engine, branch=branch, project_root=plan_project_root)
    if not result.get("success"):
        _set_error_status(result.get("message", "Unknown error"))
    else:
        # Workflow running 상태 업데이트
        if _wf_manager and _wf_id:
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

    # 백그라운드 스레드에서 worktree 생성 + 프로세스 시작
    thread = threading.Thread(
        target=_do_start_plan_runner,
        args=(command, redis_client),
        daemon=True,
    )
    thread.start()

    return None  # sentinel: main loop에서 결과 push 스킵 (이미 위에서 push)


def _launch_plan_runner_process(command: Dict, redis_client: redis.Redis, runner_id: str, worktree_path: Path, plan_file: str, engine: str, branch: str = "", project_root: Path = None) -> Dict:
    """plan-runner CLI 프로세스 실행 (worktree 생성 이후 호출)"""
    from _dr_constants import PROJECT_ROOT as _PR
    if project_root is None:
        project_root = _PR

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

    # 옵션 추가
    if command.get("max_cycles") is not None:
        cmd.extend(["--max-cycles", str(command["max_cycles"])])

    if command.get("max_tokens") is not None:
        cmd.extend(["--max-tokens", str(command["max_tokens"])])

    if command.get("until"):
        cmd.extend(["--until", command["until"]])

    if command.get("dry_run"):
        cmd.append("--dry-run")

    if command.get("skip_plan"):
        cmd.append("--skip-plan")

    if command.get("parallel"):
        cmd.append("--parallel")

    if command.get("projects"):
        cmd.extend(["--projects", command["projects"]])

    if command.get("extra_plan_dirs"):
        cmd.extend(["--extra-plan-dirs", command["extra_plan_dirs"]])

    if command.get("ignored_plans"):
        cmd.extend(["--ignored-plans", command["ignored_plans"]])

    if command.get("worktree") or worktree_path:
        cmd.append("--worktree")

    # 로그 파일 생성
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"plan-runner-{runner_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

    try:
        # subprocess 실행 및 stdout을 PIPE로 받아 스레드에서 파일+Redis 동시 기록
        log_handle = open(log_file, "w", encoding="utf-8")
        log_handle.write(f"[TRIGGER] {command.get('trigger', 'unknown')} | plan={plan_file} | engine={engine} | runner_id={runner_id}\n")
        log_handle.flush()

        import os
        import re as _re
        env = _make_plan_runner_env(
            runner_id,
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

        process = subprocess.Popen(
            cmd,
            cwd=str(PLAN_RUNNER_MODULE_PATH),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        _running_processes[runner_id] = process
        _running_log_files[runner_id] = log_file

        # 별도 스레드에서 stdout 을 파일 + Redis publish
        thread = threading.Thread(
            target=_stream_output,
            args=(process, log_handle, redis_client, runner_id),
            daemon=True,
        )
        thread.start()
        _stream_threads[runner_id] = thread

        # Redis에 상태 저장 (per-runner 키)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path", str(log_file))
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", process.pid)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file or PLAN_FILE_ALL)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch or f"runner/{runner_id}")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", command.get("engine", "claude"))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:fix_engine", command.get("fix_engine", "claude"))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", str(worktree_path))
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:quota_stopped")
        redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)
        trigger = command.get("trigger", "unknown")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", trigger)

        logger.info(f"plan-runner started (PID: {process.pid}, log: {log_file})")

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
        proc.terminate()

        # 5초 대기
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # 강제 종료
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
            redis_client.lrem("plan-runner:merge-wait-queue", 0, rid)
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
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        # _DummyProcess 또는 proc 없음 → Redis PID로 직접 SIGKILL
        if pid_str:
            try:
                pid = int(pid_str)
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
