"""
태그 관련 API 엔드포인트

- GET /api/ic/tags: 태그 목록 조회
- POST /api/ic/tags: 태그 추가
- PUT /api/ic/tags/{id}: 태그 수정 (폴더 규칙 포함)
- POST /api/ic/files/bulk-tag: 파일에 일괄 태그 부여
- DELETE /api/ic/tags/{id}: 태그 삭제
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db
from ..utils.pagination import apply_pagination

router = APIRouter(prefix="/tags", tags=["Tags"])


# === 요청/응답 스키마 ===
class TagCreate(BaseModel):
    """태그 생성 요청"""
    name: str
    folder_template: Optional[str] = None  # 예: {category}/{year}/{tag}
    folder_action: Optional[str] = None    # move/copy/link


class TagFolderRuleUpdate(BaseModel):
    """태그 폴더 규칙 업데이트 요청"""
    folder_template: Optional[str] = None
    folder_action: Optional[str] = None  # move/copy/link


class BulkTagRequest(BaseModel):
    """일괄 태그 요청"""
    file_ids: list[int]
    tag_names: list[str]


# === 엔드포인트 ===
@router.get("/")
async def get_tags(
    sort_by: str = "usage",  # usage/name/recent
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    태그 목록 조회

    Args:
        sort_by: 정렬 기준 (usage=사용량, name=이름, recent=최근)
        limit: 최대 개수
    """
    order_clause = "usage_count DESC"
    if sort_by == "name":
        order_clause = "name ASC"
    elif sort_by == "recent":
        order_clause = "created_at DESC"

    query = text(f"""
        SELECT id, name, usage_count, created_at, folder_template, folder_action
        FROM tags
        ORDER BY {order_clause}
        LIMIT :limit
    """)
    total = db.execute(text("SELECT COUNT(*) FROM tags")).scalar() or 0

    try:
        tags = db.execute(query, {"limit": limit}).fetchall()
    except Exception:
        # folder_template/folder_action 컬럼 없을 경우 fallback
        fallback_query = text(f"""
            SELECT id, name, usage_count, created_at
            FROM tags ORDER BY {order_clause} LIMIT :limit
        """)
        tags = db.execute(fallback_query, {"limit": limit}).fetchall()
        return {
            "tags": [
                {"id": t.id, "name": t.name, "usage_count": t.usage_count or 0, "created_at": t.created_at,
                 "folder_template": None, "folder_action": None}
                for t in tags
            ],
            "total": total,
        }

    return {
        "tags": [
            {
                "id": tag.id,
                "name": tag.name,
                "usage_count": tag.usage_count or 0,
                "created_at": tag.created_at,
                "folder_template": getattr(tag, 'folder_template', None),
                "folder_action": getattr(tag, 'folder_action', None),
            }
            for tag in tags
        ],
        "total": total,
    }


@router.post("/")
async def create_tag(
    request: TagCreate,
    db: Session = Depends(get_db)
):
    """
    태그 추가

    - 중복 확인 후 생성
    """
    # 빈 이름 검증
    if not request.name or not request.name.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="태그 이름은 비어있을 수 없습니다.")

    # 중복 확인
    dup_query = text("SELECT id FROM tags WHERE name = :name")
    duplicate = db.execute(dup_query, {"name": request.name}).fetchone()

    if duplicate:
        return {
            "status": "exists",
            "tag_id": duplicate.id,
            "message": "이미 존재하는 태그입니다."
        }

    # 태그 생성 (folder_template, folder_action 포함)
    try:
        insert_query = text("""
            INSERT INTO tags (name, usage_count, folder_template, folder_action)
            VALUES (:name, 0, :folder_template, :folder_action)
        """)
        db.execute(insert_query, {
            "name": request.name,
            "folder_template": request.folder_template,
            "folder_action": request.folder_action
        })
    except Exception:
        # folder_template/folder_action 컬럼이 없는 경우 fallback (migration 007 전)
        insert_query = text("INSERT INTO tags (name, usage_count) VALUES (:name, 0)")
        db.execute(insert_query, {"name": request.name})
    db.commit()

    # 생성된 태그 조회
    new_tag_query = text("SELECT id FROM tags WHERE name = :name")
    new_tag = db.execute(new_tag_query, {"name": request.name}).fetchone()

    return {
        "status": "created",
        "tag_id": new_tag.id,
        "message": "태그 생성 완료"
    }


