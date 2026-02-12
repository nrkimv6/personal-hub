"""
이미지 분류 규칙 관리 API

- GET /api/ic/rules: 규칙 목록 조회
- POST /api/ic/rules: 규칙 추가
- DELETE /api/ic/rules/{id}: 규칙 삭제
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db

router = APIRouter(prefix="/rules", tags=["Rules"])


class RuleResponse(BaseModel):
    """분류 규칙 응답"""
    id: int
    pattern: str
    category_path: str
    priority: int
    enabled: bool


class RuleCreateRequest(BaseModel):
    """규칙 생성 요청"""
    pattern: str
    category_path: str
    priority: int = 100
    enabled: bool = True


@router.get("")
async def get_rules(db: Session = Depends(get_db)) -> list[RuleResponse]:
    """분류 규칙 목록 조회"""

    # classification_rules 테이블 확인
    result = db.execute(text("""
        SELECT id, pattern, category_path, priority, enabled
        FROM classification_rules
        ORDER BY priority DESC, id ASC
    """)).fetchall()

    return [
        RuleResponse(
            id=row[0],
            pattern=row[1],
            category_path=row[2],
            priority=row[3],
            enabled=bool(row[4])
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
        INSERT INTO classification_rules (pattern, category_path, priority, enabled)
        VALUES (:pattern, :category_path, :priority, :enabled)
    """), {
        "pattern": request.pattern,
        "category_path": request.category_path,
        "priority": request.priority,
        "enabled": request.enabled
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
