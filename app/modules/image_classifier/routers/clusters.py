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
    capture_time: Optional[datetime]
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
    db: Session = Depends(get_db),
):
    """클러스터 목록 조회 (preview_file_ids 포함)"""

    result = db.execute(text("""
        SELECT
            tc.id,
            tc.start_time,
            tc.end_time,
            tc.file_count,
            CAST((julianday(tc.end_time) - julianday(tc.start_time)) * 1440 AS INTEGER) as duration_minutes,
            c.full_path,
            tc.reviewed
        FROM time_clusters tc
        LEFT JOIN categories c ON tc.category_id = c.id
        ORDER BY tc.start_time DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    clusters = []
    for row in result:
        cid = row[0]
        # 첫 5개 파일 ID
        preview_rows = db.execute(text("""
            SELECT id FROM file_classifications
            WHERE cluster_id = :cid
            ORDER BY id ASC LIMIT 5
        """), {"cid": cid}).fetchall()
        preview_ids = [r[0] for r in preview_rows]

        clusters.append({
            "cluster_id": cid,
            "start_time": row[1],
            "end_time": row[2],
            "file_count": row[3],
            "duration_minutes": row[4] or 0,
            "category_path": row[5],
            "reviewed": bool(row[6]) if row[6] is not None else False,
            "preview_file_ids": preview_ids,
        })

    return clusters


class AssignCategoryRequest(BaseModel):
    """클러스터 카테고리 지정 요청"""
    category_id: int


@router.post("/{cluster_id}/assign")
async def assign_cluster_category(
    cluster_id: int,
    request: AssignCategoryRequest,
    db: Session = Depends(get_db),
):
    """클러스터에 카테고리 지정 (클러스터 + 소속 파일 모두)"""
    # 클러스터 존재 확인
    row = db.execute(text("SELECT id FROM time_clusters WHERE id = :id"), {"id": cluster_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="클러스터를 찾을 수 없습니다")

    # 클러스터 카테고리 업데이트
    db.execute(
        text("UPDATE time_clusters SET category_id = :cat_id WHERE id = :id"),
        {"cat_id": request.category_id, "id": cluster_id}
    )
    # 소속 파일도 업데이트
    db.execute(
        text("UPDATE file_classifications SET final_category_id = :cat_id, status = 'user_classified' WHERE cluster_id = :cid"),
        {"cat_id": request.category_id, "cid": cluster_id}
    )
    db.commit()
    return {"status": "ok"}


@router.post("/{cluster_id}/review")
async def review_cluster(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """클러스터 검토 완료 표시"""
    row = db.execute(text("SELECT id FROM time_clusters WHERE id = :id"), {"id": cluster_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="클러스터를 찾을 수 없습니다")

    # reviewed 컬럼이 없을 수 있으므로 안전하게 처리
    try:
        db.execute(text("UPDATE time_clusters SET reviewed = 1 WHERE id = :id"), {"id": cluster_id})
    except Exception:
        db.execute(text("ALTER TABLE time_clusters ADD COLUMN reviewed BOOLEAN DEFAULT 0"))
        db.execute(text("UPDATE time_clusters SET reviewed = 1 WHERE id = :id"), {"id": cluster_id})
    db.commit()
    return {"status": "ok"}


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
            CAST((julianday(tc.end_time) - julianday(tc.start_time)) * 1440 AS INTEGER) as duration_minutes,
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
            COALESCE(f.user_date, f.extracted_date) as capture_time
        FROM file_classifications f
        WHERE f.cluster_id = :cluster_id
        ORDER BY COALESCE(f.user_date, f.extracted_date) ASC
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
        duration_minutes=cluster_row[4] or 0,
        category_path=cluster_row[5],
        files=files
    )
