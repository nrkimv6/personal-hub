"""
카테고리 관련 API 엔드포인트

- GET /api/ic/categories: 카테고리 트리 조회
- POST /api/ic/categories: 카테고리 추가
- PUT /api/ic/categories/{id}: 카테고리 수정
- DELETE /api/ic/categories/{id}: 카테고리 삭제
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db

router = APIRouter(prefix="/categories", tags=["Categories"])


# === 요청/응답 스키마 ===
class CategoryCreate(BaseModel):
    """카테고리 생성 요청"""
    name: str
    parent_id: Optional[int] = None
    importance: Optional[str] = "medium"  # high/medium/low
    target_folder_template: Optional[str] = None
    description: Optional[str] = None


class CategoryUpdate(BaseModel):
    """카테고리 수정 요청"""
    name: Optional[str] = None
    parent_id: Optional[int] = None
    importance: Optional[str] = None
    target_folder_template: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


class CategoryResponse(BaseModel):
    """카테고리 응답"""
    id: int
    name: str
    parent_id: Optional[int]
    full_path: str
    importance: str
    target_folder_template: Optional[str]
    description: Optional[str]
    sort_order: int
    children: list["CategoryResponse"] = []


# === 엔드포인트 ===
@router.get("/")
async def get_categories(
    include_tree: bool = True,
    db: Session = Depends(get_db)
):
    """
    카테고리 목록 조회

    Args:
        include_tree: True면 트리 구조, False면 플랫 리스트
    """
    query = text("""
        SELECT id, name, parent_id, full_path, importance,
               target_folder_template, description, sort_order
        FROM categories
        ORDER BY sort_order, full_path
    """)
    rows = db.execute(query).fetchall()

    categories = []
    for row in rows:
        categories.append({
            "id": row.id,
            "name": row.name,
            "parent_id": row.parent_id,
            "full_path": row.full_path,
            "importance": row.importance or "medium",
            "target_folder_template": row.target_folder_template,
            "description": row.description,
            "sort_order": row.sort_order or 0,
            "children": []
        })

    if not include_tree:
        return {"categories": categories}

    # 트리 구조 생성
    tree = build_category_tree(categories)

    return {"categories": tree}


@router.post("/", response_model=CategoryResponse)
async def create_category(
    request: CategoryCreate,
    db: Session = Depends(get_db)
):
    """
    카테고리 생성

    - full_path는 자동 생성 (parent/child 형태)
    """
    # 부모 카테고리 확인
    parent_path = ""
    if request.parent_id:
        parent_query = text("SELECT full_path FROM categories WHERE id = :parent_id")
        parent = db.execute(parent_query, {"parent_id": request.parent_id}).fetchone()

        if not parent:
            raise HTTPException(status_code=404, detail="부모 카테고리를 찾을 수 없습니다.")

        parent_path = parent.full_path

    # full_path 생성
    full_path = f"{parent_path}/{request.name}" if parent_path else request.name

    # 중복 확인
    dup_query = text("SELECT id FROM categories WHERE full_path = :path")
    duplicate = db.execute(dup_query, {"path": full_path}).fetchone()

    if duplicate:
        raise HTTPException(status_code=409, detail="이미 존재하는 카테고리 경로입니다.")

    # 삽입
    insert_query = text("""
        INSERT INTO categories (name, parent_id, full_path, importance, target_folder_template, description, sort_order)
        VALUES (:name, :parent_id, :full_path, :importance, :target_folder_template, :description, 0)
    """)
    db.execute(insert_query, {
        "name": request.name,
        "parent_id": request.parent_id,
        "full_path": full_path,
        "importance": request.importance,
        "target_folder_template": request.target_folder_template,
        "description": request.description,
    })
    db.commit()

    # 생성된 카테고리 조회
    new_cat_query = text("""
        SELECT id, name, parent_id, full_path, importance, target_folder_template, description, sort_order
        FROM categories
        WHERE full_path = :path
    """)
    new_cat = db.execute(new_cat_query, {"path": full_path}).fetchone()

    return CategoryResponse(
        id=new_cat.id,
        name=new_cat.name,
        parent_id=new_cat.parent_id,
        full_path=new_cat.full_path,
        importance=new_cat.importance,
        target_folder_template=new_cat.target_folder_template,
        description=new_cat.description,
        sort_order=new_cat.sort_order,
        children=[]
    )


@router.put("/{category_id}")
async def update_category(
    category_id: int,
    request: CategoryUpdate,
    db: Session = Depends(get_db)
):
    """
    카테고리 수정

    - name 변경 시 full_path도 자동 업데이트
    - 하위 카테고리의 full_path도 재계산
    """
    # 기존 카테고리 조회
    cat_query = text("SELECT * FROM categories WHERE id = :cat_id")
    category = db.execute(cat_query, {"cat_id": category_id}).fetchone()

    if not category:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다.")

    old_full_path = category.full_path

    # 업데이트할 필드 구성
    updates = []
    params = {"cat_id": category_id}

    if request.name:
        # full_path 재계산
        parent_path = ""
        if category.parent_id:
            parent_query = text("SELECT full_path FROM categories WHERE id = :parent_id")
            parent = db.execute(parent_query, {"parent_id": category.parent_id}).fetchone()
            parent_path = parent.full_path if parent else ""

        new_full_path = f"{parent_path}/{request.name}" if parent_path else request.name
        updates.append("name = :name")
        updates.append("full_path = :full_path")
        params["name"] = request.name
        params["full_path"] = new_full_path

    if request.parent_id is not None:
        updates.append("parent_id = :parent_id")
        params["parent_id"] = request.parent_id

    if request.importance:
        updates.append("importance = :importance")
        params["importance"] = request.importance

    if request.target_folder_template is not None:
        updates.append("target_folder_template = :target_folder_template")
        params["target_folder_template"] = request.target_folder_template

    if request.description is not None:
        updates.append("description = :description")
        params["description"] = request.description

    if request.sort_order is not None:
        updates.append("sort_order = :sort_order")
        params["sort_order"] = request.sort_order

    if not updates:
        raise HTTPException(status_code=400, detail="수정할 내용이 없습니다.")

    # 업데이트 실행
    update_query = text(f"""
        UPDATE categories
        SET {', '.join(updates)}
        WHERE id = :cat_id
    """)
    db.execute(update_query, params)

    # full_path가 변경된 경우 하위 카테고리도 업데이트
    if "full_path" in params:
        new_full_path = params["full_path"]
        children_query = text("""
            SELECT id, full_path
            FROM categories
            WHERE full_path LIKE :pattern
            AND id != :cat_id
        """)
        children = db.execute(children_query, {
            "pattern": f"{old_full_path}/%",
            "cat_id": category_id
        }).fetchall()

        for child in children:
            child_new_path = child.full_path.replace(old_full_path, new_full_path, 1)
            child_update_query = text("""
                UPDATE categories
                SET full_path = :new_path
                WHERE id = :child_id
            """)
            db.execute(child_update_query, {"new_path": child_new_path, "child_id": child.id})

    db.commit()

    return {
        "status": "success",
        "category_id": category_id,
        "message": "카테고리 수정 완료"
    }


@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    force: bool = False,
    db: Session = Depends(get_db)
):
    """
    카테고리 삭제

    Args:
        force: True면 하위 카테고리와 매핑된 파일도 모두 삭제
    """
    # 카테고리 조회
    cat_query = text("SELECT full_path FROM categories WHERE id = :cat_id")
    category = db.execute(cat_query, {"cat_id": category_id}).fetchone()

    if not category:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다.")

    full_path = category.full_path

    # 하위 카테고리 확인
    children_query = text("""
        SELECT COUNT(*) as count
        FROM categories
        WHERE full_path LIKE :pattern
        AND id != :cat_id
    """)
    children_count = db.execute(children_query, {
        "pattern": f"{full_path}/%",
        "cat_id": category_id
    }).fetchone().count

    if children_count > 0 and not force:
        raise HTTPException(
            status_code=400,
            detail=f"하위 카테고리가 {children_count}개 있습니다. force=true로 강제 삭제하거나 먼저 하위 카테고리를 삭제하세요."
        )

    # 매핑된 폴더/파일 확인
    mapped_folders_query = text("SELECT COUNT(*) as count FROM folder_mappings WHERE category_id = :cat_id")
    mapped_folders_count = db.execute(mapped_folders_query, {"cat_id": category_id}).fetchone().count

    mapped_files_query = text("SELECT COUNT(*) as count FROM file_classifications WHERE final_category_id = :cat_id")
    mapped_files_count = db.execute(mapped_files_query, {"cat_id": category_id}).fetchone().count

    if (mapped_folders_count > 0 or mapped_files_count > 0) and not force:
        raise HTTPException(
            status_code=400,
            detail=f"매핑된 폴더({mapped_folders_count}개) 또는 파일({mapped_files_count}개)이 있습니다. force=true로 강제 삭제하세요."
        )

    # 하위 카테고리 삭제
    if force and children_count > 0:
        delete_children_query = text("""
            DELETE FROM categories
            WHERE full_path LIKE :pattern
            AND id != :cat_id
        """)
        db.execute(delete_children_query, {"pattern": f"{full_path}/%", "cat_id": category_id})

    # 매핑 해제
    if force:
        db.execute(text("UPDATE folder_mappings SET category_id = NULL WHERE category_id = :cat_id"), {"cat_id": category_id})
        db.execute(text("UPDATE file_classifications SET final_category_id = NULL WHERE final_category_id = :cat_id"), {"cat_id": category_id})

    # 카테고리 삭제
    delete_query = text("DELETE FROM categories WHERE id = :cat_id")
    db.execute(delete_query, {"cat_id": category_id})

    db.commit()

    return {
        "status": "success",
        "category_id": category_id,
        "children_deleted": children_count if force else 0,
        "message": "카테고리 삭제 완료"
    }


# === 헬퍼 함수 ===
def build_category_tree(categories: list[dict]) -> list[dict]:
    """
    플랫 리스트를 트리 구조로 변환

    Args:
        categories: 카테고리 딕셔너리 리스트

    Returns:
        트리 구조 리스트 (parent_id가 None인 루트만)
    """
    # ID로 빠른 조회를 위한 맵
    cat_map = {cat["id"]: cat for cat in categories}

    # 루트 카테고리
    roots = []

    for cat in categories:
        if cat["parent_id"] is None:
            roots.append(cat)
        else:
            # 부모에 자식 추가
            parent = cat_map.get(cat["parent_id"])
            if parent:
                parent["children"].append(cat)

    return roots
