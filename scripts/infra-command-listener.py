"""
Redis Infra Command Listener

Session 1 (사용자 세션)에서 실행되는 인프라 명령 리스너입니다.
API 서버(Session 0)에서 Redis를 통해 전달된 infra 재시작 명령을 수신하고 실행합니다.

동작 방식:
    - BRPOP으로 infra:commands 키를 블로킹 대기 (CPU 0%)
    - restart-listener: command_listener watchdog+worker kill 후 재시작
    - restart-infra: 지정 infra 프로세스 재시작
    - 결과를 infra:command_results에 반환

사용법:
    python scripts/infra-command-listener.py

아키텍처:
    API (Session 0) → Redis LPUSH infra:commands → [이 리스너 (Session 1)] → browser_workers.py
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
COMMANDS_KEY = "infra:commands"
RESULTS_KEY = "infra:command_results"
BRPOP_TIMEOUT = 30

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent

# python 실행파일: venv alias 우선, fallback to python.exe
_alias = PROJECT_ROOT / ".venv" / "Scripts" / "monitorpage-worker.exe"
PYTHON_EXE = _alias if _alias.exists() else PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
BROWSER_WORKERS_PY = SCRIPT_DIR / "browser_workers.py"

# 로깅 설정
log_dir = PROJECT_ROOT / "logs" / "admin"
log_dir.mkdir(parents=True, exist_ok=True)
_log_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / f"infra_command_listener_{_log_timestamp}.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def execute_infra_action(action: str, target: str | None = None) -> dict:
    """browser_workers.py를 호출하여 infra 액션을 실행합니다.

    Args:
        action: "restart-listener" | "restart-infra"
        target: restart-infra 시 대상 infra 이름 (e.g. "api_watchdog")

    Returns:
        dict: {"success": bool, "message": str}
    """
    if action not in ("restart-listener", "restart-infra"):
        return {"success": False, "message": f"알 수 없는 액션: {action}"}

    if not BROWSER_WORKERS_PY.exists():
        return {"success": False, "message": f"스크립트 없음: {BROWSER_WORKERS_PY}"}

    cmd = [str(PYTHON_EXE), str(BROWSER_WORKERS_PY), action]
    if action == "restart-infra":
        if not target:
            return {"success": False, "message": "restart-infra: target 필수"}
        cmd.append(target)

    try:
        logger.info(f"인프라 액션 실행: {action} target={target}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )
        output = result.stdout.strip()
        error = result.stderr.strip()

        if result.returncode == 0:
            logger.info(f"인프라 액션 성공: {action}\n{output}")
            return {"success": True, "message": f"인프라 {action} 완료"}
        else:
            logger.error(f"인프라 액션 실패: {action}\nstdout: {output}\nstderr: {error}")
            return {"success": False, "message": f"인프라 {action} 실패: {error or output}"}

    except subprocess.TimeoutExpired:
        logger.error(f"인프라 액션 타임아웃: {action}")
        return {"success": False, "message": f"인프라 {action} 타임아웃 (60초)"}
    except Exception as e:
        logger.error(f"인프라 액션 예외: {action}: {e}")
        return {"success": False, "message": f"인프라 {action} 예외: {str(e)}"}


def main():
    """메인 루프: Redis BRPOP으로 infra 명령 대기 및 실행."""
    logger.info("=" * 50)
    logger.info("Infra Command Listener 시작")
    logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info(f"명령 키: {COMMANDS_KEY}")
    logger.info(f"결과 키: {RESULTS_KEY}")
    logger.info("=" * 50)

    reconnect_delay = 1

    while True:
        try:
            r = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            r.ping()
            logger.info("Redis 연결 성공")
            reconnect_delay = 1

            while True:
                result = r.brpop(COMMANDS_KEY, timeout=BRPOP_TIMEOUT)
                if result is None:
                    continue

                _, raw_data = result

                try:
                    command = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(f"잘못된 명령 형식: {raw_data}")
                    continue

                action = command.get("action")
                target = command.get("target")
                source = command.get("source", "unknown")
                logger.info(f"명령 수신: action={action}, target={target}, source={source}")

                action_result = execute_infra_action(action, target)
                action_result["action"] = action
                action_result["executed_at"] = datetime.now().isoformat()

                r.lpush(RESULTS_KEY, json.dumps(action_result, ensure_ascii=False))
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

    logger.info("Infra Command Listener 종료")


if __name__ == "__main__":
    main()
