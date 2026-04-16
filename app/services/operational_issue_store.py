"""
운영 장애 이력 저장소.

DB 연결 장애처럼 error_logs 테이블에 바로 저장할 수 없는 상황을 위해
파일(JSONL)에도 운영 장애 이력을 남긴다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
import traceback as tb
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger(__name__)


class OperationalIssueSource:
    DATABASE = "database"
    MIGRATION = "migration"


class OperationalIssueStore:
    FILE_PATH = Path("logs") / "operational-issues.jsonl"
    MAX_MESSAGE_LENGTH = 2000
    MAX_TRACEBACK_LENGTH = 12000
    MAX_CONTEXT_LENGTH = 4000

    @classmethod
    def _make_serializable(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (list, tuple)):
            return [cls._make_serializable(item) for item in value]
        if isinstance(value, dict):
            return {str(k): cls._make_serializable(v) for k, v in value.items()}
        return str(value)

    @classmethod
    def _build_record(
        cls,
        *,
        error: Exception,
        source: str,
        severity: str,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc)
        safe_context = cls._make_serializable(context or {})
        context_text = json.dumps(safe_context, ensure_ascii=False)[: cls.MAX_CONTEXT_LENGTH]
        fingerprint_source = f"{source}|{severity}|{type(error).__name__}|{str(error)[:300]}|{context_text}"
        fingerprint = hashlib.sha1(fingerprint_source.encode("utf-8")).hexdigest()

        return {
            "id": f"{int(created_at.timestamp() * 1000)}-{fingerprint[:8]}",
            "created_at": created_at.isoformat(),
            "source": source,
            "severity": severity,
            "error_type": type(error).__name__,
            "message": str(error)[: cls.MAX_MESSAGE_LENGTH],
            "traceback": "".join(
                tb.format_exception(type(error), error, error.__traceback__)
            )[: cls.MAX_TRACEBACK_LENGTH],
            "context": safe_context,
            "fingerprint": fingerprint,
        }

    @classmethod
    def record(
        cls,
        *,
        error: Exception,
        source: str,
        severity: str,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        record = cls._build_record(
            error=error,
            source=source,
            severity=severity,
            context=context,
        )
        cls.FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with cls.FILE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    @classmethod
    def list(
        cls,
        *,
        source: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not cls.FILE_PATH.exists():
            return []

        items: list[dict[str, Any]] = []
        search_lower = search.lower() if search else None

        with cls.FILE_PATH.open("r", encoding="utf-8") as f:
            for line in reversed(f.readlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if source and item.get("source") != source:
                    continue

                if search_lower:
                    haystack = " ".join(
                        [
                            str(item.get("error_type") or ""),
                            str(item.get("message") or ""),
                            json.dumps(item.get("context") or {}, ensure_ascii=False),
                        ]
                    ).lower()
                    if search_lower not in haystack:
                        continue

                items.append(item)
                if len(items) >= limit:
                    break

        return items


class OperationalIssueReporter:
    ALERT_COOLDOWN_SECONDS = 300.0
    _alert_lock = threading.Lock()
    _recent_alerts: dict[str, float] = {}
    _local = threading.local()

    @classmethod
    def report(
        cls,
        *,
        error: Exception,
        source: str,
        severity: str,
        context: Optional[dict[str, Any]] = None,
        notify: bool = True,
        persist_error_log: bool = True,
    ) -> dict[str, Any]:
        # error_logs 저장 중 DB 예외가 다시 발생할 수 있으므로 재진입은 무시한다.
        if getattr(cls._local, "active", False):
            return {"skipped": True, "reason": "reentrant"}

        cls._local.active = True
        try:
            record = OperationalIssueStore.record(
                error=error,
                source=source,
                severity=severity,
                context=context,
            )

            if persist_error_log:
                try:
                    from app.services.error_collector import ErrorCollector

                    ErrorCollector.capture_sync(
                        error=error,
                        source=source,
                        severity=severity,
                        context=context,
                        notify=False,
                    )
                except Exception as db_store_error:
                    logger.debug("error_logs 저장 실패 (fallback 유지): %s", db_store_error)

            if notify and cls._should_notify(record):
                cls._send_telegram(record)

            return record
        finally:
            cls._local.active = False

    @classmethod
    def _should_notify(cls, record: dict[str, Any]) -> bool:
        now = time.monotonic()
        fingerprint = str(record.get("fingerprint") or "")

        with cls._alert_lock:
            expired = [
                key for key, sent_at in cls._recent_alerts.items()
                if now - sent_at > cls.ALERT_COOLDOWN_SECONDS
            ]
            for key in expired:
                cls._recent_alerts.pop(key, None)

            last_sent = cls._recent_alerts.get(fingerprint)
            if last_sent and now - last_sent <= cls.ALERT_COOLDOWN_SECONDS:
                return False

            cls._recent_alerts[fingerprint] = now
            return True

    @classmethod
    def _send_telegram(cls, record: dict[str, Any]) -> None:
        try:
            from app.shared.notification import NotificationService

            message = (
                "[Operational issue]\n"
                f"Source: {record.get('source')}\n"
                f"Severity: {record.get('severity')}\n"
                f"Type: {record.get('error_type')}\n"
                f"Message: {str(record.get('message') or '')[:500]}\n"
                f"Time: {record.get('created_at')}"
            )

            notification_service = NotificationService()

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        notification_service.send_telegram(message, force_send=True)
                    )
                else:
                    loop.run_until_complete(
                        notification_service.send_telegram(message, force_send=True)
                    )
            except RuntimeError:
                asyncio.run(
                    notification_service.send_telegram(message, force_send=True)
                )
        except Exception as notify_error:
            logger.warning("운영 장애 텔레그램 알림 실패: %s", notify_error)
