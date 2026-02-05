"""
Redis Worker Command Listener

Session 1 (사용자 세션)에서 실행되는 워커 명령 리스너입니다.
API 서버(Session 0)에서 Redis를 통해 전달된 명령을 수신하고 실행합니다.

동작 방식:
    - BRPOP으로 worker:commands 키를 블로킹 대기 (CPU 0%)
    - 명령 수신 시 browser-workers.ps1 호출
    - 결과를 worker:command_results에 반환

사용법:
    python scripts/worker-command-listener.py

아키텍처:
    API (Session 0) → Redis LPUSH → [이 리스너 (Session 1)] → browser-workers.ps1
"""
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import redis

# 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
COMMANDS_KEY = "worker:commands"
RESULTS_KEY = "worker:command_results"
BRPOP_TIMEOUT = 0  # 0 = 무한 대기

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
BROWSER_WORKERS_SCRIPT = SCRIPT_DIR / "browser-workers.ps1"

# 로깅 설정
log_dir = PROJECT_ROOT / "logs" / "dev"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "worker_command_listener.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def execute_worker_action(action: str) -> dict:
    """browser-workers.ps1을 호출하여 워커 액션을 실행합니다.

    Args:
        action: start, stop, restart

    Returns:
        dict: {success: bool, message: str, pid: int|None}
    """
    if action not in ("start", "stop", "restart"):
        return {"success": False, "message": f"알 수 없는 액션: {action}"}

    if not BROWSER_WORKERS_SCRIPT.exists():
        return {"success": False, "message": f"스크립트 없음: {BROWSER_WORKERS_SCRIPT}"}

    try:
        logger.info(f"워커 액션 실행: {action}")

        result = subprocess.run(
            [
                "powershell.exe",
                "-ExecutionPolicy", "Bypass",
                "-File", str(BROWSER_WORKERS_SCRIPT),
                "-Action", action,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )

        output = result.stdout.strip()
        error = result.stderr.strip()

        if result.returncode == 0:
            logger.info(f"워커 액션 성공: {action}\n{output}")

            # PID 추출 시도 (start 시)
            pid = None
            if action in ("start", "restart"):
                for line in output.split("\n"):
                    if "PID:" in line:
                        try:
                            pid = int(line.split("PID:")[1].strip().rstrip(")"))
                        except (ValueError, IndexError):
                            pass

            return {
                "success": True,
                "message": f"워커 {action} 완료",
                "pid": pid,
            }
        else:
            logger.error(f"워커 액션 실패: {action}\nstdout: {output}\nstderr: {error}")
            return {
                "success": False,
                "message": f"워커 {action} 실패: {error or output}",
            }

    except subprocess.TimeoutExpired:
        logger.error(f"워커 액션 타임아웃: {action}")
        return {"success": False, "message": f"워커 {action} 타임아웃 (60초)"}
    except Exception as e:
        logger.error(f"워커 액션 예외: {action}: {e}")
        return {"success": False, "message": f"워커 {action} 예외: {str(e)}"}


def main():
    """메인 루프: Redis BRPOP으로 명령 대기 및 실행."""
    logger.info("=" * 50)
    logger.info("Worker Command Listener 시작")
    logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info(f"명령 키: {COMMANDS_KEY}")
    logger.info(f"결과 키: {RESULTS_KEY}")
    logger.info(f"스크립트: {BROWSER_WORKERS_SCRIPT}")
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

            # BRPOP 루프 (블로킹 대기)
            while True:
                result = r.brpop(COMMANDS_KEY, timeout=BRPOP_TIMEOUT)

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

                # 액션 실행
                action_result = execute_worker_action(action)
                action_result["action"] = action
                action_result["executed_at"] = datetime.now().isoformat()

                # 결과 반환 (API가 BRPOP으로 대기 중)
                r.lpush(RESULTS_KEY, json.dumps(action_result, ensure_ascii=False))
                # 결과 키 만료 설정 (30초 후 자동 삭제, 누적 방지)
                r.expire(RESULTS_KEY, 30)

                logger.info(f"명령 결과 반환: {action_result}")

        except redis.ConnectionError as e:
            logger.warning(f"Redis 연결 실패: {e}, {reconnect_delay}초 후 재시도")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

        except KeyboardInterrupt:
            logger.info("Ctrl+C로 종료")
            break

        except Exception as e:
            logger.error(f"예상치 못한 오류: {e}", exc_info=True)
            time.sleep(5)

    logger.info("Worker Command Listener 종료")


if __name__ == "__main__":
    main()
