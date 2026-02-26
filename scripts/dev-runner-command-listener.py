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
STATE_KEY = "plan-runner:state"
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

LOG_CHANNEL = "plan-runner:logs"

# 전역 프로세스 관리
_current_process: Optional[subprocess.Popen] = None
_current_log_file: Optional[Path] = None
_stream_thread: Optional[threading.Thread] = None


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


def _cleanup_process_state(redis_client: redis.Redis):
    """전역 프로세스 변수 + Redis 상태 정리"""
    global _current_process, _current_log_file, _stream_thread

    _current_process = None
    _current_log_file = None

    if _stream_thread and _stream_thread.is_alive():
        _stream_thread.join(timeout=3)
    _stream_thread = None

    try:
        redis_client.set(STATE_KEY + ":status", "stopped")
        redis_client.delete(
            STATE_KEY + ":pid",
            STATE_KEY + ":plan_file",
            STATE_KEY + ":start_time",
            STATE_KEY + ":log_file_path",
            STATE_KEY + ":stream_log_path",
        )
    except Exception:
        pass


def _stream_output(process: subprocess.Popen, log_handle, redis_client: redis.Redis):
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

            # 4. 직전 억제 요약 먼저 publish
            if suppressed_count > 0:
                try:
                    redis_client.publish(LOG_CHANNEL, f"[NOISE] {suppressed_count} lines suppressed")
                except redis.ConnectionError:
                    pass
                suppressed_count = 0

            # 5. Quota 에러 감지 → 자동 종료
            if any(marker in stripped for marker in QUOTA_ERROR_MARKERS):
                logger.warning("[DEV-RUNNER] quota 에러 감지, plan-runner 자동 종료")
                try:
                    redis_client.publish(LOG_CHANNEL, "[DEV-RUNNER] quota 에러 감지. 자동 종료.")
                    redis_client.set(STATE_KEY + ":quota_stopped", "1", ex=3600)
                except redis.ConnectionError:
                    pass
                process.terminate()
                break

            # 6. 정상 라인 publish (ANSI 이스케이프 코드 제거)
            try:
                redis_client.publish(LOG_CHANNEL, _ANSI_ESCAPE.sub('', stripped))
            except redis.ConnectionError:
                pass  # Redis 끊겨도 파일 기록은 계속

        # 루프 종료 후 잔여 억제 요약
        if suppressed_count > 0:
            try:
                redis_client.publish(LOG_CHANNEL, f"[NOISE] {suppressed_count} lines suppressed")
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
        _cleanup_process_state(redis_client)


def start_plan_runner(command: Dict, redis_client: redis.Redis) -> Dict:
    """plan-runner CLI 실행 시작

    Args:
        command: {action: "run", plan_file: str, max_cycles: int, ...}
        redis_client: Redis 클라이언트

    Returns:
        dict: {success: bool, message: str, pid: int|None, log_file: str|None}
    """
    global _current_process, _current_log_file

    # 이미 실행 중이면 에러 (stale 프로세스 자동 정리 포함)
    if _current_process and _current_process.poll() is None:
        if not _is_pid_alive(_current_process.pid):
            # OS 레벨에서 죽은 프로세스 면 자동 정리
            logger.warning(f"Stale process detected (PID: {_current_process.pid}), cleaning up")
            _cleanup_process_state(redis_client)
        else:
            return {
                "success": False,
                "message": f"Already running (PID: {_current_process.pid})"
            }
    elif _current_process and _current_process.poll() is not None:
        # 종료되었지만 정리 안 된 경우
        logger.info(f"Previous process ended (exit code: {_current_process.returncode}), cleaning up")
        _cleanup_process_state(redis_client)

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

        _current_process = process
        _current_log_file = log_file

        # 별도 스레드에서 stdout 을 파일 + Redis publish
        global _stream_thread
        _stream_thread = threading.Thread(
            target=_stream_output,
            args=(process, log_handle, redis_client),
            daemon=True,
        )
        _stream_thread.start()

        # Redis에 상태 저장
        redis_client.set(STATE_KEY + ":log_file_path", str(log_file))
        redis_client.set(STATE_KEY + ":stream_log_path", str(log_file))
        redis_client.set(STATE_KEY + ":pid", process.pid)
        redis_client.set(STATE_KEY + ":plan_file", plan_file or "ALL")
        redis_client.set(STATE_KEY + ":start_time", datetime.now().isoformat())
        redis_client.set(STATE_KEY + ":status", "running")
        redis_client.set(STATE_KEY + ":engine", command.get("engine", "claude"))
        redis_client.delete(STATE_KEY + ":quota_stopped")

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