@router.post("/bulk-tag")
async def bulk_tag_files(
    request: BulkTagRequest,
    db: Session = Depends(get_db)
):
    """
    파일에 일괄 태그 부여

    - 태그가 없으면 자동 생성
    - file_tags 테이블에 연결
    """
    # 태그 생성/조회
    tag_ids = []
    for tag_name in request.tag_names:
        # 태그 존재 확인
        query = text("SELECT id FROM tags WHERE name = :name")
        tag = db.execute(query, {"name": tag_name}).fetchone()

        if tag:
            tag_id = tag.id
        else:
            # 태그 생성
            insert_query = text("INSERT INTO tags (name, usage_count) VALUES (:name, 0)")
            db.execute(insert_query, {"name": tag_name})
            db.flush()

            new_tag_query = text("SELECT id FROM tags WHERE name = :name")
            tag_id = db.execute(new_tag_query, {"name": tag_name}).fetchone().id

        tag_ids.append(tag_id)

    # 파일-태그 연결
    added_count = 0
    for file_id in request.file_ids:
        for tag_id in tag_ids:
            # 중복 확인
            dup_query = text("""
                SELECT 1 FROM file_tags
                WHERE file_id = :file_id AND tag_id = :tag_id
            """)
            exists = db.execute(dup_query, {"file_id": file_id, "tag_id": tag_id}).fetchone()

            if not exists:
                insert_query = text("""
                    INSERT INTO file_tags (file_id, tag_id)
                    VALUES (:file_id, :tag_id)
                """)
                db.execute(insert_query, {"file_id": file_id, "tag_id": tag_id})

                # 사용량 증가
                update_query = text("""
                    UPDATE tags
                    SET usage_count = usage_count + 1
                    WHERE id = :tag_id
                """)
                db.execute(update_query, {"tag_id": tag_id})

                added_count += 1

    db.commit()

    return {
        "status": "success",
        "files_tagged": len(request.file_ids),
        "tags_added": added_count,
        "message": "일괄 태그 부여 완료"
    }


@router.get("/files/{file_id}")
async def get_file_tags(
    file_id: int,
    db: Session = Depends(get_db)
):
    """
    파일별 태그 목록 조회

    Args:
        file_id: 파일 ID
    """
    query = text("""
        SELECT t.id, t.name
        FROM tags t
        JOIN file_tags ft ON ft.tag_id = t.id
        WHERE ft.file_id = :file_id
        ORDER BY t.name ASC
    """)
    tags = db.execute(query, {"file_id": file_id}).fetchall()

    return {
        "tags": [{"id": tag.id, "name": tag.name} for tag in tags]
    }


@router.delete("/files/{file_id}/{tag_id}")
async def remove_file_tag(
    file_id: int,
    tag_id: int,
    db: Session = Depends(get_db)
):
    """
    파일-태그 관계 삭제 (태그 엔티티 삭제 아님)

    Args:
        file_id: 파일 ID
        tag_id: 태그 ID
    """
    # 관계 존재 확인
    check_query = text("""
        SELECT 1 FROM file_tags
        WHERE file_id = :file_id AND tag_id = :tag_id
    """)
    exists = db.execute(check_query, {"file_id": file_id, "tag_id": tag_id}).fetchone()

    if not exists:
        raise HTTPException(status_code=404, detail="파일-태그 관계를 찾을 수 없습니다.")

    # 관계 삭제
    delete_query = text("""
        DELETE FROM file_tags
        WHERE file_id = :file_id AND tag_id = :tag_id
    """)
    db.execute(delete_query, {"file_id": file_id, "tag_id": tag_id})

    # usage_count 감소 (0 미만 방지)
    update_query = text("""
        UPDATE tags
        SET usage_count = MAX(0, usage_count - 1)
        WHERE id = :tag_id
    """)
    db.execute(update_query, {"tag_id": tag_id})

    db.commit()

    return {
        "status": "success",
        "file_id": file_id,
        "tag_id": tag_id,
    }


@router.put("/{tag_id}")
async def update_tag(
    tag_id: int,
    request: TagFolderRuleUpdate,
    db: Session = Depends(get_db)
):
    """
    태그 수정 (폴더 규칙 포함)

    - folder_template: 출력 폴더 경로 템플릿
    - folder_action: move/copy/link
    """
    tag = db.execute(text("SELECT id FROM tags WHERE id = :tag_id"), {"tag_id": tag_id}).fetchone()
    if not tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    updates = []
    params: dict = {"tag_id": tag_id}

    if request.folder_template is not None:
        updates.append("folder_template = :folder_template")
        params["folder_template"] = request.folder_template or None

    if request.folder_action is not None:
        valid_actions = ["move", "copy", "link"]
        if request.folder_action and request.folder_action not in valid_actions:
            raise HTTPException(status_code=400, detail=f"folder_action은 {valid_actions} 중 하나여야 합니다.")
        updates.append("folder_action = :folder_action")
        params["folder_action"] = request.folder_action or None

    if not updates:
        raise HTTPException(status_code=400, detail="수정할 내용이 없습니다.")

    try:
        db.execute(text(f"UPDATE tags SET {', '.join(updates)} WHERE id = :tag_id"), params)
        db.commit()
    except Exception:
        raise HTTPException(status_code=500, detail="태그 수정 실패 (마이그레이션 007 적용 필요)")

    return {"status": "success", "tag_id": tag_id}


