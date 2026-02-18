"""Auto Next Configuration"""

from pydantic_settings import BaseSettings
from pathlib import Path
from typing import List


class AutoNextConfig(BaseSettings):
    """auto-next 모듈 설정"""

    # DB 경로
    AUTO_NEXT_DB_PATH: Path = Path(r"D:\work\project\service\wtools\common\tools\auto-next\data\tasks.db")

    # wtools 프로젝트 기본 경로
    WTOOLS_BASE_DIR: Path = Path(r"D:\work\project\service\wtools")

    # plan 문서 디렉토리
    PLAN_DIR: Path = Path("common/docs/plan")

    # 로그 디렉토리
    LOG_DIR: Path = Path("common/logs")
    LOG_FILE_PATTERN: str = "auto-next-*.log"

    # 프로젝트 디렉토리 목록 (plan 탐색용)
    PROJECT_DIRS: List[str] = [
        "activity-hub", "admin-tools", "auth-worker", "cross-noti",
        "gentle-words", "line-minder", "memo-alarm", "mini-toolbox",
        "sacred-hours", "screenshot-generator", "story-weaver",
        "tb-wish", "tool-view", "wedding-mass-guide",
    ]

    # 외부 plan 저장 파일
    EXTERNAL_PLANS_FILE: Path = Path(r"D:\work\project\tools\monitor-page\data\external_plans.json")

    # 수동 무시 plan 저장 파일
    IGNORED_PLANS_FILE: Path = Path(r"D:\work\project\tools\monitor-page\data\ignored_plans.json")

    # 외부 경로 화이트리스트
    ALLOWED_EXTERNAL_PATHS: List[str] = [r"D:\work\project"]

    # auto-next CLI 명령어
    AUTO_NEXT_CLI_CMD: str = "python -m auto_next"

    # auto-next 모듈 경로
    AUTO_NEXT_MODULE_PATH: Path = Path(r"D:\work\project\service\wtools\common\tools\auto-next")

    # auto-next 전용 Python 실행 파일 (monitor-page venv가 아닌 auto-next venv 사용)
    AUTO_NEXT_PYTHON: Path = Path(r"D:\work\project\service\wtools\common\tools\auto-next\.venv\Scripts\python.exe")

    class Config:
        env_prefix = "AUTO_NEXT_"
        case_sensitive = True


# 싱글톤 인스턴스
config = AutoNextConfig()

__all__ = ['config']
