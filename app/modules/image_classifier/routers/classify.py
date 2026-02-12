"""
AI 분류 라우터

CLI 기반 (Claude CLI / Gemini CLI) 또는 API 기반 이미지 분류
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import logging

from ..database import get_db
from ..adapters.claude_cli import ClaudeCLIAdapter
from ..adapters.gemini_cli import GeminiCLIAdapter

router = APIRouter(prefix="/api/ic/classify", tags=["classify"])
logger = logging.getLogger(__name__)

# 전역 상태 (실제 프로덕션에서는 Redis 등 사용)
classification_status = {
    "running": False,
    "total": 0,
    "processed": 0,
    "failed": 0,
    "current_file": None,
    "model": None,
}


class ClassifyRequest(BaseModel):
    """AI 분류 요청"""
    file_ids: Optional[List[int]] = None  # None이면 전체 미분류 파일
    model: str = "claude_cli"  # claude_cli, gemini_cli, api
    batch_size: int = 10
    gap_minutes: int = 60  # 시간 클러스터링 간격


class ClassifyResponse(BaseModel):
    """분류 응답"""
    message: str
    total: int
    status: str


@router.post("/start", response_model=ClassifyResponse)
async def start_classification(
    request: ClassifyRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    AI 분류 시작 (백그라운드 작업)
    """
    global classification_status

    if classification_status["running"]:
        raise HTTPException(status_code=400, detail="Classification already running")

    # 분류할 파일 조회
    if request.file_ids:
        query = text("""
            SELECT id, file_path
            FROM file_classifications
            WHERE id IN :file_ids
              AND (status = 'pending' OR status = 'folder_mapped')
        """)
        files = db.execute(query, {"file_ids": tuple(request.file_ids)}).fetchall()
    else:
        query = text("""
            SELECT id, file_path
            FROM file_classifications
            WHERE status = 'pending' OR status = 'folder_mapped'
            ORDER BY id
        """)
        files = db.execute(query).fetchall()

    total = len(files)

    if total == 0:
        raise HTTPException(status_code=400, detail="No files to classify")

    # 상태 초기화
    classification_status = {
        "running": True,
        "total": total,
        "processed": 0,
        "failed": 0,
        "current_file": None,
        "model": request.model,
    }

    # 백그라운드 작업 시작
    background_tasks.add_task(
        run_classification,
        files,
        request.model,
        request.batch_size,
        request.gap_minutes,
    )

    return ClassifyResponse(
        message=f"Classification started for {total} files",
        total=total,
        status="running",
    )


@router.get("/status")
async def get_status():
    """분류 진행 상태 조회"""
    return classification_status


@router.post("/stop")
async def stop_classification():
    """분류 중지"""
    global classification_status

    if not classification_status["running"]:
        raise HTTPException(status_code=400, detail="No classification running")

    classification_status["running"] = False

    return {"message": "Classification stopped"}


async def run_classification(
    files: List[tuple],
    model: str,
    batch_size: int,
    gap_minutes: int,
):
    """
    실제 분류 실행 (백그라운드)
    """
    global classification_status

    # 모델 어댑터 선택
    if model == "claude_cli":
        adapter = ClaudeCLIAdapter()
    elif model == "gemini_cli":
        adapter = GeminiCLIAdapter()
    else:
        logger.error(f"Unknown model: {model}")
        classification_status["running"] = False
        return

    try:
        for file in files:
            if not classification_status["running"]:
                logger.info("Classification stopped by user")
                break

            file_id, file_path = file
            classification_status["current_file"] = file_path

            try:
                # CLI로 분류 실행
                result = await adapter.classify_image(file_path)

                if result and result.category:
                    # DB 업데이트 (새 세션 사용)
                    from ..database import SessionLocal

                    db = SessionLocal()
                    try:
                        update_query = text("""
                            UPDATE file_classifications
                            SET ai_category_id = :category_id,
                                ai_confidence = :confidence,
                                ai_reasoning = :reasoning,
                                ai_model = :model,
                                final_category_id = :category_id,
                                status = 'ai_classified',
                                classified_at = datetime('now')
                            WHERE id = :file_id
                        """)
                        db.execute(update_query, {
                            "file_id": file_id,
                            "category_id": result.category_id,
                            "confidence": result.confidence,
                            "reasoning": result.reasoning,
                            "model": model,
                        })
                        db.commit()

                        classification_status["processed"] += 1
                    finally:
                        db.close()
                else:
                    classification_status["failed"] += 1

            except Exception as e:
                logger.error(f"Classification failed for {file_path}: {e}")
                classification_status["failed"] += 1

            # 짧은 딜레이
            await asyncio.sleep(0.5)

    finally:
        classification_status["running"] = False
        classification_status["current_file"] = None

        logger.info(
            f"Classification completed: {classification_status['processed']}/{classification_status['total']} "
            f"(failed: {classification_status['failed']})"
        )
