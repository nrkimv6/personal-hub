"""Dev Runner Configuration"""

from pydantic_settings import BaseSettings
from pathlib import Path
from typing import List


class DevRunnerConfig(BaseSettings):
    """dev-runner 모듈 설정"""

    # [초기 시드용] wtools 프로젝트 기본 경로 — 최초 실행 시 하위 프로젝트를 registered_paths.json에 자동 등록
    WTOOLS_BASE_DIR: Path = Path(r"D:\work\project\service\wtools")

    # plan 문서 디렉토리
    PLAN_DIR: Path = Path("common/docs/plan")

    # 로그 디렉토리
    LOG_DIR: Path = Path("common/logs")
    LOG_FILE_PATTERN: str = "plan-runner-*.log"

    # [초기 시드용] 프로젝트 디렉토리 목록 — 최초 마이그레이션 시에만 사용
    PROJECT_DIRS: List[str] = [
        "activity-hub", "admin-tools", "auth-worker", "cross-noti",
        "gentle-words", "line-minder", "memo-alarm", "mini-toolbox",
        "sacred-hours", "screenshot-generator", "story-weaver",
        "tb-wish", "tool-view", "wedding-mass-guide",
    ]

    # [마이그레이션 전용] 기존 외부 plan 저장 파일 — registered_paths.json 이전 완료 후 삭제 가능
    EXTERNAL_PLANS_FILE: Path = Path(r"D:\work\project\tools\monitor-page\data\external_plans.json")

    # 등록된 경로 저장 파일 (재시작 후에도 유지)
    REGISTERED_PATHS_FILE: Path = Path(r"D:\work\project\tools\monitor-page\data\registered_paths.json")

    # 수동 무시 plan 저장 파일
    IGNORED_PLANS_FILE: Path = Path(r"D:\work\project\tools\monitor-page\data\ignored_plans.json")

    # 등록 허용 경로 화이트리스트
    ALLOWED_PATHS: List[str] = [r"D:\work\project"]

    # plan-runner CLI 명령어
    PLAN_RUNNER_CLI_CMD: str = "python -m plan_runner"

    # plan-runner 모듈 경로
    PLAN_RUNNER_MODULE_PATH: Path = Path(r"D:\work\project\service\wtools\common\tools\plan-runner")

    # plan-runner 전용 Python 실행 파일 (monitor-page venv가 아닌 plan-runner venv 사용)
    PLAN_RUNNER_PYTHON: Path = Path(r"D:\work\project\service\wtools\common\tools\plan-runner\.venv\Scripts\python.exe")

    # 동시 실행 가능한 최대 runner 수
    MAX_CONCURRENT_RUNNERS: int = 3

    # worktree 기본 디렉토리
    WORKTREE_BASE_DIR: Path = Path(r"D:\work\project\tools\monitor-page\.worktrees")

    class Config:
        env_prefix = "DEV_RUNNER_"
        case_sensitive = True


# 싱글톤 인스턴스
config = DevRunnerConfig()

__all__ = ['config']
