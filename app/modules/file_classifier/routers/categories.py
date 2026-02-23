"""카테고리 CRUD API"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db

router = APIRouter(tags=["File Classifier - Categories"])


class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


def _build_tree(rows: list, parent_id=None) -> list:
    result = []
    for r in rows:
        if r["parent_id"] == parent_id:
            node = dict(r)
            node["children"] = _build_tree(rows, r["id"])
            result.append(node)
    return sorted(result, key=lambda x: x["sort_order"])


@router.get("/categories")
async def list_categories(db: Session = Depends(get_db)):
    """카테고리 트리 반환"""
    rows = db.execute(text(
        "SELECT id, name, parent_id, full_path, description, sort_order "
        "FROM fc_categories ORDER BY sort_order, id"
    )).fetchall()
    data = [
        {"id": r[0], "name": r[1], "parent_id": r[2],
         "full_path": r[3], "description": r[4], "sort_order": r[5]}
        for r in rows
    ]
    return _build_tree(data)


@router.post("/categories")
async def create_category(data: CategoryCreate, db: Session = Depends(get_db)):
    # full_path 계산
    if data.parent_id:
        parent = db.execute(text(
            "SELECT full_path FROM fc_categories WHERE id = :id"
        ), {"id": data.parent_id}).fetchone()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent category not found")
        full_path = f"{parent[0]}/{data.name}"
    else:
        full_path = data.name

    result = db.execute(text(
        "INSERT INTO fc_categories (name, parent_id, full_path, description, sort_order) "
        "VALUES (:name, :parent_id, :full_path, :description, :sort_order)"
    ), {
        "name": data.name, "parent_id": data.parent_id,
        "full_path": full_path, "description": data.description,
        "sort_order": data.sort_order
    })
    db.commit()
    return {"id": result.lastrowid, "full_path": full_path, "status": "created"}


@router.put("/categories/{cat_id}")
async def update_category(cat_id: int, data: CategoryUpdate, db: Session = Depends(get_db)):
    existing = db.execute(text("SELECT id FROM fc_categories WHERE id = :id"), {"id": cat_id}).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")

    updates = {}
    if data.name is not None:
        updates["name"] = data.name
    if data.description is not None:
        updates["description"] = data.description
    if data.sort_order is not None:
        updates["sort_order"] = data.sort_order

    if updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = cat_id
        db.execute(text(f"UPDATE fc_categories SET {set_clause} WHERE id = :id"), updates)
        db.commit()

    return {"status": "updated"}


@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: int, db: Session = Depends(get_db)):
    # 자식이 있으면 400
    children = db.execute(text(
        "SELECT COUNT(*) FROM fc_categories WHERE parent_id = :id"
    ), {"id": cat_id}).fetchone()
    if children[0] > 0:
        raise HTTPException(status_code=400, detail="Cannot delete category with children")

    db.execute(text("DELETE FROM fc_categories WHERE id = :id"), {"id": cat_id})
    db.commit()
    return {"status": "deleted"}


@router.get("/categories/{cat_id}/files")
async def get_category_files(
    cat_id: int,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db)
):
    """카테고리에 속한 파일 목록"""
    offset = (page - 1) * page_size
    rows = db.execute(text(
        "SELECT id, file_name, file_path, file_size, status "
        "FROM fc_files WHERE rule_category_id = :cat_id OR final_category_id = :cat_id "
        "LIMIT :limit OFFSET :offset"
    ), {"cat_id": cat_id, "limit": page_size, "offset": offset}).fetchall()

    total = db.execute(text(
        "SELECT COUNT(*) FROM fc_files WHERE rule_category_id = :cat_id OR final_category_id = :cat_id"
    ), {"cat_id": cat_id}).fetchone()[0]

    return {
        "items": [{"id": r[0], "file_name": r[1], "file_path": r[2], "file_size": r[3], "status": r[4]} for r in rows],
        "total": total,
        "page": page,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 1
    }
