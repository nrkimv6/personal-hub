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

# 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0  # --redis-db 인자로 오버라이드 가능 (테스트 격리용)
COMMANDS_KEY = "plan-runner:commands"
RESULTS_KEY = "plan-runner:command_results"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
HEARTBEAT_INTERVAL = 10  # heartbeat 갱신 주기 (초)
HEARTBEAT_TTL = 30  # heartbeat 만료 시간 (초, 3회 미갱신 시 만료)

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

# 전역 프로세스 관리
_running_processes: dict = {}
_running_log_files: dict = {}
_stream_threads: dict = {}
_merge_orchestrator_process: Optional[subprocess.Popen] = None
_merge_orchestrator_log_path: Optional[Path] = None
_merge_orchestrator_attached_pid: Optional[int] = None  # listener 재시작 후 재연결된 PID (Popen 없이 관리)

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


def _poll_merge_results(redis_client: redis.Redis):
    """plan-runner:merge-results 큐에서 MergeOrchestrator 결과를 소비하여 Workflow DB에 반영"""
    if not _wf_manager:
        return
    while True:
        try:
            raw = redis_client.lpop("plan-runner:merge-results")
            if raw is None:
                break
            try:
                result = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"[_poll_merge_results] JSON 파싱 실패 (무시): {raw!r:.200}")
                continue
            runner_id = result.get("runner_id")
            if not runner_id:
                continue
            wf = _wf_manager.get_by_runner_id(runner_id)
            if not wf or wf["status"] != "merge_pending":
                continue
            if result.get("success"):
                _wf_manager.update_status(wf["id"], "merged")
                logger.info(f"[_poll_merge_results] workflow {wf['id']} → merged (runner: {runner_id})")
            else:
                _wf_manager.update_status(
                    wf["id"], "failed",
                    error_message=result.get("message", "merge failed")[:500],
                )
                logger.info(f"[_poll_merge_results] workflow {wf['id']} → failed (runner: {runner_id})")
        except Exception as e:
            logger.warning(f"[_poll_merge_results] 처리 오류 (무시): {e}")
            break


def _cleanup_process_state(runner_id: str, redis_client: redis.Redis, reason: str = "process_cleanup"):
    """전역 프로세스 변수 + Redis 상태 정리 (per-runner) + Workflow DB 갱신"""
    global _running_processes, _running_log_files, _stream_threads

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
        if t.is_alive():
            t.join(timeout=3)

    try:
        # worktree 정리 (머지 완료 또는 실패로 정리 필요한 경우)
        merge_status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        # merge_status가 없거나 "merged"가 아닌 경우에만 worktree 정리 시도
        # (머지 워크플로가 별도로 관리하는 경우 스킵)
        if merge_status not in ("pending_merge", "conflict", "queued"):
            try:
                plan_file_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
                if plan_file_val == "ALL":
                    plan_file_val = None
                WorktreeManager.remove(runner_id, WORKTREE_BASE_DIR, plan_file=plan_file_val or None)
            except Exception as wt_e:
                logger.warning(f"worktree 정리 실패 (runner_id: {runner_id}): {wt_e}")
        elif merge_status in ("merging", "testing"):
            # 프로세스가 죽은 상태에서 중간 상태로 남은 경우 — stale worktree 정리
            try:
                plan_file_val = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
                if plan_file_val == "ALL":
                    plan_file_val = None
                WorktreeManager.remove(runner_id, WORKTREE_BASE_DIR, plan_file=plan_file_val or None)
                logger.info(f"stale 중간 상태 worktree 정리: {runner_id} (merge_status={merge_status})")
            except Exception as wt_e:
                logger.warning(f"stale worktree 정리 실패 (runner_id: {runner_id}): {wt_e}")

        redis_client.delete(
            f"{RUNNER_KEY_PREFIX}:{runner_id}:status",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:pid",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:engine",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path",
        )
        redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
    except Exception:
        pass

    # Workflow DB: running 상태인 경우 failed로 전이
    try:
        if _wf_manager:
            wf = _wf_manager.get_by_runner_id(runner_id)
            if wf and wf["status"] == "running":
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
                logger.info(f"[reconnect] orphan {orphan_id} PID {pid} 종료됨 → cleanup")
                _cleanup_process_state(orphan_id, redis_client, reason="reconnect_orphan_scan")
    except Exception as e:
        logger.warning(f"[reconnect] orphan scan 실패: {e}")


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

        # Workflow 상태 업데이트: 정상 종료(0) → merge_pending, 비정상 → failed
        if _wf_manager and runner_id:
            try:
                wf = _wf_manager.get_by_runner_id(runner_id)
                if wf:
                    if exit_code == 0:
                        # merge-queue에 올라갈 것이므로 merge_pending
                        _wf_manager.update_status(wf["id"], "merge_pending")
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

        _cleanup_process_state(runner_id, redis_client)


