"""
파일 관련 API 엔드포인트

- GET /api/ic/files/{id}/thumbnail: 썸네일 서빙
- GET /api/ic/files: 파일 리스트 조회
"""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db
from ..config import settings
from ..workers.thumbnail import get_thumbnail_path

router = APIRouter(prefix="/files", tags=["Files"])


@router.get("/{file_id}/thumbnail")
async def get_thumbnail(file_id: int):
    """
    썸네일 이미지 서빙

    Args:
        file_id: file_classifications.id

    Returns:
        JPEG 이미지
    """
    thumbnail_path = get_thumbnail_path(file_id, settings)

    if not thumbnail_path.exists():
        raise HTTPException(status_code=404, detail="썸네일이 생성되지 않았습니다.")

    return FileResponse(thumbnail_path, media_type="image/jpeg")


@router.get("")
async def get_files(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    category_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    importance: Optional[str] = None,
    order_by: str = "id",  # id, extracted_date, importance
    order_dir: str = "asc",  # asc, desc
    db: Session = Depends(get_db),
):
    """
    파일 리스트 조회 (페이지네이션)

    Args:
        skip: 오프셋
        limit: 제한 수
        status: 상태 필터 (pending/folder_mapped/ai_classified/approved/moved/error)
        category_id: 카테고리 ID 필터
        date_from: 날짜 시작 (YYYY-MM-DD)
        date_to: 날짜 종료 (YYYY-MM-DD)
        importance: 중요도 필터 (high/medium/low)
        order_by: 정렬 필드
        order_dir: 정렬 방향
    """
    # 기본 쿼리
    query = "SELECT * FROM file_classifications WHERE 1=1"
    params = {}

    # 필터 조건
    if status:
        query += " AND status = :status"
        params["status"] = status

    if category_id is not None:
        query += " AND final_category_id = :cat_id"
        params["cat_id"] = category_id

    if date_from:
        query += " AND extracted_date >= :date_from"
        params["date_from"] = date_from

    if date_to:
        query += " AND extracted_date <= :date_to"
        params["date_to"] = date_to

    if importance:
        query += " AND importance = :importance"
        params["importance"] = importance

    # 정렬
    valid_order_by = {"id", "extracted_date", "importance"}
    valid_order_dir = {"asc", "desc"}

    if order_by not in valid_order_by:
        order_by = "id"
    if order_dir not in valid_order_dir:
        order_dir = "asc"

    query += f" ORDER BY {order_by} {order_dir.upper()}"

    # 페이지네이션
    query += " LIMIT :limit OFFSET :skip"
    params["limit"] = limit
    params["skip"] = skip

    result = db.execute(text(query), params).fetchall()

    # 딕셔너리로 변환
    files = []
    for row in result:
        files.append({
            "id": row.id,
            "file_path": row.file_path,
            "file_size": row.file_size,
            "extracted_date": row.extracted_date,
            "date_source": row.date_source,
            "final_category_id": row.final_category_id,
            "status": row.status,
            "importance": row.importance,
            "ai_confidence": row.ai_confidence,
        })

    return {
        "files": files,
        "skip": skip,
        "limit": limit,
        "total": len(files),
    }
