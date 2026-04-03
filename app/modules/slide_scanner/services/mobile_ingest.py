"""Mobile ingest helpers for slide scanner pre-gate pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_exif_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None

    value = raw.strip()
    if not value:
        return None

    # Common EXIF format: 2026:04:03 14:21:59
    try:
        parsed = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
        return parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    # ISO fallback (with or without timezone).
    try:
        parsed = datetime.fromisoformat(value)
        return _ensure_utc(parsed)
    except ValueError:
        return None


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return _ensure_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_captured_at(
    exif_dt: str | None,
    file_mtime: float | None,
    ingested_at: datetime,
) -> datetime:
    if exif_dt:
        parsed = _parse_exif_datetime(exif_dt)
        if parsed:
            return parsed

    if file_mtime is not None:
        return datetime.fromtimestamp(float(file_mtime), tz=timezone.utc)

    return _ensure_utc(ingested_at)


def build_dedupe_key(
    device_serial: str,
    source_uri: str,
    source_mtime_utc: str,
    source_size_bytes: int,
) -> str:
    payload = (
        f"{device_serial.strip()}|"
        f"{source_uri.strip()}|"
        f"{source_mtime_utc.strip()}|"
        f"{int(source_size_bytes)}"
    )
    return sha1(payload.encode("utf-8")).hexdigest()


def _resolve_source_mtime_utc(item: dict[str, Any], ingested_at: datetime) -> str:
    raw_iso = item.get("source_mtime_utc")
    parsed_iso = _parse_iso_datetime(str(raw_iso) if raw_iso is not None else None)
    if parsed_iso:
        return parsed_iso.isoformat()

    file_mtime = _as_float(item.get("source_mtime"))
    if file_mtime is not None:
        return datetime.fromtimestamp(file_mtime, tz=timezone.utc).isoformat()

    return ingested_at.isoformat()


def _normalize_ingested_item(item: dict[str, Any]) -> dict[str, Any]:
    ingested_raw = item.get("ingested_at")
    if isinstance(ingested_raw, datetime):
        ingested_at = _ensure_utc(ingested_raw)
    else:
        ingested_at = _parse_iso_datetime(str(ingested_raw) if ingested_raw is not None else None)
        if ingested_at is None:
            ingested_at = datetime.now(timezone.utc)

    device_serial = str(item.get("device_serial") or "").strip()
    if not device_serial:
        raise ValueError("device_serial is required")

    source_uri = str(item.get("source_uri") or "").strip()
    if not source_uri:
        raise ValueError("source_uri is required")

    pc_inbox_path = str(item.get("pc_inbox_path") or "").strip()
    if not pc_inbox_path:
        raise ValueError("pc_inbox_path is required")

    original_filename = str(item.get("original_filename") or "").strip()
    if not original_filename:
        original_filename = PurePosixPath(source_uri).name
    if not original_filename:
        raise ValueError("original_filename is required")

    source_mtime = _as_float(item.get("source_mtime"))
    source_mtime_utc = _resolve_source_mtime_utc(item, ingested_at)
    source_size_bytes = _as_int(item.get("source_size_bytes"))
    if source_size_bytes is None:
        source_size_bytes = 0
    if source_size_bytes < 0:
        source_size_bytes = 0

    captured_at = resolve_captured_at(
        exif_dt=str(item.get("exif_datetime") or "").strip() or None,
        file_mtime=source_mtime,
        ingested_at=ingested_at,
    )

    # Dedupe key is used in tests and future logging/telemetry; DB uniqueness is still enforced by index.
    build_dedupe_key(
        device_serial=device_serial,
        source_uri=source_uri,
        source_mtime_utc=source_mtime_utc,
        source_size_bytes=source_size_bytes,
    )

    return {
        "device_id": str(item.get("device_id") or device_serial),
        "device_serial": device_serial,
        "original_filename": original_filename,
        "source_uri": source_uri,
        "source_mtime_utc": source_mtime_utc,
        "source_size_bytes": source_size_bytes,
        "source_sha256": item.get("source_sha256"),
        "pc_inbox_path": pc_inbox_path,
        "captured_at_utc": captured_at.isoformat(),
        "ingested_at": ingested_at.isoformat(),
        "error_message": item.get("error_message"),
    }


def register_ingested_items(db: Session, pulled_items: list[dict[str, Any]]) -> dict[str, int]:
    stats = {"inserted": 0, "skipped": 0, "failed": 0}

    insert_sql = text(
        """
        INSERT OR IGNORE INTO mobile_ingest_items (
            device_id,
            device_serial,
            original_filename,
            source_uri,
            source_mtime_utc,
            source_size_bytes,
            source_sha256,
            pc_inbox_path,
            captured_at_utc,
            ingested_at,
            error_message
        ) VALUES (
            :device_id,
            :device_serial,
            :original_filename,
            :source_uri,
            :source_mtime_utc,
            :source_size_bytes,
            :source_sha256,
            :pc_inbox_path,
            :captured_at_utc,
            :ingested_at,
            :error_message
        )
        """
    )

    for item in pulled_items:
        try:
            params = _normalize_ingested_item(item)
        except Exception:
            stats["failed"] += 1
            continue

        try:
            with db.begin_nested():
                result = db.execute(insert_sql, params)
            if result.rowcount and result.rowcount > 0:
                stats["inserted"] += 1
            else:
                stats["skipped"] += 1
        except Exception:
            stats["failed"] += 1

    db.commit()
    return stats
