"""
파일 분류 모듈 헬스체크 라우터
"""

import os
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings

router = APIRouter(tags=["File Classifier - Health"])


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """파일 분류 모듈 헬스체크"""

    # DB 연결 확인
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"

    # 주요 테이블 존재 확인
    tables_ok = True
    tables_status = {}
    for table in ["fc_files", "fc_categories", "fc_rules", "fc_task_progress"]:
        try:
            db.execute(text(f"SELECT COUNT(*) FROM {table}"))
            tables_status[table] = "ok"
        except Exception as e:
            tables_status[table] = f"error: {str(e)}"
            tables_ok = False

    return {
        "status": "ok" if db_status == "ok" and tables_ok else "error",
        "module": "file_classifier",
        "version": "0.1.0",
        "database": db_status,
        "tables": tables_status,
        "settings": {
            "scan_roots": settings.SCAN_ROOT_FOLDERS,
            "target_folder": settings.TARGET_ROOT_FOLDER,
            "llm_mode": settings.LLM_MODE,
            "dry_run_default": settings.DRY_RUN_DEFAULT,
        }
    }


@router.get("/diagnostic")
async def diagnostic_check(db: Session = Depends(get_db)):
    """전체 모듈 상태 진단"""
    results = {}

    # 1. 설정 유효성
    settings_issues = []
    if not settings.SCAN_ROOT_FOLDERS:
        settings_issues.append("SCAN_ROOT_FOLDERS가 비어있습니다")
    if settings.LLM_MODE not in ("cli", "api"):
        settings_issues.append(f"LLM_MODE가 유효하지 않습니다: {settings.LLM_MODE}")

    results["settings"] = {
        "status": "ok" if not settings_issues else "warning",
        "message": "설정 정상" if not settings_issues else f"{len(settings_issues)}개 문제 발견",
        "details": settings_issues if settings_issues else None,
    }

    # 2. 데이터베이스
    try:
        file_count = db.execute(text("SELECT COUNT(*) FROM fc_files")).scalar() or 0
        results["database"] = {
            "status": "ok",
            "message": f"파일 {file_count}개 등록됨",
            "details": {"files": file_count},
        }
    except Exception as e:
        results["database"] = {
            "status": "error",
            "message": f"DB 오류: {str(e)}",
            "details": None,
        }

    # 3. 스캔 루트 존재 여부
    scan_issues = []
    for folder in settings.SCAN_ROOT_FOLDERS:
        if not os.path.exists(folder):
            scan_issues.append(f"경로 없음: {folder}")

    results["scan"] = {
        "status": "ok" if not scan_issues and settings.SCAN_ROOT_FOLDERS else "warning",
        "message": (
            f"{len(settings.SCAN_ROOT_FOLDERS)}개 스캔 루트"
            if settings.SCAN_ROOT_FOLDERS else "스캔 루트 미설정"
        ),
        "details": scan_issues if scan_issues else None,
    }

    # 전체 상태 판단
    statuses = [v["status"] for v in results.values()]
    overall = "error" if "error" in statuses else ("warning" if "warning" in statuses else "ok")

    return {
        "overall": overall,
        "modules": results,
    }
