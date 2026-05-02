"""
Redis Worker Command Listener

Session 1 (사용자 세션)에서 실행되는 워커 명령 리스너입니다.
API 서버(Session 0)에서 Redis를 통해 전달된 명령을 수신하고 실행합니다.

동작 방식:
    - BRPOP으로 worker:commands 및 monitor:notification:desktop 키를 블로킹 대기 (CPU 0%)
    - 워커 명령 수신 시 browser-workers.ps1 호출
    - Desktop 알림 수신 시 plyer.notification.notify() 호출 (Session 0 릴레이)
    - 결과를 worker:command_results에 반환

사용법:
    python scripts/services/worker-command-listener.py
    python scripts/services/worker-command-listener.py --check-imports  # import 확인 후 즉시 종료

아키텍처:
    API (Session 0) → Redis LPUSH worker:commands → [이 리스너 (Session 1)] → browser-workers.ps1
    notification_service (Session 0) → Redis LPUSH monitor:notification:desktop → [이 리스너 (Session 1)] → plyer.notification
"""
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# sys.path bootstrap — app import 이전에 PROJECT_ROOT를 경로에 추가
# 직접 실행 시 sys.path[0]은 스크립트 디렉토리(scripts/services/)이므로 app/ 패키지를 찾지 못함
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # scripts/services/ → scripts/ → project root
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import redis

from app.shared.process.subprocess_text import with_text_subprocess_defaults

# 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
COMMANDS_KEY = "worker:commands"
RESULTS_KEY = "worker:command_results"
DESKTOP_NOTIFICATION_KEY = "monitor:notification:desktop"  # Session 0 → Session 1 Desktop 알림 릴레이
LAUNCH_CLI_KEY = "worker:launch-cli"  # Session 0 → Session 1 CLI 콘솔 실행 릴레이
LAUNCH_CLI_RESULTS_KEY = "worker:launch-cli:results"  # launch-cli 결과 큐
OPEN_APP_KEY = "worker:open-app"  # Session 0 → Session 1 generic GUI open 릴레이
BRPOP_TIMEOUT = 30  # 초 (0 = 무한 대기, 양수 = 타임아웃 후 루프 재시작)

# Podman 자동 복구 설정
PODMAN_RECOVERY_THRESHOLD = 3   # Redis 연속 실패 N회 후 Podman 복구 시도
PODMAN_RECOVERY_COOLDOWN = 600  # 초 (10분) — 쿨다운 내 재시도 방지

# 마지막 Podman 복구 시도 시각 (Unix timestamp, 0 = 미시도)
_last_podman_recovery_time: float = 0.0

BROWSER_WORKERS_SCRIPT = SCRIPT_DIR / "browser-workers.ps1"

# 로깅 설정
log_dir = PROJECT_ROOT / "logs" / "admin"
log_dir.mkdir(parents=True, exist_ok=True)
_log_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / f"worker_command_listener_{_log_timestamp}.log", encoding="utf-8"),
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
            **with_text_subprocess_defaults(
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(PROJECT_ROOT),
            ),
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


def send_desktop_notification(message: str) -> bool:
    """Desktop 알림을 표시합니다 (Session 0에서 릴레이된 알림).

    Args:
        message: 표시할 알림 메시지

    Returns:
        bool: 성공 여부
    """
    try:
        from plyer import notification

        # Windows 알림 시스템 메시지 길이 제한 (256자)
        if len(message) > 256:
            message = message[:253] + "..."

        notification.notify(
            title="알림",
            message=message,
            timeout=10,
        )
        logger.info(f"Desktop 알림 표시 완료: {message[:50]}...")
        return True
    except ImportError:
        logger.warning("plyer 미설치 — Desktop 알림 표시 불가 (pip install plyer)")
        return False
    except Exception as e:
        logger.error(f"Desktop 알림 표시 실패: {e}")
        return False


