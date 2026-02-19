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

router = APIRouter(prefix="/classify", tags=["classify"])
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


CLI_MAX_WORKERS = 2  # CLI 동시 호출 수


class ClassifyRequest(BaseModel):
    """AI 분류 요청"""
    file_ids: Optional[List[int]] = None  # None이면 전체 미분류 파일
    model: str = "claude_cli"  # claude_cli, gemini_cli, api
    batch_size: int = 10
    gap_minutes: int = 60  # 시간 클러스터링 간격
    max_workers: int = CLI_MAX_WORKERS  # CLI 동시 호출 수


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

    # 분류할 파일 조회 (이미 AI 분류 완료된 파일 제외 = resume 지원)
    if request.file_ids:
        query = text("""
            SELECT id, file_path
            FROM file_classifications
            WHERE id IN :file_ids
              AND (status = 'pending' OR (status = 'folder_mapped' AND ai_category_id IS NULL))
        """)
        files = db.execute(query, {"file_ids": tuple(request.file_ids)}).fetchall()
    else:
        query = text("""
            SELECT id, file_path
            FROM file_classifications
            WHERE status = 'pending' OR (status = 'folder_mapped' AND ai_category_id IS NULL)
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
        request.max_workers,
    )

    return ClassifyResponse(
        message=f"Classification started for {total} files",
        total=total,
        status="running",
    )


@router.get("/status")
async def get_status(db: Session = Depends(get_db)):
    """분류 진행 상태 조회 — 메모리 우선, DB fallback"""
    if classification_status["running"]:
        return classification_status

    # DB에서 최신 작업 조회
    from ..workers.task_progress import TaskProgressManager
    progress_mgr = TaskProgressManager(db)
    latest = progress_mgr.get_latest('ai_classify')

    if latest:
        return {
            "running": latest["status"] == "running",
            "total": latest["total_items"] or 0,
            "processed": latest["processed_items"] or 0,
            "failed": 0,
            "current_file": latest["current_item"],
            "model": None,
            "status": latest["status"],
            "error": latest["error_message"],
        }

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
    max_workers: int = CLI_MAX_WORKERS,
):
    """
    실제 분류 실행 (백그라운드) — 병렬 CLI 호출 + DB 진행 추적
    """
    global classification_status

    from ..database import SessionLocal
    from ..workers.task_progress import TaskProgressManager

    progress_db = SessionLocal()
    progress_mgr = TaskProgressManager(progress_db)
    task_id = progress_mgr.start_task('ai_classify', len(files))
    classification_status["task_id"] = task_id

    # 모델 어댑터 선택
    if model == "claude_cli":
        adapter = ClaudeCLIAdapter()
    elif model == "gemini_cli":
        adapter = GeminiCLIAdapter()
    else:
        logger.error(f"Unknown model: {model}")
        classification_status["running"] = False
        progress_mgr.fail_task(task_id, f"Unknown model: {model}")
        progress_db.close()
        return

    semaphore = asyncio.Semaphore(max_workers)

    async def classify_one(file_id: int, file_path: str):
        """단일 파일 분류 (세마포어 제어)"""
        async with semaphore:
            if not classification_status["running"]:
                return

            classification_status["current_file"] = file_path

            try:
                result = await adapter.classify_image(file_path)

                if result and result.category:
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

    try:
        # 배치 단위로 병렬 처리
        for i in range(0, len(files), batch_size):
            if not classification_status["running"]:
                msg = "Classification stopped by user"
                logger.info(msg)
                from ..workers.log_buffer import pipeline_logs
                pipeline_logs.add("classify", msg)
                progress_mgr.pause_task(task_id)
                break

            batch = files[i:i + batch_size]
            tasks = [classify_one(f.id, f.file_path) for f in batch]
            await asyncio.gather(*tasks)

            # DB 진행 업데이트
            try:
                processed_total = classification_status["processed"] + classification_status["failed"]
                progress_mgr.update_progress(
                    task_id, processed_total,
                    f"배치 {i // batch_size + 1} 완료"
                )
            except Exception:
                pass
        else:
            progress_mgr.complete_task(task_id)

    except Exception as e:
        progress_mgr.fail_task(task_id, str(e))
        raise
    finally:
        classification_status["running"] = False
        classification_status["current_file"] = None
        progress_db.close()

        msg = (
            f"Classification completed: {classification_status['processed']}/{classification_status['total']} "
            f"(failed: {classification_status['failed']})"
        )
        logger.info(msg)
        from ..workers.log_buffer import pipeline_logs
        pipeline_logs.add("classify", msg)
