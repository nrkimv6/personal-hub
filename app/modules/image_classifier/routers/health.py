"""
이미지 분류 모듈 헬스체크 라우터
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..adapters.claude_cli import ClaudeCLIAdapter
from ..adapters.gemini_cli import GeminiCLIAdapter

router = APIRouter(prefix="/api/ic", tags=["Image Classifier - Health"])


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """이미지 분류 모듈 헬스체크"""

    # DB 연결 확인
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Claude CLI 사용 가능 여부
    claude_adapter = ClaudeCLIAdapter()
    claude_available = await claude_adapter.is_available()

    # Gemini CLI 사용 가능 여부
    gemini_adapter = GeminiCLIAdapter()
    gemini_available = await gemini_adapter.is_available()

    return {
        "status": "ok",
        "module": "image_classifier",
        "version": "0.1.0",
        "database": db_status,
        "ai_adapters": {
            "claude_cli": {
                "available": claude_available,
                "path": settings.CLAUDE_CLI_PATH
            },
            "gemini_cli": {
                "available": gemini_available,
                "path": settings.GEMINI_CLI_PATH
            },
            "mode": settings.AI_MODE
        },
        "settings": {
            "scan_roots": settings.SCAN_ROOT_FOLDERS,
            "clip_model": settings.CLIP_MODEL_NAME,
            "clip_gpu": settings.CLIP_USE_GPU,
            "cluster_gap_minutes": settings.CLUSTER_GAP_MINUTES
        }
    }


@router.get("/diagnostic")
async def diagnostic_check(db: Session = Depends(get_db)):
    """전체 모듈 상태 진단"""
    import os

    results = {}

    # 1. 설정 유효성
    settings_issues = []
    if not settings.SCAN_ROOT_FOLDERS:
        settings_issues.append("SCAN_ROOT_FOLDERS가 비어있습니다")
    if settings.AI_MODE not in ("cli", "api"):
        settings_issues.append(f"AI_MODE가 유효하지 않습니다: {settings.AI_MODE}")
    if settings.CLI_MAX_WORKERS <= 0:
        settings_issues.append(f"CLI_MAX_WORKERS가 유효하지 않습니다: {settings.CLI_MAX_WORKERS}")

    results["settings"] = {
        "status": "ok" if not settings_issues else "warning",
        "message": "설정 정상" if not settings_issues else f"{len(settings_issues)}개 문제 발견",
        "details": settings_issues if settings_issues else None
    }

    # 2. 데이터베이스
    try:
        folder_count = db.execute(text("SELECT COUNT(*) FROM folder_mappings")).scalar() or 0
        file_count = db.execute(text("SELECT COUNT(*) FROM file_classifications")).scalar() or 0
        results["database"] = {
            "status": "ok",
            "message": f"폴더 {folder_count}개, 파일 {file_count}개",
            "details": {"folders": folder_count, "files": file_count}
        }
    except Exception as e:
        results["database"] = {
            "status": "error",
            "message": f"DB 오류: {str(e)}",
            "details": None
        }

    # 3. 스캔 루트 존재 여부
    scan_issues = []
    for folder in settings.SCAN_ROOT_FOLDERS:
        if not os.path.exists(folder):
            scan_issues.append(f"경로 없음: {folder}")

    results["scan"] = {
        "status": "ok" if not scan_issues and settings.SCAN_ROOT_FOLDERS else ("warning" if scan_issues else "warning"),
        "message": f"{len(settings.SCAN_ROOT_FOLDERS)}개 스캔 루트" if settings.SCAN_ROOT_FOLDERS else "스캔 루트 미설정",
        "details": scan_issues if scan_issues else None
    }

    # 4. AI 분류
    try:
        classified = db.execute(text("SELECT COUNT(*) FROM file_classifications WHERE status = 'ai_classified'")).scalar() or 0
        unclassified = db.execute(text("SELECT COUNT(*) FROM file_classifications WHERE final_category_id IS NULL")).scalar() or 0

        claude_adapter = ClaudeCLIAdapter()
        claude_ok = await claude_adapter.is_available()

        results["ai_classification"] = {
            "status": "ok" if claude_ok else "warning",
            "message": f"분류 {classified}개, 미분류 {unclassified}개" + (" (Claude 사용 불가)" if not claude_ok else ""),
            "details": {"classified": classified, "unclassified": unclassified, "claude_available": claude_ok}
        }
    except Exception as e:
        results["ai_classification"] = {
            "status": "error",
            "message": str(e),
            "details": None
        }

    # 5. 중복
    try:
        dup_count = db.execute(text("SELECT COUNT(DISTINCT phash) FROM file_classifications WHERE phash IS NOT NULL GROUP BY phash HAVING COUNT(*) > 1")).fetchall()
        results["duplicates"] = {
            "status": "ok",
            "message": f"중복 그룹 {len(dup_count)}개",
            "details": {"groups": len(dup_count)}
        }
    except Exception:
        results["duplicates"] = {
            "status": "ok",
            "message": "중복 데이터 없음",
            "details": None
        }

    # 6. 카테고리
    try:
        cat_count = db.execute(text("SELECT COUNT(*) FROM categories")).scalar() or 0
        mapped_folders = db.execute(text("SELECT COUNT(*) FROM folder_mappings WHERE category_id IS NOT NULL")).scalar() or 0
        total_folders = db.execute(text("SELECT COUNT(*) FROM folder_mappings")).scalar() or 0
        pct = round(mapped_folders / total_folders * 100) if total_folders > 0 else 0

        results["categories"] = {
            "status": "ok" if cat_count > 0 else "warning",
            "message": f"{cat_count}개 카테고리, 매핑률 {pct}%",
            "details": {"categories": cat_count, "mapped_folders": mapped_folders, "total_folders": total_folders}
        }
    except Exception as e:
        results["categories"] = {
            "status": "error",
            "message": str(e),
            "details": None
        }

    # 전체 상태 판단
    statuses = [v["status"] for v in results.values()]
    overall = "error" if "error" in statuses else ("warning" if "warning" in statuses else "ok")

    return {
        "overall": overall,
        "modules": results
    }
