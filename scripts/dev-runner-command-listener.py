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
import argparse
import json
import logging
import msvcrt
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

_ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

import redis

# listener_noise_filter는 scripts/ 디렉토리에 위치 — sys.path로 직접 로드
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from listener_noise_filter import NOISE_BLOCK_MARKERS as _NOISE_BLOCK_MARKERS, is_noise_line as _is_noise_line
from worktree_manager import WorktreeManager, WorktreeError
from workflow_manager import WorkflowManager
from plan_worktree_helpers import (
    is_plan_in_progress as _is_plan_in_progress,
    parse_plan_worktree_info as _parse_plan_worktree_info,
    write_plan_worktree_info as _write_plan_worktree_info,
    remove_plan_header_fields as _remove_plan_header_fields,
)

# 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0  # --redis-db 인자로 오버라이드 가능 (테스트 격리용)
COMMANDS_KEY = "plan-runner:commands"
RESULTS_KEY = "plan-runner:command_results"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"  # sorted set: score=종료 timestamp
PLAN_FILE_ALL = "__ALL_PLANS__"  # 전체실행 sentinel — plan_file 미지정 시 Redis에 저장
_LEGACY_ALL = "ALL"  # 하위 호환: 이전 버전에서 저장된 "ALL" 값 인식용
RECENT_RUNNERS_TTL = 86400  # 24시간 (초) — executor_service.py의 RECENT_RUNNERS_TTL과 동일하게 유지
# per-runner 키 suffix 전체 목록 — app/modules/dev_runner/services/executor_service.py의 RUNNER_KEY_SUFFIXES와 동일
RUNNER_KEY_SUFFIXES = (
    "status", "pid", "plan_file", "start_time", "log_file_path", "stream_log_path",
    "engine", "worktree_path", "branch", "merge_status", "merge_requested",
    "current_cycle", "quota_stopped", "error", "restart_after_merge", "test_source",
)
HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
HEARTBEAT_INTERVAL = 10  # heartbeat 갱신 주기 (초)
HEARTBEAT_TTL = 30  # heartbeat 만료 시간 (초, 3회 미갱신 시 만료)

# merge 활성 상태 — cleanup 보호 가드 및 reconnect 복구 조건에 사용
MERGE_ACTIVE_STATUSES = ("queued", "merging", "pending_merge", "resolving", "testing", "fixing")

QUOTA_ERROR_MARKERS = ["TerminalQuotaError", "exhausted your capacity", "[QUOTA]"]

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
WORKTREE_BASE_DIR = PROJECT_ROOT / ".worktrees"
WTOOLS_BASE_DIR = Path("D:/work/project/service/wtools")
PLAN_RUNNER_MODULE_PATH = WTOOLS_BASE_DIR / "common/tools/plan-runner"
PLAN_RUNNER_PYTHON = PLAN_RUNNER_MODULE_PATH / ".venv/Scripts/python.exe"
LOG_DIR = WTOOLS_BASE_DIR / "common/logs"

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

LOG_CHANNEL_PREFIX = "plan-runner:logs"

# ── lock file (중복 실행 방지) ──────────────────────────────────
_LOCK_FILE_PATH = PROJECT_ROOT / ".pids" / "dev_runner_listener.lock"
_lock_fd = None  # 열린 fd를 전역에 보관 → 프로세스 종료 시 OS가 자동 해제


def _acquire_lock() -> bool:
    """exclusive lock file 획득. 이미 다른 인스턴스가 실행 중이면 False 반환."""
    global _lock_fd
    _LOCK_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        _lock_fd = open(str(_LOCK_FILE_PATH), "w", encoding="utf-8")
        msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        return True
    except OSError:
        if _lock_fd:
            _lock_fd.close()
            _lock_fd = None
        return False


# 전역 프로세스 관리
_running_processes: dict = {}
_running_log_files: dict = {}
_stream_threads: dict = {}
# MergeOrchestrator 전역변수 — 인라인 merge로 대체됨 (Phase 3에서 제거)
# (제거됨: _merge_orchestrator_process, _merge_orchestrator_log_path, _merge_orchestrator_attached_pid)

# WorkflowManager (main()에서 초기화)
_wf_manager: Optional[WorkflowManager] = None


def _is_pid_alive(pid: int) -> bool:
    """PID가 실제로 살아있는지 OS 레벨 확인 (Windows)"""
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


# [DEPRECATED] _poll_merge_results — MergeOrchestrator 제거로 불필요
# merge 결과는 _do_inline_merge에서 직접 workflow_manager를 통해 처리됨


def _cleanup_process_state(runner_id: str, redis_client: redis.Redis, reason: str = "process_cleanup"):
    """전역 프로세스 변수 + Redis 상태 정리 (per-runner) + Workflow DB 갱신"""
    global _running_processes, _running_log_files, _stream_threads

    # 🔴 머지 보호 가드: reconnect_* / heartbeat_* 계열 reason이면 머지 진행 중 cleanup 거부
    if reason and reason.startswith(("reconnect_", "heartbeat_")):
        try:
            merge_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            if merge_status in MERGE_ACTIVE_STATUSES:
                logger.warning(
                    f"[cleanup] 머지 진행중 runner {runner_id} cleanup 거부 "
                    f"(reason={reason}, merge_status={merge_status})"
                )
                return
        except Exception as _guard_err:
            logger.debug(f"[cleanup] 머지 가드 조회 실패 (무시): {_guard_err}")

    # cleanup 직전 SSE 클라이언트에 완료 신호 publish
    try:
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        redis_client.publish(log_channel, "__COMPLETED__")
    except Exception:
        pass

    _running_processes.pop(runner_id, None)
    _running_log_files.pop(runner_id, None)
    if runner_id in _stream_threads:
        t = _stream_threads.pop(runner_id)
        if t.is_alive() and t is not threading.current_thread():
            t.join(timeout=3)

    try:
        # worktree 정리 (머지 완료 또는 실패로 정리 필요한 경우)
        merge_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        plan_file_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        if plan_file_val in (PLAN_FILE_ALL, _LEGACY_ALL):
            plan_file_val = None

        # 구현중 plan은 워크트리 보존 (재실행 시 이어서 작업 가능)
        _preserve_worktree = False
        if plan_file_val and _is_plan_in_progress(plan_file_val):
            _preserve_worktree = True
            logger.info(f"워크트리 보존 (plan 구현중): {runner_id}")

        # merge_status가 없거나 "merged"가 아닌 경우에만 worktree 정리 시도
        # (머지 워크플로가 별도로 관리하는 경우 스킵)
        if not _preserve_worktree and merge_status not in ("pending_merge", "conflict", "queued"):
            try:
                WorktreeManager.remove(runner_id, WORKTREE_BASE_DIR, plan_file=plan_file_val or None)
            except Exception as wt_e:
                logger.warning(f"worktree 정리 실패 (runner_id: {runner_id}): {wt_e}")
        elif not _preserve_worktree and merge_status in ("merging", "testing"):
            # 프로세스가 죽은 상태에서 중간 상태로 남은 경우 — stale worktree 정리
            try:
                WorktreeManager.remove(runner_id, WORKTREE_BASE_DIR, plan_file=plan_file_val or None)
                logger.info(f"stale 중간 상태 worktree 정리: {runner_id} (merge_status={merge_status})")
            except Exception as wt_e:
                logger.warning(f"stale worktree 정리 실패 (runner_id: {runner_id}): {wt_e}")

        # 종료된 runner를 RECENT_RUNNERS에 등록하여 탭 이력 보존
        # 키는 즉시 삭제 대신 EXPIRE 설정 — TTL 만료 후 자동 소멸
        # _preserve_worktree=True 시 worktree_path 키만 TTL 없이 보존 (재실행 시 재사용)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        for suffix in RUNNER_KEY_SUFFIXES:
            if _preserve_worktree and suffix == "worktree_path":
                continue  # 워크트리 보존 시 worktree_path는 TTL 설정 스킵
            key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"
            redis_client.expire(key, RECENT_RUNNERS_TTL)
        redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
        redis_client.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})
    except Exception:
        pass

    # Workflow DB: running 상태인 경우 failed로 전이
    try:
        if _wf_manager:
            wf = _wf_manager.get_by_runner_id(runner_id)
            if wf and wf["status"] in ("running", "merge_pending", "merging"):
                _wf_manager.update_status(wf["id"], "failed", error_message=f"Cleanup: {reason}")
                logger.info(f"[cleanup] workflow {wf['id']} → failed (reason: {reason})")
    except Exception as e:
        logger.warning(f"[cleanup] workflow DB 갱신 실패 (무시): {e}")


class _DummyProcess:
    """재연결된 plan-runner 프로세스를 위한 래퍼.

    기존 코드의 ``proc.poll()`` 호출과 호환되도록 poll() / wait() 인터페이스를 제공한다.
    실제 stdout pipe는 없으므로 로그 tailing은 별도 스레드(_tail_log_and_publish)가 담당한다.
    """

    def __init__(self, pid: int):
        self.pid = pid
        self.returncode: Optional[int] = None

    def poll(self) -> Optional[int]:
        """프로세스가 살아있으면 None, 종료되었으면 -1 반환."""
        if self.returncode is not None:
            return self.returncode
        if not _is_pid_alive(self.pid):
            self.returncode = -1
        return self.returncode


