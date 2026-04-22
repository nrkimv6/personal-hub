"""Pydantic schemas for MP4 -> GIF APIs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Mp4GifTaskStatus = Literal["queued", "running", "completed", "failed"]


class Mp4GifTaskAcceptedResponse(BaseModel):
    task_id: str
    status: Mp4GifTaskStatus


class Mp4GifTaskStatusResponse(BaseModel):
    task_id: str
    status: Mp4GifTaskStatus
    source_name: str
    fps: int
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Mp4GifHealthResponse(BaseModel):
    ffmpeg_ok: bool
    ffmpeg_path: str | None = None
    work_root: str
    work_root_exists: bool
    max_upload_mb: int = Field(..., ge=1)
    error_message: str | None = None
