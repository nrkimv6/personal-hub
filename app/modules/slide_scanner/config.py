"""Slide scanner configuration."""

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

    DATA_DIR: Path = DATA_ROOT
    ORIGINALS_DIR: Path = DATA_ROOT / "originals"
    OUTPUT_DIR: Path = DATA_ROOT / "output"

    THUMBNAIL_SIZE: tuple[int, int] = (320, 320)
    THUMBNAIL_QUALITY: int = 82

    class Config:
        env_prefix = "SS_"
        case_sensitive = False


settings = SlideScannerSettings()


def ensure_dirs() -> None:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


ensure_dirs()
