"""
Redis Auto-Next Command Listener

Session 1 (사용자 세션)에서 실행되는 auto-next 명령 리스너입니다.
API 서버(Session 0)에서 Redis를 통해 전달된 명령을 수신하고 실행합니다.

동작 방식:
    - BRPOP으로 auto-next:commands 키를 블로킹 대기 (CPU 0%)
    - 명령 수신 시 auto-next CLI 실행
    - 실행 결과/PID를 auto-next:command_results에 반환
    - stop 명령 시 프로세스 terminate

사용법:
    python scripts/auto-next-command-listener.py

아키텍처:
    API (Session 0) → Redis LPUSH → [이 리스너 (Session 1)] → auto-next CLI
"""
import json
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

import redis

# 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
COMMANDS_KEY = "auto-next:commands"
RESULTS_KEY = "auto-next:command_results"
STATE_KEY = "auto-next:state"
HEARTBEAT_KEY = "auto-next:listener:heartbeat"
HEARTBEAT_INTERVAL = 10  # heartbeat 갱신 주기 (초)
HEARTBEAT_TTL = 30  # heartbeat 만료 시간 (초, 3회 미갱신 시 만료)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
WTOOLS_BASE_DIR = Path("D:/work/project/service/wtools")
AUTO_NEXT_MODULE_PATH = WTOOLS_BASE_DIR / "common/tools/auto-next"
AUTO_NEXT_PYTHON = AUTO_NEXT_MODULE_PATH / ".venv/Scripts/python.exe"
LOG_DIR = WTOOLS_BASE_DIR / "common/logs"

# 로깅 설정
log_dir = PROJECT_ROOT / "logs" / "dev"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "auto_next_command_listener.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

LOG_CHANNEL = "auto-next:logs"

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
    """프로세스 stdout을 라인별로 읽어 파일 기록 + Redis publish 동시 수행"""
    try:
        for line in process.stdout:
            stripped = line.rstrip('\n')
            # 파일에 기록
            log_handle.write(line)
            log_handle.flush()
            # Redis Pub/Sub으로 publish
            try:
                redis_client.publish(LOG_CHANNEL, stripped)
            except redis.ConnectionError:
                pass  # Redis 끊겨도 파일 기록은 계속
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


def start_auto_next(command: Dict, redis_client: redis.Redis) -> Dict:
    """auto-next CLI 실행 시작

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
            # OS 레벨에서 죽은 프로세스 → 자동 정리
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
    is_parallel = command.get("parallel", False)
    if not plan_file and not is_parallel:
        return {"success": False, "message": "plan_file required (use parallel mode for batch execution)"}

    cmd = [
        str(AUTO_NEXT_PYTHON),
        "-m",
        "auto_next",
        "run",
    ]

    if plan_file:
        cmd.extend(["--plan-file", plan_file])

    # 옵션 추가
    if command.get("max_cycles"):
        cmd.extend(["--max-cycles", str(command["max_cycles"])])

    if command.get("max_tokens"):
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

    # 로그 파일 생성
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"auto-next-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

    try:
        # subprocess 실행 — stdout을 PIPE로 받아 스레드에서 파일+Redis 동시 기록
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
            cwd=str(AUTO_NEXT_MODULE_PATH),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        _current_process = process
        _current_log_file = log_file

        # 별도 스레드에서 stdout → 파일 + Redis publish
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

        logger.info(f"auto-next started (PID: {process.pid}, log: {log_file})")

        return {
            "success": True,
            "message": "auto-next started",
            "pid": process.pid,
            "log_file": str(log_file),
        }

    except Exception as e:
        logger.error(f"Failed to start auto-next: {e}")
        return {
            "success": False,
            "message": f"Failed to start: {str(e)}"
        }


def stop_auto_next(redis_client: redis.Redis) -> Dict:
    """auto-next 프로세스 종료

    Returns:
        dict: {success: bool, message: str}
    """
    global _current_process, _current_log_file

    if not _current_process or _current_process.poll() is not None:
        return {"success": False, "message": "Not running"}

    try:
        logger.info(f"Stopping auto-next (PID: {_current_process.pid})...")

        # Windows: terminate() 호출
        _current_process.terminate()

        # 5초 대기
        try:
            _current_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # 강제 종료
            _current_process.kill()
            _current_process.wait()

        logger.info("auto-next stopped")

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
        logger.error(f"Failed to stop auto-next: {e}")
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

    if _current_process and _current_process.poll() is None:
        return {
            "success": True,
            "running": True,
            "pid": _current_process.pid,
            "log_file": str(_current_log_file) if _current_log_file else None,
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
        }


def force_stop_auto_next(redis_client: redis.Redis) -> Dict:
    """강제 종료 - kill 후 전역 상태 초기화 (리셋용)

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
        return start_auto_next(command, redis_client)
    elif action == "stop":
        return stop_auto_next(redis_client)
    elif action == "force-stop":
        return force_stop_auto_next(redis_client)
    elif action == "status":
        return get_status(redis_client)
    else:
        return {"success": False, "message": f"Unknown action: {action}"}


def main():
    """메인 루프: Redis BRPOP으로 명령 대기 및 실행."""
    logger.info("=" * 50)
    logger.info("Auto-Next Command Listener 시작")
    logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info(f"명령 키: {COMMANDS_KEY}")
    logger.info(f"결과 키: {RESULTS_KEY}")
    logger.info(f"상태 키: {STATE_KEY}")
    logger.info(f"auto-next 모듈: {AUTO_NEXT_MODULE_PATH}")
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

            # Redis 재연결 시 현재 프로세스 상태 복원
            # (Redis 재시작 등으로 키가 날아간 경우 status: running 복원)
            if _current_process and _current_process.poll() is None and _is_pid_alive(_current_process.pid):
                r.set(STATE_KEY + ":status", "running")
                r.set(STATE_KEY + ":pid", _current_process.pid)
                logger.info(f"Redis 재연결: 프로세스 상태 복원 (PID: {_current_process.pid})")

            # 초기 heartbeat 설정
            last_heartbeat = 0

            # BRPOP 루프 (블로킹 대기)
            while True:
                # heartbeat 갱신
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    r.set(HEARTBEAT_KEY, datetime.now().isoformat(), ex=HEARTBEAT_TTL)
                    # 프로세스 실행 중이면 Redis 상태 동기화
                    # (Redis 키 만료 또는 재시작으로 날아간 경우 10초 내 복원)
                    if _current_process and _current_process.poll() is None:
                        if r.get(STATE_KEY + ":status") != "running":
                            r.set(STATE_KEY + ":status", "running")
                            r.set(STATE_KEY + ":pid", _current_process.pid)
                            logger.info(f"heartbeat: Redis 상태 복원 (PID: {_current_process.pid})")
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
            logger.warning(f"Redis 연결 실패: {e}, {reconnect_delay}초 후 재시도")
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

    logger.info("Auto-Next Command Listener 종료")


if __name__ == "__main__":
    main()
