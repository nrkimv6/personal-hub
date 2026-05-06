"""Pydantic schemas for MP4 -> GIF APIs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Mp4GifTaskStatus = Literal["queued", "running", "completed", "failed"]

# 허용하는 overwrite 모드 목록 (route 상수와 일치시킨다)
OverwriteMode = Literal["overwrite", "suffix", "fail_if_exists"]


class Mp4GifTaskAcceptedResponse(BaseModel):
    task_id: str
    status: Mp4GifTaskStatus


class Mp4GifTaskStatusResponse(BaseModel):
    task_id: str
    status: Mp4GifTaskStatus
    source_name: str
    fps: int
    width: int | None = None
    start_seconds: float | None = None
    duration_seconds: float | None = None
    overwrite_mode: OverwriteMode = "overwrite"
    download_filename: str | None = None
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