def _do_start_plan_runner(command: Dict, redis_client: redis.Redis):
    """plan-runner CLI 실행 (백그라운드 스레드에서 호출 — worktree 생성 포함)

    API는 이미 "accepted"를 받았으므로 여기서는 result_key에 push하지 않음.
    실패 시 runner 상태를 Redis에 기록.
    """
    runner_id = command.get("runner_id")
    _wf_id: Optional[int] = None

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

    # worktree 생성 (시간이 걸릴 수 있음)
    try:
        worktree_path, branch = WorktreeManager.create(runner_id, WORKTREE_BASE_DIR, plan_file=plan_file)
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
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file or "ALL")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch or f"runner/{runner_id}")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", command.get("engine", "claude"))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", str(worktree_path))
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:quota_stopped")
        redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        logger.info(f"plan-runner started (PID: {process.pid}, log: {log_file})")

        # orchestrator가 미실행이면 항상 자동 spawn
        if not _merge_orchestrator_process or _merge_orchestrator_process.poll() is not None:
            orch_result = start_merge_orchestrator(redis_client)
            logger.info(f"Merge Orchestrator 자동 시작: {orch_result.get('message', '')}")

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


def _do_retry_merge(runner_id: str, redis_client: redis.Redis, command_id: str) -> None:
    """retry-merge 실제 작업 (백그라운드 스레드에서 실행)"""
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    try:
        worktree_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
        if not worktree_path_str:
            result = {"success": False, "message": f"worktree_path not found for runner {runner_id}"}
            redis_client.lpush(result_key, json.dumps(result, ensure_ascii=False))
            redis_client.expire(result_key, 60)
            return
        from merge_workflow import MergeWorkflow
        worktree_path = Path(worktree_path_str)
        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        if plan_file == "ALL":
            plan_file = None
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "pending_merge")
        wf = MergeWorkflow(PROJECT_ROOT, redis_client, str(PLAN_RUNNER_PYTHON), workflow_manager=_wf_manager)
        merge_result = wf.run(runner_id, worktree_path, WORKTREE_BASE_DIR, plan_file=plan_file)
        logger.info(f"[retry_merge] 결과: merged={merge_result.merged}, conflict={merge_result.conflict}, message={merge_result.message[:200]}")
        result = {"success": merge_result.merged, "message": merge_result.message, "conflict": merge_result.conflict, "action": "retry-merge"}
    except Exception as e:
        logger.error(f"[retry_merge] 실패: {e}")
        result = {"success": False, "message": str(e), "action": "retry-merge"}
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
        args=(runner_id, redis_client, command_id),
        daemon=True,
    )
    thread.start()
    return None


def _do_resolve_conflict(runner_id: str, redis_client: redis.Redis, command_id: str) -> None:
    """resolve-conflict 실제 작업 (백그라운드 스레드에서 실행)"""
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    try:
        worktree_path_str = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
        if not worktree_path_str:
            result = {"success": False, "message": f"worktree_path not found for runner {runner_id}"}
            redis_client.lpush(result_key, json.dumps(result, ensure_ascii=False))
            redis_client.expire(result_key, 60)
            return
        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        if plan_file == "ALL":
            plan_file = None
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "resolving")
        from conflict_resolver import ConflictResolver
        resolver = ConflictResolver(PROJECT_ROOT, redis_client)
        # 이전 충돌 상태 정리 (실패 무시)
        subprocess.run(["git", "merge", "--abort"], capture_output=True, cwd=str(PROJECT_ROOT))
        # branch 계산
        if plan_file:
            branch = f"plan/{Path(plan_file).stem}"
        else:
            branch = f"runner/{runner_id}"
        # 충돌 상태 재현
        subprocess.run(
            ["git", "merge", branch, "--no-ff"],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
        )
        resolve_result = resolver.try_resolve(runner_id, branch)
        if resolve_result.success:
            commit_proc = subprocess.run(
                ["git", "commit", "--no-edit", "-m", f"merge: {branch} (auto-resolved)"],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
            )
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
            result = {"success": True, "message": "충돌 자동 해결 완료", "action": "resolve-conflict"}
        else:
            subprocess.run(["git", "merge", "--abort"], capture_output=True, cwd=str(PROJECT_ROOT))
            redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "conflict")
            result = {"success": False, "reason": resolve_result.reason, "action": "resolve-conflict"}
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
        daemon=True,
    )
    thread.start()
    return None