def _tail_log_and_publish(runner_id: str, log_path: str, redis_client: redis.Redis):
    """로그 파일 끝(EOF)부터 새 줄을 읽어 Redis log channel에 publish하는 스레드.

    재연결된 runner에서 pipe가 없을 때 파일 tailing으로 대체 스트리밍한다.
    PID 종료 + 더 이상 새 줄 없음 → 스레드 종료.
    """
    log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            # 파일 끝으로 이동 (재연결 전 기존 내용은 재발행하지 않음)
            f.seek(0, 2)
            while True:
                # runner가 이미 cleanup됐으면 스레드 종료
                if runner_id not in _running_processes:
                    break
                line = f.readline()
                if line:
                    stripped = line.rstrip('\n')
                    try:
                        redis_client.publish(log_channel, _ANSI_ESCAPE.sub('', stripped))
                    except redis.ConnectionError:
                        pass
                else:
                    # 더 읽을 내용 없음 — PID가 죽었는지 확인
                    proc = _running_processes.get(runner_id)
                    if proc is not None and proc.poll() is not None:
                        # 프로세스 종료 후 파일에 추가된 잔여 라인을 한 번 더 드레인
                        # (plan-runner가 종료 직전 _log()로 기록한 FAIL 로그 등)
                        time.sleep(0.3)  # 파일 flush 대기
                        while True:
                            remaining = f.readline()
                            if not remaining:
                                break
                            _stripped = remaining.rstrip('\n')
                            if _stripped:
                                try:
                                    redis_client.publish(log_channel, _ANSI_ESCAPE.sub('', _stripped))
                                except redis.ConnectionError:
                                    pass
                        break
                    time.sleep(0.2)
    except FileNotFoundError:
        logger.warning(f"[tail_log] 로그 파일 없음: {log_path}")
    except Exception as e:
        logger.error(f"[tail_log] 스레드 오류 (runner_id={runner_id}): {e}")


def _monitor_pid_until_exit(runner_id: str, pid: int, redis_client: redis.Redis):
    """PID 종료를 1초 간격으로 감지하여 _cleanup_process_state()를 호출하는 스레드."""
    while True:
        # 이미 cleanup됐으면 즉시 종료 (중복 cleanup 방지)
        if runner_id not in _running_processes:
            break
        if not _is_pid_alive(pid):
            logger.info(f"[monitor_pid] runner {runner_id} PID {pid} 종료 감지 → tail 스레드 완료 대기")
            # tail 스레드가 파일 끝까지 drain 하도록 최대 5초 대기
            # (plan-runner 종료 직전 _log("FAIL", ...) 등 마지막 로그가 publish된 후
            # __COMPLETED__가 발행되도록 순서를 보장함)
            tail_thread = _stream_threads.get(runner_id)
            if tail_thread and tail_thread.is_alive():
                tail_thread.join(timeout=5)
            logger.info(f"[monitor_pid] runner {runner_id} → cleanup")
            _cleanup_process_state(runner_id, redis_client, reason="pid_exit_detected")
            break
        time.sleep(1)


def _attach_to_running_process(runner_id: str, pid: int, redis_client: redis.Redis):
    """listener 재시작 시 이미 살아있는 plan-runner에 재연결.

    pipe가 없으므로 로그 파일 tailing + PID 모니터 스레드로 대체 연결한다.
    """
    # 로그 파일 경로 조회
    log_file_path = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")
    if not log_file_path:
        log_file_path = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
    if not log_file_path or not Path(log_file_path).exists():
        logger.warning(f"[attach] runner {runner_id} 로그 파일 없음 → cleanup")
        _cleanup_process_state(runner_id, redis_client, reason="no_log_file")
        return

    # _DummyProcess 등록 (기존 heartbeat 루프의 proc.poll() 호환)
    dummy = _DummyProcess(pid)
    _running_processes[runner_id] = dummy
    _running_log_files[runner_id] = Path(log_file_path)

    # tailing 스레드 시작
    tail_thread = threading.Thread(
        target=_tail_log_and_publish,
        args=(runner_id, log_file_path, redis_client),
        daemon=True,
    )
    tail_thread.start()
    _stream_threads[runner_id] = tail_thread

    # PID 모니터 스레드 시작
    monitor_thread = threading.Thread(
        target=_monitor_pid_until_exit,
        args=(runner_id, pid, redis_client),
        daemon=True,
    )
    monitor_thread.start()

    logger.info(f"[listener] 재시작 감지: runner {runner_id} PID {pid} 생존 → 재연결")


def _recover_pending_merge(runner_id: str, redis_client: redis.Redis, merge_status: str | None) -> None:
    """리스너 재시작 시 미완료 머지 복구.

    _stream_output 스레드가 없는 상태에서 merge_requested 또는 merge_status 활성인 러너에 대해
    _do_inline_merge()를 재호출하여 머지를 완료한다.

    Args:
        runner_id: 복구할 러너 ID
        redis_client: Redis 클라이언트
        merge_status: 현재 merge_status 값 (None 포함)
    """
    from merge_lock import acquire_merge_lock, release_merge_lock  # noqa: F401 (import used in _do_inline_merge)

    logger.info(f"[recover_merge] runner {runner_id} 머지 복구 시작 (merge_status={merge_status})")

    try:
        if merge_status in ("merging", "resolving"):
            # stale lock 해제 후 queued로 재설정
            try:
                release_merge_lock(redis_client, runner_id)
                logger.info(f"[recover_merge] runner {runner_id} stale merge lock 해제 (merge_status={merge_status})")
            except Exception as _e:
                logger.debug(f"[recover_merge] lock 해제 실패 (무시): {_e}")
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "queued")
            # merge_requested 플래그가 없으면 새로 설정 (재진입 용)
            _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
            if not _mr:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")

        elif merge_status in ("queued", "pending_merge") or merge_status is None:
            # merge_requested가 있으면 그대로 _do_inline_merge 호출
            _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
            if not _mr:
                # merge_requested 없으면 새로 설정
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
        else:
            logger.info(f"[recover_merge] runner {runner_id} merge_status={merge_status} → 복구 불필요")
            return

        _do_inline_merge(runner_id, redis_client)

    except Exception as e:
        logger.warning(f"[recover_merge] runner {runner_id} 머지 복구 실패: {e}")


def _reconnect_surviving_runners(redis_client: redis.Redis):
    """listener 시작(또는 재시작) 시 한 번 호출.

    Redis active_runners 목록을 순회하여:
    - PID가 살아있으면 → _attach_to_running_process() 로 재연결
    - PID가 죽어있거나 없으면 → _cleanup_process_state() 로 정리

    추가로 scan_iter("plan-runner:runners:*:status")로 전체 runner 키를 탐색하여
    active_runners set에 없는 고아 키도 정리한다.
    """
    try:
        runner_ids = redis_client.smembers(ACTIVE_RUNNERS_KEY)
    except Exception as e:
        logger.warning(f"[reconnect] active_runners 조회 실패: {e}")
        return

    for runner_id in runner_ids:
        pid_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
        if not pid_str:
            # PID 없는 경우에도 merge_status 확인 — dm-* 러너는 PID를 세팅하지 않으므로
            try:
                _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
                _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            except Exception:
                _mr, _ms = None, None
            if _mr or _ms in MERGE_ACTIVE_STATUSES:
                logger.warning(
                    f"[reconnect] runner {runner_id} PID 없으나 머지 대기중 "
                    f"(merge_requested={bool(_mr)}, merge_status={_ms}) → _recover_pending_merge"
                )
                if not (runner_id in _stream_threads and _stream_threads[runner_id].is_alive()):
                    import threading
                    t = threading.Thread(
                        target=_recover_pending_merge,
                        args=(runner_id, redis_client, _ms),
                        daemon=True,
                    )
                    t.start()
            else:
                logger.info(f"[listener] runner {runner_id} PID 정보 없음 → cleanup")
                _cleanup_process_state(runner_id, redis_client, reason="reconnect_orphan")
            continue
        try:
            pid = int(pid_str)
        except ValueError:
            logger.warning(f"[reconnect] runner {runner_id} 잘못된 PID 값: {pid_str!r} → cleanup")
            _cleanup_process_state(runner_id, redis_client, reason="reconnect_orphan")
            continue

        # 이미 _running_processes에 등록된 경우(Redis 재연결 상황) 스킵
        if runner_id in _running_processes:
            continue

        if _is_pid_alive(pid):
            _attach_to_running_process(runner_id, pid, redis_client)
        else:
            # PID 사망 전 머지 상태 확인 — merge_requested 또는 merge_status 활성 상태면 cleanup 스킵
            try:
                _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
                _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            except Exception:
                _mr, _ms = None, None

            if _mr or _ms in MERGE_ACTIVE_STATUSES:
                logger.warning(
                    f"[reconnect] runner {runner_id} PID {pid} 죽었으나 머지 대기중 "
                    f"(merge_requested={bool(_mr)}, merge_status={_ms}) → cleanup 스킵"
                )
                # _stream_output 스레드가 없는 경우(리스너 재시작) 머지 복구 실행
                if not (runner_id in _stream_threads and _stream_threads[runner_id].is_alive()):
                    import threading
                    t = threading.Thread(
                        target=_recover_pending_merge,
                        args=(runner_id, redis_client, _ms),
                        daemon=True,
                    )
                    t.start()
            else:
                logger.info(f"[listener] 재시작 감지: runner {runner_id} PID {pid} 종료됨 → cleanup")
                _cleanup_process_state(runner_id, redis_client, reason="reconnect_orphan")

    # --- 고아 키 탐색: active_runners set에 없지만 runners:*:status 키가 존재하는 경우 ---
    try:
        for key in redis_client.scan_iter(f"{RUNNER_KEY_PREFIX}:*:status"):
            # key 형태: "plan-runner:runners:{runner_id}:status"
            # RUNNER_KEY_PREFIX = "plan-runner:runners"
            prefix = f"{RUNNER_KEY_PREFIX}:"
            suffix = ":status"
            if not (key.startswith(prefix) and key.endswith(suffix)):
                continue
            orphan_id = key[len(prefix):-len(suffix)]
            if not orphan_id:
                continue
            if orphan_id in runner_ids:
                continue  # active_runners에 이미 있음 → 위에서 처리됨
            logger.info(f"[reconnect] orphan key found (not in active_runners): {orphan_id}")
            pid_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:pid")
            if not pid_str:
                # PID 없는 경우에도 merge_status 확인 — dm-* 러너는 PID를 세팅하지 않으므로
                try:
                    _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:merge_requested")
                    _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:merge_status")
                except Exception:
                    _mr, _ms = None, None
                if _mr or _ms in MERGE_ACTIVE_STATUSES:
                    logger.warning(
                        f"[reconnect] orphan {orphan_id} PID 없으나 머지 대기중 "
                        f"(merge_requested={bool(_mr)}, merge_status={_ms}) → _recover_pending_merge"
                    )
                    if not (orphan_id in _stream_threads and _stream_threads[orphan_id].is_alive()):
                        import threading
                        t = threading.Thread(
                            target=_recover_pending_merge,
                            args=(orphan_id, redis_client, _ms),
                            daemon=True,
                        )
                        t.start()
                else:
                    logger.info(f"[reconnect] orphan {orphan_id} PID 없음 → cleanup")
                    _cleanup_process_state(orphan_id, redis_client, reason="reconnect_orphan_scan")
                continue
            try:
                pid = int(pid_str)
            except ValueError:
                logger.warning(f"[reconnect] orphan {orphan_id} 잘못된 PID: {pid_str!r} → cleanup")
                _cleanup_process_state(orphan_id, redis_client, reason="reconnect_orphan_scan")
                continue
            if _is_pid_alive(pid):
                logger.info(f"[reconnect] orphan {orphan_id} PID {pid} 생존 → 재연결")
                _attach_to_running_process(orphan_id, pid, redis_client)
            else:
                # PID 사망 전 머지 상태 확인
                try:
                    _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:merge_requested")
                    _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{orphan_id}:merge_status")
                except Exception:
                    _mr, _ms = None, None

                if _mr or _ms in MERGE_ACTIVE_STATUSES:
                    logger.warning(
                        f"[reconnect] orphan {orphan_id} PID {pid} 죽었으나 머지 대기중 "
                        f"(merge_requested={bool(_mr)}, merge_status={_ms}) → cleanup 스킵"
                    )
                    if not (orphan_id in _stream_threads and _stream_threads[orphan_id].is_alive()):
                        import threading
                        t = threading.Thread(
                            target=_recover_pending_merge,
                            args=(orphan_id, redis_client, _ms),
                            daemon=True,
                        )
                        t.start()
                else:
                    logger.info(f"[reconnect] orphan {orphan_id} PID {pid} 종료됨 → cleanup")
                    _cleanup_process_state(orphan_id, redis_client, reason="reconnect_orphan_scan")
    except Exception as e:
        logger.warning(f"[reconnect] orphan scan 실패: {e}")


