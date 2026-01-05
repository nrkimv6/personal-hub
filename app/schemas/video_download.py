"""
VideoDownload 스키마 (Pydantic) - 비디오 다운로드 요청 관리
"""
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional, Literal


# 다운로드 타입 정의
DownloadType = Literal["youtube", "youtube_stream", "vimeo"]

# 상태 정의
DownloadStatus = Literal["pending", "picked", "processing", "completed", "failed", "cancelled"]


class VideoDownloadBase(BaseModel):
    """VideoDownload 기본 스키마"""
    url: str
    download_type: DownloadType


class VideoDownloadCreate(VideoDownloadBase):
    """VideoDownload 생성 스키마"""
    quality: Optional[str] = "best"
    embedding_url: Optional[str] = None  # Vimeo용
    output_filename: Optional[str] = None


class VideoDownloadUpdate(BaseModel):
    """VideoDownload 수정 스키마"""
    status: Optional[DownloadStatus] = None
    progress: Optional[int] = None
    output_path: Optional[str] = None
    file_size: Optional[int] = None
    title: Optional[str] = None
    error_message: Optional[str] = None


class VideoDownloadResponse(VideoDownloadBase):
    """VideoDownload 응답 스키마"""
    id: int
    status: DownloadStatus
    quality: str
    embedding_url: Optional[str] = None
    output_filename: Optional[str] = None
    progress: int
    output_path: Optional[str] = None
    file_size: Optional[int] = None
    title: Optional[str] = None
    picked_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    worker_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class VideoDownloadList(BaseModel):
    """VideoDownload 목록 응답"""
    items: list[VideoDownloadResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class VideoDownloadCreateRequest(BaseModel):
    """다운로드 요청 API 엔드포인트용"""
    url: str
    download_type: Optional[DownloadType] = None  # 자동 감지 가능
    quality: Optional[str] = "best"
    embedding_url: Optional[str] = None  # Vimeo용
    output_filename: Optional[str] = None


class VideoDownloadCreateResponse(BaseModel):
    """다운로드 요청 생성 응답"""
    success: bool
    download_id: int
    url: str
    download_type: DownloadType
    status: DownloadStatus
    message: str


class VideoDownloadStats(BaseModel):
    """다운로드 통계 응답"""
    total: int
    pending: int
    picked: int
    processing: int
    completed: int
    failed: int
    cancelled: int


class VideoDownloadBatchCreate(BaseModel):
    """배치 다운로드 요청 스키마"""
    urls: list[str]
    download_type: Optional[DownloadType] = None  # 자동 감지 또는 지정
    quality: str = "best"
    embedding_url: Optional[str] = None  # Vimeo용 (전체 URL에 적용)
    output_prefix: Optional[str] = None  # 파일명 접두사 (선택)


class VideoDownloadBatchResponse(BaseModel):
    """배치 다운로드 요청 응답 스키마"""
    success: bool
    created_count: int
    skipped_count: int  # 중복 URL
    download_ids: list[int]
    message: str
