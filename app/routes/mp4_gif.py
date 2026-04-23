"""MP4 -> GIF conversion API routes."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import SessionLocal, get_db
from app.models.mp4_gif_task import Mp4GifTask
from app.schemas.mp4_gif import (
    Mp4GifHealthResponse,
    Mp4GifTaskAcceptedResponse,
    Mp4GifTaskStatusResponse,
)
from app.services.mp4_gif_service import (
    cleanup_expired_workdirs,
    ffmpeg_health,
    get_task_input_path,
    get_task_output_path,
    get_work_root,
    run_ffmpeg_conversion,
    validate_mp4_upload,
)

router = APIRouter(prefix="/api/v1/mp4-gif", tags=["mp4-gif"])


def _serialize_task(task: Mp4GifTask) -> Mp4GifTaskStatusResponse:
    return Mp4GifTaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        source_name=task.source_name,
        fps=task.fps,
        start_seconds=task.start_seconds,
        duration_seconds=task.duration_seconds,
        error_message=task.error_message,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )


def _run_task(task_id: str) -> None:
    cleanup_expired_workdirs()
    db = SessionLocal()
    try:
        task = db.query(Mp4GifTask).filter(Mp4GifTask.task_id == task_id).first()
        if task is None:
            return

        task.mark_running()
        db.commit()

        input_path = Path(task.stored_input_path)
        output_path = Path(task.stored_output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        error_message = run_ffmpeg_conversion(
            input_path, output_path, task.fps,
            start_seconds=task.start_seconds,
            duration_seconds=task.duration_seconds,
        )
        if error_message:
            task.mark_failed(error_message)
        else:
            task.mark_completed()

        db.commit()
    finally:
        db.close()


@router.post("/tasks", status_code=202, response_model=Mp4GifTaskAcceptedResponse)
async def create_task(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    fps: int = Form(10),
    start_seconds: float | None = Form(None),
    duration_seconds: float | None = Form(None),
    db: Session = Depends(get_db),
):
    if fps <= 0:
        raise HTTPException(status_code=400, detail="fps는 1 이상의 정수여야 합니다.")
    if start_seconds is not None and start_seconds < 0:
        raise HTTPException(status_code=400, detail="start_seconds는 0 이상이어야 합니다.")
    if duration_seconds is not None and duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="duration_seconds는 0보다 커야 합니다.")

    source_name = file.filename or "video.mp4"
    file_bytes = await file.read()
    try:
        validate_mp4_upload(source_name, len(file_bytes))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if file.content_type and file.content_type.lower() not in {"video/mp4", "application/mp4"}:
        if Path(source_name).suffix.lower() != ".mp4":
            raise HTTPException(status_code=400, detail="MP4 파일만 업로드할 수 있습니다.")

    task_id = str(uuid4())
    input_path = get_task_input_path(task_id, source_name)
    output_path = get_task_output_path(task_id, source_name)
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_bytes(file_bytes)

    task = Mp4GifTask(
        task_id=task_id,
        status=Mp4GifTask.STATUS_QUEUED,
        source_name=source_name,
        stored_input_path=str(input_path),
        stored_output_path=str(output_path),
        fps=fps,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
    )
    db.add(task)
    db.commit()

    background_tasks.add_task(_run_task, task_id)
    return Mp4GifTaskAcceptedResponse(task_id=task_id, status=task.status)


@router.get("/tasks/{task_id}", response_model=Mp4GifTaskStatusResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Mp4GifTask).filter(Mp4GifTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="변환 작업을 찾을 수 없습니다.")
    return _serialize_task(task)


@router.get("/tasks/{task_id}/result")
def get_task_result(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Mp4GifTask).filter(Mp4GifTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="변환 작업을 찾을 수 없습니다.")
    if task.status == Mp4GifTask.STATUS_FAILED:
        raise HTTPException(status_code=409, detail=task.error_message or "변환이 실패했습니다.")
    if task.status != Mp4GifTask.STATUS_COMPLETED:
        raise HTTPException(status_code=409, detail="변환이 아직 완료되지 않았습니다.")

    result_path = Path(task.stored_output_path)
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="결과 GIF 파일을 찾을 수 없습니다.")

    return FileResponse(
        path=str(result_path),
        media_type="image/gif",
        filename=f"{Path(task.source_name).stem}.gif",
    )


@router.get("/health", response_model=Mp4GifHealthResponse)
def get_health():
    work_root = get_work_root()
    ffmpeg_ok, ffmpeg_path = ffmpeg_health()
    error_message = None if ffmpeg_ok else "ffmpeg 실행 파일을 찾을 수 없습니다. PATH 설정을 확인하세요."
    return Mp4GifHealthResponse(
        ffmpeg_ok=ffmpeg_ok,
        ffmpeg_path=ffmpeg_path,
        work_root=str(work_root),
        work_root_exists=work_root.exists(),
        max_upload_mb=int(settings.MP4_GIF_MAX_UPLOAD_MB),
        error_message=error_message,
    )
