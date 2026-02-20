"""
파일 관련 API 엔드포인트

- GET /api/ic/files/{id}/thumbnail: 썸네일 서빙
- GET /api/ic/files: 파일 리스트 조회
"""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
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
    order_by: str = "id",  # id, extracted_date, importance, ai_confidence
    order_dir: str = "asc",  # asc, desc
    tag_id: Optional[int] = None,
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
        tag_id: 태그 ID 필터
    """
    # 기본 쿼리 (tag_id 필터 시 JOIN 필요)
    if tag_id is not None:
        query = """
            SELECT fc.*
            FROM file_classifications fc
            JOIN file_tags ft ON ft.file_id = fc.id
            WHERE ft.tag_id = :tag_id
        """
        params: dict = {"tag_id": tag_id}
    else:
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
    valid_order_by = {"id", "extracted_date", "importance", "ai_confidence"}
    valid_order_dir = {"asc", "desc"}

    if order_by not in valid_order_by:
        order_by = "id"
    if order_dir not in valid_order_dir:
        order_dir = "asc"

    # ai_confidence는 NULL이 있을 수 있으므로 NULLS LAST 처리
    # SQLite: ORDER BY (ai_confidence IS NULL), ai_confidence ASC
    # tag_id JOIN 시 fc. 접두사로 모호성 방지
    col_prefix = "fc." if tag_id is not None else ""
    if order_by == "ai_confidence":
        query += f" ORDER BY ({col_prefix}ai_confidence IS NULL), {col_prefix}ai_confidence {order_dir.upper()}"
    else:
        query += f" ORDER BY {col_prefix}{order_by} {order_dir.upper()}"

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


class ApproveRequest(BaseModel):
    """파일 승인 요청"""
    file_ids: list[int]


class RollbackResponse(BaseModel):
    """롤백 응답"""
    status: str
    file_id: int


@router.post("/approve")
async def approve_files(
    request: ApproveRequest,
    db: Session = Depends(get_db),
):
    """
    선택된 파일들을 승인 (status → approved)
    """
    if not request.file_ids:
        raise HTTPException(status_code=400, detail="파일 ID가 필요합니다.")

    db.execute(
        text("UPDATE file_classifications SET status = 'approved' WHERE id IN :ids"),
        {"ids": tuple(request.file_ids)}
    )
    db.commit()

    return {"status": "ok", "approved_count": len(request.file_ids)}


class BulkClassifyRequest(BaseModel):
    """파일 일괄 카테고리 지정 요청"""
    file_ids: list[int]
    category_id: int


@router.put("/bulk-classify")
async def bulk_classify_files(
    request: BulkClassifyRequest,
    db: Session = Depends(get_db),
):
    """
    선택된 파일들에 카테고리 지정 (status → approved)
    """
    if not request.file_ids:
        raise HTTPException(status_code=400, detail="파일 ID가 필요합니다.")

    db.execute(
        text("""
            UPDATE file_classifications
            SET final_category_id = :cat_id, status = 'approved'
            WHERE id IN :ids
        """),
        {"cat_id": request.category_id, "ids": tuple(request.file_ids)}
    )
    db.commit()

    return {"status": "ok", "classified_count": len(request.file_ids)}


class BulkDeleteRequest(BaseModel):
    """파일 일괄 삭제 요청"""
    file_ids: list[int]


@router.post("/bulk-delete")
async def bulk_delete_files(
    request: BulkDeleteRequest,
    db: Session = Depends(get_db),
):
    """
    선택된 파일들을 DB에서 삭제 (연관 데이터 포함)
    """
    if not request.file_ids:
        raise HTTPException(status_code=400, detail="파일 ID가 필요합니다.")

    ids = tuple(request.file_ids)

    # 연관 데이터 정리
    for table in ["image_features", "file_tags", "duplicate_members"]:
        try:
            db.execute(text(f"DELETE FROM {table} WHERE file_id IN :ids"), {"ids": ids})
        except Exception:
            pass

    # 썸네일 파일 삭제
    for file_id in request.file_ids:
        thumb = get_thumbnail_path(file_id, settings)
        if thumb.exists():
            try:
                thumb.unlink()
            except Exception:
                pass

    # 본 테이블 삭제
    db.execute(text("DELETE FROM file_classifications WHERE id IN :ids"), {"ids": ids})
    db.commit()

    return {"status": "ok", "deleted_count": len(request.file_ids)}


@router.post("/{file_id}/rollback")
async def rollback_file(
    file_id: int,
    db: Session = Depends(get_db),
):
    """
    파일을 이전 상태로 롤백 (moved → ai_classified)
    """
    result = db.execute(
        text("SELECT status FROM file_classifications WHERE id = :id"),
        {"id": file_id}
    ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    # moved → ai_classified, approved → ai_classified, ai_classified → pending
    current = result[0]
    rollback_map = {
        "moved": "ai_classified",
        "approved": "ai_classified",
        "ai_classified": "folder_mapped",
        "folder_mapped": "pending",
    }
    new_status = rollback_map.get(current, "pending")

    db.execute(
        text("UPDATE file_classifications SET status = :status WHERE id = :id"),
        {"status": new_status, "id": file_id}
    )
    db.commit()

    return {"status": "ok", "file_id": file_id, "new_status": new_status}
