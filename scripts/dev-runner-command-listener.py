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

# 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
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
WTOOLS_BASE_DIR = Path("D:/work/project/service/wtools")
PLAN_RUNNER_MODULE_PATH = WTOOLS_BASE_DIR / "common/tools/plan-runner"
PLAN_RUNNER_PYTHON = PLAN_RUNNER_MODULE_PATH / ".venv/Scripts/python.exe"
LOG_DIR = WTOOLS_BASE_DIR / "common/logs"

# 로깅 설정
log_dir = PROJECT_ROOT / "logs" / "dev"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "dev_runner_command_listener.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

LOG_CHANNEL_PREFIX = "plan-runner:logs"

# 전역 프로세스 관리
_running_processes: dict = {}
_running_log_files: dict = {}
_stream_threads: dict = {}


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


def _cleanup_process_state(runner_id: str, redis_client: redis.Redis):
    """전역 프로세스 변수 + Redis 상태 정리 (per-runner)"""
    global _running_processes, _running_log_files, _stream_threads

    _running_processes.pop(runner_id, None)
    _running_log_files.pop(runner_id, None)
    if runner_id in _stream_threads:
        t = _stream_threads.pop(runner_id)
        if t.is_alive():
            t.join(timeout=3)

    try:
        redis_client.delete(
            f"{RUNNER_KEY_PREFIX}:{runner_id}:status",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:pid",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path",
            f"{RUNNER_KEY_PREFIX}:{runner_id}:engine",
        )
        redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
    except Exception:
        pass


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
        logger.info(f"Output streaming thread finished (exit code: {process.returncode})")
        _cleanup_process_state(runner_id, redis_client)


def start_plan_runner(command: Dict, redis_client: redis.Redis) -> Dict:
    """plan-runner CLI 실행 시작

    Args:
        command: {action: "run", runner_id: str, plan_file: str, max_cycles: int, ...}
        redis_client: Redis 클라이언트

    Returns:
        dict: {success: bool, message: str, pid: int|None, log_file: str|None}
    """
    runner_id = command.get("runner_id")
    if not runner_id:
        return {"success": False, "message": "runner_id required"}

    # 동일 runner_id로 이미 실행 중이면 에러 (stale 프로세스 자동 정리 포함)
    proc = _running_processes.get(runner_id)
    if proc and proc.poll() is None:
        if not _is_pid_alive(proc.pid):
            # OS 레벨에서 죽은 프로세스 면 자동 정리
            logger.warning(f"Stale process detected (PID: {proc.pid}), cleaning up")
            _cleanup_process_state(runner_id, redis_client)
        else:
            return {
                "success": False,
                "message": f"Already running (PID: {proc.pid})"
            }
    elif proc and proc.poll() is not None:
        # 종료되었지만 정리 안 된 경우
        logger.info(f"Previous process ended (exit code: {proc.returncode}), cleaning up")
        _cleanup_process_state(runner_id, redis_client)

    # 명령어 구성
    plan_file = command.get("plan_file")
    engine = command.get("engine")
    is_parallel = command.get("parallel", False)
    if not plan_file and not is_parallel:
        return {"success": False, "message": "plan_file required (use parallel mode for batch execution)"}

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

    # 로그 파일 생성
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"plan-runner-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

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
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path", str(log_file))
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", process.pid)
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file or "ALL")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", command.get("engine", "claude"))
        redis_client.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:quota_stopped")
        redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)

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
    elif action == "status":
        return get_status(redis_client)
    else:
        return {"success": False, "message": f"Unknown action: {action}"}


def main():
    """메인 루프: Redis BRPOP으로 명령 대기 및 실행."""
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
                decode_responses=True,
                socket_connect_timeout=5,
            )
            r.ping()
            logger.info("Redis 연결 성공")
            reconnect_delay = 1  # 연결 성공 시 리셋

            # 초기 heartbeat 설정 (시작 즉시 한 번 찍음)
            r.set(HEARTBEAT_KEY, datetime.now().isoformat(), ex=HEARTBEAT_TTL)
            last_heartbeat = time.time()

            # Redis 재연결 시 현재 프로세스 상태 복원
            # (Redis 캐시 등으로 데이터가 날아갈 경우 status: running 복원)
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
                    # 각 runner 상태 동기화
                    # (Redis 키 만료 또는 재시작으로 날아갈 경우 10초마다 복원)
                    for rid, proc in list(_running_processes.items()):
                        if proc.poll() is None:
                            if r.get(f"{RUNNER_KEY_PREFIX}:{rid}:status") != "running":
                                r.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
                                r.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", proc.pid)
                                r.sadd(ACTIVE_RUNNERS_KEY, rid)
                                logger.info(f"heartbeat: Redis 상태 복원 (runner_id: {rid}, PID: {proc.pid})")
                        else:
                            # 프로세스가 종료되었는데 전역변수가 남아있는 경우 즉시 cleanup
                            logger.warning(f"heartbeat: 프로세스 종료 감지 (runner_id: {rid}, exit code: {proc.returncode}), 상태 정리")
                            _cleanup_process_state(rid, r)
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
                command_result["action"] = action
                command_result["executed_at"] = datetime.now().isoformat()

                # 결과 반환 (API가 BRPOP으로 대기 중)
                r.lpush(RESULTS_KEY, json.dumps(command_result, ensure_ascii=False))
                # 결과 키 만료 설정 (30초 후 자동 삭제, 누적 방지)
                r.expire(RESULTS_KEY, 30)

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
    main()