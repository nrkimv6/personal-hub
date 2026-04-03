"""Slide scanner configuration."""

import json
from pathlib import Path

from pydantic_settings import BaseSettings


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data" / "slide_scanner"


class SlideScannerSettings(BaseSettings):
    """Runtime settings for slide scanner module."""

    RECTIFIER_ROOT: Path = Path(r"D:\work\project\service\wtools\common\tools\slide-rectifier")
    RECTIFIER_PYTHON: Path = Path(
        r"D:\work\project\service\wtools\common\tools\slide-rectifier\.venv\Scripts\python.exe"
    )
    RECTIFIER_DETECT_ENGINE: str = "opencv"

    DATA_DIR: Path = DATA_ROOT
    ORIGINALS_DIR: Path = DATA_ROOT / "originals"
    OUTPUT_DIR: Path = DATA_ROOT / "output"
    ARCHIVE_DIR: Path = DATA_ROOT / "archive"

    MOBILE_INBOX_DIR: Path = DATA_ROOT / "mobile_inbox"
    MOBILE_APPROVED_DIR: Path = DATA_ROOT / "mobile_approved"
    MOBILE_REJECTED_DIR: Path = DATA_ROOT / "mobile_rejected"

    ADB_PATH: Path = Path("adb")
    MOBILE_REMOTE_ROOTS: tuple[str, ...] = (
        "/sdcard/DCIM/Camera",
        "/sdcard/Pictures",
        "/sdcard/Download",
    )
    MOBILE_DEVICE_ALIAS_JSON: str = "{}"

    THUMBNAIL_SIZE: tuple[int, int] = (320, 320)
    THUMBNAIL_QUALITY: int = 82

    class Config:
        env_prefix = "SS_"
        case_sensitive = False


settings = SlideScannerSettings()


def parse_mobile_device_aliases(raw: str) -> dict[str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    if not isinstance(payload, dict):
        return {}

    normalized: dict[str, str] = {}
    for key, value in payload.items():
        key_text = str(key).strip()
        value_text = str(value).strip()
        if key_text and value_text:
            normalized[key_text] = value_text
    return normalized


def ensure_dirs() -> None:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    settings.MOBILE_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    settings.MOBILE_APPROVED_DIR.mkdir(parents=True, exist_ok=True)
    settings.MOBILE_REJECTED_DIR.mkdir(parents=True, exist_ok=True)


ensure_dirs()
