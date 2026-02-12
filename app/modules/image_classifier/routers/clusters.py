"""
시간 클러스터 관리 API

- GET /api/ic/clusters: 클러스터 목록 조회
- GET /api/ic/clusters/{id}: 클러스터 상세 조회
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import datetime

from ..database import get_db

router = APIRouter(prefix="/clusters", tags=["Clusters"])


class ClusterSummary(BaseModel):
    """클러스터 요약"""
    cluster_id: int
    start_time: datetime
    end_time: datetime
    file_count: int
    duration_minutes: int
    category_path: Optional[str]


class ClusterFileResponse(BaseModel):
    """클러스터 내 파일"""
    file_id: int
    file_path: str
    capture_time: datetime
    thumbnail_url: Optional[str]


class ClusterDetailResponse(BaseModel):
    """클러스터 상세"""
    cluster_id: int
    start_time: datetime
    end_time: datetime
    file_count: int
    duration_minutes: int
    category_path: Optional[str]
    files: list[ClusterFileResponse]


@router.get("")
async def get_clusters(
    limit: int = 100,
    db: Session = Depends(get_db)
) -> list[ClusterSummary]:
    """클러스터 목록 조회"""

    result = db.execute(text("""
        SELECT
            tc.id,
            tc.start_time,
            tc.end_time,
            tc.file_count,
            tc.duration_minutes,
            c.full_path
        FROM time_clusters tc
        LEFT JOIN categories c ON tc.category_id = c.id
        ORDER BY tc.start_time DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    return [
        ClusterSummary(
            cluster_id=row[0],
            start_time=row[1],
            end_time=row[2],
            file_count=row[3],
            duration_minutes=row[4],
            category_path=row[5]
        )
        for row in result
    ]


@router.get("/{cluster_id}")
async def get_cluster_detail(
    cluster_id: int,
    db: Session = Depends(get_db)
) -> ClusterDetailResponse:
    """클러스터 상세 조회"""

    # 클러스터 기본 정보
    cluster_row = db.execute(text("""
        SELECT
            tc.id,
            tc.start_time,
            tc.end_time,
            tc.file_count,
            tc.duration_minutes,
            c.full_path
        FROM time_clusters tc
        LEFT JOIN categories c ON tc.category_id = c.id
        WHERE tc.id = :cluster_id
    """), {"cluster_id": cluster_id}).fetchone()

    if not cluster_row:
        raise HTTPException(status_code=404, detail="클러스터를 찾을 수 없습니다")

    # 클러스터 내 파일 목록
    files_result = db.execute(text("""
        SELECT
            f.id,
            f.file_path,
            f.capture_time
        FROM files f
        WHERE f.time_cluster_id = :cluster_id
        ORDER BY f.capture_time ASC
    """), {"cluster_id": cluster_id}).fetchall()

    files = [
        ClusterFileResponse(
            file_id=row[0],
            file_path=row[1],
            capture_time=row[2],
            thumbnail_url=f"/api/ic/files/{row[0]}/thumbnail"
        )
        for row in files_result
    ]

    return ClusterDetailResponse(
        cluster_id=cluster_row[0],
        start_time=cluster_row[1],
        end_time=cluster_row[2],
        file_count=cluster_row[3],
        duration_minutes=cluster_row[4],
        category_path=cluster_row[5],
        files=files
    )
