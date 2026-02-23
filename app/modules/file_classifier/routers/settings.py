"""설정 API"""
from typing import List, Optional
from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings, save_settings_to_file

router = APIRouter(tags=["File Classifier - Settings"])


class SettingsUpdate(BaseModel):
    SCAN_ROOT_FOLDERS: Optional[List[str]] = None
    EXCLUDE_FOLDERS: Optional[List[str]] = None
    MAX_FILES_PER_SCAN: Optional[int] = None
    TARGET_ROOT_FOLDER: Optional[str] = None
    DRY_RUN_DEFAULT: Optional[bool] = None
    USE_TRASH: Optional[bool] = None
    LLM_MODE: Optional[str] = None
    ARCHIVE_TIMEOUT_SECONDS: Optional[int] = None


@router.get("/settings")
async def get_settings():
    """현재 설정 반환"""
    return {
        "SCAN_ROOT_FOLDERS": settings.SCAN_ROOT_FOLDERS,
        "EXCLUDE_FOLDERS": settings.EXCLUDE_FOLDERS,
        "MAX_FILES_PER_SCAN": settings.MAX_FILES_PER_SCAN,
        "TARGET_ROOT_FOLDER": settings.TARGET_ROOT_FOLDER,
        "DRY_RUN_DEFAULT": settings.DRY_RUN_DEFAULT,
        "USE_TRASH": settings.USE_TRASH,
        "LLM_MODE": settings.LLM_MODE,
        "ARCHIVE_TIMEOUT_SECONDS": settings.ARCHIVE_TIMEOUT_SECONDS,
        "OBSIDIAN_VAULT_PATH": settings.OBSIDIAN_VAULT_PATH,
    }


@router.put("/settings")
async def update_settings(data: SettingsUpdate):
    """설정 변경 + 저장"""
    if data.SCAN_ROOT_FOLDERS is not None:
        settings.SCAN_ROOT_FOLDERS = data.SCAN_ROOT_FOLDERS
    if data.EXCLUDE_FOLDERS is not None:
        settings.EXCLUDE_FOLDERS = data.EXCLUDE_FOLDERS
    if data.MAX_FILES_PER_SCAN is not None:
        settings.MAX_FILES_PER_SCAN = data.MAX_FILES_PER_SCAN
    if data.TARGET_ROOT_FOLDER is not None:
        settings.TARGET_ROOT_FOLDER = data.TARGET_ROOT_FOLDER
    if data.DRY_RUN_DEFAULT is not None:
        settings.DRY_RUN_DEFAULT = data.DRY_RUN_DEFAULT
    if data.USE_TRASH is not None:
        settings.USE_TRASH = data.USE_TRASH
    if data.LLM_MODE is not None:
        settings.LLM_MODE = data.LLM_MODE
    if data.ARCHIVE_TIMEOUT_SECONDS is not None:
        settings.ARCHIVE_TIMEOUT_SECONDS = data.ARCHIVE_TIMEOUT_SECONDS

    save_settings_to_file()
    return {"status": "updated"}
