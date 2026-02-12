"""
이미지 분류 모듈 설정

API 키, 모델 선택, 리밋, 스캔 대상 경로 등
"""

import json
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings


class ImageClassifierSettings(BaseSettings):
    """이미지 분류 시스템 설정"""

    # === 스캔 설정 ===
    SCAN_ROOT_FOLDERS: list[str] = []  # 스캔 대상 루트 폴더 목록
    IMAGE_EXTENSIONS: tuple[str, ...] = (
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff"
    )
    MAX_FILES_PER_SCAN: int = 300000  # 스캔 파일 수 제한

    # === pHash 설정 ===
    PHASH_HASH_SIZE: int = 16  # 해시 크기 (8, 16, 32 등)
    PHASH_DUPLICATE_THRESHOLD: int = 10  # hamming distance 임계값 (≤10: 매우 유사)

    # === CLIP 설정 ===
    CLIP_MODEL_NAME: str = "clip-ViT-B-32"  # sentence-transformers 모델명
    CLIP_BATCH_SIZE: int = 64  # GPU 배치 크기 (GTX 1660S: 64~128)
    CLIP_USE_GPU: bool = True  # GPU 사용 여부 (CUDA 감지 자동)

    # === FAISS 설정 ===
    FAISS_INDEX_TYPE: str = "IndexFlatIP"  # Inner Product (cosine similarity용)
    FAISS_SIMILARITY_THRESHOLD: float = 0.85  # 유사도 임계값 (0.85 이상 = 매우 유사)

    # === 썸네일 설정 ===
    THUMBNAIL_SIZE: tuple[int, int] = (300, 300)  # 썸네일 크기
    THUMBNAIL_QUALITY: int = 85  # JPEG 품질 (1-100)
    THUMBNAIL_DIR: Path = Path(__file__).parents[4] / "data" / "image_classifier" / "thumbnails"

    # === AI 분류 설정 (CLI 우선) ===
    AI_MODE: str = "cli"  # "cli" | "api"
    CLAUDE_CLI_PATH: str = "claude"  # claude CLI 실행 경로
    CLAUDE_MODEL: str = "claude-sonnet-4-5-20250929"  # Claude CLI 모델 ID
    GEMINI_CLI_PATH: str = "gemini"  # gemini CLI 실행 경로

    # API 키 (선택적 — API 모드 시에만 사용)
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None

    # CLI 병렬 실행 수
    CLI_MAX_WORKERS: int = 2  # 동시 CLI 호출 수 (2~3개 권장)
    CLI_TIMEOUT_SECONDS: int = 30  # CLI 호출 타임아웃

    # === 시간 클러스터링 설정 ===
    CLUSTER_GAP_MINUTES: int = 60  # 1시간 이내 촬영 = 같은 클러스터

    # === 파일 이동 설정 ===
    TARGET_ROOT_FOLDER: Optional[str] = None  # 최종 정리 폴더 루트 (예: D:\정리)
    USE_TRASH: bool = True  # 원본 삭제 시 휴지통 사용 (send2trash)

    # === 워커 설정 ===
    MAX_WORKERS_PER_TASK: int = 4  # 작업당 최대 워커 수 (CPU 코어 고려)

    class Config:
        env_prefix = "IC_"  # 환경변수 접두사: IC_SCAN_ROOT_FOLDERS 등
        case_sensitive = False


# 전역 설정 인스턴스
settings = ImageClassifierSettings()


def ensure_dirs():
    """필요한 디렉토리 생성"""
    settings.THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)


# 모듈 로드 시 디렉토리 생성
ensure_dirs()


def save_settings_to_file():
    """설정을 JSON 파일에 저장"""
    settings_dict = {
        "SCAN_ROOT_FOLDERS": settings.SCAN_ROOT_FOLDERS,
        "AI_MODE": settings.AI_MODE,
        "CLAUDE_CLI_PATH": settings.CLAUDE_CLI_PATH,
        "GEMINI_CLI_PATH": settings.GEMINI_CLI_PATH,
        "CLI_MAX_WORKERS": settings.CLI_MAX_WORKERS,
        "CLI_TIMEOUT_SECONDS": settings.CLI_TIMEOUT_SECONDS,
        "CLUSTER_GAP_MINUTES": settings.CLUSTER_GAP_MINUTES,
        "TARGET_ROOT_FOLDER": settings.TARGET_ROOT_FOLDER,
        "USE_TRASH": settings.USE_TRASH,
        "MAX_FILES_PER_SCAN": settings.MAX_FILES_PER_SCAN,
        "PHASH_DUPLICATE_THRESHOLD": settings.PHASH_DUPLICATE_THRESHOLD,
        "CLIP_BATCH_SIZE": settings.CLIP_BATCH_SIZE,
        "CLIP_USE_GPU": settings.CLIP_USE_GPU,
        "FAISS_SIMILARITY_THRESHOLD": settings.FAISS_SIMILARITY_THRESHOLD,
    }

    settings_file = Path(__file__).parents[3] / "data" / "image_classifier" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(settings_dict, f, indent=2, ensure_ascii=False)


def load_settings_from_file():
    """파일에서 설정 로드 (있으면)"""
    settings_file = Path(__file__).parents[3] / "data" / "image_classifier" / "settings.json"

    if not settings_file.exists():
        return

    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            saved = json.load(f)

        # 런타임 설정 덮어쓰기
        for key, value in saved.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
    except Exception as e:
        print(f"[경고] 설정 파일 로드 실패: {e}")


# 모듈 로드 시 저장된 설정 복원
load_settings_from_file()
