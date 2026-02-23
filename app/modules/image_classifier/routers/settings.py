"""
이미지 분류 모듈 설정 관리 API

- GET /api/ic/settings: 현재 설정 조회
- PUT /api/ic/settings: 설정 업데이트
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..config import settings, save_settings_to_file
from ..database import get_db

router = APIRouter(prefix="/settings", tags=["Settings"])


class SettingsResponse(BaseModel):
    """설정 응답"""
    scan_root_folders: list[str]
    image_extensions: list[str]
    max_files_per_scan: int
    phash_hash_size: int
    phash_duplicate_threshold: int
    clip_model_name: str
    clip_batch_size: int
    clip_use_gpu: bool
    faiss_similarity_threshold: float
    thumbnail_size: tuple[int, int]
    thumbnail_quality: int
    ai_mode: str
    claude_cli_path: str
    claude_model: str
    gemini_cli_path: str
    cli_max_workers: int
    cli_timeout_seconds: int
    cluster_gap_minutes: int
    target_root_folder: Optional[str]
    use_trash: bool
    max_workers_per_task: int


class SettingsUpdateRequest(BaseModel):
    """설정 업데이트 요청"""
    scan_root_folders: Optional[list[str]] = None
    max_files_per_scan: Optional[int] = None
    phash_duplicate_threshold: Optional[int] = None
    clip_batch_size: Optional[int] = None
    clip_use_gpu: Optional[bool] = None
    faiss_similarity_threshold: Optional[float] = None
    ai_mode: Optional[str] = None
    claude_model: Optional[str] = None
    cli_max_workers: Optional[int] = None
    cli_timeout_seconds: Optional[int] = None
    cluster_gap_minutes: Optional[int] = None
    target_root_folder: Optional[str] = None
    use_trash: Optional[bool] = None


@router.get("")
async def get_settings() -> SettingsResponse:
    """현재 설정 조회"""
    return SettingsResponse(
        scan_root_folders=settings.SCAN_ROOT_FOLDERS,
        image_extensions=list(settings.IMAGE_EXTENSIONS),
        max_files_per_scan=settings.MAX_FILES_PER_SCAN,
        phash_hash_size=settings.PHASH_HASH_SIZE,
        phash_duplicate_threshold=settings.PHASH_DUPLICATE_THRESHOLD,
        clip_model_name=settings.CLIP_MODEL_NAME,
        clip_batch_size=settings.CLIP_BATCH_SIZE,
        clip_use_gpu=settings.CLIP_USE_GPU,
        faiss_similarity_threshold=settings.FAISS_SIMILARITY_THRESHOLD,
        thumbnail_size=settings.THUMBNAIL_SIZE,
        thumbnail_quality=settings.THUMBNAIL_QUALITY,
        ai_mode=settings.AI_MODE,
        claude_cli_path=settings.CLAUDE_CLI_PATH,
        claude_model=settings.CLAUDE_MODEL,
        gemini_cli_path=settings.GEMINI_CLI_PATH,
        cli_max_workers=settings.CLI_MAX_WORKERS,
        cli_timeout_seconds=settings.CLI_TIMEOUT_SECONDS,
        cluster_gap_minutes=settings.CLUSTER_GAP_MINUTES,
        target_root_folder=settings.TARGET_ROOT_FOLDER,
        use_trash=settings.USE_TRASH,
        max_workers_per_task=settings.MAX_WORKERS_PER_TASK
    )


@router.put("")
async def update_settings(request: SettingsUpdateRequest):
    """설정 업데이트 (런타임만 반영, 영구 저장 안 됨)"""

    if request.scan_root_folders is not None:
        settings.SCAN_ROOT_FOLDERS = request.scan_root_folders

    if request.max_files_per_scan is not None:
        settings.MAX_FILES_PER_SCAN = request.max_files_per_scan

    if request.phash_duplicate_threshold is not None:
        settings.PHASH_DUPLICATE_THRESHOLD = request.phash_duplicate_threshold

    if request.clip_batch_size is not None:
        settings.CLIP_BATCH_SIZE = request.clip_batch_size

    if request.clip_use_gpu is not None:
        settings.CLIP_USE_GPU = request.clip_use_gpu

    if request.faiss_similarity_threshold is not None:
        settings.FAISS_SIMILARITY_THRESHOLD = request.faiss_similarity_threshold

    if request.ai_mode is not None:
        settings.AI_MODE = request.ai_mode

    if request.claude_model is not None:
        settings.CLAUDE_MODEL = request.claude_model

    if request.cli_max_workers is not None:
        settings.CLI_MAX_WORKERS = request.cli_max_workers

    if request.cli_timeout_seconds is not None:
        settings.CLI_TIMEOUT_SECONDS = request.cli_timeout_seconds

    if request.cluster_gap_minutes is not None:
        settings.CLUSTER_GAP_MINUTES = request.cluster_gap_minutes

    if request.target_root_folder is not None:
        settings.TARGET_ROOT_FOLDER = request.target_root_folder

    if request.use_trash is not None:
        settings.USE_TRASH = request.use_trash

    # 파일에 저장
    try:
        save_settings_to_file()
        return {
            "status": "ok",
            "message": "설정이 저장되었습니다 (영구 저장됨)"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"설정 저장 실패: {str(e)}"
        }


# =========================================================
# year_annotations CRUD
# =========================================================

class YearAnnotationCreate(BaseModel):
    year: int
    annotation: str
    color: Optional[str] = None


class YearAnnotationUpdate(BaseModel):
    annotation: Optional[str] = None
    color: Optional[str] = None


@router.get("/year-annotations")
async def list_year_annotations(db: Session = Depends(get_db)):
    """연도 메모 목록 조회"""
    rows = db.execute(
        text("SELECT id, year, annotation, color FROM year_annotations ORDER BY year")
    ).fetchall()
    return {
        "year_annotations": [
            {"id": r.id, "year": r.year, "annotation": r.annotation, "color": r.color}
            for r in rows
        ]
    }


@router.post("/year-annotations", status_code=201)
async def create_year_annotation(body: YearAnnotationCreate, db: Session = Depends(get_db)):
    """연도 메모 생성"""
    existing = db.execute(
        text("SELECT id FROM year_annotations WHERE year = :year"),
        {"year": body.year}
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail=f"{body.year}년 메모가 이미 존재합니다.")

    db.execute(
        text("INSERT INTO year_annotations (year, annotation, color) VALUES (:year, :annotation, :color)"),
        {"year": body.year, "annotation": body.annotation, "color": body.color}
    )
    db.commit()

    row = db.execute(
        text("SELECT id, year, annotation, color FROM year_annotations WHERE year = :year"),
        {"year": body.year}
    ).fetchone()
    return {"id": row.id, "year": row.year, "annotation": row.annotation, "color": row.color}


@router.put("/year-annotations/{annotation_id}")
async def update_year_annotation(
    annotation_id: int,
    body: YearAnnotationUpdate,
    db: Session = Depends(get_db),
):
    """연도 메모 수정"""
    row = db.execute(
        text("SELECT id, year, annotation, color FROM year_annotations WHERE id = :id"),
        {"id": annotation_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="연도 메모를 찾을 수 없습니다.")

    new_annotation = body.annotation if body.annotation is not None else row.annotation
    new_color = body.color if body.color is not None else row.color

    db.execute(
        text("UPDATE year_annotations SET annotation = :annotation, color = :color WHERE id = :id"),
        {"annotation": new_annotation, "color": new_color, "id": annotation_id}
    )
    db.commit()
    return {"id": annotation_id, "year": row.year, "annotation": new_annotation, "color": new_color}


@router.delete("/year-annotations/{annotation_id}", status_code=204)
async def delete_year_annotation(annotation_id: int, db: Session = Depends(get_db)):
    """연도 메모 삭제"""
    row = db.execute(
        text("SELECT id FROM year_annotations WHERE id = :id"),
        {"id": annotation_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="연도 메모를 찾을 수 없습니다.")

    db.execute(text("DELETE FROM year_annotations WHERE id = :id"), {"id": annotation_id})
    db.commit()
    return None