def _detect_orphan_workflows(redis_client: redis.Redis) -> int:
    """listener 시작 시 DB↔Redis 교차검증: running/merge_pending 워크플로우 중 active_runners에 없는 것을 failed로 전이"""
    if _wf_manager is None:
        return 0
    cleaned = 0
    try:
        for status in ("running", "merge_pending"):
            workflows = _wf_manager.list_workflows(status=status)
            for wf in workflows:
                runner_id = wf.get("runner_id")
                if not runner_id:
                    continue
                if redis_client.sismember(ACTIVE_RUNNERS_KEY, runner_id):
                    continue
                # 머지 대기중인 러너는 failed 전이 스킵
                try:
                    _mr = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
                    _ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
                except Exception:
                    _mr, _ms = None, None
                if _mr or _ms in MERGE_ACTIVE_STATUSES:
                    logger.info(
                        f"[orphan] workflow {wf['id']} slug={wf.get('slug', '?')} (runner={runner_id}) "
                        f"머지 대기중 (merge_requested={bool(_mr)}, merge_status={_ms}) → failed 전이 스킵"
                    )
                    continue
                _wf_manager.update_status(
                    wf["id"], "failed",
                    error_message="orphan: listener 재시작 시 active_runners에 없음"
                )
                logger.warning(f"[orphan] workflow {wf['id']} slug={wf.get('slug', '?')} (runner={runner_id}) → failed")
                cleaned += 1
    except Exception as e:
        logger.warning(f"[orphan] workflow 고아 탐지 실패: {e}")
    return cleaned


def _detect_orphan_plans(redis_client: redis.Redis) -> int:
    """plan 파일 '> 상태: 구현중' 교차검증: Workflow DB에 대응 running 레코드가 없으면 경고"""
    import re as _re

    if _wf_manager is None:
        return 0
    warnings_count = 0
    plan_dir = PROJECT_ROOT / "docs" / "plan"
    if not plan_dir.is_dir():
        return 0
    try:
        all_workflows = _wf_manager.list_workflows()
        for plan_file in plan_dir.glob("*.md"):
            try:
                with open(plan_file, "r", encoding="utf-8") as f:
                    head_lines = [f.readline() for _ in range(20)]
            except Exception:
                continue
            is_impl = any(_re.search(r">\s*상태:\s*구현중", line) for line in head_lines if line)
            if not is_impl:
                continue
            filename = plan_file.name
            # Workflow DB에서 이 plan에 대한 레코드 찾기 (dev-runner가 시작한 plan만 검증)
            any_record = [
                w for w in all_workflows
                if w.get("plan_file") and filename in w["plan_file"]
            ]
            if not any_record:
                # dev-runner를 통하지 않은 plan → 검증 대상 아님
                continue
            matching = [w for w in any_record if w.get("status") == "running"]
            if not matching:
                logger.warning(f"[orphan-plan] {filename}: 상태=구현중이지만 Workflow DB에 running 레코드 없음")
                warnings_count += 1
            else:
                for w in matching:
                    rid = w.get("runner_id")
                    if rid and not redis_client.sismember(ACTIVE_RUNNERS_KEY, rid):
                        logger.warning(f"[orphan-plan] {filename}: runner {rid}가 active_runners에 없음")
                        warnings_count += 1
    except Exception as e:
        logger.warning(f"[orphan-plan] plan 고아 탐지 실패: {e}")
    return warnings_count


def _resolve_todo_file(plan_file_str: str | None) -> str | None:
    """mode B plan의 실제 TODO 파일 경로 반환.

    archive에 보관된 plan 문서나 체크박스가 없는 plan 문서를 받으면
    대응하는 _todo.md 파일 경로를 반환한다.
    """
    if plan_file_str is None:
        return None
    # sentinel 값은 그대로 반환 (전체실행 모드)
    if plan_file_str in (PLAN_FILE_ALL, _LEGACY_ALL):
        return plan_file_str

    plan_path = Path(plan_file_str)
    todo_candidate = plan_path.parent.parent / "plan" / f"{plan_path.stem}_todo.md"

    # archive 경로인 경우 → _todo.md 시도
    if "docs/archive" in plan_file_str.replace("\\", "/") or "docs\\archive" in plan_file_str:
        if todo_candidate.is_file():
            logger.debug(f"[resolve-todo] archive path → {todo_candidate}")
            return str(todo_candidate)
        return plan_file_str

    # plan 폴더이지만 체크박스가 0개인 경우 → _todo.md 시도
    try:
        if plan_path.is_file():
            content = plan_path.read_text(encoding="utf-8")
            if not re.search(r'- \[ \]', content):
                if todo_candidate.is_file():
                    logger.debug(f"[resolve-todo] no checkboxes → {todo_candidate}")
                    return str(todo_candidate)
    except Exception:
        pass

    return plan_file_str


def _restart_plan_runner_after_merge(plan_file: str, redis_client: redis.Redis, remaining: int) -> None:
    """merge 완료 후 plan에 잔여 항목이 있을 때 non-worktree 모드로 plan-runner 재시작.

    worktree 없이 PROJECT_ROOT에서 직접 실행하여 남은 TODO 항목을 계속 처리한다.
    """
    import os as _os
    runner_id = uuid.uuid4().hex[:8]
    cmd = [
        str(PLAN_RUNNER_PYTHON),
        "-m",
        "plan_runner",
        "run",
        "--plan-file",
        plan_file,
    ]
    # --worktree 플래그 미포함 — non-worktree 모드로 실행

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_filename = f"plan-runner-restart-{runner_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    log_file = LOG_DIR / log_filename

    try:
        env = _os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env.pop("CLAUDECODE", None)
        env["PLAN_RUNNER_RUNNER_ID"] = runner_id
        env["PLAN_RUNNER_WORK_DIR"] = str(PROJECT_ROOT)
        env["PLAN_RUNNER_WORKTREE_PATH"] = str(PROJECT_ROOT)
        env["REDIS_DB"] = str(REDIS_DB)
        # 로그 prefix 식별자
        _plan_basename = __import__('os').path.splitext(__import__('os').path.basename(plan_file or ""))[0]
        _plan_basename = __import__('re').sub(r'^\d{4}-\d{2}-\d{2}[_-]', '', _plan_basename)
        _plan_parts = _plan_basename.replace('_', '-').split('-')
        _plan_short = '-'.join(_plan_parts[:2]) if len(_plan_parts) >= 2 else _plan_parts[0]
        env["PLAN_RUNNER_NAME"] = f"PLAN-RUNNER#{_plan_short}@{runner_id[:4]}"

        log_handle = open(log_file, "w", encoding="utf-8")
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

        thread = threading.Thread(
            target=_stream_output,
            args=(process, log_handle, redis_client, runner_id),
            daemon=True,
        )
        thread.start()
        _stream_threads[runner_id] = thread

        # Redis per-runner 상태 등록
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path", str(log_file))
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", process.pid)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "main")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", "claude")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", str(PROJECT_ROOT))
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:quota_stopped")
        redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        logger.info(
            f"[RESTART-AFTER-MERGE] plan-runner 재시작: {plan_file} "
            f"(잔여 {remaining}개, runner_id={runner_id}, PID={process.pid})"
        )
    except Exception as e:
        logger.error(f"[RESTART-AFTER-MERGE] plan-runner 재시작 실패: {e}")


def _run_subprocess_streaming(cmd: list, env: dict, cwd: str, pub_fn, tag: str, timeout: int = 300) -> dict:
    """서브프로세스를 실행하며 stdout을 라인별로 실시간 pub_fn에 전달한다.

    capture_output=True 방식 대신 Popen + 라인 스트리밍으로 교체하여
    장시간 실행 중에도 로그 채널이 끊기지 않도록 한다.

    Returns:
        {"success": bool, "message": str, "output": str}
    """
    import os as _os
    output_lines: list[str] = []
    timed_out = False
    _timer = None

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        def _kill_on_timeout():
            nonlocal timed_out
            timed_out = True
            try:
                proc.kill()
            except Exception:
                pass

        _timer = threading.Timer(timeout, _kill_on_timeout)
        _timer.start()

        for line in proc.stdout:
            stripped = line.rstrip()
            output_lines.append(stripped)
            if pub_fn and stripped:
                try:
                    pub_fn(f"[{tag}] {stripped}")
                except Exception:
                    pass

        proc.wait()

    except Exception as e:
        if _timer:
            _timer.cancel()
        return {"success": False, "message": str(e), "output": "\n".join(output_lines)}
    finally:
        if _timer:
            _timer.cancel()

    if timed_out:
        return {"success": False, "message": f"{tag} timeout ({timeout}s)", "output": "\n".join(output_lines)}

    output_text = "\n".join(output_lines)
    if proc.returncode == 0:
        return {"success": True, "message": f"{tag} 성공", "output": output_text}

    # 실패 시 핵심 에러 라인 추출 (마지막 Error/Exception 라인 우선)
    error_lines = [l.strip() for l in output_lines if l.strip() and ("Error" in l or "Exception" in l)]
    if error_lines:
        msg = error_lines[-1][:300]
    else:
        non_empty = [l.strip() for l in output_lines if l.strip() and not l.strip().startswith(("│", "┌", "└", "├", "─"))]
        msg = "; ".join(non_empty[-3:])[:300] if non_empty else f"exit code {proc.returncode}"
    return {"success": False, "message": msg, "output": output_text}


