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
    """)).fetchall()

    return [
        RuleResponse(
            id=row[0],
            rule_type=row[1],
            category_id=row[2],
            rule_content=row[3],
            priority=row[4],
            is_active=bool(row[5]),
            source=row[6],
            hit_count=row[7] or 0,
            category_name=row[8] if len(row) > 8 else None
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
