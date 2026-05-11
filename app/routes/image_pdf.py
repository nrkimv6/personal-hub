"""Image -> PDF conversion API routes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import SessionLocal, get_db
from app.models.image_pdf_task import ImagePdfTask
from app.schemas.image_pdf import (
    ImagePdfConvertOptions,
    ImagePdfHealthResponse,
    ImagePdfTaskAcceptedResponse,
    ImagePdfTaskStatusResponse,
)
from app.services.image_pdf_service import (
    ImagePdfError,
    convert_images_to_pdf,
    image_pdf_health,
    validate_file_bytes,
    validate_uploads,
)

router = APIRouter(prefix="/api/v1/image-pdf", tags=["image-pdf"])


def _error_detail(exc: ImagePdfError) -> dict:
    return {"error": exc.error, "filename": exc.filename, "detail": exc.message}


def _download_filename(output_name: str | None) -> str:
    name = output_name.strip() if output_name else ""
    if not name:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"image-pdf-{stamp}.pdf"
    if not name.lower().endswith(".pdf"):
        return f"{name}.pdf"
    return name


def _task_artifact_url(task_id: str) -> str:
    return f"/api/v1/image-pdf/tasks/{task_id}/result"


def _work_root() -> Path:
    return Path(settings.IMAGE_PDF_WORK_ROOT)


def _task_input_dir(task_id: str) -> Path:
    return _work_root() / task_id / "input"


def _task_output_path(task_id: str) -> Path:
    return _work_root() / task_id / "result.pdf"


def _serialize_task(task: ImagePdfTask) -> ImagePdfTaskStatusResponse:
    try:
        source_names = json.loads(task.source_names)
    except (TypeError, json.JSONDecodeError):
        source_names = []
    if not isinstance(source_names, list):
        source_names = []
    return ImagePdfTaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        source_names=[str(name) for name in source_names],
        file_count=task.file_count,
        bw=task.bw,
        white=task.white,
        black=task.black,
        quality=task.quality,
        preserve_dpi=task.preserve_dpi,
        download_filename=task.download_filename,
        artifact_url=_task_artifact_url(task.task_id) if task.status == ImagePdfTask.STATUS_COMPLETED else None,
        error_message=task.error_message,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )


def _run_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(ImagePdfTask).filter(ImagePdfTask.task_id == task_id).first()
        if task is None:
            return

        task.mark_running()
        db.commit()

        input_dir = Path(task.stored_input_dir)
        file_bytes = [
            (path.name.split("-", 1)[1] if "-" in path.name else path.name, path.read_bytes())
            for path in sorted(input_dir.iterdir())
            if path.is_file()
        ]
        options = ImagePdfConvertOptions(
            bw=task.bw,
            white=task.white,
            black=task.black,
            quality=task.quality,
            preserve_dpi=task.preserve_dpi,
            output_name=task.download_filename,
        )
        pdf_bytes = convert_images_to_pdf(file_bytes, options)

        output_path = Path(task.stored_output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(pdf_bytes)
        task.mark_completed()
        db.commit()
    except (ImagePdfError, ValidationError, OSError) as exc:
        task = db.query(ImagePdfTask).filter(ImagePdfTask.task_id == task_id).first()
        if task is not None:
            task.mark_failed(str(exc))
            db.commit()
    finally:
        db.close()


@router.get("/health", response_model=ImagePdfHealthResponse)
def get_health():
    return ImagePdfHealthResponse(**image_pdf_health())


@router.post("/convert", status_code=202, response_model=ImagePdfTaskAcceptedResponse)
async def convert(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    bw: bool = Form(False),
    white: int = Form(200),
    black: int = Form(80),
    quality: int = Form(85),
    preserve_dpi: bool = Form(False),
    output_name: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        options = ImagePdfConvertOptions(
            bw=bw,
            white=white,
            black=black,
            quality=quality,
            preserve_dpi=preserve_dpi,
            output_name=output_name,
        )
        validate_uploads(files)
        file_bytes = [(file.filename or "image", await file.read()) for file in files]
        validate_file_bytes(file_bytes)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_error", "filename": None, "detail": str(exc)},
        ) from exc
    except ImagePdfError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_error_detail(exc)) from exc

    filename = _download_filename(options.output_name)
    task_id = str(uuid4())
    input_dir = _task_input_dir(task_id)
    input_dir.mkdir(parents=True, exist_ok=True)
    for index, (name, data) in enumerate(file_bytes):
        safe_name = Path(name).name or f"image-{index}"
        (input_dir / f"{index:04d}-{safe_name}").write_bytes(data)

    output_path = _task_output_path(task_id)
    task = ImagePdfTask(
        task_id=task_id,
        status=ImagePdfTask.STATUS_QUEUED,
        source_names=json.dumps([name for name, _ in file_bytes], ensure_ascii=False),
        file_count=len(file_bytes),
        stored_input_dir=str(input_dir),
        stored_output_path=str(output_path),
        bw=options.bw,
        white=options.white,
        black=options.black,
        quality=options.quality,
        preserve_dpi=options.preserve_dpi,
        download_filename=filename,
    )
    db.add(task)
    db.commit()

    background_tasks.add_task(_run_task, task_id)
    return ImagePdfTaskAcceptedResponse(
        task_id=task_id,
        status=task.status,
        artifact_url=_task_artifact_url(task_id),
    )


@router.get("/tasks/{task_id}", response_model=ImagePdfTaskStatusResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(ImagePdfTask).filter(ImagePdfTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="PDF 변환 작업을 찾을 수 없습니다.")
    return _serialize_task(task)


@router.get("/tasks/{task_id}/result")
def get_task_result(task_id: str, db: Session = Depends(get_db)):
    task = db.query(ImagePdfTask).filter(ImagePdfTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="PDF 변환 작업을 찾을 수 없습니다.")
    if task.status == ImagePdfTask.STATUS_FAILED:
        raise HTTPException(status_code=409, detail=task.error_message or "PDF 변환이 실패했습니다.")
    if task.status != ImagePdfTask.STATUS_COMPLETED:
        raise HTTPException(status_code=409, detail="PDF 변환이 아직 완료되지 않았습니다.")

    result_path = Path(task.stored_output_path)
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="결과 PDF 파일을 찾을 수 없습니다.")

    return FileResponse(
        path=str(result_path),
        media_type="application/pdf",
        filename=task.download_filename or _download_filename(None),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(task.download_filename or _download_filename(None))}"},
    )