def _launch_conflict_resolver_process(runner_id: str, branch: str, worktree_path: Path, redis_client, pub_fn=None) -> dict:
    """plan-runner resolve 서브커맨드로 conflict 자동 해결 프로세스를 실행한다.

    stdout을 라인별로 실시간 pub_fn에 전달하여 로그 끊김을 방지한다.

    Returns:
        {"success": True/False, "message": str}
    """
    import os
    cmd = [
        str(PLAN_RUNNER_PYTHON),
        "-m",
        "plan_runner",
        "resolve",
        "--branch", branch,
        "--project-dir", str(PROJECT_ROOT),
    ]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("CLAUDECODE", None)
    env["PLAN_RUNNER_WORK_DIR"] = str(worktree_path)
    env["PLAN_RUNNER_RUNNER_ID"] = runner_id
    env["REDIS_DB"] = str(REDIS_DB)

    result = _run_subprocess_streaming(
        cmd=cmd,
        env=env,
        cwd=str(PLAN_RUNNER_MODULE_PATH),
        pub_fn=pub_fn,
        tag="RESOLVE",
        timeout=300,
    )
    if result["success"]:
        logger.info(f"[conflict-resolver] auto-resolve 성공 (runner_id={runner_id})")
    else:
        logger.warning(f"[conflict-resolver] auto-resolve 실패 (runner_id={runner_id}): {result['message']}")
    return {"success": result["success"], "message": result["message"]}


def _launch_auto_fix_process(runner_id: str, test_output: str, targets: dict, redis_client, pub_fn=None) -> dict:
    """plan-runner auto-fix 서브커맨드로 자동 수정 프로세스를 실행한다.

    stdout을 라인별로 실시간 pub_fn에 전달하여 로그 끊김을 방지한다.

    Returns:
        {"success": bool, "message": str}
    """
    import os
    # test_output을 임시 파일에 기록
    error_file_path = PROJECT_ROOT / "logs" / f"auto-fix-{runner_id}.log"
    try:
        error_file_path.parent.mkdir(parents=True, exist_ok=True)
        error_file_path.write_text(test_output, encoding="utf-8")
    except Exception as e:
        if pub_fn:
            pub_fn(f"[AUTO-FIX] error-file 기록 실패: {e}")

    target_args = []
    for t in targets:
        target_args += ["--target", t]

    cmd = [
        str(PLAN_RUNNER_PYTHON), "-m", "plan_runner", "auto-fix",
        str(PROJECT_ROOT),
        *target_args,
        "--max-attempts", "1",
        "--skip-test",
        "--error-file", str(error_file_path),
    ]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("CLAUDECODE", None)
    env["PLAN_RUNNER_RUNNER_ID"] = runner_id
    env["REDIS_DB"] = str(REDIS_DB)

    result = _run_subprocess_streaming(
        cmd=cmd,
        env=env,
        cwd=str(PLAN_RUNNER_MODULE_PATH),
        pub_fn=pub_fn,
        tag="AUTO-FIX",
        timeout=300,
    )
    if result["success"]:
        logger.info(f"[auto-fix] 성공 (runner_id={runner_id})")
    else:
        logger.warning(f"[auto-fix] 실패 (runner_id={runner_id}): {result['message']}")
    return {"success": result["success"], "message": result["message"]}


def _post_merge_pipeline(runner_id: str, redis_client, pub_fn) -> bool:
    """merge 성공 후 서비스 재시작 → HTTP/빌드 테스트 → auto-fix 파이프라인.

    Returns:
        True: 모든 테스트 통과 (또는 변경 대상 없음)
        False: fix 실패 → revert 완료
    """
    import sys as _sys
    _sys.path.insert(0, str(PLAN_RUNNER_MODULE_PATH))
    from plan_runner.core.merge import (
        detect_restart_targets, restart_services, revert_merge,
        run_http_tests, run_frontend_build,
    )

    python_path = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")

    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "testing")
    except Exception:
        pass

    # 1. 변경 대상 감지
    try:
        targets = detect_restart_targets(PROJECT_ROOT)
    except Exception as e:
        pub_fn(f"[PIPELINE] detect_restart_targets 오류: {e} — 테스트 스킵")
        return True

    if not targets:
        pub_fn("[PIPELINE] 변경 대상 없음 — 테스트 스킵")
        return True

    # 2. 서비스 재시작
    try:
        restart_services(PROJECT_ROOT, python_path, targets)
        pub_fn(f"[PIPELINE] 서비스 재시작 완료 (targets: {list(targets.keys())})")
    except Exception as e:
        pub_fn(f"[PIPELINE] 서비스 재시작 실패: {e}")

    test_output = ""
    test_passed = True

    # 3. 테스트/빌드
    if targets.get("frontend"):
        try:
            build_result = run_frontend_build(PROJECT_ROOT)
            if not build_result.passed:
                test_output = build_result.output
                test_passed = False
                pub_fn(f"[PIPELINE] frontend 빌드 실패: {build_result.output[:200]}")
        except Exception as e:
            test_output = str(e)
            test_passed = False
            pub_fn(f"[PIPELINE] frontend 빌드 오류: {e}")

    if test_passed and (targets.get("api") or targets.get("worker")):
        try:
            http_result = run_http_tests(PROJECT_ROOT, python_path)
            if not http_result.passed:
                test_output = http_result.output
                test_passed = False
                pub_fn(f"[PIPELINE] HTTP 테스트 실패: {http_result.output[:200]}")
        except Exception as e:
            test_output = str(e)
            test_passed = False
            pub_fn(f"[PIPELINE] HTTP 테스트 오류: {e}")

    if test_passed:
        pub_fn("[PIPELINE] post-merge 검증 통과")
        return True

    # 4. auto-fix 시도
    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "fixing")
    except Exception:
        pass
    pub_fn("[PIPELINE] auto-fix 시도 중...")
    fix_result = _launch_auto_fix_process(runner_id, test_output, targets, redis_client, pub_fn=pub_fn)

    if fix_result["success"]:
        # fix 후 재테스트
        retry_passed = True
        if targets.get("frontend"):
            try:
                retry_result = run_frontend_build(PROJECT_ROOT)
                if not retry_result.passed:
                    retry_passed = False
                    pub_fn(f"[PIPELINE] fix 후 빌드 재실패: {retry_result.output[:200]}")
            except Exception as e:
                retry_passed = False
        if retry_passed and (targets.get("api") or targets.get("worker")):
            try:
                retry_http = run_http_tests(PROJECT_ROOT, python_path)
                if not retry_http.passed:
                    retry_passed = False
                    pub_fn(f"[PIPELINE] fix 후 HTTP 재실패: {retry_http.output[:200]}")
            except Exception as e:
                retry_passed = False
        if retry_passed:
            pub_fn("[PIPELINE] auto-fix 후 검증 통과")
            return True

    # 5. 최종 실패 → revert
    pub_fn("[PIPELINE] fix 실패 — revert 진행")
    try:
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "test_failed")
    except Exception:
        pass
    try:
        revert_merge(PROJECT_ROOT)
        pub_fn("[PIPELINE] revert 완료")
    except Exception as e:
        pub_fn(f"[PIPELINE] revert 실패: {e}")
    try:
        restart_services(PROJECT_ROOT, python_path, targets)
    except Exception:
        pass
    return False