def stop_plan_runner(redis_client: redis.Redis) -> Dict:
    """plan-runner 프로세스 종료

    Returns:
        dict: {success: bool, message: str}
    """
    global _current_process, _current_log_file

    if not _current_process or _current_process.poll() is not None:
        return {"success": False, "message": "Not running"}

    try:
        logger.info(f"Stopping plan-runner (PID: {_current_process.pid})...")

        # Windows: terminate() 호출
        _current_process.terminate()

        # 5초 대기
        try:
            _current_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # 강제 종료
            _current_process.kill()
            _current_process.wait()

        logger.info("plan-runner stopped")

        # 스트리밍 스레드 정리
        global _stream_thread
        if _stream_thread and _stream_thread.is_alive():
            _stream_thread.join(timeout=5)
        _stream_thread = None

        # Redis 상태 업데이트
        redis_client.set(STATE_KEY + ":status", "stopped")
        redis_client.delete(STATE_KEY + ":pid")
        redis_client.delete(STATE_KEY + ":log_file_path")
        redis_client.delete(STATE_KEY + ":stream_log_path")

        _current_process = None
        _current_log_file = None

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
    """현재 실행 상태 조회

    Returns:
        dict: {success: bool, running: bool, pid: int|None, log_file: str|None}
    """
    global _current_process, _current_log_file

    quota_stopped = bool(redis_client.get(STATE_KEY + ":quota_stopped"))

    if _current_process and _current_process.poll() is None:
        return {
            "success": True,
            "running": True,
            "pid": _current_process.pid,
            "log_file": str(_current_log_file) if _current_log_file else None,
            "quota_stopped": quota_stopped,
        }
    else:
        # 종료된 경우 Redis 상태 정리
        if _current_process:
            redis_client.set(STATE_KEY + ":status", "stopped")
            redis_client.delete(STATE_KEY + ":pid")
            redis_client.delete(STATE_KEY + ":log_file_path")
            redis_client.delete(STATE_KEY + ":stream_log_path")
            _current_process = None
            _current_log_file = None

        return {
            "success": True,
            "running": False,
            "pid": None,
            "log_file": None,
            "quota_stopped": quota_stopped,
        }


def force_stop_plan_runner(redis_client: redis.Redis) -> Dict:
    """강제 종료 - kill 및 전역 상태 초기화 (리셋용)

    Returns:
        dict: {success: bool, message: str}
    """
    global _current_process, _current_log_file, _stream_thread

    pid = _current_process.pid if _current_process else None

    if _current_process:
        try:
            _current_process.kill()
            _current_process.wait(timeout=5)
        except Exception:
            pass

    _cleanup_process_state(redis_client)

    msg = f"Force stopped (PID: {pid})" if pid else "Force cleaned (no process)"
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
        return stop_plan_runner(redis_client)
    elif action == "force-stop":
        return force_stop_plan_runner(redis_client)
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
    logger.info(f"상태 키: {STATE_KEY}")
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
            if _current_process and _current_process.poll() is None and _is_pid_alive(_current_process.pid):
                r.set(STATE_KEY + ":status", "running")
                r.set(STATE_KEY + ":pid", _current_process.pid)
                logger.info(f"Redis 재연결: 프로세스 상태 복원 (PID: {_current_process.pid})")

            # BRPOP 루프 (블로킹 대기)
            while True:
                # heartbeat 갱신
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    r.set(HEARTBEAT_KEY, datetime.now().isoformat(), ex=HEARTBEAT_TTL)
                    # 프로세스 실행 중이면 Redis 상태 동기화
                    # (Redis 키 만료 또는 재시작으로 날아갈 경우 10초마다 복원)
                    if _current_process and _current_process.poll() is None:
                        if r.get(STATE_KEY + ":status") != "running":
                            r.set(STATE_KEY + ":status", "running")
                            r.set(STATE_KEY + ":pid", _current_process.pid)
                            logger.info(f"heartbeat: Redis 상태 복원 (PID: {_current_process.pid})")
                    elif _current_process and _current_process.poll() is not None:
                        # 프로세스가 종료되었는데 전역변수가 남아있는 경우 즉시 cleanup
                        logger.warning(f"heartbeat: 프로세스 종료 감지 (exit code: {_current_process.returncode}), 상태 정리")
                        _cleanup_process_state(r)
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