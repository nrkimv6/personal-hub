"""Expo 운영 콘솔 집계 서비스."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, settings
from app.models import CrawledPage, CrawlRequest, Event, Popup
from app.modules.instagram.services.worker_status_service import WorkerStatusService
from app.schemas.expo import (
    ExpoCollectionPreviewItem,
    ExpoCollectionStatusResponse,
    ExpoExportPayload,
    ExpoExportRecordResponse,
    ExpoPipelineStatusResponse,
    ExpoPublishedStatusResponse,
    ExpoSeedDocument,
    ExpoWorkerStatusSummary,
)
from app.services.collect_service import CollectService
from app.shared.io.json_store import read_json, write_json_atomic

logger = logging.getLogger("expo.service")


class ExpoNotFoundError(ValueError):
    """알 수 없는 expo slug."""


class ExpoService:
    """Expo 운영 상태 집계 및 export 기록 관리."""

    def __init__(self, db: Session):
        self.db = db

    def load_seed_map(self, slug: str) -> dict[str, Any]:
        path = self._seed_path(slug)
        payload = read_json(path, default=None)
        if payload is None:
            raise ExpoNotFoundError(f"Unknown expo slug: {slug}")
        ExpoSeedDocument.model_validate(payload)
        return payload

    def record_export(self, slug: str, payload: ExpoExportPayload) -> ExpoExportRecordResponse:
        seed = self.load_seed_map(slug)
        if payload.slug != slug:
            raise ValueError("payload slug mismatch")

        record = payload.model_dump(mode="json")
        record["booth_count"] = len(payload.booths)
        record["recorded_at"] = datetime.now().isoformat()
        record["admin_url"] = self._build_admin_url(slug)
        write_json_atomic(self._export_record_path(slug), record)

        return ExpoExportRecordResponse(
            slug=slug,
            version=payload.version,
            title=payload.title or seed.get("title", slug),
            exported_at=payload.exported_at,
            booth_count=len(payload.booths),
            admin_url=record["admin_url"],
        )

    def get_published_status(self, slug: str) -> ExpoPublishedStatusResponse:
        self.load_seed_map(slug)

        checked_at = datetime.now()
        admin_url = self._build_admin_url(slug)
        base_url = (settings.ADMIN_TOOLS_BASE_URL or "").strip().rstrip("/")

        if not base_url:
            return ExpoPublishedStatusResponse(
                slug=slug,
                status="unknown",
                checked_at=checked_at,
                admin_url=admin_url,
                source="fallback",
                detail="ADMIN_TOOLS_BASE_URL not configured",
            )

        inferred_status_url = f"{base_url}/api/v1/expo/{slug}/published-status"
        try:
            response = httpx.get(inferred_status_url, timeout=5.0)
            response.raise_for_status()
            payload = response.json()
            status = payload.get("status")
            if status not in {"published", "draft", "unknown"}:
                status = "unknown"
            last_published_at = self._coerce_datetime(payload.get("last_published_at"))
            return ExpoPublishedStatusResponse(
                slug=slug,
                status=status,
                checked_at=checked_at,
                last_published_at=last_published_at,
                admin_url=payload.get("admin_url") or admin_url,
                source="remote",
                detail=payload.get("detail"),
            )
        except Exception as exc:
            logger.info("admin-tools published status fallback: slug=%s error=%s", slug, exc)
            return ExpoPublishedStatusResponse(
                slug=slug,
                status="unknown",
                checked_at=checked_at,
                admin_url=admin_url,
                source="fallback",
                detail="admin-tools status unavailable",
            )

    def get_pipeline_status(self, slug: str) -> ExpoPipelineStatusResponse:
        seed = self.load_seed_map(slug)
        record = self._read_export_record(slug)
        published_status = self.get_published_status(slug)

        booth_seed_count = len(seed.get("booths", []))
        time_slot_count = len(seed.get("timeSlots", []))
        event_count = self.db.query(func.count(Event.id)).scalar() or 0
        popup_count = self.db.query(func.count(Popup.id)).scalar() or 0

        return ExpoPipelineStatusResponse(
            slug=slug,
            title=seed.get("title", slug),
            booth_seed_count=booth_seed_count,
            time_slot_count=time_slot_count,
            event_count=event_count,
            popup_count=popup_count,
            last_exported_at=self._coerce_datetime(record.get("exported_at")),
            last_export_booth_count=int(record.get("booth_count") or 0),
            published_status=published_status,
            worker=self._get_worker_summary(),
        )

    def get_collection_status(self, slug: str) -> ExpoCollectionStatusResponse:
        seed = self.load_seed_map(slug)
        collect_service = CollectService(self.db)
        summary = collect_service.get_recent_crawl_summary(hours=24)
        previews = collect_service.get_recent_source_previews(limit=5)
        record = self._read_export_record(slug)
        published_status = self.get_published_status(slug)

        return ExpoCollectionStatusResponse(
            slug=slug,
            title=seed.get("title", slug),
            recent_completed_requests=summary["recent_completed_requests"],
            failed_request_count=summary["failed_request_count"],
            pending_request_count=summary["pending_request_count"],
            matching_pending_count=summary["matching_pending_count"],
            last_collected_at=summary["last_collected_at"],
            last_exported_at=self._coerce_datetime(record.get("exported_at")),
            published_status=published_status,
            worker=self._get_worker_summary(),
            recent_sources=[ExpoCollectionPreviewItem(**preview) for preview in previews],
        )

    def _read_export_record(self, slug: str) -> dict[str, Any]:
        self.load_seed_map(slug)
        return read_json(self._export_record_path(slug), default={})

    def _seed_path(self, slug: str) -> Path:
        return PROJECT_ROOT / "frontend" / "src" / "routes" / "expo" / slug / "expo-data.json"

    def _export_record_path(self, slug: str) -> Path:
        return Path(settings.DATA_DIR) / "expo" / slug / "export-record.json"

    def _build_admin_url(self, slug: str) -> str | None:
        base_url = (settings.ADMIN_TOOLS_BASE_URL or "").strip().rstrip("/")
        if not base_url:
            return None
        return f"{base_url}/expo/{slug}"

    def _get_worker_summary(self) -> ExpoWorkerStatusSummary:
        health = WorkerStatusService(self.db).check_health()
        status = health.get("status")
        if status not in {"healthy", "warning", "dead", "no_worker"}:
            status = "unknown"

        return ExpoWorkerStatusSummary(
            status=status,
            current_state=health.get("current_state"),
            heartbeat_age_seconds=health.get("heartbeat_age_seconds"),
            last_heartbeat=self._coerce_datetime(health.get("last_heartbeat")),
            message=health.get("message") or "No worker status available",
        )

    @staticmethod
    def _coerce_datetime(value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None