def _do_inline_merge(runner_id: str, redis_client: redis.Redis) -> None:
    """merge_requested 플래그가 있을 때 _stream_output finally에서 호출되는 인라인 merge 함수.

    실행 순서:
      1. merge_status = "queued" 설정 + acquire_merge_lock() (blocking)
      2. lock 획득 후 merge_status = "merging" + MergeWorkflow.run()
      3. 성공 → merge_status = "merged", workflow = "merged" + release_merge_lock()
      4. 실패 → merge_status = "conflict"/"test_failed" + release_merge_lock() + worktree 보존
      5. merge 로그를 runner 로그 채널(plan-runner:log:{id})에 publish
      6. merge 완료/실패 후 _cleanup_process_state() 호출
    """
    from merge_lock import acquire_merge_lock, release_merge_lock
    from merge_workflow import MergeWorkflow
    from plan_runner.core.pipeline import pre_merge_gate, auto_commit_stage

    log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    log_list_key = f"plan-runner:logs:list:{runner_id}"

    def _pub(msg: str) -> None:
        """runner 로그 채널에 merge 로그 publish + Redis list에 히스토리 저장"""
        logger.info(f"[MERGE] {msg}")
        try:
            redis_client.publish(log_channel, f"[MERGE] {msg}")
        except Exception:
            pass
        try:
            redis_client.rpush(log_list_key, f"[MERGE] {msg}")
            redis_client.expire(log_list_key, 86400)
        except Exception:
            pass

    try:
        # 1. merge_status = "queued" 설정 (merge_requested 삭제 전에 — heartbeat 경쟁 조건 방지)
        # merge_requested 삭제 후 merge_status 설정 전에 heartbeat가 실행되면
        # 둘 다 없는 상태로 판단하여 조기 cleanup 가능
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "queued")
        except Exception:
            pass

        # merge_requested 플래그 삭제 (중복 진입 방지, merge_status가 이미 설정된 후)
        try:
            redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
        except Exception:
            pass
        _pub("merge lock 대기 중...")

        lock_acquired = acquire_merge_lock(redis_client, runner_id, timeout=600)
        if not lock_acquired:
            _pub("merge lock 획득 실패 (timeout) — merge 중단")
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
            except Exception:
                pass
            _cleanup_process_state(runner_id, redis_client)
            return

        # 2. lock 획득 후 merge 실행
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merging")
        except Exception:
            pass
        _pub("merge lock 획득 완료 — merge 시작")

        # 2-1. pre_merge_gate: main 브랜치 확인 + git clean 확인
        # 이미 lock을 획득했으므로 "다른 머지" 메시지는 무시 (lock already held)
        gate_ok, gate_msg = pre_merge_gate(PROJECT_ROOT, redis_client)
        if not gate_ok:
            if "다른 머지" in gate_msg:
                # lock이 이미 우리가 획득함 — 정상 (pre_merge_gate 내부에서 lock 재획득 실패한 것)
                _pub("[pre-merge] lock already held — proceeding")
            elif "dirty" in gate_msg:
                # dirty 상태 — 안전망 커밋 후 gate 재검사 (최대 3회)
                for attempt in range(3):
                    _pub(f"[pre-merge] dirty 감지 — 안전망 커밋 시도 ({attempt + 1}/3): {gate_msg}")
                    committed = auto_commit_stage(PROJECT_ROOT, "chore: pre-merge safety commit")
                    _pub(f"[pre-merge] 안전망 커밋 결과: {'성공' if committed else '변경없음/실패'}")
                    gate_ok, gate_msg = pre_merge_gate(PROJECT_ROOT, redis_client)
                    if gate_ok or "dirty" not in gate_msg:
                        # 성공하거나 dirty 외 다른 이유 실패 시 루프 중단
                        break
                if not gate_ok:
                    _pub(f"[pre-merge] gate 실패 (3회 재시도 후): {gate_msg}")
                    try:
                        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
                    except Exception:
                        pass
                    release_merge_lock(redis_client, runner_id)
                    _cleanup_process_state(runner_id, redis_client)
                    return
            else:
                # main 브랜치 아님 등 기타 실패
                _pub(f"[pre-merge] gate 실패: {gate_msg}")
                try:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
                except Exception:
                    pass
                release_merge_lock(redis_client, runner_id)
                _cleanup_process_state(runner_id, redis_client)
                return

        # worktree 경로, plan_file, branch 조회
        worktree_path_str = None
        plan_file_str = None
        branch_str = None
        try:
            worktree_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
            plan_file_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
            branch_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")
        except Exception:
            pass

        worktree_path = Path(worktree_path_str) if worktree_path_str else None
        plan_file = plan_file_str if (plan_file_str and plan_file_str not in (PLAN_FILE_ALL, _LEGACY_ALL)) else None

        if not worktree_path or not worktree_path.is_dir():
            _pub(f"worktree 경로 없음 또는 유효하지 않음: {worktree_path_str} — merge 중단")
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
            except Exception:
                pass
            release_merge_lock(redis_client, runner_id)
            _cleanup_process_state(runner_id, redis_client)
            return

        # [Phase 2-4] merge 전 worktree 사전 제거 — git merge 충돌 방지 (branch는 보존)
        try:
            _pub(f"[pre-merge] worktree 사전 제거 시작: {worktree_path}")
            WorktreeManager.remove(
                runner_id, WORKTREE_BASE_DIR,
                plan_file=plan_file,
                branch=branch_str,
                delete_branch=False,  # branch 보존 — merge 대상 branch가 필요
            )
            _pub("[pre-merge] worktree 사전 제거 완료")
        except Exception as wt_pre_err:
            _pub(f"[pre-merge] worktree 사전 제거 실패 (무시, merge 계속): {wt_pre_err}")

        # [Phase 2-5] branch divergence 시 rebase 시도 — merge 전 branch를 main 위로 rebase
        if branch_str:
            try:
                _pub(f"[pre-merge] rebase 시도: git rebase main {branch_str}")
                rebase_result = subprocess.run(
                    ["git", "rebase", "main", branch_str],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                )
                if rebase_result.returncode == 0:
                    _pub(f"[pre-merge] rebase 성공")
                else:
                    rebase_msg = (rebase_result.stderr.strip() or rebase_result.stdout.strip())[:300]
                    _pub(f"[pre-merge] rebase 실패 (무시, merge 강행): {rebase_msg}")
                    # rebase 실패 시 abort하여 상태 복원
                    subprocess.run(
                        ["git", "rebase", "--abort"],
                        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                    )
            except Exception as rebase_err:
                _pub(f"[pre-merge] rebase 예외 (무시, merge 강행): {rebase_err}")

        workflow = MergeWorkflow(
            project_root=PROJECT_ROOT,
            redis_client=redis_client,
            workflow_manager=_wf_manager,
        )
        result = workflow.run(
            runner_id=runner_id,
            worktree_path=worktree_path,
            base_dir=WORKTREE_BASE_DIR,
            plan_file=plan_file,
            branch=branch_str,
        )

        # 3/4. 결과 처리
        if result.merged:
            _pub("merge 성공 — post-merge 파이프라인 실행")
            pipeline_ok = _post_merge_pipeline(runner_id, redis_client, _pub)
            if not pipeline_ok:
                _pub("post-merge 파이프라인 실패 — worktree 보존 (이미 revert 완료)")
                return
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
            except Exception:
                pass
            _pub("merge 성공 — 완료")

            # plan 잔여 항목 확인 — 잔여 있으면 재시작 플래그 설정
            resolved_plan_file = _resolve_todo_file(plan_file)
            remaining_count = 0
            if resolved_plan_file:
                try:
                    plan_path = Path(resolved_plan_file)
                    if plan_path.is_file():
                        content = plan_path.read_text(encoding="utf-8")
                        remaining = re.findall(r'- \[ \]', content)
                        remaining_count = len(remaining)
                        _pub(f"plan 잔여 항목 확인 (resolved: {resolved_plan_file}): {remaining_count}개")
                    else:
                        _pub(f"plan 파일 없음 (잔여 확인 불가): {resolved_plan_file}")
                except Exception as e:
                    _pub(f"plan 잔여 항목 확인 실패: {e}")
            else:
                _pub("plan_file 미지정 — 잔여 항목 확인 생략")

            if remaining_count > 0:
                try:
                    redis_client.set(
                        f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge",
                        resolved_plan_file,
                    )
                    _pub(f"[RESTART-FLAG] plan 잔여 {remaining_count}개 → 재시작 플래그 설정: {resolved_plan_file}")
                except Exception as e:
                    _pub(f"재시작 플래그 설정 실패: {e}")
        elif result.conflict:
            _pub(f"merge 충돌 발생 — plan-runner resolve 시도 중...")
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "resolving")
            except Exception:
                pass

            # auto-resolve: plan-runner resolve 서브커맨드 실행
            # 전제: MergeWorkflow가 keep_conflict=True로 merge_to_main을 호출했으므로
            # project_root working tree에 충돌 마커가 남아있는 상태임
            _resolve_branch = branch_str or (f"plan/{Path(plan_file).stem}" if plan_file else f"runner/{runner_id}")
            resolve_result = _launch_conflict_resolver_process(
                runner_id, _resolve_branch, worktree_path, redis_client, pub_fn=_pub
            )

            if resolve_result["success"]:
                # merge commit이 실제로 생성됐는지 검증
                try:
                    log_proc = subprocess.run(
                        ["git", "log", "-1", "--format=%s"],
                        capture_output=True, text=True, cwd=str(PROJECT_ROOT)
                    )
                    last_subject = log_proc.stdout.strip()
                    if "merge:" not in last_subject.lower() and _resolve_branch.lower() not in last_subject.lower():
                        _pub(f"auto-resolve 경고: merge commit 미확인 (last: {last_subject[:100]}) — conflict로 처리")
                        try:
                            subprocess.run(["git", "merge", "--abort"], capture_output=True, cwd=str(PROJECT_ROOT))
                        except Exception:
                            pass
                        try:
                            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "conflict")
                        except Exception:
                            pass
                    else:
                        _pub("auto-resolve 성공 — post-merge 파이프라인 실행")
                        pipeline_ok = _post_merge_pipeline(runner_id, redis_client, _pub)
                        try:
                            WorktreeManager.remove(runner_id, WORKTREE_BASE_DIR, plan_file=plan_file, branch=branch_str)
                            _pub("worktree/branch 정리 완료")
                        except Exception as wt_err:
                            _pub(f"worktree 정리 실패 (무시): {wt_err}")
                        if not pipeline_ok:
                            _pub("post-merge 파이프라인 실패 (이미 revert 완료)")
                            _cleanup_process_state(runner_id, redis_client)
                            return
                        try:
                            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
                        except Exception:
                            pass
                        _cleanup_process_state(runner_id, redis_client)
                except Exception as verify_err:
                    _pub(f"auto-resolve merge commit 검증 실패 ({verify_err}) — merged로 처리, pipeline 실행")
                    pipeline_ok = _post_merge_pipeline(runner_id, redis_client, _pub)
                    try:
                        WorktreeManager.remove(runner_id, WORKTREE_BASE_DIR, plan_file=plan_file, branch=branch_str)
                        _pub("worktree/branch 정리 완료")
                    except Exception as wt_err:
                        _pub(f"worktree 정리 실패 (무시): {wt_err}")
                    if not pipeline_ok:
                        _cleanup_process_state(runner_id, redis_client)
                        return
                    try:
                        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
                    except Exception:
                        pass
                    _cleanup_process_state(runner_id, redis_client)
            else:
                _pub(f"auto-resolve 실패 — clean 상태로 복원 후 worktree 보존: {resolve_result['message'][:200]}")
                # 충돌 상태(keep_conflict=True로 유지됨)를 abort하여 main을 clean 상태로 복원
                try:
                    subprocess.run(["git", "merge", "--abort"], capture_output=True, cwd=str(PROJECT_ROOT))
                    _pub("git merge --abort 완료 (main clean 복원)")
                except Exception as abort_err:
                    _pub(f"merge --abort 실패 (무시): {abort_err}")
                try:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "conflict")
                except Exception:
                    pass
        else:
            _pub(f"merge 실패: {result.message[:200]}")
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
            except Exception:
                pass

        release_merge_lock(redis_client, runner_id)

    except Exception as e:
        logger.error(f"[_do_inline_merge] 예외 발생 (runner_id={runner_id}): {e}")
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
        except Exception:
            pass
        try:
            release_merge_lock(redis_client, runner_id)
        except Exception:
            pass

    finally:
        # merge 완료/실패 후 cleanup + 재시작
        # 순서: 재시작 플래그 읽기 → 재시작 실행 → cleanup
        # (cleanup이 WorktreeManager.remove 등에서 hang될 경우에도 재시작 보장)
        logger.info(f"[_do_inline_merge] finally 블록 진입 (runner_id={runner_id})")

        # [Phase 4-9] merge-results Redis list에 결과 push (merge history API 용)
        try:
            _final_merge_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            _merge_success = _final_merge_status == "merged"
            _merge_result_payload = json.dumps({
                "runner_id": runner_id,
                "branch": locals().get("branch_str"),
                "plan_file": locals().get("plan_file_str"),
                "timestamp": datetime.now().isoformat(),
                "status": "completed" if _merge_success else "failed",
                "success": _merge_success,
                "message": f"merge_status={_final_merge_status}",
            }, ensure_ascii=False)
            redis_client.lpush("plan-runner:merge-results", _merge_result_payload)
            redis_client.expire("plan-runner:merge-results", 86400 * 7)
            logger.info(f"[_do_inline_merge] merge-results push 완료 (runner_id={runner_id}, success={_merge_success})")
        except Exception as _mr_err:
            logger.warning(f"[_do_inline_merge] merge-results push 실패 (무시): {_mr_err}")

        _restart_plan_file = None
        _restart_remaining = 0
        try:
            _restart_plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge")
            if _restart_plan_file:
                # _todo.md 재확인 (플래그 저장 시점과 실행 시점 불일치 방지)
                _restart_plan_file = _resolve_todo_file(_restart_plan_file)
                # remaining 수 재계산 (플래그 설정 시점과 다를 수 있음)
                try:
                    _content = Path(_restart_plan_file).read_text(encoding="utf-8")
                    _restart_remaining = len(re.findall(r'- \[ \]', _content))
                except Exception:
                    _restart_remaining = 1  # 파일 읽기 실패 시 재시작은 허용
                redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge")
                logger.info(f"[_do_inline_merge] 재시작 플래그 확인: plan={_restart_plan_file}, remaining={_restart_remaining}")
        except Exception as e:
            logger.warning(f"[_do_inline_merge] restart_after_merge 플래그 읽기 실패: {e}")

        # 재시작 (cleanup 전에 실행 — cleanup hang 시에도 재시작 보장)
        if _restart_plan_file and _restart_remaining > 0:
            _restart_plan_runner_after_merge(_restart_plan_file, redis_client, _restart_remaining)

        _cleanup_process_state(runner_id, redis_client)
        logger.info(f"[_do_inline_merge] finally 블록 완료 (runner_id={runner_id})")