def _do_cleanup_worktree(runner_id: str, redis_client: redis.Redis, command_id: str) -> None:
    """cleanup-worktree 실제 작업 (백그라운드 스레드에서 실행)"""
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    try:
        plan_file = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        # "ALL"은 parallel 모드 placeholder이므로 plan_file로 취급하지 않음
        if plan_file == "ALL":
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
        daemon=True,
    )
    thread.start()
    return None


def start_merge_orchestrator(redis_client: redis.Redis) -> Dict:
    """plan-runner merge-orchestrator 프로세스 시작"""
    global _merge_orchestrator_process, _merge_orchestrator_log_path, _merge_orchestrator_attached_pid
    if _merge_orchestrator_process and _merge_orchestrator_process.poll() is None:
        return {"success": False, "message": f"이미 실행 중 (PID: {_merge_orchestrator_process.pid})"}
    # listener 재시작 후 재연결된 고아 프로세스가 살아있으면 중복 시작 방지
    if _merge_orchestrator_attached_pid and _is_pid_alive(_merge_orchestrator_attached_pid):
        return {"success": False, "message": f"이미 실행 중 (재연결 PID: {_merge_orchestrator_attached_pid})"}

    try:
        cmd = [str(PLAN_RUNNER_PYTHON), "-m", "plan_runner", "merge-orchestrator"]
        LOGS_DIR = PROJECT_ROOT / "logs" / "admin"
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime as _dt
        _ts = _dt.now().strftime('%Y%m%d_%H%M%S')
        log_path = LOGS_DIR / f"merge-orchestrator_{_ts}.log"
        log_file = open(str(log_path), "w", encoding="utf-8")
        _merge_orchestrator_log_path = log_path
        import os as _os
        env = _os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        _merge_orchestrator_process = subprocess.Popen(
            cmd, stdout=log_file, stderr=log_file,
            cwd=str(PLAN_RUNNER_MODULE_PATH), env=env
        )
        pid = _merge_orchestrator_process.pid
        logger.info(f"Merge Orchestrator 시작 (PID: {pid}, log: {log_path})")

        # 2초 대기 후 생존 확인
        time.sleep(2)
        rc = _merge_orchestrator_process.poll()
        if rc is not None:
            # 즉시 종료됨 — 로그 파일 내용 읽어서 원인 보고
            log_file.close()
            try:
                content = log_path.read_text(encoding="utf-8").strip()
            except Exception:
                content = "(로그 파일 읽기 실패)"
            log_tail = content[-500:] if len(content) > 500 else content
            logger.error(f"[MergeOrch] 즉시 종료 (PID: {pid}, exit code: {rc})")
            if log_tail:
                logger.error(f"[MergeOrch] 로그 내용:\n{log_tail}")
            else:
                logger.error("[MergeOrch] 로그 파일 비어있음 — 프로세스 시작 자체 실패")
            _merge_orchestrator_process = None
            return {"success": False, "message": f"Orchestrator 즉시 종료 (exit code: {rc}): {log_tail[:200]}"}

        # PID를 Redis에 저장 (listener 재시작 시 재연결용)
        redis_client.set("plan-runner:merge-orchestrator:pid", pid)
        return {"success": True, "message": f"Orchestrator 시작 (PID: {pid})"}
    except Exception as e:
        logger.error(f"Merge Orchestrator 시작 실패: {e}")
        return {"success": False, "message": str(e)}


