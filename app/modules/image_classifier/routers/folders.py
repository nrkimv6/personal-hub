"""
폴더 매핑 관련 API 엔드포인트

- POST /api/ic/folders/classify: 폴더 자동 분류 실행
- POST /api/ic/folders/ai-suggest: AI 카테고리 추천
- PUT /api/ic/folders/{id}/map: 매핑 저장
- POST /api/ic/folders/bulk-map: 일괄 매핑
- POST /api/ic/folders/inherit: 상위 매핑 상속
"""

import asyncio
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db, SessionLocal
from ..workers.folder_classifier import FolderClassifier
from ..adapters.base import ClassifyRequest
from ..adapters.claude_cli import ClaudeCLIAdapter
from ..adapters.gemini_cli import GeminiCLIAdapter
from ..config import settings

router = APIRouter(prefix="/folders", tags=["Folders"])


# === 요청/응답 스키마 ===
class AISuggestRequest(BaseModel):
    """AI 추천 요청"""
    folder_id: int
    sample_images: Optional[list[str]] = None  # 불명확 폴더용 샘플 이미지 경로


class AISuggestResponse(BaseModel):
    """AI 추천 응답"""
    folder_id: int
    folder_path: str
    suggested_category: str
    confidence: float
    reasoning: str


class MapFolderRequest(BaseModel):
    """폴더 매핑 요청"""
    category_id: int


class BulkMapRequest(BaseModel):
    """일괄 매핑 요청"""
    folder_ids: list[int]
    category_id: int


class InheritRequest(BaseModel):
    """상속 요청"""
    parent_folder_id: int
    apply_to_children: bool = True


# === 전역 분류 상태 ===
classify_state = {
    "is_running": False,
    "total": 0,
    "processed": 0,
    "current_folder": None,
    "error": None,
}


def update_classify_progress(total: int, processed: int, current_folder: str):
    """분류 진행 상태 업데이트 콜백"""
    global classify_state
    classify_state.update({
        "total": total,
        "processed": processed,
        "current_folder": current_folder,
    })


async def run_classify_task(force: bool):
    """분류 백그라운드 태스크"""
    global classify_state
    db = SessionLocal()
    try:
        classifier = FolderClassifier(db)
        classifier.classify_all_folders(force=force, on_progress=update_classify_progress)
        classify_state["is_running"] = False
    except Exception as e:
        classify_state["error"] = str(e)
        classify_state["is_running"] = False
    finally:
        db.close()


# === 엔드포인트 ===
@router.post("/classify")
async def classify_folders(
    background_tasks: BackgroundTasks,
    force: bool = False,
):
    """
    폴더 자동 분류 실행 (비동기)

    - force=False (기본): unknown 폴더만 분류
    - force=True: 이미 분류된 폴더도 재분류
    - 백그라운드에서 실행, /classify/status로 진행률 확인
    """
    global classify_state

    if classify_state["is_running"]:
        raise HTTPException(status_code=409, detail="폴더 분류가 이미 실행 중입니다.")

    classify_state.update({
        "is_running": True,
        "total": 0,
        "processed": 0,
        "current_folder": None,
        "error": None,
    })

    background_tasks.add_task(run_classify_task, force)

    return JSONResponse(
        status_code=202,
        content={
            "status": "started",
            "message": "폴더 분류가 시작되었습니다.",
        }
    )


@router.get("/classify/status")
async def get_classify_status():
    """폴더 분류 진행 상태 조회"""
    global classify_state

    progress = 0.0
    if classify_state["total"] > 0:
        progress = (classify_state["processed"] / classify_state["total"]) * 100

    return {
        "is_running": classify_state["is_running"],
        "total": classify_state["total"],
        "processed": classify_state["processed"],
        "progress_percent": round(progress, 2),
        "current_folder": classify_state["current_folder"],
        "error": classify_state["error"],
    }