def _stream_output(process: subprocess.Popen, log_handle, redis_client: redis.Redis, runner_id: str = ""):
    """프로세스 stdout을 라인별로 읽어 파일 기록 + Redis publish 동시 수행

    노이즈 필터:
    - xterm.js: Parsing error 블록 → 파일 기록만, publish 억제
    - node-pty AttachConsole failed 스택트레이스 → 파일 기록만, publish 억제
    - 억제된 줄이 있으면 정상 라인 직전에 요약 1줄 publish
    - rate-limiter: 동일 라인 0.5초 내 10회 이상 반복 시 burst 억제
    """
    suppressed_count = 0
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

            # 5. Quota 에러 감지 → 자동 종료
            if any(marker in stripped for marker in QUOTA_ERROR_MARKERS):
                logger.warning("[DEV-RUNNER] quota 에러 감지, plan-runner 자동 종료")
                try:
                    redis_client.publish(log_channel, "[DEV-RUNNER] quota 에러 감지. 자동 종료.")
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:quota_stopped", "1", ex=3600)
                except redis.ConnectionError:
                    pass
                process.terminate()
                break

            # 6. 정상 라인 publish (ANSI 이스케이프 코드 제거)
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
        except Exception:
            pass
        exit_code = process.returncode
        logger.info(f"Output streaming thread finished (exit code: {exit_code})")
        logger.info(f"[_stream_output] finally 분기 시작 (runner_id={runner_id!r}, exit_code={exit_code})")

        # 이중 큐잉 방지: runner 내부 _publish_merge_request()가 이미 큐잉하므로
        # command-listener에서는 큐잉하지 않음

        # stdout 버퍼 drain: 로그 파일에 기록된 잔여 라인을 publish
        # (process.stdout 루프 종료 후 파일에 기록되었지만 아직 publish되지 않은 내용)
        log_file_path = _running_log_files.get(runner_id) if runner_id else None
        if log_file_path and runner_id:
            log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
            try:
                with open(str(log_file_path), "r", encoding="utf-8", errors="replace") as _drain_f:
                    # 파일 끝으로 이동한 뒤 마지막 2KB만 확인 (종료 직전 로그가 주 대상)
                    _drain_f.seek(0, 2)
                    end_pos = _drain_f.tell()
                    # 최대 8KB 역방향으로 재읽기
                    start_pos = max(0, end_pos - 8192)
                    _drain_f.seek(start_pos)
                    tail_lines = _drain_f.readlines()
                    # 마지막 50줄만 대상
                    for _tail_line in tail_lines[-50:]:
                        _stripped = _tail_line.rstrip('\n')
                        if _stripped:
                            try:
                                redis_client.publish(log_channel, _ANSI_ESCAPE.sub('', _stripped))
                            except redis.ConnectionError:
                                pass
            except Exception as _drain_err:
                logger.debug(f"[_stream_output] stdout drain 실패 (무시): {_drain_err}")

        # merge_requested 플래그 확인 (1회) — 이후 workflow 상태 업데이트 + 분기 모두에 재사용
        _merge_requested = False
        if runner_id:
            try:
                _flag = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested")
                _merge_requested = bool(_flag)
            except Exception as e:
                logger.warning(f"[_stream_output] merge_requested 플래그 조회 실패 (runner_id={runner_id}): {e}")

        # exit_code != 0인 경우: merge_requested가 있어도 커밋 수를 확인해 판정
        if runner_id and _merge_requested and exit_code != 0:
            try:
                branch = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")
                if branch:
                    _git_log = subprocess.run(
                        ["git", "log", f"main..{branch}", "--oneline"],
                        capture_output=True, text=True, cwd=str(PROJECT_ROOT)
                    )
                    commit_lines = [l for l in _git_log.stdout.splitlines() if l.strip()]
                    count = len(commit_lines)
                    if count > 0:
                        logger.info(
                            f"[_stream_output] exit_code={exit_code}이지만 worktree 커밋 {count}개 존재 — merge 시도"
                        )
                    else:
                        _merge_requested = False
                        logger.info(
                            f"[_stream_output] exit_code={exit_code}, worktree 커밋 없음 — merge 스킵"
                        )
                else:
                    _merge_requested = False
                    logger.info(
                        f"[_stream_output] exit_code={exit_code}, branch 정보 없음 — merge 스킵"
                    )
            except Exception as e:
                _merge_requested = False
                logger.warning(f"[_stream_output] exit_code!=0 커밋 수 확인 실패 — merge 스킵: {e}")

        logger.info(
            f"[_stream_output] merge 판정: exit_code={exit_code}, merge_requested={_merge_requested}, runner_id={runner_id}"
        )

        # Workflow 상태 업데이트: 정상 종료(0) → merge_pending or completed, 비정상 → failed
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
                        # exit_code is None: 프로세스가 kill/OOM 등으로 비정상 종료
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
    """plan-runner CLI 실행 (백그라운드 스레드에서 호출 — worktree 생성 포함)

    API는 이미 "accepted"를 받았으므로 여기서는 result_key에 push하지 않음.
    실패 시 runner 상태를 Redis에 기록.
    """
    runner_id = command.get("runner_id")
    _wf_id: Optional[int] = None

    # test_source가 있으면 Redis에 저장 (pytest TC 추적용)
    test_source = command.get("test_source")
    if runner_id and test_source:
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:test_source", test_source)
        except Exception:
            pass

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

    # worktree 생성 또는 재사용 (시간이 걸릴 수 있음)
    try:
        _reused_worktree = False
        if plan_file:
            existing_branch, existing_wt_rel = _parse_plan_worktree_info(plan_file)
            if existing_branch and existing_wt_rel:
                existing_wt_path = PROJECT_ROOT / existing_wt_rel
                if existing_wt_path.is_dir():
                    worktree_path = existing_wt_path
                    branch = existing_branch
                    _reused_worktree = True
                    logger.info(f"기존 워크트리 재사용: {worktree_path} (branch: {branch})")
                else:
                    # 경로 없음 → plan 헤더에서 필드 제거 후 신규 생성
                    _remove_plan_header_fields(plan_file)
                    logger.info(f"워크트리 경로 없음, 신규 생성: {existing_wt_rel}")
        if not _reused_worktree:
            worktree_path, branch = WorktreeManager.create(runner_id, WORKTREE_BASE_DIR, plan_file=plan_file)
            # Phase 4: plan 헤더에 branch/worktree 기록 (수동 /implement와 동일 패턴)
            if plan_file:
                worktree_rel = str(worktree_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
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

    result = _launch_plan_runner_process(command, redis_client, runner_id, worktree_path, plan_file, engine, branch=branch)
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
    """plan-runner CLI 실행 시작 — 즉시 accepted 반환, worktree+프로세스는 백그라운드

    Args:
        command: {action: "run", runner_id: str, plan_file: str, max_cycles: int, ...}
        redis_client: Redis 클라이언트

    Returns:
        dict: {success: bool, message: str} — 즉시 반환 (실제 결과는 per-command key로 전달)
    """
    runner_id = command.get("runner_id")
    if not runner_id:
        return {"success": False, "message": "runner_id required"}

    # 동일 runner_id로 이미 실행 중이면 에러 (stale 프로세스 자동 정리 포함)
    # _running_processes에 없더라도 Redis에 running 상태가 남아있고 PID가 살아있으면 중복 실행 방지
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


def _launch_plan_runner_process(command: Dict, redis_client: redis.Redis, runner_id: str, worktree_path: Path, plan_file: str, engine: str, branch: str = "") -> Dict:
    """plan-runner CLI 프로세스 실행 (worktree 생성 이후 호출)"""

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

    if command.get("pipeline"):
        cmd.extend(["--pipeline", str(command["pipeline"])])

    # 로그 파일 생성
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"plan-runner-{runner_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

    try:
        # subprocess 실행 및 stdout을 PIPE로 받아 스레드에서 파일+Redis 동시 기록
        log_handle = open(log_file, "w", encoding="utf-8")

        # UTF-8 강제
        import os
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env.pop("CLAUDECODE", None)  # 중첩 세션 감지 방지
        env["PLAN_RUNNER_WORK_DIR"] = str(worktree_path)
        env["PLAN_RUNNER_WORKTREE_PATH"] = str(worktree_path)
        env["PLAN_RUNNER_RUNNER_ID"] = runner_id
        env["REDIS_DB"] = str(REDIS_DB)  # 테스트 격리: plan-runner가 동일 DB 사용
        # 로그 prefix 식별자: plan명(날짜 제거, 첫 2단어) + runner_id 앞 4자
        _plan_basename = os.path.splitext(os.path.basename(plan_file or ""))[0]
        _plan_basename = __import__('re').sub(r'^\d{4}-\d{2}-\d{2}[_-]', '', _plan_basename)
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
        # stream_log_path는 executor._open_log() 실행 후 per-runner 키로 갱신됨 (초기엔 빈 값)
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", process.pid)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file or PLAN_FILE_ALL)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch or f"runner/{runner_id}")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", command.get("engine", "claude"))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", str(worktree_path))
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:quota_stopped")
        redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        logger.info(f"plan-runner started (PID: {process.pid}, log: {log_file})")

        # MergeOrchestrator 자동 spawn 제거됨 — 인라인 merge로 대체

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
    """plan-runner 프로세스 종료

    Args:
        runner_id: 종료할 runner의 ID
        redis_client: Redis 클라이언트

    Returns:
        dict: {success: bool, message: str}
    """
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
    """현재 실행 상태 조회 (모든 runner 요약)

    Returns:
        dict: {success: bool, running: bool, runners: list, ...}
    """
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
        _cleanup_process_state(rid, redis_client)

    return {
        "success": True,
        "running": len(running_runners) > 0,
        "runners": running_runners,
        "pid": running_runners[0]["pid"] if running_runners else None,
        "log_file": running_runners[0]["log_file"] if running_runners else None,
    }