def _reconnect_surviving_merge_orchestrator(redis_client: redis.Redis):
    """listener 시작(또는 재시작) 시 기존 MergeOrchestrator 프로세스 재연결.

    Redis에 저장된 PID를 확인하여:
    - PID가 살아있으면 → _merge_orchestrator_attached_pid에 기록 (중복 시작 방지)
    - PID가 죽어있으면 → Redis 키 정리
    """
    global _merge_orchestrator_attached_pid
    pid_str = redis_client.get("plan-runner:merge-orchestrator:pid")
    if not pid_str:
        return
    try:
        pid = int(pid_str)
    except (ValueError, TypeError):
        redis_client.delete("plan-runner:merge-orchestrator:pid")
        return

    if _is_pid_alive(pid):
        _merge_orchestrator_attached_pid = pid
        logger.info(f"[MergeOrch] 기존 프로세스 재연결 (PID: {pid})")
    else:
        logger.info(f"[MergeOrch] 기존 프로세스 종료됨 (PID: {pid}) → Redis 정리")
        redis_client.delete("plan-runner:merge-orchestrator:pid")


def stop_merge_orchestrator(redis_client: redis.Redis) -> Dict:
    """plan-runner merge-orchestrator 프로세스 종료"""
    global _merge_orchestrator_process, _merge_orchestrator_attached_pid
    # 재연결된 고아 프로세스 종료
    if _merge_orchestrator_attached_pid and _is_pid_alive(_merge_orchestrator_attached_pid):
        import ctypes
        try:
            kernel32 = ctypes.windll.kernel32
            PROCESS_TERMINATE = 0x0001
            handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, _merge_orchestrator_attached_pid)
            if handle:
                kernel32.TerminateProcess(handle, 0)
                kernel32.CloseHandle(handle)
                logger.info(f"Merge Orchestrator (재연결 PID: {_merge_orchestrator_attached_pid}) 종료")
        except Exception as e:
            logger.error(f"재연결 Orchestrator 종료 실패: {e}")
        _merge_orchestrator_attached_pid = None
        redis_client.delete("plan-runner:merge-orchestrator:pid")
        return {"success": True, "message": f"Orchestrator (재연결) 종료"}
    if not _merge_orchestrator_process or _merge_orchestrator_process.poll() is not None:
        return {"success": False, "message": "Orchestrator가 실행 중이 아님"}
    try:
        _merge_orchestrator_process.terminate()
        _merge_orchestrator_process.wait(timeout=5)
        logger.info("Merge Orchestrator 종료")
        _merge_orchestrator_process = None
        redis_client.delete("plan-runner:merge-orchestrator:pid")
        return {"success": True, "message": "Orchestrator 종료"}
    except Exception as e:
        logger.error(f"Merge Orchestrator 종료 실패: {e}")
        return {"success": False, "message": str(e)}


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

            # 시작/재시작 시 pending 머지 큐가 있으면 orchestrator 자동 시작
            pending_count = r.llen("plan-runner:merge-queue")
            if pending_count > 0:
                logger.info(f"[MergeQueue] pending 항목 {pending_count}개 감지 → Orchestrator 자동 시작")
                start_merge_orchestrator(r)

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
                            # 프로세스가 종료되었는데 전역변수가 남아있는 경우 즉시 cleanup
                            logger.warning(f"heartbeat: 프로세스 종료 감지 (runner_id: {rid}, exit code: {proc.returncode}), 상태 정리")
                            _cleanup_process_state(rid, r, reason="heartbeat_dead_process")
                    # Orchestrator health check
                    if _merge_orchestrator_process and _merge_orchestrator_process.poll() is not None:
                        rc = _merge_orchestrator_process.returncode
                        logger.warning(f"[MergeOrch] 비정상 종료 감지 (exit code: {rc})")
                        if _merge_orchestrator_log_path and _merge_orchestrator_log_path.exists():
                            try:
                                lines = _merge_orchestrator_log_path.read_text(encoding="utf-8").strip().splitlines()
                                tail = lines[-5:] if len(lines) > 5 else lines
                                if tail:
                                    logger.warning(f"[MergeOrch] 마지막 로그:\n" + "\n".join(tail))
                            except Exception:
                                pass
                        _merge_orchestrator_process = None
                        r.delete("plan-runner:merge-orchestrator:pid")
                    # 재연결 PID 생존 확인
                    if _merge_orchestrator_attached_pid and not _is_pid_alive(_merge_orchestrator_attached_pid):
                        logger.warning(f"[MergeOrch] 재연결 PID {_merge_orchestrator_attached_pid} 종료 감지 → 정리")
                        _merge_orchestrator_attached_pid = None
                        r.delete("plan-runner:merge-orchestrator:pid")

                    # merge-results 큐 소비 → Workflow DB 업데이트
                    _poll_merge_results(r)

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