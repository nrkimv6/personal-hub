"""Dev Runner Settings Service — JSON 파일 기반 설정 읽기/쓰기"""

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import json
import logging

from app.modules.dev_runner.config import config

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path("data/dev_runner_settings.json")


@dataclass
class DevRunnerSettings:
    max_concurrent_runners: int
    updated_at: str | None = None


class SettingsService:
    """JSON 파일 기반 dev-runner 설정 서비스"""

    def __init__(self, settings_file: Path = SETTINGS_FILE):
        self._file = settings_file

    def get(self) -> DevRunnerSettings:
        """현재 설정 반환. 파일 없거나 손상된 경우 config 기본값 사용."""
        if not self._file.exists():
            return DevRunnerSettings(max_concurrent_runners=config.MAX_CONCURRENT_RUNNERS)

        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return DevRunnerSettings(
                max_concurrent_runners=data.get("max_concurrent_runners", config.MAX_CONCURRENT_RUNNERS),
                updated_at=data.get("updated_at"),
            )
        except Exception:
            logger.warning(f"[settings_service] 설정 파일 읽기 실패, 기본값 사용: {self._file}")
            return DevRunnerSettings(max_concurrent_runners=config.MAX_CONCURRENT_RUNNERS)

    def update(self, max_concurrent_runners: int) -> DevRunnerSettings:
        """설정 저장. max_concurrent_runners 범위: 1~10."""
        if not (1 <= max_concurrent_runners <= 10):
            raise ValueError(f"max_concurrent_runners는 1~10 사이여야 합니다. (입력값: {max_concurrent_runners})")

        settings = DevRunnerSettings(
            max_concurrent_runners=max_concurrent_runners,
            updated_at=datetime.now().isoformat(),
        )

        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[settings_service] 설정 저장: max_concurrent_runners={max_concurrent_runners}")

        return settings


# 싱글톤 인스턴스
settings_service = SettingsService()

__all__ = ["DevRunnerSettings", "SettingsService", "settings_service"]