def force_stop_plan_runner(runner_id: str, redis_client: redis.Redis) -> Dict:
    """강제 종료 - kill 및 전역 상태 초기화 (리셋용)

    Args:
        runner_id: 강제 종료할 runner의 ID (비어있으면 모든 runner 정리)
        redis_client: Redis 클라이언트

    Returns:
        dict: {success: bool, message: str}
    """
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
    """강제 종료 (SIGKILL) — graceful stop과 달리 즉시 프로세스 사망.

    사용자가 "강제 종료" 버튼을 눌렀을 때 호출된다.
    _DummyProcess(재연결된 프로세스)는 proc.kill()이 없으므로
    Windows API(TerminateProcess)로 직접 종료한다.
    """
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


def _do_retry_merge(runner_id: str, redis_client: redis.Redis, command_id: str, command: Dict | None = None) -> None:
    """retry-merge 실제 작업 (백그라운드 스레드에서 실행) — _do_inline_merge와 동일한 흐름"""
    from merge_lock import acquire_merge_lock, release_merge_lock
    from merge_workflow import MergeWorkflow
    from plan_runner.core.pipeline import pre_merge_gate, auto_commit_stage

    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

    def _pub(msg: str) -> None:
        logger.info(f"[RETRY-MERGE] {msg}")
        try:
            redis_client.publish(log_channel, f"[MERGE] {msg}")
        except Exception:
            pass

    result = {"success": False, "message": "unknown error", "action": "retry-merge"}
    try:
        worktree_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
        # Redis 키 만료 시 command payload로 재발급
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

        worktree_path = Path(worktree_path_str)
        if not worktree_path.is_dir():
            result = {"success": False, "message": f"worktree dir not found: {worktree_path_str}", "action": "retry-merge"}
            return

        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        if plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
            plan_file = None
        plan_file = _resolve_todo_file(plan_file)

        # 1. merge_status = "queued" + lock 대기
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "queued")
        except Exception:
            pass
        _pub("merge lock 대기 중...")

        lock_acquired = acquire_merge_lock(redis_client, runner_id, timeout=600)
        if not lock_acquired:
            _pub("merge lock 획득 실패 (timeout) — merge 중단")
            try:
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
            except Exception:
                pass
            result = {"success": False, "message": "merge lock 획득 실패 (timeout)", "action": "retry-merge"}
            return

        # 2. lock 획득 후 merge 실행
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merging")
        except Exception:
            pass
        _pub("merge lock 획득 완료 — merge 시작")

        # 2-1. pre_merge_gate: main 브랜치 확인 + git clean 확인
        # 이미 lock을 획득했으므로 "다른 머지" 메시지는 무시 (lock already held)
        gate_ok, gate_msg = pre_merge_gate(PROJECT_ROOT, redis_client)
        if not gate_ok:
            if "다른 머지" in gate_msg:
                # lock이 이미 우리가 획득함 — 정상 (pre_merge_gate 내부에서 lock 재획득 실패한 것)
                _pub("[pre-merge] lock already held — proceeding")
            elif "dirty" in gate_msg:
                # dirty 상태 — 안전망 커밋 후 gate 재검사 (최대 3회)
                for attempt in range(3):
                    _pub(f"[pre-merge] dirty 감지 — 안전망 커밋 시도 ({attempt + 1}/3): {gate_msg}")
                    committed = auto_commit_stage(PROJECT_ROOT, "chore: pre-merge safety commit")
                    _pub(f"[pre-merge] 안전망 커밋 결과: {'성공' if committed else '변경없음/실패'}")
                    gate_ok, gate_msg = pre_merge_gate(PROJECT_ROOT, redis_client)
                    if gate_ok or "dirty" not in gate_msg:
                        # 성공하거나 dirty 외 다른 이유 실패 시 루프 중단
                        break
                if not gate_ok:
                    _pub(f"[pre-merge] gate 실패 (3회 재시도 후): {gate_msg}")
                    result = {"success": False, "message": f"pre-merge gate 실패: {gate_msg}", "action": "retry-merge"}
                    try:
                        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
                    except Exception:
                        pass
                    release_merge_lock(redis_client, runner_id)
                    return
            else:
                # main 브랜치 아님 등 기타 실패
                _pub(f"[pre-merge] gate 실패: {gate_msg}")
                result = {"success": False, "message": f"pre-merge gate 실패: {gate_msg}", "action": "retry-merge"}
                try:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
                except Exception:
                    pass
                release_merge_lock(redis_client, runner_id)
                return

        try:
            workflow = MergeWorkflow(
                project_root=PROJECT_ROOT,
                redis_client=redis_client,
                workflow_manager=_wf_manager,
            )
            merge_result = workflow.run(
                runner_id=runner_id,
                worktree_path=worktree_path,
                base_dir=WORKTREE_BASE_DIR,
                plan_file=plan_file,
            )

            # 3. 결과 처리
            if merge_result.merged and merge_result.tests_passed:
                _pub("merge 성공 — 완료")
                try:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
                except Exception:
                    pass
                result = {"success": True, "message": merge_result.message, "action": "retry-merge"}
            elif merge_result.conflict:
                _pub(f"merge 충돌 발생 — worktree 보존: {merge_result.message[:200]}")
                try:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "conflict")
                except Exception:
                    pass
                result = {"success": False, "message": merge_result.message, "conflict": True, "action": "retry-merge"}
            elif merge_result.merged and not merge_result.tests_passed:
                _pub(f"merge 후 테스트 실패 — worktree 보존: {merge_result.message[:200]}")
                try:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "test_failed")
                except Exception:
                    pass
                result = {"success": False, "message": merge_result.message, "action": "retry-merge"}
            else:
                _pub(f"merge 실패: {merge_result.message[:200]}")
                try:
                    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
                except Exception:
                    pass
                result = {"success": False, "message": merge_result.message, "action": "retry-merge"}

        finally:
            release_merge_lock(redis_client, runner_id)

    except Exception as e:
        logger.error(f"[retry_merge] 실패: {e}")
        try:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error")
        except Exception:
            pass
        try:
            release_merge_lock(redis_client, runner_id)
        except Exception:
            pass
        result = {"success": False, "message": str(e), "action": "retry-merge"}

    finally:
        _cleanup_process_state(runner_id, redis_client)
        redis_client.lpush(result_key, json.dumps(result, ensure_ascii=False))
        redis_client.expire(result_key, 60)

        # [Phase 4-10] merge-results Redis list에 결과 push (merge history API 용)
        try:
            _final_merge_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            _merge_success = _final_merge_status == "merged"
            _plan_file_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
            _branch_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")
            _merge_result_payload = json.dumps({
                "runner_id": runner_id,
                "branch": _branch_val,
                "plan_file": _plan_file_val,
                "timestamp": datetime.now().isoformat(),
                "status": "completed" if _merge_success else "failed",
                "success": _merge_success,
                "message": f"merge_status={_final_merge_status}",
            }, ensure_ascii=False)
            redis_client.lpush("plan-runner:merge-results", _merge_result_payload)
            redis_client.expire("plan-runner:merge-results", 86400 * 7)
            logger.info(f"[_do_retry_merge] merge-results push 완료 (runner_id={runner_id}, success={_merge_success})")
        except Exception as _mr_err:
            logger.warning(f"[_do_retry_merge] merge-results push 실패 (무시): {_mr_err}")


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


