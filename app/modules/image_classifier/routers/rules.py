"""
이미지 분류 규칙 관리 API

- GET /api/ic/rules: 규칙 목록 조회
- POST /api/ic/rules: 규칙 추가
- DELETE /api/ic/rules/{id}: 규칙 삭제
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db

router = APIRouter(prefix="/rules", tags=["Rules"])


class RuleResponse(BaseModel):
    """분류 규칙 응답"""
    id: int
    rule_type: str
    category_id: int
    rule_content: str
    priority: int
    is_active: bool
    source: Optional[str] = None
    hit_count: int = 0
    category_name: Optional[str] = None


class RuleCreateRequest(BaseModel):
    """규칙 생성 요청"""
    rule_type: str = "keyword"
    category_id: int
    rule_content: str
    priority: int = 0
    is_active: bool = True
    source: str = "user"


@router.get("")
async def get_rules(db: Session = Depends(get_db)) -> list[RuleResponse]:
    """분류 규칙 목록 조회"""

    result = db.execute(text("""
        SELECT r.id, r.rule_type, r.category_id, r.rule_content, r.priority, r.is_active, r.source, r.hit_count,
               COALESCE(c.full_path, CAST(r.category_id AS TEXT)) as category_name
        FROM classification_rules r
        LEFT JOIN categories c ON r.category_id = c.id
        ORDER BY r.priority DESC, r.id ASC
    """)).mappings().all()

    return [
        RuleResponse(
            id=row["id"],
            rule_type=row["rule_type"],
            category_id=row["category_id"],
            rule_content=row["rule_content"],
            priority=row["priority"],
            is_active=bool(row["is_active"]),
            source=row["source"],
            hit_count=row["hit_count"] or 0,
            category_name=row["category_name"]
        )
        for row in result
    ]


@router.post("")
async def create_rule(
    request: RuleCreateRequest,
    db: Session = Depends(get_db)
):
    """분류 규칙 추가"""

    db.execute(text("""
        INSERT INTO classification_rules (rule_type, category_id, rule_content, priority, is_active, source)
        VALUES (:rule_type, :category_id, :rule_content, :priority, :is_active, :source)
    """), {
        "rule_type": request.rule_type,
        "category_id": request.category_id,
        "rule_content": request.rule_content,
        "priority": request.priority,
        "is_active": request.is_active,
        "source": request.source
    })
    db.commit()

    return {"status": "ok", "message": "규칙이 추가되었습니다"}


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    """분류 규칙 삭제"""

    result = db.execute(
        text("DELETE FROM classification_rules WHERE id = :id"),
        {"id": rule_id}
    )
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다")

    return {"status": "ok", "message": "규칙이 삭제되었습니다"}


class RulePreviewRequest(BaseModel):
    """규칙 미리보기 요청"""
    category_id: Optional[int] = None
    tag_id: Optional[int] = None
    limit: int = 10


@router.post("/preview")
async def preview_rule(
    request: RulePreviewRequest,
    db: Session = Depends(get_db)
):
    """
    폴더 규칙 미리보기

    카테고리 또는 태그 ID로 해당 규칙의 적용 대상 파일 목록과
    이동 예상 경로를 반환합니다.

    Request: { category_id or tag_id, limit: 10 }
    Response: [{ file_path: 원본, target_path: 이동 예상 경로 }]
    """
    if not request.category_id and not request.tag_id:
        raise HTTPException(status_code=400, detail="category_id 또는 tag_id 중 하나를 지정하세요.")

    folder_template = None
    folder_action = None

    if request.category_id:
        row = db.execute(
            text("SELECT folder_template, folder_action FROM categories WHERE id = :id"),
            {"id": request.category_id}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다.")
        folder_template = row.folder_template
        folder_action = row.folder_action

        # 해당 카테고리의 파일 목록
        files = db.execute(text("""
            SELECT id, file_path FROM file_classifications
            WHERE final_category_id = :category_id AND status = 'classified'
            LIMIT :limit
        """), {"category_id": request.category_id, "limit": request.limit}).fetchall()

    else:
        try:
            row = db.execute(
                text("SELECT folder_template, folder_action FROM tags WHERE id = :id"),
                {"id": request.tag_id}
            ).fetchone()
        except Exception:
            raise HTTPException(status_code=500, detail="태그 폴더 규칙 조회 실패 (마이그레이션 007 필요)")
        if not row:
            raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")
        folder_template = row.folder_template
        folder_action = row.folder_action

        # 해당 태그의 파일 목록
        files = db.execute(text("""
            SELECT fc.id, fc.file_path FROM file_classifications fc
            JOIN file_tags ft ON ft.file_id = fc.id
            WHERE ft.tag_id = :tag_id
            LIMIT :limit
        """), {"tag_id": request.tag_id, "limit": request.limit}).fetchall()

    if not folder_template:
        return {"previews": [], "message": "폴더 규칙이 설정되지 않았습니다.", "folder_action": folder_action}

    import os
    import re
    from datetime import datetime

    previews = []
    for file in files:
        file_path = file.file_path or ""
        filename = os.path.basename(file_path)
        # 간단한 템플릿 변수 치환 (실제 적용 시에는 DB 정보 활용)
        now = datetime.now()
        target = folder_template
        target = target.replace("{year}", str(now.year))
        target = target.replace("{month}", f"{now.month:02d}")
        target = target.replace("{tag}", "")
        target = target.replace("{category}", "")
        # 중복 슬래시 제거
        target = re.sub(r"[/\\]+", "/", target).strip("/")
        target_path = f"{target}/{filename}" if target else filename

        previews.append({
            "file_id": file.id,
            "file_path": file_path,
            "target_path": target_path,
        })

    return {
        "previews": previews,
        "folder_template": folder_template,
        "folder_action": folder_action or "move",
    }


class RuleUpdateRequest(BaseModel):
    """규칙 수정 요청"""
    rule_type: Optional[str] = None
    category_id: Optional[int] = None
    rule_content: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


@router.post("/{rule_id}/toggle")
async def toggle_rule(rule_id: int, db: Session = Depends(get_db)):
    """규칙 활성/비활성 토글"""

    result = db.execute(
        text("SELECT is_active FROM classification_rules WHERE id = :id"),
        {"id": rule_id}
    ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다")

    new_active = not bool(result[0])
    db.execute(
        text("UPDATE classification_rules SET is_active = :active WHERE id = :id"),
        {"active": new_active, "id": rule_id}
    )
    db.commit()

    return {"status": "ok", "is_active": new_active}


@router.put("/{rule_id}")
async def update_rule(
    rule_id: int,
    request: RuleUpdateRequest,
    db: Session = Depends(get_db)
):
    """규칙 수정"""

    # 존재 확인
    existing = db.execute(
        text("SELECT id FROM classification_rules WHERE id = :id"),
        {"id": rule_id}
    ).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다")

    # 업데이트할 필드만 처리
    updates = {}
    if request.rule_type is not None:
        updates["rule_type"] = request.rule_type
    if request.category_id is not None:
        updates["category_id"] = request.category_id
    if request.rule_content is not None:
        updates["rule_content"] = request.rule_content
    if request.priority is not None:
        updates["priority"] = request.priority
    if request.is_active is not None:
        updates["is_active"] = request.is_active

    if updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = rule_id
        db.execute(text(f"UPDATE classification_rules SET {set_clause} WHERE id = :id"), updates)
        db.commit()

    return {"status": "ok", "message": "규칙이 수정되었습니다"}
