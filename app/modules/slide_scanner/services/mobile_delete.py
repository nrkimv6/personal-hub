"""Remote delete safety helpers for mobile ingest pipeline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath
from typing import Any

from send2trash import send2trash

from sqlalchemy import text
from sqlalchemy.orm import Session


_SHELL_META_CHARS = (";", "&", "|", "`", "$", "\n", "\r", "\x00")


def _normalize_posix_path(raw_path: str) -> str:
    text_path = raw_path.strip().replace("\\", "/")
    if not text_path:
        return ""
    if any(char in text_path for char in _SHELL_META_CHARS):
        return ""
    pure = PurePosixPath(text_path)
    if pure.is_absolute():
        normalized = str(pure)
    else:
        normalized = f"/{pure}"
    if "/.." in normalized or normalized.endswith("/..") or normalized == "/..":
        return ""
    return normalized


def is_allowed_remote_path(remote_path: str, allowed_roots: tuple[str, ...]) -> bool:
    normalized_remote = _normalize_posix_path(remote_path)
    if not normalized_remote:
        return False

    for root in allowed_roots:
        normalized_root = _normalize_posix_path(root).rstrip("/")
        if not normalized_root:
            continue
        if normalized_remote == normalized_root:
            return True
        if normalized_remote.startswith(f"{normalized_root}/"):
            return True
    return False


def mark_remote_delete_failed(db: Session, item_id: int, error_message: str) -> None:
    db.execute(
        text(
            """
            UPDATE mobile_ingest_items
            SET remote_delete_status = 'FAILED',
                error_message = :error_message,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :item_id
            """
        ),
        {
            "item_id": item_id,
            "error_message": error_message[:500],
        },
    )
    db.commit()


def mark_remote_delete_done(db: Session, item_id: int) -> None:
    db.execute(
        text(
            """
            UPDATE mobile_ingest_items
            SET remote_delete_status = 'DONE',
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :item_id
            """
        ),
        {"item_id": item_id},
    )
    db.commit()


def guard_remote_delete_paths(
    db: Session,
    item_id: int,
    remote_paths: list[str],
    allowed_roots: tuple[str, ...],
) -> list[str]:
    allowed: list[str] = []
    for remote_path in remote_paths:
        normalized_remote = _normalize_posix_path(remote_path)
        if not normalized_remote:
            mark_remote_delete_failed(
                db=db,
                item_id=item_id,
                error_message=f"Blocked remote delete path (invalid): {remote_path}",
            )
            return []
        if not is_allowed_remote_path(normalized_remote, allowed_roots):
            mark_remote_delete_failed(
                db=db,
                item_id=item_id,
                error_message=f"Blocked remote delete path (out of allowed roots): {normalized_remote}",
            )
            return []
        allowed.append(normalized_remote)
    return allowed


def _shell_quote(value: str) -> str:
    escaped = value.replace("'", "'\"'\"'")
    return f"'{escaped}'"


def delete_remote_images(adb_path, device_serial: str, remote_paths: list[str]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    adb_path_text = str(adb_path)
    if adb_path_text.lower().endswith(".py"):
        adb_prefix = [sys.executable, adb_path_text]
    else:
        adb_prefix = [adb_path_text]
    for remote_path in remote_paths:
        shell_command = f"rm -f -- {_shell_quote(remote_path)}"
        process = subprocess.run(
            [*adb_prefix, "-s", device_serial, "shell", shell_command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        results[remote_path] = process.returncode == 0
    return results


def _fetch_mobile_item(db: Session, item_id: int):
    row = db.execute(
        text("SELECT * FROM mobile_ingest_items WHERE id = :id"),
        {"id": item_id},
    ).fetchone()
    if not row:
        raise ValueError("Mobile ingest item not found")
    return row


def process_remote_delete_for_item(
    db: Session,
    item_id: int,
    adb_path,
    allowed_roots: tuple[str, ...],
) -> dict[str, Any]:
    row = _fetch_mobile_item(db, item_id)

    if row.remote_delete_status == "DONE":
        return {
            "status": "skipped_done",
            "item_id": item_id,
            "results": {},
        }

    normalized_paths = guard_remote_delete_paths(
        db=db,
        item_id=item_id,
        remote_paths=[str(row.source_uri)],
        allowed_roots=allowed_roots,
    )
    if not normalized_paths:
        return {
            "status": "failed",
            "item_id": item_id,
            "results": {},
            "error": "blocked by remote path guard",
        }

    results = delete_remote_images(
        adb_path=adb_path,
        device_serial=str(row.device_serial),
        remote_paths=normalized_paths,
    )
    failed_paths = [path for path, ok in results.items() if not ok]
    if failed_paths:
        mark_remote_delete_failed(
            db=db,
            item_id=item_id,
            error_message=f"Remote delete failed: {', '.join(failed_paths)}",
        )
        return {
            "status": "failed",
            "item_id": item_id,
            "results": results,
            "error": "remote delete failed",
        }

    mark_remote_delete_done(db=db, item_id=item_id)
    return {
        "status": "done",
        "item_id": item_id,
        "results": results,
    }


def cleanup_local_inbox_file(db: Session, item_id: int) -> dict[str, Any]:
    row = _fetch_mobile_item(db, item_id)

    if row.local_cleanup_status == "DONE":
        return {
            "status": "skipped_done",
            "item_id": item_id,
        }

    inbox_path = str(row.pc_inbox_path)
    try:
        send2trash(inbox_path)
    except Exception as exc:  # noqa: BLE001
        db.execute(
            text(
                """
                UPDATE mobile_ingest_items
                SET local_cleanup_status = 'FAILED',
                    error_message = :error_message,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :item_id
                """
            ),
            {
                "item_id": item_id,
                "error_message": f"Local cleanup failed: {str(exc)[:450]}",
            },
        )
        db.commit()
        return {
            "status": "failed",
            "item_id": item_id,
            "error": str(exc),
        }

    db.execute(
        text(
            """
            UPDATE mobile_ingest_items
            SET local_cleanup_status = 'DONE',
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :item_id
            """
        ),
        {"item_id": item_id},
    )
    db.commit()
    return {
        "status": "done",
        "item_id": item_id,
    }


__all__ = [
    "cleanup_local_inbox_file",
    "delete_remote_images",
    "is_allowed_remote_path",
    "mark_remote_delete_done",
    "mark_remote_delete_failed",
    "guard_remote_delete_paths",
    "process_remote_delete_for_item",
]
