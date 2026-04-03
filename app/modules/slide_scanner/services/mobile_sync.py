"""ADB-based mobile sync service for slide scanner pre-gate pipeline."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import SessionLocal
from app.modules.slide_scanner.services.mobile_ingest import register_ingested_items

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".heic",
    ".heif",
}

WINDOWS_RESERVED_CHARS = '<>:"/\\|?*'

_sync_lock = threading.Lock()
_sync_status_lock = threading.Lock()
_sync_start_lock = threading.Lock()
_sync_status: dict[str, Any] = {
    "is_running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_result": None,
    "last_error": None,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _set_sync_status(**kwargs: Any) -> None:
    with _sync_status_lock:
        _sync_status.update(kwargs)


def get_sync_status() -> dict[str, Any]:
    with _sync_status_lock:
        snapshot = deepcopy(_sync_status)
    return snapshot


def _run_adb(adb_path: Path, args: list[str], timeout_seconds: int = 30) -> subprocess.CompletedProcess[str]:
    if adb_path.suffix.lower() == ".py":
        command = [sys.executable, str(adb_path), *args]
    else:
        command = [str(adb_path), *args]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout_seconds,
    )


def _parse_adb_kv_tokens(tokens: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for token in tokens:
        if ":" not in token:
            continue
        key, value = token.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            parsed[key] = value
    return parsed


def list_connected_devices(adb_path: Path) -> list[dict[str, Any]]:
    result = _run_adb(adb_path, ["devices", "-l"], timeout_seconds=20)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "adb devices failed"
        raise RuntimeError(stderr)

    devices: list[dict[str, Any]] = []
    lines = [line.strip() for line in result.stdout.splitlines()]
    for line in lines:
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue

        serial = parts[0]
        state = parts[1]
        extras = _parse_adb_kv_tokens(parts[2:])
        devices.append(
            {
                "serial": serial,
                "state": state,
                "is_online": state == "device",
                "model": extras.get("model"),
                "device": extras.get("device"),
                "product": extras.get("product"),
                "transport_id": extras.get("transport_id"),
            }
        )
    return devices


def _quote_for_shell(raw_value: str) -> str:
    escaped = raw_value.replace("'", "'\"'\"'")
    return f"'{escaped}'"


def _parse_find_stdout(stdout: str) -> list[str]:
    paths: list[str] = []
    for line in stdout.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.lower().startswith("find:"):
            continue
        if candidate.lower().startswith("permission denied"):
            continue
        paths.append(candidate)
    return paths


def list_remote_images(device_serial: str, remote_roots: list[str]) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for remote_root in remote_roots:
        shell_command = f"find {_quote_for_shell(remote_root)} -type f"
        result = _run_adb(
            settings.ADB_PATH,
            ["-s", device_serial, "shell", shell_command],
            timeout_seconds=45,
        )

        for remote_path in _parse_find_stdout(result.stdout):
            suffix = PurePosixPath(remote_path).suffix.lower()
            if suffix not in IMAGE_EXTENSIONS:
                continue
            if remote_path in seen_paths:
                continue
            seen_paths.add(remote_path)
            discovered.append(
                {
                    "device_id": device_serial,
                    "device_serial": device_serial,
                    "source_uri": remote_path,
                    "original_filename": PurePosixPath(remote_path).name,
                }
            )

    discovered.sort(key=lambda item: str(item["source_uri"]).lower())
    return discovered


def _sanitize_windows_path_segment(segment: str) -> str:
    cleaned = "".join("_" if char in WINDOWS_RESERVED_CHARS else char for char in segment)
    cleaned = cleaned.strip().rstrip(".")
    return cleaned or "_"


def _build_local_inbox_path(inbox_root: Path, device_serial: str, remote_path: str) -> Path:
    remote_parts = [part for part in PurePosixPath(remote_path).parts if part not in ("/", "")]
    if not remote_parts:
        remote_parts = ["unknown"]

    filename = remote_parts[-1]
    parent_parts = remote_parts[:-1]
    safe_parts = [_sanitize_windows_path_segment(part) for part in parent_parts]
    safe_filename = _sanitize_windows_path_segment(filename)

    target_dir = inbox_root / _sanitize_windows_path_segment(device_serial)
    for part in safe_parts:
        target_dir = target_dir / part

    return target_dir / safe_filename


def _compute_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _read_remote_stat(device_serial: str, remote_path: str) -> tuple[float | None, int | None]:
    shell_command = f"stat -c '%Y|%s' {_quote_for_shell(remote_path)}"
    result = _run_adb(
        settings.ADB_PATH,
        ["-s", device_serial, "shell", shell_command],
        timeout_seconds=20,
    )
    if result.returncode != 0:
        return None, None

    line = result.stdout.strip().splitlines()
    if not line:
        return None, None
    last = line[-1].strip()
    if "|" not in last:
        return None, None

    mtime_text, size_text = last.split("|", 1)
    try:
        mtime = float(mtime_text.strip())
    except ValueError:
        mtime = None
    try:
        size = int(size_text.strip())
    except ValueError:
        size = None
    return mtime, size


def pull_images(device_serial: str, remote_items: list[dict[str, Any]], inbox_root: Path) -> list[dict[str, Any]]:
    pulled: list[dict[str, Any]] = []

    for remote_item in remote_items:
        remote_path = str(remote_item.get("source_uri") or "").strip()
        original_filename = str(remote_item.get("original_filename") or "").strip()
        if not remote_path:
            pulled.append(
                {
                    "device_id": device_serial,
                    "device_serial": device_serial,
                    "source_uri": remote_path,
                    "original_filename": original_filename,
                    "pull_ok": False,
                    "error_message": "source_uri is empty",
                }
            )
            continue

        local_path = _build_local_inbox_path(inbox_root, device_serial, remote_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        pull_result = _run_adb(
            settings.ADB_PATH,
            ["-s", device_serial, "pull", remote_path, str(local_path)],
            timeout_seconds=180,
        )

        if pull_result.returncode != 0:
            pulled.append(
                {
                    "device_id": device_serial,
                    "device_serial": device_serial,
                    "source_uri": remote_path,
                    "original_filename": original_filename or PurePosixPath(remote_path).name,
                    "pc_inbox_path": str(local_path),
                    "pull_ok": False,
                    "error_message": pull_result.stderr.strip() or pull_result.stdout.strip() or "adb pull failed",
                }
            )
            continue

        if not local_path.exists():
            pulled.append(
                {
                    "device_id": device_serial,
                    "device_serial": device_serial,
                    "source_uri": remote_path,
                    "original_filename": original_filename or PurePosixPath(remote_path).name,
                    "pc_inbox_path": str(local_path),
                    "pull_ok": False,
                    "error_message": "adb pull finished but file does not exist locally",
                }
            )
            continue

        remote_mtime, remote_size = _read_remote_stat(device_serial, remote_path)
        local_stat = local_path.stat()
        size_bytes = remote_size if remote_size is not None else local_stat.st_size
        source_mtime_utc = None
        if remote_mtime is not None:
            source_mtime_utc = datetime.fromtimestamp(remote_mtime, tz=timezone.utc).isoformat()

        pulled.append(
            {
                "device_id": str(remote_item.get("device_id") or device_serial),
                "device_serial": str(remote_item.get("device_serial") or device_serial),
                "source_uri": remote_path,
                "original_filename": original_filename or PurePosixPath(remote_path).name,
                "source_mtime": remote_mtime,
                "source_mtime_utc": source_mtime_utc,
                "source_size_bytes": size_bytes,
                "source_sha256": _compute_sha256(local_path),
                "pc_inbox_path": str(local_path),
                "ingested_at": _utc_now(),
                "pull_ok": True,
            }
        )

    return pulled


def run_sync_once(db: Session) -> dict[str, Any]:
    if not _sync_lock.acquire(blocking=False):
        status = get_sync_status()
        return {
            "status": "already_running",
            "message": "mobile sync is already running",
            "last_started_at": status.get("last_started_at"),
        }

    started_at = _utc_now_iso()
    _set_sync_status(
        is_running=True,
        last_started_at=started_at,
        last_error=None,
    )

    try:
        devices = list_connected_devices(settings.ADB_PATH)
        online_devices = [device for device in devices if device.get("is_online")]

        remote_candidates = 0
        pull_attempted = 0
        pull_failed = 0
        pulled_success_items: list[dict[str, Any]] = []
        pull_errors: list[dict[str, Any]] = []

        for device in online_devices:
            device_serial = str(device["serial"])
            remote_items = list_remote_images(device_serial, list(settings.MOBILE_REMOTE_ROOTS))
            remote_candidates += len(remote_items)
            pulled_items = pull_images(device_serial, remote_items, settings.MOBILE_INBOX_DIR)

            for pulled in pulled_items:
                pull_attempted += 1
                if pulled.get("pull_ok"):
                    pulled_success_items.append(pulled)
                else:
                    pull_failed += 1
                    pull_errors.append(
                        {
                            "device_serial": device_serial,
                            "source_uri": pulled.get("source_uri"),
                            "error_message": pulled.get("error_message"),
                        }
                    )

        register_stats = {"inserted": 0, "skipped": 0, "failed": 0}
        if pulled_success_items:
            register_stats = register_ingested_items(db, pulled_success_items)

        finished_at = _utc_now_iso()
        result = {
            "status": "ok",
            "started_at": started_at,
            "finished_at": finished_at,
            "devices_total": len(devices),
            "devices_online": len(online_devices),
            "remote_candidates": remote_candidates,
            "pulled": len(pulled_success_items),
            "inserted": register_stats["inserted"],
            "skipped": register_stats["skipped"],
            "failed": pull_failed + register_stats["failed"],
            "pull_attempted": pull_attempted,
            "pull_failed": pull_failed,
            "register_failed": register_stats["failed"],
            "errors": pull_errors,
        }
        _set_sync_status(
            is_running=False,
            last_finished_at=finished_at,
            last_result=result,
            last_error=None,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        finished_at = _utc_now_iso()
        error_result = {
            "status": "error",
            "started_at": started_at,
            "finished_at": finished_at,
            "error": str(exc),
        }
        _set_sync_status(
            is_running=False,
            last_finished_at=finished_at,
            last_result=error_result,
            last_error=str(exc),
        )
        return error_result
    finally:
        _sync_lock.release()


def _run_sync_background_worker() -> None:
    db = SessionLocal()
    try:
        run_sync_once(db)
    finally:
        db.close()


def run_sync_background() -> dict[str, Any]:
    with _sync_start_lock:
        status = get_sync_status()
        if status.get("is_running") or _sync_lock.locked():
            return {
                "status": "already_running",
                "message": "mobile sync is already running",
            }

        started_at = _utc_now_iso()
        _set_sync_status(
            is_running=True,
            last_started_at=started_at,
            last_error=None,
        )

        worker = threading.Thread(
            target=_run_sync_background_worker,
            name="slide-scanner-mobile-sync",
            daemon=True,
        )
        try:
            worker.start()
        except Exception as exc:  # noqa: BLE001
            _set_sync_status(is_running=False, last_error=str(exc))
            return {
                "status": "error",
                "error": str(exc),
            }
        return {
            "status": "started",
            "started_at": started_at,
        }


__all__ = [
    "get_sync_status",
    "list_connected_devices",
    "list_remote_images",
    "pull_images",
    "run_sync_background",
    "run_sync_once",
]
