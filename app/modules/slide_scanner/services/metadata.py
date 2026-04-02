"""Metadata extraction helpers for slide scanner."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.ExifTags import TAGS

from app.modules.image_classifier.workers.metadata import FILENAME_DATE_PATTERNS


def _parse_exif_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _extract_exif_datetime_original(image: Image.Image) -> datetime | None:
    try:
        exif = image.getexif()
        if not exif:
            return None

        for key, raw_value in exif.items():
            if TAGS.get(key, key) == "DateTimeOriginal":
                parsed = _parse_exif_datetime(str(raw_value))
                if parsed:
                    return parsed
    except Exception:
        return None
    return None


def _extract_datetime_from_filename(file_name: str) -> datetime | None:
    for pattern, date_format in FILENAME_DATE_PATTERNS:
        match = re.search(pattern, file_name, re.IGNORECASE)
        if not match or date_format is None:
            continue

        date_text = "".join(group for group in match.groups() if group is not None)
        if not date_text:
            continue

        try:
            return datetime.strptime(date_text, date_format)
        except ValueError:
            continue
    return None


def guess_source_app(file_name: str) -> str | None:
    lowered = file_name.lower()
    if lowered.startswith("kakaotalk_"):
        return "KakaoTalk"
    if lowered.startswith("screenshot_") or lowered.startswith("스크린샷"):
        return "Screenshot"
    if lowered.startswith("img_") or lowered.startswith("dsc_"):
        return "Camera"
    if lowered.startswith("photo "):
        return "Photos"
    if "whatsapp" in lowered:
        return "WhatsApp"
    return None


def extract_slide_metadata(file_path: Path, image: Image.Image) -> tuple[str | None, str | None]:
    """Return `(captured_at_iso, source_app)` for a slide image."""

    exif_dt = _extract_exif_datetime_original(image)
    mtime_dt = datetime.fromtimestamp(file_path.stat().st_mtime)
    filename_dt = _extract_datetime_from_filename(file_path.name)

    captured_at = exif_dt or mtime_dt or filename_dt
    source_app = guess_source_app(file_path.name)

    captured_at_iso = captured_at.isoformat(timespec="seconds") if captured_at else None
    return captured_at_iso, source_app
