"""
이미지 분류 모듈 헬스체크 라우터
"""

from fastapi import APIRouter, Depends
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
        db.execute("SELECT 1")
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
