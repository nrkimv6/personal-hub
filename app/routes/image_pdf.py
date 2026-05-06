"""Image -> PDF conversion API routes."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from app.schemas.image_pdf import ImagePdfConvertOptions, ImagePdfHealthResponse
from app.services.image_pdf_service import (
    ImagePdfError,
    convert_images_to_pdf,
    image_pdf_health,
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


@router.get("/health", response_model=ImagePdfHealthResponse)
def get_health():
    return ImagePdfHealthResponse(**image_pdf_health())


@router.post("/convert")
async def convert(
    files: list[UploadFile] = File(...),
    bw: bool = Form(False),
    white: int = Form(200),
    black: int = Form(80),
    quality: int = Form(85),
    preserve_dpi: bool = Form(False),
    output_name: str | None = Form(None),
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
        pdf_bytes = convert_images_to_pdf(file_bytes, options)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_error", "filename": None, "detail": str(exc)},
        ) from exc
    except ImagePdfError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_error_detail(exc)) from exc

    filename = _download_filename(options.output_name)
    encoded = quote(filename)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )
