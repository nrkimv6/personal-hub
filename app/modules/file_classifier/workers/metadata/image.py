"""이미지 파일 메타데이터 추출 (Pillow)"""
import json
import re
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text

_SCREENSHOT_PATTERNS = [
    r'screenshot', r'screen', r'스크린샷', r'캡처', r'capture',
    r'screen\s*shot', r'scr\d+',
]


def _is_screenshot(filename: str) -> bool:
    name_lower = filename.lower()
    for pat in _SCREENSHOT_PATTERNS:
        if re.search(pat, name_lower):
            return True
    return False


def extract(file_id: int, file_path: str, db: Session) -> dict:
    meta = {}

    try:
        from PIL import Image, ExifTags
        with Image.open(file_path) as img:
            meta["width"] = img.width
            meta["height"] = img.height
            meta["format"] = img.format

            has_exif = False
            try:
                exif_data = img._getexif()
                if exif_data:
                    has_exif = True
                    # GPS 정보 있으면 사진일 가능성 높음
                    for tag_id, value in exif_data.items():
                        tag = ExifTags.TAGS.get(tag_id, tag_id)
                        if tag == "GPSInfo":
                            meta["has_gps"] = True
            except (AttributeError, Exception):
                pass

            meta["has_exif"] = has_exif
    except Exception as e:
        meta["error"] = str(e)

    # 스크린샷 판단
    filename = Path(file_path).name
    meta["is_screenshot_hint"] = _is_screenshot(filename)

    try:
        db.execute(text(
            "UPDATE fc_files SET metadata_json = :meta WHERE id = :id"
        ), {"meta": json.dumps(meta), "id": file_id})
    except Exception as e:
        meta["db_error"] = str(e)

    return meta
