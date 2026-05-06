"""Service helpers for image -> PDF conversion."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
import PIL

from app.schemas.image_pdf import ImagePdfConvertOptions

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_OK = True
except ImportError:
    HEIC_OK = False


SUPPORTED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "heic", "heif"}
HEIC_EXTENSIONS = {"heic", "heif"}
MAX_FILES = 50
MAX_PER_FILE_MB = 25
MAX_TOTAL_MB = 200


@dataclass
class ImagePdfError(ValueError):
    error: str
    message: str
    filename: str | None = None
    status_code: int = 422

    def __str__(self) -> str:
        return self.message


def image_pdf_health() -> dict:
    return {
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        "heic_supported": HEIC_OK,
        "pillow_version": PIL.__version__,
        "max_files": MAX_FILES,
        "max_per_file_mb": MAX_PER_FILE_MB,
        "max_total_mb": MAX_TOTAL_MB,
    }


def _extension(filename: str) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def validate_uploads(files: list[UploadFile]) -> None:
    if not files:
        raise ImagePdfError("empty_files", "이미지 파일을 1개 이상 업로드하세요.", None, 400)
    if len(files) > MAX_FILES:
        raise ImagePdfError("too_many_files", f"최대 {MAX_FILES}개까지 업로드할 수 있습니다.", None, 413)

    total_size = 0
    max_file_bytes = MAX_PER_FILE_MB * 1024 * 1024
    max_total_bytes = MAX_TOTAL_MB * 1024 * 1024
    for file in files:
        name = file.filename or ""
        ext = _extension(name)
        if ext not in SUPPORTED_EXTENSIONS:
            raise ImagePdfError("unsupported_extension", "지원하지 않는 이미지 형식입니다.", name, 415)
        if ext in HEIC_EXTENSIONS and not HEIC_OK:
            raise ImagePdfError("heic_unsupported", "이 환경에서는 HEIC/HEIF 변환을 지원하지 않습니다.", name, 422)

        size = getattr(file, "size", None)
        if size is not None:
            if size <= 0:
                raise ImagePdfError("empty", "비어 있는 파일입니다.", name, 422)
            if size > max_file_bytes:
                raise ImagePdfError(
                    "file_too_large",
                    f"파일당 최대 {MAX_PER_FILE_MB}MB까지 업로드할 수 있습니다.",
                    name,
                    413,
                )
            total_size += size

    if total_size > max_total_bytes:
        raise ImagePdfError("total_too_large", f"총 업로드 용량은 최대 {MAX_TOTAL_MB}MB입니다.", None, 413)


def validate_file_bytes(file_bytes: list[tuple[str, bytes]]) -> None:
    if not file_bytes:
        raise ImagePdfError("empty_files", "이미지 파일을 1개 이상 업로드하세요.", None, 400)
    if len(file_bytes) > MAX_FILES:
        raise ImagePdfError("too_many_files", f"최대 {MAX_FILES}개까지 업로드할 수 있습니다.", None, 413)

    total_size = 0
    max_file_bytes = MAX_PER_FILE_MB * 1024 * 1024
    max_total_bytes = MAX_TOTAL_MB * 1024 * 1024
    for name, data in file_bytes:
        ext = _extension(name)
        if ext not in SUPPORTED_EXTENSIONS:
            raise ImagePdfError("unsupported_extension", "지원하지 않는 이미지 형식입니다.", name, 415)
        if ext in HEIC_EXTENSIONS and not HEIC_OK:
            raise ImagePdfError("heic_unsupported", "이 환경에서는 HEIC/HEIF 변환을 지원하지 않습니다.", name, 422)
        if not data:
            raise ImagePdfError("empty", "비어 있는 파일입니다.", name, 422)
        if len(data) > max_file_bytes:
            raise ImagePdfError(
                "file_too_large",
                f"파일당 최대 {MAX_PER_FILE_MB}MB까지 업로드할 수 있습니다.",
                name,
                413,
            )
        total_size += len(data)

    if total_size > max_total_bytes:
        raise ImagePdfError("total_too_large", f"총 업로드 용량은 최대 {MAX_TOTAL_MB}MB입니다.", None, 413)


def _open_image(name: str, data: bytes) -> Image.Image:
    ext = _extension(name)
    if ext not in SUPPORTED_EXTENSIONS:
        raise ImagePdfError("unsupported_extension", "지원하지 않는 이미지 형식입니다.", name, 415)
    if ext in HEIC_EXTENSIONS and not HEIC_OK:
        raise ImagePdfError("heic_unsupported", "이 환경에서는 HEIC/HEIF 변환을 지원하지 않습니다.", name, 422)
    if not data:
        raise ImagePdfError("empty", "비어 있는 파일입니다.", name, 422)

    try:
        img = Image.open(BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImagePdfError("corrupt", "이미지를 열 수 없습니다.", name, 422) from exc

    img = ImageOps.exif_transpose(img)
    if img.mode in {"RGBA", "LA"} or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _apply_bw(img: Image.Image, white_thresh: int, black_thresh: int) -> Image.Image:
    if white_thresh <= black_thresh:
        raise ImagePdfError("invalid_threshold", "white 값은 black 값보다 커야 합니다.", None, 422)

    gray = img.convert("L")
    span = max(white_thresh - black_thresh, 1)

    def normalize(value: int) -> int:
        if value >= white_thresh:
            return 255
        if value <= black_thresh:
            return 0
        return round((value - black_thresh) * 255 / span)

    return gray.point(normalize).convert("RGB")


def _first_dpi(images: Iterable[Image.Image]) -> tuple[int, int]:
    for img in images:
        dpi = img.info.get("dpi")
        if isinstance(dpi, tuple) and len(dpi) >= 2:
            try:
                return max(1, int(dpi[0])), max(1, int(dpi[1]))
            except (TypeError, ValueError):
                return (96, 96)
    return (96, 96)


def convert_images_to_pdf(
    file_bytes: list[tuple[str, bytes]],
    options: ImagePdfConvertOptions,
) -> bytes:
    validate_file_bytes(file_bytes)
    if options.white <= options.black:
        raise ImagePdfError("invalid_threshold", "white 값은 black 값보다 커야 합니다.", None, 422)

    images: list[Image.Image] = []
    for name, data in file_bytes:
        img = _open_image(name, data)
        if options.bw:
            img = _apply_bw(img, options.white, options.black)
        images.append(img)

    if not images:
        raise ImagePdfError("empty_files", "이미지 파일을 1개 이상 업로드하세요.", None, 400)

    buf = BytesIO()
    first, rest = images[0], images[1:]
    dpi = _first_dpi(images) if options.preserve_dpi else (96, 96)
    first.save(
        buf,
        format="PDF",
        save_all=True,
        append_images=rest,
        quality=options.quality,
        dpi=dpi,
    )
    return buf.getvalue()
