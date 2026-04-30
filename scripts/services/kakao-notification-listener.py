"""Session 1 Kakao notification listener.

Redis 큐에 적재된 Kakao payload를 꺼내 `kakaocli-win.exe send`로 전송합니다.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import redis.asyncio as aioredis

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.shared.notification.kakao_queue import (
    KakaoNotificationQueue,
    is_payload_expired,
    normalize_kakao_metadata,
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
GUARD_STATE_FILE = PROJECT_ROOT / "logs" / "kakao_guard_state.json"
DEAD_LETTER_ALERT_KEY_PREFIX = "notification:kakao:dead-letter-alert"


class SendResult:
    def __init__(self, success: bool, retryable: bool = False, error: Optional[str] = None):
        self.success = success
        self.retryable = retryable
        self.error = error


class KakaoInputGuardError(RuntimeError):
    """입력 잠금 보호를 확보하지 못했음을 나타냅니다."""


def _get_setting(name: str, default):
    return getattr(settings, name, default)


def _get_cli_path() -> Path:
    return Path(
        _get_setting(
            "MEGABEAUTY_KAKAO_ALERT_CLI_PATH",
            r"D:\work\project\tools\kakaocli-win\.venv\Scripts\kakaocli-win.exe",
        )
    )


def _get_session_id() -> str:
    return os.environ.get("SESSIONNAME") or os.environ.get("WT_SESSION") or "unknown"


def _is_remote_session() -> bool:
    session_name = os.environ.get("SESSIONNAME", "")
    return session_name.upper().startswith("RDP")


def _write_guard_state(state: str, *, error: Optional[str] = None) -> None:
    GUARD_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "state": state,
        "pid": os.getpid(),
        "session_id": _get_session_id(),
    }
    if state == "acquired":
        payload["acquired_at"] = datetime.now().isoformat(timespec="seconds")
    elif state == "released":
        payload["released_at"] = datetime.now().isoformat(timespec="seconds")
    elif state == "failed":
        payload["failed_at"] = datetime.now().isoformat(timespec="seconds")
    if error:
        payload["error"] = error
    GUARD_STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _block_input(block: bool) -> bool:
    user32 = getattr(getattr(ctypes, "windll", None), "user32", None)
    if user32 is None:
        return False
    return bool(user32.BlockInput(bool(block)))


class KakaoInputGuard:
    """짧은 전송 크리티컬 섹션 동안 물리 입력을 차단합니다."""

    def __init__(self, *, enabled: bool, timeout_seconds: int, abort_on_remote_session: bool):
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.abort_on_remote_session = abort_on_remote_session
        self.acquired = False

    def __enter__(self) -> "KakaoInputGuard":
        if not self.enabled:
            return self
        if self.abort_on_remote_session and _is_remote_session():
            error = "remote session detected"
            _write_guard_state("failed", error=error)
            raise KakaoInputGuardError(error)
        if not _block_input(True):
            error = "BlockInput acquire failed"
            _write_guard_state("failed", error=error)
            raise KakaoInputGuardError(error)
        self.acquired = True
        _write_guard_state("acquired")
        logger.info("Kakao input guard acquired: timeout=%ss", self.timeout_seconds)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.acquired:
            return
        self.acquired = False
        released = _block_input(False)
        if not released:
            logger.error("Kakao input guard release reported failure")
        _write_guard_state("released", error=None if released else "BlockInput release failed")
        logger.info("Kakao input guard released")


def _preflight_kakao_room(room_name: str) -> SendResult:
    try:
        from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
    except Exception as exc:
        return SendResult(False, retryable=True, error=f"kakao preflight import failed: {exc}")

    controller = KakaoAppController()
    try:
        if not controller.is_running():
            return SendResult(False, retryable=True, error="KakaoTalk process is not running")
        if not controller.find_window_by_title(room_name) and not controller.find_main_window():
            return SendResult(False, retryable=True, error=f"KakaoTalk window not found: {room_name}")
    except Exception as exc:
        return SendResult(False, retryable=True, error=f"kakao preflight failed: {exc}")
    return SendResult(True)


async def _send_via_cli_raw(room_name: str, message: str, *, timeout_seconds: int) -> SendResult:
    cli_path = _get_cli_path()
    if not cli_path.exists():
        error = f"kakaocli-win.exe를 찾지 못했습니다: {cli_path}"
        logger.error(error)
        return SendResult(False, retryable=False, error=error)

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
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            error = f"kakaocli-win 전송 타임아웃 ({timeout_seconds}s): room={room_name}"
            logger.error(error)
            return SendResult(False, retryable=True, error=error)

        if proc.returncode == 0:
            if stdout:
                logger.info("kakaocli-win 전송 성공: %s", stdout.decode("utf-8", errors="replace").strip())
            else:
                logger.info("kakaocli-win 전송 성공: room=%s", room_name)
            return SendResult(True)

        stderr_text = stderr.decode("utf-8", errors="replace").strip() if stderr else ""
        stdout_text = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
        logger.error(
            "kakaocli-win 전송 실패 (code=%s, room=%s) stdout=%s stderr=%s",
            proc.returncode,
            room_name,
            stdout_text,
            stderr_text,
        )
        return SendResult(False, retryable=True, error=stderr_text or stdout_text or f"exit code {proc.returncode}")
    except Exception as e:
        logger.error("kakaocli-win 전송 예외: %s", e)
        return SendResult(False, retryable=True, error=str(e))


async def _send_via_cli_guarded(room_name: str, message: str, *, guard_required: bool = True) -> SendResult:
    guard_enabled = bool(_get_setting("MEGABEAUTY_KAKAO_INPUT_GUARD_ENABLED", False)) and guard_required
    guard_timeout = int(_get_setting("MEGABEAUTY_KAKAO_INPUT_GUARD_TIMEOUT_SECONDS", CLI_TIMEOUT_SEC))
    abort_remote = bool(_get_setting("MEGABEAUTY_KAKAO_INPUT_GUARD_ABORT_ON_REMOTE_SESSION", True))

    if guard_enabled:
        preflight = _preflight_kakao_room(room_name)
        if not preflight.success:
            logger.warning("Kakao preflight failed: %s", preflight.error)
            return preflight

    try:
        with KakaoInputGuard(
            enabled=guard_enabled,
            timeout_seconds=guard_timeout,
            abort_on_remote_session=abort_remote,
        ):
            return await _send_via_cli_raw(room_name, message, timeout_seconds=guard_timeout)
    except KakaoInputGuardError as exc:
        logger.warning("Kakao input guard failed: %s", exc)
        return SendResult(False, retryable=True, error=str(exc))


async def _send_via_cli(room_name: str, message: str) -> bool:
    """기존 테스트/호출부 호환을 위한 bool 래퍼."""
    result = await _send_via_cli_guarded(room_name, message, guard_required=True)
    return result.success


async def _send_dead_letter_alert_once(queue: KakaoNotificationQueue, payload: dict, error: str) -> None:
    alert_key = f"{_get_setting('REDIS_QUEUE_PREFIX', 'monitor')}:{DEAD_LETTER_ALERT_KEY_PREFIX}:{payload.get('id', 'unknown')}"
    try:
        accepted = await queue.client.set(alert_key, "1", ex=3600, nx=True)
        if not accepted:
            return
    except Exception as exc:
        logger.warning("Kakao dead-letter alert cooldown set failed: %s", exc)
        return

    try:
        from app.shared.notification.notification_service import NotificationService

        await NotificationService().send_telegram(
            f"⚠️ Kakao 알림 dead-letter 적재\nid={payload.get('id')}\nerror={error}",
            force_send=True,
        )
    except Exception as exc:
        logger.warning("Kakao dead-letter Telegram alert failed: %s", exc)


async def _handle_failed_payload(
    queue: Optional[KakaoNotificationQueue],
    payload: dict,
    result: SendResult,
) -> None:
    error = result.error or "unknown kakao send failure"
    if queue is None:
        logger.warning("Kakao payload 처리 실패(queue 없음): id=%s error=%s", payload.get("id"), error)
        return

    metadata = normalize_kakao_metadata(payload.get("metadata"))
    retry_count = int(metadata.get("retry_count") or 0)
    max_retries = int(_get_setting("MEGABEAUTY_KAKAO_INPUT_GUARD_MAX_RETRIES", 3))
    if result.retryable and retry_count < max_retries:
        requeued = await queue.requeue(payload, last_error=error)
        logger.warning(
            "Kakao payload 재큐잉: id=%s retry=%s/%s ok=%s error=%s",
            payload.get("id"),
            retry_count + 1,
            max_retries,
            requeued,
            error,
        )
        return

    dead_lettered = await queue.dead_letter(payload, last_error=error)
    logger.error("Kakao payload dead-letter 적재: id=%s ok=%s error=%s", payload.get("id"), dead_lettered, error)
    await _send_dead_letter_alert_once(queue, payload, error)


async def _process_payload(payload: dict, queue: Optional[KakaoNotificationQueue] = None) -> None:
    if not payload:
        return

    if is_payload_expired(payload):
        logger.info("만료된 Kakao payload 폐기: id=%s", payload.get("id"))
        return

    room_name = payload.get("room_name") or _get_setting("MEGABEAUTY_KAKAO_ALERT_ROOM_NAME", "소나무봇")
    message = payload.get("message")
    if not message:
        logger.warning("메시지 없는 Kakao payload 무시: %s", payload)
        if queue is not None:
            await _handle_failed_payload(queue, payload, SendResult(False, retryable=False, error="missing message"))
        return
    metadata = normalize_kakao_metadata(payload.get("metadata"))
    payload["metadata"] = metadata
    guard_required = bool(metadata.get("guard_required", True))

    logger.info(
        "Kakao payload 처리 시작: id=%s room=%s source=%s",
        payload.get("id"),
        room_name,
        payload.get("source"),
    )
    result = await _send_via_cli_guarded(room_name, message, guard_required=guard_required)
    if not result.success:
        await _handle_failed_payload(queue, payload, result)


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
                await _process_payload(payload, queue)
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
