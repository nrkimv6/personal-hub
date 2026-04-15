"""Session 1 Kakao notification listener.

Redis 큐에 적재된 Kakao payload를 꺼내 `kakaocli-win.exe send`로 전송합니다.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

import redis.asyncio as aioredis

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.shared.notification.kakao_queue import (
    KakaoNotificationQueue,
    is_payload_expired,
)

LOG_DIR = PROJECT_ROOT / "logs" / "admin"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_TS = datetime.now().strftime("%Y%m%d_%H%M%S")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"kakao_notification_listener_{_LOG_TS}.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

QUEUE_TIMEOUT_SEC = 30
CLI_TIMEOUT_SEC = 60


def _get_setting(name: str, default):
    return getattr(settings, name, default)


def _get_cli_path() -> Path:
    return Path(
        _get_setting(
            "MEGABEAUTY_KAKAO_ALERT_CLI_PATH",
            r"D:\work\project\tools\kakaocli-win\.venv\Scripts\kakaocli-win.exe",
        )
    )


async def _send_via_cli(room_name: str, message: str) -> bool:
    cli_path = _get_cli_path()
    if not cli_path.exists():
        logger.error("kakaocli-win.exe를 찾지 못했습니다: %s", cli_path)
        return False

    cli_workdir = cli_path.parent
    if len(cli_path.parents) >= 3:
        cli_workdir = cli_path.parents[2]

    try:
        proc = await asyncio.create_subprocess_exec(
            str(cli_path),
            "send",
            room_name,
            message,
            cwd=str(cli_workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=CLI_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error("kakaocli-win 전송 타임아웃 (%ss): room=%s", CLI_TIMEOUT_SEC, room_name)
            return False

        if proc.returncode == 0:
            if stdout:
                logger.info("kakaocli-win 전송 성공: %s", stdout.decode("utf-8", errors="replace").strip())
            else:
                logger.info("kakaocli-win 전송 성공: room=%s", room_name)
            return True

        stderr_text = stderr.decode("utf-8", errors="replace").strip() if stderr else ""
        stdout_text = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
        logger.error(
            "kakaocli-win 전송 실패 (code=%s, room=%s) stdout=%s stderr=%s",
            proc.returncode,
            room_name,
            stdout_text,
            stderr_text,
        )
        return False
    except Exception as e:
        logger.error("kakaocli-win 전송 예외: %s", e)
        return False


async def _process_payload(payload: dict) -> None:
    if not payload:
        return

    if is_payload_expired(payload):
        logger.info("만료된 Kakao payload 폐기: id=%s", payload.get("id"))
        return

    room_name = payload.get("room_name") or _get_setting("MEGABEAUTY_KAKAO_ALERT_ROOM_NAME", "소나무봇")
    message = payload.get("message")
    if not message:
        logger.warning("메시지 없는 Kakao payload 무시: %s", payload)
        return

    logger.info(
        "Kakao payload 처리 시작: id=%s room=%s source=%s",
        payload.get("id"),
        room_name,
        payload.get("source"),
    )
    await _send_via_cli(room_name, message)


async def main() -> int:
    client = aioredis.Redis(
        host=_get_setting("REDIS_HOST", "localhost"),
        port=_get_setting("REDIS_PORT", 6379),
        decode_responses=True,
    )
    queue = KakaoNotificationQueue(client)
    logger.info("Kakao notification listener started: queue=%s", queue.queue_name)

    try:
        while True:
            payload = await queue.pop(timeout=QUEUE_TIMEOUT_SEC)
            if payload is None:
                continue
            try:
                await _process_payload(payload)
            except Exception as e:
                logger.error("Kakao payload 처리 중 오류: %s", e)
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        logger.info("Kakao notification listener interrupted")
    finally:
        await client.aclose()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
