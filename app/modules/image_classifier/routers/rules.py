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
        SELECT id, rule_type, category_id, rule_content, priority, is_active, source, hit_count
        FROM classification_rules
        ORDER BY priority DESC, id ASC
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
            hit_count=row[7] or 0
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