def execute_launch_cli(payload: dict) -> dict:
    """Session 1에서 CLI 콘솔 창을 실행합니다 (API Session 0에서 릴레이된 명령).

    Args:
        payload: launch-cli 페이로드 (engine, name, config_dir, extra_env, engine_cmd, env_key)

    Returns:
        dict: {success: bool, status: str, engine: str, profile: str} 또는 실패 시 error 포함
    """
    try:
        env = os.environ.copy()

        # config_dir 주입
        env_key = payload.get("env_key")
        config_dir = payload.get("config_dir")
        if env_key and config_dir:
            env[env_key] = config_dir
        elif env_key and not config_dir:
            env.pop(env_key, None)

        # extra_env 병합
        for k, v in (payload.get("extra_env") or {}).items():
            env[k] = v

        engine_cmd = payload.get("engine_cmd", "claude")

        subprocess.Popen(
            ["cmd", "/k", engine_cmd],
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            close_fds=True,
        )

        logger.info(f"launch-cli 실행 완료: engine={payload.get('engine')}, profile={payload.get('name')}")
        return {
            "success": True,
            "status": "launched",
            "engine": payload.get("engine"),
            "profile": payload.get("name"),
        }

    except Exception as e:
        logger.error(f"launch-cli 실행 실패: {e}")
        return {
            "success": False,
            "status": "error",
            "message": str(e),
            "engine": payload.get("engine"),
            "profile": payload.get("name"),
        }


def execute_open_app(payload: dict) -> dict:
    """Session 1에서 GUI 앱 열기 요청을 실행합니다."""
    app_name = str(payload.get("app_name") or "").strip().lower()
    args = payload.get("args") or []

    if app_name not in {"explorer", "code", "default"}:
        return {"success": False, "status": "error", "message": f"unsupported app: {app_name}"}
    if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
        return {"success": False, "status": "error", "message": "args must be a list of strings"}

    path_args = [arg for arg in args if arg and not arg.startswith("/") and not arg.startswith("-")]
    for raw_path in path_args:
        path_to_check = raw_path
        if app_name == "code" and ":" in raw_path:
            maybe_path, maybe_line = raw_path.rsplit(":", 1)
            if maybe_line.isdigit():
                path_to_check = maybe_path

        path = Path(path_to_check)
        if not path.is_absolute():
            return {"success": False, "status": "error", "message": f"path must be absolute: {raw_path}"}
        if not path.exists():
            return {"success": False, "status": "error", "message": f"path not found: {raw_path}"}

    try:
        if app_name == "default":
            command = ["cmd", "/c", "start", "", *args]
        else:
            command = [app_name, *args]

        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        logger.info(f"open-app 실행 완료: app={app_name}, args={args}")
        return {"success": True, "status": "opened", "app_name": app_name, "args": args}
    except Exception as e:
        logger.error(f"open-app 실행 실패: {e}")
        return {"success": False, "status": "error", "message": str(e), "app_name": app_name}


def attempt_podman_recovery() -> bool:
    """Podman Machine SSH 터널 재수립 + Redis 컨테이너 복구.

    Redis 연속 실패가 PODMAN_RECOVERY_THRESHOLD 이상일 때 호출된다.
    Session 1(사용자 세션)에서만 실행 가능 (podman machine stop/start 필요).

    Returns:
        bool: True = 복구 성공 (Redis ping 확인), False = 복구 불필요 또는 실패
    """
    try:
        # 1. Podman 소켓 연결 확인
        check = subprocess.run(["podman", "ps"], capture_output=True, timeout=5)
        if check.returncode == 0:
            logger.info("Podman socket OK — Redis 문제는 Podman 외 원인")
            return False

        logger.warning("Podman socket unreachable — recycling Machine to re-establish SSH tunnel...")

        # 2. Machine stop
        subprocess.run(["podman", "machine", "stop"], capture_output=True, timeout=15)
        time.sleep(3)

        # 3. Machine start (포트 재할당 포함 최대 60초)
        start_result = subprocess.run(["podman", "machine", "start"], capture_output=True, timeout=60)
        if start_result.returncode != 0:
            logger.error(f"podman machine start 실패: {start_result.stderr.decode('utf-8', errors='replace').strip()}")
            return False

        # 4. SSH 터널 수립 + WSL2 VM 초기화 대기
        time.sleep(15)

        # 5. Redis 컨테이너 시작
        subprocess.run(["podman", "start", "monitor-redis"], capture_output=True, timeout=10)
        time.sleep(3)

        # 6. Redis ping 확인
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, socket_connect_timeout=5)
            r.ping()
            r.close()
            logger.info("Podman Machine + Redis 복구 완료")
            return True
        except Exception:
            logger.error("Podman Machine 복구했으나 Redis 연결 실패")
            return False

    except (subprocess.TimeoutExpired, Exception) as e:
        logger.error(f"Podman 복구 중 예외: {e}")
        return False


