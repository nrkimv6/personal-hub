"""
파일 목록 API 엔드포인트

- GET /files: 파일 목록 (file_group, extension, status 필터, 검색, 페이지네이션)
- GET /files/{id}: 파일 상세
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db

router = APIRouter(tags=["File Classifier - Files"])


class FileItem(BaseModel):
    id: int
    file_path: str
    file_name: str
    extension: Optional[str]
    file_size: Optional[int]
    file_modified_at: Optional[str]
    file_group: str
    status: str
    rule_category_id: Optional[int]
    llm_category_id: Optional[int]
    final_category_id: Optional[int]
    llm_confidence: Optional[float]
    suggested_path: Optional[str]
    moved_path: Optional[str]
    is_deletable: Optional[bool]
    created_at: str


class FilesResponse(BaseModel):
    items: list[FileItem]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("/files", response_model=FilesResponse)
async def list_files(
    file_group: Optional[str] = None,
    extension: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    """파일 목록 조회 (필터 + 페이지네이션)"""
    conditions = []
    params: dict = {}

    if file_group:
        conditions.append("file_group = :file_group")
        params["file_group"] = file_group

    if extension:
        conditions.append("extension = :extension")
        params["extension"] = extension.lower() if not extension.startswith(".") else extension.lower()

    if status:
        conditions.append("status = :status")
        params["status"] = status

    if search:
        conditions.append("(file_name LIKE :search OR file_path LIKE :search)")
        params["search"] = f"%{search}%"

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    # 전체 수
    count_sql = f"SELECT COUNT(*) FROM fc_files {where_clause}"
    total = db.execute(text(count_sql), params).scalar() or 0

    # 페이지네이션
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    rows = db.execute(
        text(f"""
            SELECT id, file_path, file_name, extension, file_size, file_modified_at,
                   file_group, status, rule_category_id, llm_category_id, final_category_id,
                   llm_confidence, suggested_path, moved_path, is_deletable, created_at
            FROM fc_files
            {where_clause}
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).fetchall()

    items = [
        FileItem(
            id=r.id,
            file_path=r.file_path,
            file_name=r.file_name,
            extension=r.extension,
            file_size=r.file_size,
            file_modified_at=r.file_modified_at,
            file_group=r.file_group,
            status=r.status,
            rule_category_id=r.rule_category_id,
            llm_category_id=r.llm_category_id,
            final_category_id=r.final_category_id,
            llm_confidence=r.llm_confidence,
            suggested_path=r.suggested_path,
            moved_path=r.moved_path,
            is_deletable=bool(r.is_deletable) if r.is_deletable is not None else False,
            created_at=r.created_at,
        )
        for r in rows
    ]

    import math
    return FilesResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if page_size > 0 else 0,
    )


@router.get("/files/{file_id}")
async def get_file(file_id: int, db: Session = Depends(get_db)):
    """파일 상세 조회"""
    row = db.execute(
        text("SELECT * FROM fc_files WHERE id = :id"),
        {"id": file_id},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

    result = dict(row._mapping)

    # 음악 메타데이터 포함
    if row.file_group == "music":
        meta = db.execute(
            text("SELECT * FROM fc_music_meta WHERE file_id = :id"),
            {"id": file_id},
        ).fetchone()
        result["music_meta"] = dict(meta._mapping) if meta else None

    # 압축 내부 목록 (최대 20개)
    elif row.file_group == "archive":
        contents = db.execute(
            text("SELECT * FROM fc_archive_contents WHERE file_id = :id LIMIT 20"),
            {"id": file_id},
        ).fetchall()
        result["archive_contents"] = [dict(r._mapping) for r in contents]

    # 설치파일 메타데이터
    elif row.file_group == "installer":
        meta = db.execute(
            text("SELECT * FROM fc_installer_meta WHERE file_id = :id"),
            {"id": file_id},
        ).fetchone()
        result["installer_meta"] = dict(meta._mapping) if meta else None

    return result