@router.get("/{tag_id}/files")
async def get_tag_files(
    tag_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    태그별 파일 목록 조회

    Args:
        tag_id: 태그 ID
        skip: 오프셋
        limit: 제한 수
    """
    # 태그 존재 확인
    tag_query = text("SELECT id FROM tags WHERE id = :tag_id")
    tag = db.execute(tag_query, {"tag_id": tag_id}).fetchone()
    if not tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    # 파일 목록 조회
    _fq_params: dict = {"tag_id": tag_id}
    _fq_sql = apply_pagination(
        "SELECT fc.* FROM file_classifications fc"
        " JOIN file_tags ft ON ft.file_id = fc.id"
        " WHERE ft.tag_id = :tag_id",
        _fq_params, skip, limit,
    )
    rows = db.execute(text(_fq_sql), _fq_params).fetchall()

    # 총 개수 조회
    count_query = text("""
        SELECT COUNT(*) as total
        FROM file_classifications fc
        JOIN file_tags ft ON ft.file_id = fc.id
        WHERE ft.tag_id = :tag_id
    """)
    total = db.execute(count_query, {"tag_id": tag_id}).fetchone().total

    files = []
    for row in rows:
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
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.put("/{tag_id}/folder-rule")
async def update_tag_folder_rule(
    tag_id: int,
    request: TagFolderRuleUpdate,
    db: Session = Depends(get_db)
):
    """
    태그 폴더 규칙 수정

    - folder_template: 출력 폴더 경로 템플릿 ({category}, {year}, {tag} 등)
    - folder_action: move/copy/link
    """
    tag = db.execute(text("SELECT id FROM tags WHERE id = :tag_id"), {"tag_id": tag_id}).fetchone()
    if not tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    updates = []
    params: dict = {"tag_id": tag_id}

    if request.folder_template is not None:
        updates.append("folder_template = :folder_template")
        params["folder_template"] = request.folder_template or None

    if request.folder_action is not None:
        valid_actions = ["move", "copy", "link"]
        if request.folder_action and request.folder_action not in valid_actions:
            raise HTTPException(status_code=400, detail=f"folder_action은 {valid_actions} 중 하나여야 합니다.")
        updates.append("folder_action = :folder_action")
        params["folder_action"] = request.folder_action or None

    if not updates:
        raise HTTPException(status_code=400, detail="수정할 내용이 없습니다.")

    try:
        db.execute(text(f"UPDATE tags SET {', '.join(updates)} WHERE id = :tag_id"), params)
        db.commit()
    except Exception:
        raise HTTPException(status_code=500, detail="폴더 규칙 수정 실패 (마이그레이션 007 적용 필요)")

    return {"status": "success", "tag_id": tag_id}


@router.delete("/{tag_id}")
async def delete_tag(
    tag_id: int,
    force: bool = False,
    db: Session = Depends(get_db)
):
    """
    태그 삭제

    Args:
        force: True면 연결된 파일 관계도 모두 삭제
    """
    # 태그 조회
    tag_query = text("SELECT id, name FROM tags WHERE id = :tag_id")
    tag = db.execute(tag_query, {"tag_id": tag_id}).fetchone()

    if not tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    # 연결된 파일 확인
    usage_query = text("SELECT COUNT(*) as count FROM file_tags WHERE tag_id = :tag_id")
    usage_count = db.execute(usage_query, {"tag_id": tag_id}).fetchone().count

    if usage_count > 0 and not force:
        raise HTTPException(
            status_code=400,
            detail=f"{usage_count}개 파일에 사용 중입니다. force=true로 강제 삭제하세요."
        )

    # 파일-태그 관계 삭제
    if force:
        delete_relations_query = text("DELETE FROM file_tags WHERE tag_id = :tag_id")
        db.execute(delete_relations_query, {"tag_id": tag_id})

    # 태그 삭제
    delete_query = text("DELETE FROM tags WHERE id = :tag_id")
    db.execute(delete_query, {"tag_id": tag_id})

    db.commit()

    return {
        "status": "success",
        "tag_id": tag_id,
        "relations_deleted": usage_count if force else 0,
        "message": "태그 삭제 완료"
    }
