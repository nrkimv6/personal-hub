"""
파일 관련 API 엔드포인트

- GET /api/ic/files/{id}/thumbnail: 썸네일 서빙
- GET /api/ic/files: 파일 리스트 조회
"""

import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db
from ..config import settings
from ..workers.thumbnail import get_thumbnail_path
from ..workers.feedback import FeedbackLearner
from ..utils.pagination import validate_sort, apply_pagination

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


@router.get("/{file_id}")
async def get_file_detail(
    file_id: int,
    db: Session = Depends(get_db),
):
    """
    파일 상세 조회

    Args:
        file_id: file_classifications.id

    Returns:
        { file: {...}, classifications: [{category_name, confidence, engine, reasoning}], tags: [{id, name}] }
    """
    # 기본 파일 정보
    file_row = db.execute(
        text("SELECT * FROM file_classifications WHERE id = :id"),
        {"id": file_id}
    ).fetchone()

    if not file_row:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    file_data = {
        "id": file_row.id,
        "file_path": file_row.file_path,
        "file_size": file_row.file_size,
        "extracted_date": file_row.extracted_date,
        "date_source": file_row.date_source,
        "final_category_id": file_row.final_category_id,
        "status": file_row.status,
        "importance": file_row.importance,
        "ai_confidence": file_row.ai_confidence,
    }

    # 분류 이력 (카테고리 JOIN)
    classification_rows = db.execute(
        text("""
            SELECT fc_hist.confidence, fc_hist.engine, fc_hist.reasoning,
                   c.name AS category_name, c.full_path AS category_path
            FROM file_classification_history fc_hist
            LEFT JOIN categories c ON c.id = fc_hist.category_id
            WHERE fc_hist.file_id = :id
            ORDER BY fc_hist.id DESC
        """),
        {"id": file_id}
    ).fetchall()

    classifications = []
    for row in classification_rows:
        classifications.append({
            "category_name": row.category_name,
            "category_path": row.category_path,
            "confidence": row.confidence,
            "engine": row.engine,
            "reasoning": row.reasoning,
        })

    # 태그 목록
    tag_rows = db.execute(
        text("""
            SELECT t.id, t.name
            FROM file_tags ft
            JOIN tags t ON t.id = ft.tag_id
            WHERE ft.file_id = :id
        """),
        {"id": file_id}
    ).fetchall()

    tags = [{"id": row.id, "name": row.name} for row in tag_rows]

    return {
        "file": file_data,
        "classifications": classifications,
        "tags": tags,
    }


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
            SELECT fc.*, c.full_path AS category_path
            FROM file_classifications fc
            JOIN file_tags ft ON ft.file_id = fc.id
            LEFT JOIN categories c ON c.id = fc.final_category_id
            WHERE ft.tag_id = :tag_id
        """
        count_query = """
            SELECT COUNT(*) FROM file_classifications fc
            JOIN file_tags ft ON ft.file_id = fc.id
            WHERE ft.tag_id = :tag_id
        """
        params: dict = {"tag_id": tag_id}
        count_params: dict = {"tag_id": tag_id}
    else:
        query = """
            SELECT fc.*, c.full_path AS category_path
            FROM file_classifications fc
            LEFT JOIN categories c ON c.id = fc.final_category_id
            WHERE 1=1
        """
        count_query = "SELECT COUNT(*) FROM file_classifications fc WHERE 1=1"
        params = {}
        count_params = {}

    # 필터 조건
    col_prefix = "fc."
    if status:
        query += f" AND {col_prefix}status = :status"
        count_query += f" AND {col_prefix}status = :status"
        params["status"] = status
        count_params["status"] = status

    if category_id is not None:
        query += f" AND {col_prefix}final_category_id = :cat_id"
        count_query += f" AND {col_prefix}final_category_id = :cat_id"
        params["cat_id"] = category_id
        count_params["cat_id"] = category_id

    if date_from:
        query += f" AND {col_prefix}extracted_date >= :date_from"
        count_query += f" AND {col_prefix}extracted_date >= :date_from"
        params["date_from"] = date_from
        count_params["date_from"] = date_from

    if date_to:
        query += f" AND {col_prefix}extracted_date <= :date_to"
        count_query += f" AND {col_prefix}extracted_date <= :date_to"
        params["date_to"] = date_to
        count_params["date_to"] = date_to

    if importance:
        query += f" AND {col_prefix}importance = :importance"
        count_query += f" AND {col_prefix}importance = :importance"
        params["importance"] = importance
        count_params["importance"] = importance

    # 정렬
    order_by, order_dir = validate_sort(
        order_by, order_dir,
        {"id", "extracted_date", "importance", "ai_confidence"},
    )

    if order_by == "ai_confidence":
        query += f" ORDER BY ({col_prefix}ai_confidence IS NULL), {col_prefix}ai_confidence {order_dir.upper()}"
    else:
        query += f" ORDER BY {col_prefix}{order_by} {order_dir.upper()}"

    # 페이지네이션
    query = apply_pagination(query, params, skip, limit)

    # total 카운트 (페이지네이션 전 전체 개수)
    total = db.execute(text(count_query), count_params).scalar()

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
            "moved_path": getattr(row, "moved_path", None),
            "moved_at": getattr(row, "moved_at", None),
            "category_path": getattr(row, "category_path", None),
        })

    return {
        "files": files,
        "skip": skip,
        "limit": limit,
        "total": total,
        "has_more": skip + len(files) < total,
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

    # 카테고리 변경 전 원래 카테고리 조회 (feedback 기록용)
    ids_tuple = tuple(request.file_ids)
    original_rows = db.execute(
        text("SELECT id, final_category_id FROM file_classifications WHERE id IN :ids"),
        {"ids": ids_tuple}
    ).fetchall()
    original_map = {row.id: row.final_category_id for row in original_rows}

    db.execute(
        text("""
            UPDATE file_classifications
            SET final_category_id = :cat_id, status = 'approved'
            WHERE id IN :ids
        """),
        {"cat_id": request.category_id, "ids": ids_tuple}
    )
    db.commit()

    # 카테고리가 실제로 변경된 파일에 대해 feedback 기록
    learner = FeedbackLearner(db)
    feedback_count = 0
    for file_id in request.file_ids:
        original_cat = original_map.get(file_id)
        if original_cat is not None and original_cat != request.category_id:
            try:
                learner.record_correction(file_id, original_cat, request.category_id)
                feedback_count += 1
            except Exception as e:
                logger.warning(f"Failed to record feedback for file {file_id}: {e}")

    return {"status": "ok", "classified_count": len(request.file_ids), "feedback_recorded": feedback_count}


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


class OpenLocalRequest(BaseModel):
    path: Optional[str] = None
    folder: Optional[str] = None
    file_id: Optional[int] = None


@router.post("/open-local")
async def open_local_file_or_folder(
    request: OpenLocalRequest,
    db: Session = Depends(get_db)
):
    """로컬 파일/폴더를 기본 뷰어/탐색기로 열기 (개발 환경 전용)"""
    import os

    # file_id로 경로 조회
    if request.file_id is not None:
        file_query = text("SELECT file_path FROM file_classifications WHERE id = :file_id")
        row = db.execute(file_query, {"file_id": request.file_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
        target = row.file_path
    else:
        target = request.path or request.folder

    if not target:
        raise HTTPException(status_code=400, detail="path, folder 또는 file_id를 지정하세요.")

    target_path = Path(target)
    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"경로를 찾을 수 없습니다: {target}")

    try:
        os.startfile(str(target_path))
        return {"status": "ok", "opened": str(target_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"열기 실패: {e}")


class OpenFolderRequest(BaseModel):
    file_id: int


@router.post("/open-folder")
async def open_folder_in_explorer(
    request: OpenFolderRequest,
    db: Session = Depends(get_db)
):
    """
    파일이 있는 폴더를 탐색기에서 열기 (파일 선택 상태로)

    - DB에서 file_id → file_path 조회
    - Windows explorer /select, 명령으로 파일을 선택한 상태로 탐색기 열기
    - 보안: SCAN_ROOT_FOLDERS 내 경로만 허용, 경로 트래버설 차단
    """
    import os
    import subprocess

    # 파일 경로 조회
    file_query = text("SELECT file_path FROM file_classifications WHERE id = :file_id")
    row = db.execute(file_query, {"file_id": request.file_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    raw_path = row.file_path
    # 경로 정규화 (심볼릭 링크 해결)
    try:
        file_path = os.path.realpath(raw_path)
    except Exception:
        file_path = raw_path

    # 보안: SCAN_ROOT_FOLDERS 내 경로만 허용
    scan_roots = settings.SCAN_ROOT_FOLDERS
    if scan_roots:
        allowed = any(
            os.path.commonpath([file_path, os.path.realpath(root)]) == os.path.realpath(root)
            for root in scan_roots
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="허용된 스캔 루트 외부 경로입니다.")

    # 파일 존재 확인
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"파일이 존재하지 않습니다: {file_path}")

    try:
        # Windows: explorer /select, "파일경로"
        subprocess.Popen(['explorer', '/select,', file_path])
        return {"status": "ok", "file_path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"탐색기 열기 실패: {e}")