def _do_direct_merge(branch: str, worktree_path_str: str | None, plan_file: str | None, redis_client: redis.Redis, command_id: str) -> None:
    """direct-merge 실제 작업 (백그라운드 스레드에서 실행) — 임시 runner_id로 _do_inline_merge 호출"""
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    from uuid import uuid4

    runner_id = f"dm-{uuid4().hex[:8]}"
    result = {"success": False, "message": "unknown error", "action": "direct-merge", "runner_id": runner_id}
    logger.info(f"[direct_merge] _do_direct_merge 스레드 진입: runner_id={runner_id}, branch={branch}, worktree={worktree_path_str}")

    try:
        # worktree_path 결정
        if worktree_path_str:
            worktree_path = Path(worktree_path_str).resolve()
        else:
            # branch 이름으로 추론 (runner/{id} → runner_{id} 변환)
            branch_slug = branch.replace("/", "_")
            worktree_path = WORKTREE_BASE_DIR / branch_slug
            if not worktree_path.is_dir():
                # git worktree list --porcelain 으로 branch 매칭
                proc = subprocess.run(
                    ["git", "worktree", "list", "--porcelain"],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT)
                )
                worktree_path_str = None
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
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "queued")
        if plan_file:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
        # TTL 설정 (24시간)
        for suffix in ("status", "worktree_path", "branch", "start_time", "merge_status", "plan_file"):
            redis_client.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", RECENT_RUNNERS_TTL)
        # SSE가 감지하도록 active_runners 등록
        redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        logger.info(f"[direct_merge] 임시 runner {runner_id} 생성, branch={branch}, worktree={worktree_path}")

        # _do_inline_merge 호출 (lock+cleanup+로그 발행 포함)
        _do_inline_merge(runner_id, redis_client)

        # 머지 결과 읽기
        final_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status") or "unknown"
        success = final_status == "merged"
        result = {
            "success": success,
            "message": f"direct-merge 완료: {final_status}",
            "merge_status": final_status,
            "action": "direct-merge",
            "runner_id": runner_id,
        }

    except Exception as e:
        import traceback
        logger.error(f"[direct_merge] 실패: {e}\n{traceback.format_exc()}")
        result = {"success": False, "message": str(e), "action": "direct-merge", "runner_id": runner_id}
    finally:
        # merge_status Redis 키 보장 (스레드 실패 시에도 상태 추적 가능)
        try:
            current_ms = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            if current_ms and current_ms not in ("merged", "conflict", "test_failed"):
                final_ms = "error" if not result.get("success") else current_ms
                redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", final_ms)
                redis_client.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", RECENT_RUNNERS_TTL)
        except Exception:
            pass
        # SSE 채널에 최종 결과 publish
        try:
            log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
            status_msg = result.get("message", "unknown")
            redis_client.publish(log_channel, f"[MERGE] direct-merge 최종 결과: {status_msg}")
        except Exception:
            pass
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
        args=(branch, worktree_path, plan_file, redis_client, command_id),
        daemon=False,
    )
    thread.start()
    return None


def _do_resolve_conflict(runner_id: str, redis_client: redis.Redis, command_id: str) -> None:
    """resolve-conflict 실제 작업 (백그라운드 스레드에서 실행).
    plan-runner resolve 서브커맨드를 통해 auto-conflict-resolver 에이전트를 실행한다.
    """
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    try:
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

        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "resolving")

        resolve_result = _launch_conflict_resolver_process(
            runner_id, branch, Path(worktree_path_str), redis_client
        )

        if resolve_result["success"]:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
            result = {"success": True, "message": "충돌 자동 해결 완료", "action": "resolve-conflict"}
        else:
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "conflict")
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
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    try:
        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        # PLAN_FILE_ALL/__ALL_PLANS__은 parallel 모드 sentinel이므로 plan_file로 취급하지 않음
        if plan_file in (PLAN_FILE_ALL, _LEGACY_ALL):
            plan_file = None
        WorktreeManager.remove(runner_id, WORKTREE_BASE_DIR, plan_file=plan_file or None)
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
# Phase 3에서 제거됨. stop_merge_orchestrator는 API 라우트 호환성 유지용으로 잠시 보존.
def start_merge_orchestrator(redis_client: redis.Redis) -> Dict:
    """[DEPRECATED] merge 로직이 _stream_output finally 블록으로 인라인화됨."""
    return {"success": False, "message": "Deprecated: merge is now handled inline in _stream_output"}


def _reconnect_surviving_merge_orchestrator(redis_client: redis.Redis):
    """[DEPRECATED] MergeOrchestrator 제거됨 — 아무것도 하지 않음."""
    pass


def stop_merge_orchestrator(redis_client: redis.Redis) -> Dict:
    """[DEPRECATED] MergeOrchestrator 제거됨 — 인라인 merge로 대체. 호환성 유지용."""
    return {"success": False, "message": "Deprecated: MergeOrchestrator removed, merge is now inline"}


def execute_command(command: Dict, redis_client: redis.Redis) -> Dict:
    """명령 실행

    Args:
        command: {action: str, ...}
        redis_client: Redis 클라이언트

    Returns:
        dict: {success: bool, message: str, ...}
    """
    action = command.get("action")

    if action == "run":
        return start_plan_runner(command, redis_client)
    elif action == "stop":
        runner_id = command.get("runner_id", "")
        return stop_plan_runner(runner_id, redis_client)
    elif action == "force-stop":
        runner_id = command.get("runner_id", "")
        return force_stop_plan_runner(runner_id, redis_client)
    elif action == "force-kill":
        runner_id = command.get("runner_id", "")
        return force_kill_plan_runner(runner_id, redis_client)
    elif action == "status":
        return get_status(redis_client)
    elif action == "retry-merge":
        return retry_merge(command, redis_client)
    elif action == "direct-merge":
        return direct_merge(command, redis_client)
    elif action == "resolve-conflict":
        return resolve_conflict(command, redis_client)
    elif action == "cleanup-worktree":
        return cleanup_worktree(command, redis_client)
    elif action == "start-orchestrator":
        return start_merge_orchestrator(redis_client)
    elif action == "stop-orchestrator":
        return stop_merge_orchestrator(redis_client)
    else:
        return {"success": False, "message": f"Unknown action: {action}"}


def main():
    """메인 루프: Redis BRPOP으로 명령 대기 및 실행."""
    if not _acquire_lock():
        logger.error("다른 listener 인스턴스가 이미 실행 중 — 중복 실행 방지로 종료")
        sys.exit(1)

    global _merge_orchestrator_process, _wf_manager, _merge_orchestrator_attached_pid
    _wf_manager = WorkflowManager(PROJECT_ROOT / "data" / "monitor.db")
    logger.info("=" * 50)
    logger.info("Dev Runner Command Listener 시작")
    logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info(f"명령 큐: {COMMANDS_KEY}")
    logger.info(f"결과 큐: {RESULTS_KEY}")
    logger.info(f"Runner Key Prefix: {RUNNER_KEY_PREFIX}")
    logger.info(f"plan-runner 모듈: {PLAN_RUNNER_MODULE_PATH}")
    logger.info("=" * 50)

    reconnect_delay = 1

    while True:
        try:
            # Redis 연결
            r = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
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
            _reconnect_surviving_runners(r)
            # listener 시작/재시작 시 DB↔Redis 교차검증으로 고아 워크플로우 탐지
            orphan_wf_count = _detect_orphan_workflows(r)
            orphan_plan_count = _detect_orphan_plans(r)
            if orphan_wf_count or orphan_plan_count:
                logger.warning(f"[orphan] 고아 탐지 완료: workflow {orphan_wf_count}개 정리, plan {orphan_plan_count}개 경고")
            # listener 시작/재시작 시 생존 MergeOrchestrator 재연결
            _reconnect_surviving_merge_orchestrator(r)

            # Redis 재연결 시 현재 프로세스 상태 복원
            # (Redis 캐시 등으로 데이터가 날아갈 경우 status: running 복원)
            for rid, proc in list(_running_processes.items()):
                if proc.poll() is None and _is_pid_alive(proc.pid):
                    r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
                    r.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", proc.pid)
                    r.sadd(ACTIVE_RUNNERS_KEY, rid)
                    logger.info(f"Redis 재연결: 프로세스 상태 복원 (runner_id: {rid}, PID: {proc.pid})")

            # merge-queue 기반 orchestrator 자동 시작 제거됨 — 인라인 merge로 대체

            # BRPOP 루프 (블로킹 대기)
            while True:
                # heartbeat 갱신
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    r.set(HEARTBEAT_KEY, datetime.now().isoformat(), ex=HEARTBEAT_TTL)
                    # 각 runner 상태 동기화
                    # (Redis 키 만료 또는 재시작으로 날아갈 경우 10초마다 복원)
                    for rid, proc in list(_running_processes.items()):
                        if proc.poll() is None:
                            current_status = r.get(f"{RUNNER_KEY_PREFIX}:{rid}:status")
                            if current_status not in (None, "stopped") and current_status != "running":
                                r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
                                r.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", proc.pid)
                                r.sadd(ACTIVE_RUNNERS_KEY, rid)
                                logger.info(f"heartbeat: Redis 상태 복원 (runner_id: {rid}, PID: {proc.pid})")
                        else:
                            # 프로세스가 종료되었는데 전역변수가 남아있는 경우 — 머지 진행 중 여부 확인 후 cleanup
                            try:
                                _hb_mr = r.get(f"{RUNNER_KEY_PREFIX}:{rid}:merge_requested")
                                _hb_ms = r.get(f"{RUNNER_KEY_PREFIX}:{rid}:merge_status")
                            except Exception:
                                _hb_mr, _hb_ms = None, None
                            if _hb_mr or _hb_ms in ("queued", "merging", "pending_merge"):
                                logger.info(
                                    f"heartbeat: runner {rid} 프로세스 종료 but 머지 진행중 "
                                    f"(merge_requested={bool(_hb_mr)}, merge_status={_hb_ms}) → cleanup 스킵"
                                )
                            else:
                                logger.warning(f"heartbeat: 프로세스 종료 감지 (runner_id: {rid}, exit code: {proc.returncode}), 상태 정리")
                                _cleanup_process_state(rid, r, reason="heartbeat_dead_process")
                    # MergeOrchestrator health check 제거됨 — 인라인 merge로 대체

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
    REDIS_DB = args.redis_db
    main()