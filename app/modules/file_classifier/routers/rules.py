"""규칙 CRUD API"""
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db

router = APIRouter(tags=["File Classifier - Rules"])


class RuleCreate(BaseModel):
    rule_type: str
    category_id: int
    rule_content: dict
    priority: int = 0
    description: Optional[str] = None


class RuleUpdate(BaseModel):
    rule_type: Optional[str] = None
    category_id: Optional[int] = None
    rule_content: Optional[dict] = None
    priority: Optional[int] = None
    description: Optional[str] = None


@router.get("/rules")
async def list_rules(db: Session = Depends(get_db)):
    rows = db.execute(text(
        "SELECT r.id, r.rule_type, r.category_id, r.rule_content, r.priority, "
        "r.is_active, r.hit_count, c.full_path as category_path "
        "FROM fc_rules r LEFT JOIN fc_categories c ON r.category_id = c.id "
        "ORDER BY r.priority DESC, r.id"
    )).fetchall()
    return [
        {
            "id": r[0], "rule_type": r[1], "category_id": r[2],
            "rule_content": json.loads(r[3]) if r[3] else {},
            "priority": r[4], "is_active": bool(r[5]),
            "hit_count": r[6], "category_path": r[7]
        }
        for r in rows
    ]


@router.post("/rules")
async def create_rule(data: RuleCreate, db: Session = Depends(get_db)):
    result = db.execute(text(
        "INSERT INTO fc_rules (rule_type, category_id, rule_content, priority) "
        "VALUES (:rule_type, :category_id, :rule_content, :priority)"
    ), {
        "rule_type": data.rule_type,
        "category_id": data.category_id,
        "rule_content": json.dumps(data.rule_content),
        "priority": data.priority
    })
    db.commit()
    return {"id": result.lastrowid, "status": "created"}


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, data: RuleUpdate, db: Session = Depends(get_db)):
    existing = db.execute(text("SELECT id FROM fc_rules WHERE id = :id"), {"id": rule_id}).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")

    updates = {}
    if data.rule_type is not None:
        updates["rule_type"] = data.rule_type
    if data.category_id is not None:
        updates["category_id"] = data.category_id
    if data.rule_content is not None:
        updates["rule_content"] = json.dumps(data.rule_content)
    if data.priority is not None:
        updates["priority"] = data.priority

    if updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = rule_id
        db.execute(text(f"UPDATE fc_rules SET {set_clause} WHERE id = :id"), updates)
        db.commit()

    return {"status": "updated"}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM fc_rules WHERE id = :id"), {"id": rule_id})
    db.commit()
    return {"status": "deleted"}


@router.put("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int, db: Session = Depends(get_db)):
    existing = db.execute(text("SELECT is_active FROM fc_rules WHERE id = :id"), {"id": rule_id}).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")
    new_val = not bool(existing[0])
    db.execute(text("UPDATE fc_rules SET is_active = :val WHERE id = :id"), {"val": new_val, "id": rule_id})
    db.commit()
    return {"status": "toggled", "is_active": new_val}
