"""비디오 다운로드 요청 서비스."""

import re
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session

from app.models import VideoDownload


class VideoDownloadService:
    """비디오 다운로드 요청 관리 서비스."""

    def __init__(self, db: Session):
        self.db = db

    def detect_download_type(self, url: str) -> str:
        """URL에서 다운로드 타입 자동 감지.

        Args:
            url: 비디오 URL

        Returns:
            다운로드 타입 (youtube, youtube_stream, vimeo)
        """
        url_lower = url.lower()

        if 'vimeo.com' in url_lower or 'player.vimeo.com' in url_lower:
            return VideoDownload.TYPE_VIMEO
        elif 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            # 라이브 스트림 감지 (live 키워드가 있으면)
            if '/live/' in url_lower or 'live' in url_lower:
                return VideoDownload.TYPE_YOUTUBE_STREAM
            return VideoDownload.TYPE_YOUTUBE

        # 기본값은 YouTube VOD
        return VideoDownload.TYPE_YOUTUBE

    def create_request(
        self,
        url: str,
        download_type: Optional[str] = None,
        quality: str = "best",
        embedding_url: Optional[str] = None,
        output_filename: Optional[str] = None
    ) -> VideoDownload:
        """새 다운로드 요청 생성.

        Args:
            url: 비디오 URL
            download_type: 다운로드 타입 (None이면 자동 감지)
            quality: 화질 설정
            embedding_url: Vimeo 임베딩 URL
            output_filename: 사용자 지정 파일명

        Returns:
            생성된 VideoDownload 객체
        """
        if not download_type:
            download_type = self.detect_download_type(url)

        request = VideoDownload(
            url=url,
            download_type=download_type,
            quality=quality,
            embedding_url=embedding_url,
            output_filename=output_filename,
            status=VideoDownload.STATUS_PENDING,
            created_at=datetime.now()
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return request

    def get_pending_requests(
        self,
        download_type: Optional[str] = None,
        limit: int = 10
    ) -> List[VideoDownload]:
        """대기 중인 요청 조회.

        Args:
            download_type: 필터링할 다운로드 타입
            limit: 최대 조회 개수

        Returns:
            대기 중인 요청 목록
        """
        query = self.db.query(VideoDownload).filter(
            VideoDownload.status == VideoDownload.STATUS_PENDING
        )
        if download_type:
            query = query.filter(VideoDownload.download_type == download_type)
        return query.order_by(VideoDownload.created_at.asc()).limit(limit).all()

    def pick_request(self, request_id: int, worker_id: str) -> Optional[VideoDownload]:
        """요청을 워커가 가져감으로 표시.

        Args:
            request_id: 요청 ID
            worker_id: 워커 ID

        Returns:
            업데이트된 요청 (없으면 None)
        """
        request = self.db.query(VideoDownload).filter(
            VideoDownload.id == request_id,
            VideoDownload.status == VideoDownload.STATUS_PENDING
        ).first()

        if request:
            request.mark_picked(worker_id)
            self.db.commit()
            self.db.refresh(request)
        return request

    def start_processing(self, request_id: int) -> Optional[VideoDownload]:
        """처리 시작으로 표시.

        Args:
            request_id: 요청 ID

        Returns:
            업데이트된 요청 (없으면 None)
        """
        request = self.db.query(VideoDownload).filter(
            VideoDownload.id == request_id
        ).first()

        if request:
            request.mark_processing()
            self.db.commit()
            self.db.refresh(request)
        return request

    def update_progress(self, request_id: int, progress: int) -> Optional[VideoDownload]:
        """진행률 업데이트.

        Args:
            request_id: 요청 ID
            progress: 진행률 (0-100)

        Returns:
            업데이트된 요청 (없으면 None)
        """
        request = self.db.query(VideoDownload).filter(
            VideoDownload.id == request_id
        ).first()

        if request:
            request.update_progress(progress)
            self.db.commit()
            self.db.refresh(request)
        return request

    def complete_request(
        self,
        request_id: int,
        output_path: str,
        file_size: int = None,
        title: str = None
    ) -> Optional[VideoDownload]:
        """요청 완료 처리.

        Args:
            request_id: 요청 ID
            output_path: 저장된 파일 경로
            file_size: 파일 크기 (bytes)
            title: 비디오 제목

        Returns:
            업데이트된 요청 (없으면 None)
        """
        request = self.db.query(VideoDownload).filter(
            VideoDownload.id == request_id
        ).first()

        if request:
            request.mark_completed(output_path, file_size, title)
            self.db.commit()
            self.db.refresh(request)
        return request

    def fail_request(self, request_id: int, error_message: str) -> Optional[VideoDownload]:
        """요청 실패 처리.

        Args:
            request_id: 요청 ID
            error_message: 에러 메시지

        Returns:
            업데이트된 요청 (없으면 None)
        """
        request = self.db.query(VideoDownload).filter(
            VideoDownload.id == request_id
        ).first()

        if request:
            request.mark_failed(error_message)
            self.db.commit()
            self.db.refresh(request)
        return request

    def cancel_request(self, request_id: int) -> Optional[VideoDownload]:
        """요청 취소.

        Args:
            request_id: 요청 ID

        Returns:
            업데이트된 요청 (없으면 None)
        """
        request = self.db.query(VideoDownload).filter(
            VideoDownload.id == request_id,
            VideoDownload.status.in_([
                VideoDownload.STATUS_PENDING,
                VideoDownload.STATUS_PICKED,
                VideoDownload.STATUS_PROCESSING
            ])
        ).first()

        if request:
            request.mark_cancelled()
            self.db.commit()
            self.db.refresh(request)
        return request

    def get_request_by_id(self, request_id: int) -> Optional[VideoDownload]:
        """ID로 요청 조회.

        Args:
            request_id: 요청 ID

        Returns:
            요청 객체 (없으면 None)
        """
        return self.db.query(VideoDownload).filter(
            VideoDownload.id == request_id
        ).first()

    def get_requests_paginated(
        self,
        page: int = 1,
        page_size: int = 20,
        download_type: Optional[str] = None,
        status: Optional[str] = None
    ) -> dict:
        """요청 이력 페이징 조회.

        Args:
            page: 페이지 번호 (1부터 시작)
            page_size: 페이지당 항목 수
            download_type: 필터링할 다운로드 타입
            status: 필터링할 상태

        Returns:
            페이징된 결과 딕셔너리
        """
        query = self.db.query(VideoDownload)

        if download_type:
            query = query.filter(VideoDownload.download_type == download_type)
        if status:
            query = query.filter(VideoDownload.status == status)

        total = query.count()
        items = query.order_by(
            VideoDownload.created_at.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()

        total_pages = (total + page_size - 1) // page_size

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }

    def cleanup_stale_processing(self, timeout_minutes: int = 60) -> int:
        """오래된 processing/picked 상태 요청을 failed로 정리.

        워커가 비정상 종료되면 요청이 processing 상태로 남을 수 있음.
        비디오 다운로드는 오래 걸릴 수 있으므로 기본 60분.

        Args:
            timeout_minutes: 상태 유지 시간 제한

        Returns:
            정리된 요청 수
        """
        cutoff = datetime.now() - timedelta(minutes=timeout_minutes)

        stale_requests = self.db.query(VideoDownload).filter(
            VideoDownload.status.in_([
                VideoDownload.STATUS_PROCESSING,
                VideoDownload.STATUS_PICKED
            ]),
            VideoDownload.picked_at < cutoff
        ).all()

        count = 0
        for request in stale_requests:
            request.mark_failed(f"Timeout: {request.status} 상태가 {timeout_minutes}분 초과")
            count += 1

        if count > 0:
            self.db.commit()

        return count

    def has_pending_for_url(self, url: str) -> bool:
        """동일 URL에 대한 pending 요청이 있는지 확인.

        Args:
            url: 비디오 URL

        Returns:
            중복 여부
        """
        return self.db.query(VideoDownload).filter(
            VideoDownload.url == url,
            VideoDownload.status == VideoDownload.STATUS_PENDING
        ).first() is not None

    def get_active_requests(
        self,
        download_type: Optional[str] = None
    ) -> List[VideoDownload]:
        """활성 상태(pending, picked, processing) 요청 조회.

        Args:
            download_type: 필터링할 다운로드 타입

        Returns:
            활성 요청 목록
        """
        query = self.db.query(VideoDownload).filter(
            VideoDownload.status.in_([
                VideoDownload.STATUS_PENDING,
                VideoDownload.STATUS_PICKED,
                VideoDownload.STATUS_PROCESSING
            ])
        )
        if download_type:
            query = query.filter(VideoDownload.download_type == download_type)
        return query.order_by(VideoDownload.created_at.asc()).all()

    def delete_request(self, request_id: int) -> bool:
        """요청 삭제 (completed 또는 failed/cancelled 상태만).

        Args:
            request_id: 요청 ID

        Returns:
            삭제 성공 여부
        """
        request = self.db.query(VideoDownload).filter(
            VideoDownload.id == request_id,
            VideoDownload.status.in_([
                VideoDownload.STATUS_COMPLETED,
                VideoDownload.STATUS_FAILED,
                VideoDownload.STATUS_CANCELLED
            ])
        ).first()

        if request:
            self.db.delete(request)
            self.db.commit()
            return True
        return False

    def get_stats(self) -> dict:
        """다운로드 통계 조회.

        Returns:
            상태별 요청 수 통계
        """
        from sqlalchemy import func

        stats = self.db.query(
            VideoDownload.status,
            func.count(VideoDownload.id)
        ).group_by(VideoDownload.status).all()

        result = {
            "total": 0,
            "pending": 0,
            "picked": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0
        }

        for status, count in stats:
            if status in result:
                result[status] = count
            result["total"] += count

        return result
