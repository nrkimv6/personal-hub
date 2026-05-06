"""비디오 다운로드 API 라우트.

YouTube/Vimeo/Instagram Reel 다운로드 요청 관리 API를 제공합니다.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import VideoDownload
from app.services.video_download_service import VideoDownloadService
from app.schemas.video_download import (
    VideoDownloadResponse,
    VideoDownloadList,
    VideoDownloadCreateRequest,
    VideoDownloadCreateResponse,
    VideoDownloadStats,
    VideoDownloadBatchCreate,
    VideoDownloadBatchResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/video-downloads", tags=["video-downloads"])


@router.post("", response_model=VideoDownloadCreateResponse)
async def create_download_request(
    body: VideoDownloadCreateRequest,
    db: Session = Depends(get_db),
):
    """
    비디오 다운로드 요청 생성

    - url: 비디오 URL (YouTube/Vimeo/Instagram Reel)
    - download_type: 다운로드 타입 (youtube/youtube_stream/vimeo/instagram), 미지정 시 자동 감지
    - quality: 화질 설정 (기본: best)
    - embedding_url: Vimeo 임베딩 URL (도메인 제한 우회용)
    - output_filename: 사용자 지정 파일명
    """
    try:
        service = VideoDownloadService(db)

        # 동일 URL의 pending 요청이 있는지 확인
        if service.has_pending_for_url(body.url):
            raise HTTPException(
                status_code=400,
                detail="동일 URL에 대한 대기 중인 요청이 있습니다."
            )

        request = service.create_request(
            url=body.url,
            download_type=body.download_type,
            quality=body.quality,
            embedding_url=body.embedding_url,
            output_filename=body.output_filename
        )

        return VideoDownloadCreateResponse(
            success=True,
            download_id=request.id,
            url=request.url,
            download_type=request.download_type,
            status=request.status,
            message=f"다운로드 요청이 생성되었습니다. (타입: {request.download_type})"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"다운로드 요청 생성 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="다운로드 요청 생성에 실패했습니다.")


@router.post("/batch", response_model=VideoDownloadBatchResponse)
async def create_batch_download_request(
    body: VideoDownloadBatchCreate,
    db: Session = Depends(get_db),
):
    """
    배치 다운로드 요청 생성 (여러 URL 동시 등록)

    - urls: 비디오 URL 목록
    - download_type: 다운로드 타입 (미지정 시 URL별 자동 감지)
    - quality: 화질 설정 (기본: best)
    - embedding_url: Vimeo 임베딩 URL (모든 Vimeo URL에 적용)
    - output_prefix: 파일명 접두사 (선택, 예: "course_01_")
    """
    try:
        if not body.urls:
            raise HTTPException(status_code=400, detail="URL 목록이 비어있습니다.")

        service = VideoDownloadService(db)
        created_requests, skipped_count = service.create_batch_requests(
            urls=body.urls,
            download_type=body.download_type,
            quality=body.quality,
            embedding_url=body.embedding_url,
            output_prefix=body.output_prefix
        )

        created_count = len(created_requests)
        download_ids = [r.id for r in created_requests]

        if created_count == 0 and skipped_count > 0:
            message = f"모든 URL이 중복되어 스킵되었습니다. ({skipped_count}개)"
        elif skipped_count > 0:
            message = f"{created_count}개 요청 생성, {skipped_count}개 중복 스킵"
        else:
            message = f"{created_count}개 다운로드 요청이 생성되었습니다."

        return VideoDownloadBatchResponse(
            success=created_count > 0,
            created_count=created_count,
            skipped_count=skipped_count,
            download_ids=download_ids,
            message=message
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"배치 다운로드 요청 생성 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="배치 다운로드 요청 생성에 실패했습니다.")


@router.get("", response_model=VideoDownloadList)
async def list_download_requests(
    status: Optional[str] = Query(None, description="상태 필터 (pending/processing/completed/failed/cancelled)"),
    download_type: Optional[str] = Query(None, description="다운로드 타입 필터 (youtube/youtube_stream/vimeo/instagram)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    다운로드 요청 목록 조회

    페이징 및 필터링 지원
    """
    service = VideoDownloadService(db)
    result = service.get_requests_paginated(
        page=page,
        page_size=page_size,
        download_type=download_type,
        status=status
    )

    return VideoDownloadList(
        items=[VideoDownloadResponse.model_validate(r) for r in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"]
    )


@router.get("/stats", response_model=VideoDownloadStats)
async def get_download_stats(
    db: Session = Depends(get_db),
):
    """
    다운로드 통계 조회 (상태별 요청 수)
    """
    service = VideoDownloadService(db)
    return service.get_stats()


@router.get("/active")
async def list_active_downloads(
    download_type: Optional[str] = Query(None, description="다운로드 타입 필터"),
    db: Session = Depends(get_db),
):
    """
    활성 다운로드 목록 조회 (pending/picked/processing)
    """
    service = VideoDownloadService(db)
    active = service.get_active_requests(download_type)

    return {
        "items": [VideoDownloadResponse.model_validate(r) for r in active],
        "total": len(active)
    }


@router.get("/{download_id}", response_model=VideoDownloadResponse)
async def get_download_request(
    download_id: int,
    db: Session = Depends(get_db),
):
    """
    다운로드 요청 상세 조회
    """
    service = VideoDownloadService(db)
    request = service.get_request_by_id(download_id)
    if not request:
        raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다.")

    return VideoDownloadResponse.model_validate(request)


@router.delete("/{download_id}")
async def cancel_download_request(
    download_id: int,
    db: Session = Depends(get_db),
):
    """
    다운로드 요청 취소

    pending/picked/processing 상태의 요청만 취소 가능
    """
    service = VideoDownloadService(db)
    request = service.get_request_by_id(download_id)

    if not request:
        raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다.")

    if request.status in [VideoDownload.STATUS_COMPLETED, VideoDownload.STATUS_FAILED, VideoDownload.STATUS_CANCELLED]:
        raise HTTPException(
            status_code=400,
            detail=f"이미 완료된 요청은 취소할 수 없습니다. (상태: {request.status})"
        )

    cancelled = service.cancel_request(download_id)
    if not cancelled:
        raise HTTPException(status_code=400, detail="요청 취소에 실패했습니다.")

    return {"success": True, "message": "다운로드 요청이 취소되었습니다."}


@router.delete("/{download_id}/remove")
async def delete_download_request(
    download_id: int,
    db: Session = Depends(get_db),
):
    """
    다운로드 요청 삭제 (완료/실패/취소된 요청만)
    """
    service = VideoDownloadService(db)
    deleted = service.delete_request(download_id)

    if not deleted:
        raise HTTPException(
            status_code=400,
            detail="삭제할 수 없는 요청입니다. (활성 상태이거나 존재하지 않음)"
        )

    return {"success": True, "message": "다운로드 요청이 삭제되었습니다."}


@router.post("/{download_id}/retry")
async def retry_download_request(
    download_id: int,
    db: Session = Depends(get_db),
):
    """
    실패한 다운로드 요청 재시도

    failed/cancelled 상태의 요청만 재시도 가능
    - 상태를 pending으로 재설정
    - progress=0, error_message=None 초기화
    """
    service = VideoDownloadService(db)
    request = service.get_request_by_id(download_id)

    if not request:
        raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다.")

    if request.status not in [VideoDownload.STATUS_FAILED, VideoDownload.STATUS_CANCELLED]:
        raise HTTPException(
            status_code=400,
            detail=f"재시도할 수 없는 상태입니다. (상태: {request.status})"
        )

    retried = service.retry_request(download_id)
    if not retried:
        raise HTTPException(status_code=400, detail="재시도에 실패했습니다.")

    return {"success": True, "message": "다운로드 요청이 재시도 대기열에 추가되었습니다."}