@router.post("/ai-suggest", response_model=AISuggestResponse)
async def ai_suggest_category(
    request: AISuggestRequest,
    db: Session = Depends(get_db)
):
    """
    AI 카테고리 추천

    - clear 폴더: 텍스트 프롬프트만 사용
    - unclear 폴더: 샘플 이미지 3~5장 포함
    """
    # 폴더 정보 조회
    query = text("""
        SELECT id, folder_path, folder_status, file_count
        FROM folder_mappings
        WHERE id = :folder_id
    """)
    folder = db.execute(query, {"folder_id": request.folder_id}).fetchone()

    if not folder:
        raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다.")

    folder_path = folder.folder_path
    folder_status = folder.folder_status

    # 카테고리 목록 조회
    categories_query = text("SELECT full_path FROM categories ORDER BY full_path")
    categories = [row.full_path for row in db.execute(categories_query).fetchall()]

    if not categories:
        raise HTTPException(
            status_code=400,
            detail="카테고리가 없습니다. 먼저 카테고리를 생성하세요."
        )

    # AI 어댑터 초기화
    adapter = ClaudeCLIAdapter(settings)

    # 샘플 이미지 (unclear 폴더인 경우)
    sample_images = request.sample_images or []

    # 프롬프트 구성
    prompt = f"""
다음 폴더에 적합한 카테고리를 추천해주세요.

**폴더 경로**: {folder_path}
**폴더 상태**: {folder_status}
**파일 수**: {folder.file_count}

**사용 가능한 카테고리**:
{chr(10).join(f"- {cat}" for cat in categories)}

폴더명과 구조를 분석하여 가장 적합한 카테고리를 선택하세요.
"""

    if sample_images:
        prompt += f"\n\n**샘플 이미지**: {len(sample_images)}장이 제공되었습니다. 이미지 내용을 참고하여 판단하세요."

    try:
        # AI 분류 요청
        classify_req = ClassifyRequest(
            image_paths=sample_images,
            prompt=prompt,
            categories=categories,
        )

        result = await adapter.classify_image(classify_req)

        return AISuggestResponse(
            folder_id=request.folder_id,
            folder_path=folder_path,
            suggested_category=result.category,
            confidence=result.confidence,
            reasoning=result.reasoning or "AI가 폴더명과 구조를 분석하여 판단했습니다."
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 추천 실패: {str(e)}")


@router.put("/{folder_id}/map")
async def map_folder(
    folder_id: int,
    request: MapFolderRequest,
    db: Session = Depends(get_db)
):
    """
    폴더 매핑 저장

    - 카테고리 ID를 폴더에 연결
    - 해당 폴더의 모든 파일에 자동 적용
    """
    # 카테고리 존재 확인
    cat_query = text("SELECT id FROM categories WHERE id = :cat_id")
    category = db.execute(cat_query, {"cat_id": request.category_id}).fetchone()

    if not category:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다.")

    # 폴더 매핑 업데이트
    update_query = text("""
        UPDATE folder_mappings
        SET category_id = :cat_id, mapped_by = 'user'
        WHERE id = :folder_id
    """)
    db.execute(update_query, {"cat_id": request.category_id, "folder_id": folder_id})

    # 해당 폴더의 모든 파일에 카테고리 적용
    files_update_query = text("""
        UPDATE file_classifications
        SET final_category_id = :cat_id,
            status = 'folder_mapped'
        WHERE source_folder_id = :folder_id
        AND (status = 'pending' OR final_category_id IS NULL)
    """)
    result = db.execute(files_update_query, {"cat_id": request.category_id, "folder_id": folder_id})

    db.commit()

    return {
        "status": "success",
        "folder_id": folder_id,
        "category_id": request.category_id,
        "files_updated": result.rowcount,
        "message": "폴더 매핑 저장 완료"
    }


@router.post("/bulk-map")
async def bulk_map_folders(
    request: BulkMapRequest,
    db: Session = Depends(get_db)
):
    """
    일괄 매핑

    - 여러 폴더를 한 번에 동일한 카테고리로 매핑
    """
    # 카테고리 존재 확인
    cat_query = text("SELECT id FROM categories WHERE id = :cat_id")
    category = db.execute(cat_query, {"cat_id": request.category_id}).fetchone()

    if not category:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다.")

    # 폴더 매핑 업데이트
    for folder_id in request.folder_ids:
        update_query = text("""
            UPDATE folder_mappings
            SET category_id = :cat_id, mapped_by = 'user'
            WHERE id = :folder_id
        """)
        db.execute(update_query, {"cat_id": request.category_id, "folder_id": folder_id})

        # 파일 업데이트
        files_update_query = text("""
            UPDATE file_classifications
            SET final_category_id = :cat_id,
                status = 'folder_mapped'
            WHERE source_folder_id = :folder_id
            AND (status = 'pending' OR final_category_id IS NULL)
        """)
        db.execute(files_update_query, {"cat_id": request.category_id, "folder_id": folder_id})

    db.commit()

    return {
        "status": "success",
        "folders_updated": len(request.folder_ids),
        "category_id": request.category_id,
        "message": "일괄 매핑 완료"
    }


@router.post("/inherit")
async def inherit_mapping(
    request: InheritRequest,
    db: Session = Depends(get_db)
):
    """
    상위 매핑 상속

    - 상위 폴더의 카테고리를 하위 폴더에 자동 적용
    """
    # 상위 폴더 조회
    parent_query = text("""
        SELECT folder_path, category_id
        FROM folder_mappings
        WHERE id = :parent_id
    """)
    parent = db.execute(parent_query, {"parent_id": request.parent_folder_id}).fetchone()

    if not parent:
        raise HTTPException(status_code=404, detail="상위 폴더를 찾을 수 없습니다.")

    if not parent.category_id:
        raise HTTPException(status_code=400, detail="상위 폴더에 카테고리가 설정되지 않았습니다.")

    parent_path = parent.folder_path
    category_id = parent.category_id

    # 하위 폴더 조회 (경로가 상위 폴더로 시작하는 폴더)
    children_query = text("""
        SELECT id
        FROM folder_mappings
        WHERE folder_path LIKE :pattern
        AND id != :parent_id
    """)
    children = db.execute(
        children_query,
        {"pattern": f"{parent_path}%", "parent_id": request.parent_folder_id}
    ).fetchall()

    # 하위 폴더에 카테고리 상속
    updated_count = 0
    for child in children:
        update_query = text("""
            UPDATE folder_mappings
            SET category_id = :cat_id,
                mapped_by = 'inherited',
                parent_mapping_id = :parent_id
            WHERE id = :child_id
        """)
        db.execute(update_query, {
            "cat_id": category_id,
            "parent_id": request.parent_folder_id,
            "child_id": child.id
        })

        # 파일 업데이트
        if request.apply_to_children:
            files_update_query = text("""
                UPDATE file_classifications
                SET final_category_id = :cat_id,
                    status = 'folder_mapped'
                WHERE source_folder_id = :child_id
                AND (status = 'pending' OR final_category_id IS NULL)
            """)
            db.execute(files_update_query, {"cat_id": category_id, "child_id": child.id})

        updated_count += 1

    db.commit()

    return {
        "status": "success",
        "parent_folder_id": request.parent_folder_id,
        "children_updated": updated_count,
        "category_id": category_id,
        "message": f"{updated_count}개 하위 폴더에 카테고리 상속 완료"
    }