def main():
    """메인 루프: Redis BRPOP으로 명령 대기 및 실행."""
    logger.info("=" * 50)
    logger.info("Worker Command Listener 시작")
    logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info(f"명령 키: {COMMANDS_KEY}")
    logger.info(f"결과 키: {RESULTS_KEY}")
    logger.info(f"Desktop 알림 키: {DESKTOP_NOTIFICATION_KEY}")
    logger.info(f"Launch CLI 키: {LAUNCH_CLI_KEY}")
    logger.info(f"Open App 키: {OPEN_APP_KEY}")
    logger.info(f"스크립트: {BROWSER_WORKERS_SCRIPT}")
    logger.info("=" * 50)

    reconnect_delay = 1
    consecutive_failures = 0

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
            consecutive_failures = 0  # 연결 복구 시 리셋

            # BRPOP 루프 (블로킹 대기) — worker:commands + notification:desktop + launch-cli + open-app 동시 대기
            while True:
                result = r.brpop([COMMANDS_KEY, DESKTOP_NOTIFICATION_KEY, LAUNCH_CLI_KEY, OPEN_APP_KEY], timeout=BRPOP_TIMEOUT)

                if result is None:
                    # timeout 경과 — 루프 계속 (연결 유지 확인)
                    continue

                queue_key, raw_data = result

                # Desktop 알림 처리
                if queue_key == DESKTOP_NOTIFICATION_KEY:
                    try:
                        payload = json.loads(raw_data)
                        message = payload.get("message", "")
                        if message:
                            logger.info(f"Desktop 알림 수신: {message[:80]}")
                            send_desktop_notification(message)
                        else:
                            logger.warning(f"Desktop 알림 페이로드에 message 없음: {raw_data}")
                    except json.JSONDecodeError:
                        logger.warning(f"잘못된 Desktop 알림 형식: {raw_data}")
                    continue

                # launch-cli 처리 (Session 1 콘솔 릴레이)
                if queue_key == LAUNCH_CLI_KEY:
                    try:
                        payload = json.loads(raw_data)
                        logger.info(f"launch-cli 수신: engine={payload.get('engine')}, profile={payload.get('name')}")
                        cli_result = execute_launch_cli(payload)
                        cli_result["executed_at"] = datetime.now().isoformat()
                        r.lpush(LAUNCH_CLI_RESULTS_KEY, json.dumps(cli_result, ensure_ascii=False))
                        r.expire(LAUNCH_CLI_RESULTS_KEY, 30)
                    except json.JSONDecodeError:
                        logger.warning(f"잘못된 launch-cli 페이로드: {raw_data}")
                    continue

                # open-app 처리 (Session 1 GUI 릴레이)
                if queue_key == OPEN_APP_KEY:
                    try:
                        payload = json.loads(raw_data)
                        logger.info(f"open-app 수신: app={payload.get('app_name')}, args={payload.get('args')}")
                        execute_open_app(payload)
                    except json.JSONDecodeError:
                        logger.warning(f"잘못된 open-app 페이로드: {raw_data}")
                    continue

                # 워커 명령 처리 (기존 로직)
                try:
                    command = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(f"잘못된 명령 형식: {raw_data}")
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
            consecutive_failures += 1
            logger.warning(f"Redis 연결 실패 ({consecutive_failures}회 연속): {e}, {reconnect_delay}초 후 재시도")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

            # Podman 복구 트리거 (연속 N회 실패 + 쿨다운 경과 시)
            if consecutive_failures >= PODMAN_RECOVERY_THRESHOLD:
                global _last_podman_recovery_time
                elapsed = time.time() - _last_podman_recovery_time
                if elapsed > PODMAN_RECOVERY_COOLDOWN:
                    _last_podman_recovery_time = time.time()
                    recovered = attempt_podman_recovery()
                    if recovered:
                        logger.info("Podman Machine 복구 완료, Redis 재연결 시도")
                        reconnect_delay = 1
                        consecutive_failures = 0
                    else:
                        logger.error(
                            "Podman Machine 복구 실패 — 수동 개입 필요: "
                            "podman machine stop && podman machine start"
                        )
                else:
                    logger.debug(
                        f"Podman 복구 쿨다운 중 ({PODMAN_RECOVERY_COOLDOWN - elapsed:.0f}초 남음)"
                    )

        except KeyboardInterrupt:
            logger.info("Ctrl+C로 종료")
            break

        except Exception as e:
            logger.error(f"예상치 못한 오류: {e}", exc_info=True)
            time.sleep(5)

    logger.info("Worker Command Listener 종료")


if __name__ == "__main__":
    if "--check-imports" in sys.argv:
        print("import check ok")
        sys.exit(0)
    main()
