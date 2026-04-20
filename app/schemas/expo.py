"""Expo 운영 콘솔 API 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ExpoExportPin(BaseModel):
    xNorm: float
    yNorm: float


class ExpoExportBooth(BaseModel):
    id: str
    name: str
    pin: ExpoExportPin


class ExpoExportPayload(BaseModel):
    version: str
    slug: str
    title: str
    exported_at: datetime
    booths: list[ExpoExportBooth]


class ExpoExportRecordResponse(BaseModel):
    slug: str
    version: str
    title: str
    exported_at: datetime
    booth_count: int
    admin_url: str | None = None


class ExpoWorkerStatusSummary(BaseModel):
    status: Literal["healthy", "warning", "dead", "no_worker", "unknown"]
    current_state: str | None = None
    heartbeat_age_seconds: int | None = None
    last_heartbeat: datetime | None = None
    message: str


class ExpoPublishedStatusResponse(BaseModel):
    slug: str
    status: Literal["published", "draft", "unknown"]
    checked_at: datetime
    last_published_at: datetime | None = None
    admin_url: str | None = None
    source: Literal["remote", "fallback"] = "fallback"
    detail: str | None = None


class ExpoPipelineStatusResponse(BaseModel):
    slug: str
    title: str
    booth_seed_count: int
    time_slot_count: int
    event_count: int
    popup_count: int
    last_exported_at: datetime | None = None
    last_export_booth_count: int = 0
    published_status: ExpoPublishedStatusResponse
    worker: ExpoWorkerStatusSummary


class ExpoCollectionPreviewItem(BaseModel):
    title: str
    url: str
    url_type: str
    collected_at: datetime
    match_status: Literal["event", "popup", "matching_pending", "analysis_pending"]


class ExpoCollectionStatusResponse(BaseModel):
    slug: str
    title: str
    recent_completed_requests: int
    failed_request_count: int
    pending_request_count: int
    matching_pending_count: int
    last_collected_at: datetime | None = None
    last_exported_at: datetime | None = None
    published_status: ExpoPublishedStatusResponse
    worker: ExpoWorkerStatusSummary
    recent_sources: list[ExpoCollectionPreviewItem]


class ExpoSeedDocument(BaseModel):
    slug: str
    title: str
    booths: list[dict]
    timeSlots: list[dict]

    model_config = ConfigDict(extra="allow")
