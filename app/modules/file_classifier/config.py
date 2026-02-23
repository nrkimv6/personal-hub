"""
파일 분류 모듈 설정

스캔 경로, 메타데이터 추출, 분류, 이동 관련 설정
"""

import json
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings


class FileClassifierSettings(BaseSettings):
    """파일 분류 시스템 설정"""

    # === 스캔 설정 ===
    SCAN_ROOT_FOLDERS: list[str] = []
    EXCLUDE_FOLDERS: list[str] = [
        "Windows", "Program Files", "Program Files (x86)",
        "$Recycle.Bin", "System Volume Information",
        ".git", "node_modules", "__pycache__", ".venv"
    ]
    MAX_FILES_PER_SCAN: int = 100000

    # === 메타데이터 설정 ===
    MUSIC_TAG_LIBRARY: str = "mutagen"
    ARCHIVE_TIMEOUT_SECONDS: int = 10
    PE_ANALYSIS_ENABLED: bool = True     # Windows 전용 PE 헤더 분석

    # === 분류 설정 (CLI 우선) ===
    LLM_MODE: str = "cli"                # "cli" | "api"
    LLM_MAX_WORKERS: int = 2
    LLM_TIMEOUT_SECONDS: int = 60        # 텍스트 정보만이라 짧게

    # API 키 (선택적 — API 모드 시에만 사용)
    ANTHROPIC_API_KEY: Optional[str] = None

    # === 이동 설정 ===
    TARGET_ROOT_FOLDER: Optional[str] = None  # 정리 대상 루트 폴더
    DRY_RUN_DEFAULT: bool = True              # 기본값: dry-run (실제 이동 없음)
    USE_TRASH: bool = True                    # 삭제 시 휴지통 사용

    # === 삭제 후보 설정 ===
    LOG_MAX_AGE_DAYS: int = 90           # 90일 이상 로그 → 삭제 후보
    TEMP_MAX_AGE_DAYS: int = 30

    # === 옵시디언 설정 ===
    OBSIDIAN_VAULT_PATH: Optional[str] = None

    class Config:
        env_prefix = "FC_"
        case_sensitive = False

    def save_settings_to_file(self, file_path: str):
        """설정을 지정한 경로의 JSON 파일에 저장"""
        settings_dict = {
            "SCAN_ROOT_FOLDERS": self.SCAN_ROOT_FOLDERS,
            "EXCLUDE_FOLDERS": self.EXCLUDE_FOLDERS,
            "MAX_FILES_PER_SCAN": self.MAX_FILES_PER_SCAN,
            "ARCHIVE_TIMEOUT_SECONDS": self.ARCHIVE_TIMEOUT_SECONDS,
            "PE_ANALYSIS_ENABLED": self.PE_ANALYSIS_ENABLED,
            "LLM_MODE": self.LLM_MODE,
            "LLM_MAX_WORKERS": self.LLM_MAX_WORKERS,
            "LLM_TIMEOUT_SECONDS": self.LLM_TIMEOUT_SECONDS,
            "TARGET_ROOT_FOLDER": self.TARGET_ROOT_FOLDER,
            "DRY_RUN_DEFAULT": self.DRY_RUN_DEFAULT,
            "USE_TRASH": self.USE_TRASH,
            "LOG_MAX_AGE_DAYS": self.LOG_MAX_AGE_DAYS,
            "TEMP_MAX_AGE_DAYS": self.TEMP_MAX_AGE_DAYS,
            "OBSIDIAN_VAULT_PATH": self.OBSIDIAN_VAULT_PATH,
        }

        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        with open(target, "w", encoding="utf-8") as f:
            json.dump(settings_dict, f, indent=2, ensure_ascii=False)

    def load_settings_from_file(self, file_path: str):
        """지정한 경로의 JSON 파일에서 설정 로드"""
        target = Path(file_path)

        if not target.exists():
            return

        try:
            with open(target, "r", encoding="utf-8") as f:
                saved = json.load(f)

            for key, value in saved.items():
                if hasattr(self, key):
                    setattr(self, key, value)
        except Exception as e:
            print(f"[경고] 설정 파일 로드 실패: {e}")


# 전역 설정 인스턴스
settings = FileClassifierSettings()

# 설정 파일 경로
_SETTINGS_FILE = Path(__file__).parents[3] / "data" / "file_classifier" / "settings.json"


def save_settings_to_file():
    """설정을 JSON 파일에 저장"""
    settings.save_settings_to_file(str(_SETTINGS_FILE))


def load_settings_from_file():
    """파일에서 설정 로드 (있으면)"""
    settings.load_settings_from_file(str(_SETTINGS_FILE))


def validate_settings():
    """비정상 설정값 교정"""
    if settings.LLM_MODE not in ("cli", "api"):
        settings.LLM_MODE = "cli"
    if settings.LLM_MAX_WORKERS <= 0:
        settings.LLM_MAX_WORKERS = 2
    if settings.ARCHIVE_TIMEOUT_SECONDS <= 0:
        settings.ARCHIVE_TIMEOUT_SECONDS = 10


# 모듈 로드 시 저장된 설정 복원 + 유효성 검증
load_settings_from_file()
validate_settings()
