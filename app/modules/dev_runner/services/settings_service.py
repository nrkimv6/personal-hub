"""Dev Runner Settings Service — JSON 파일 기반 설정 읽기/쓰기"""

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
import json
import logging

from app.modules.dev_runner.config import config

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path("data/dev_runner_settings.json")
SUPPORTED_RUN_ENGINES = {"claude", "gemini", "codex", "cc-codex"}
DEFAULT_ENGINE = "claude"


@dataclass
class DevRunnerSettings:
    max_concurrent_runners: int
    default_engine: str = DEFAULT_ENGINE
    default_fix_engine: str = DEFAULT_ENGINE
    updated_at: str | None = None


class SettingsService:
    """JSON 파일 기반 dev-runner 설정 서비스"""

    def __init__(self, settings_file: Path = SETTINGS_FILE):
        self._file = settings_file

    @staticmethod
    def _normalize_engine(value: Any, fallback: str = DEFAULT_ENGINE) -> str:
        if value is None:
            return fallback
        if not isinstance(value, str):
            value = str(value)
        normalized = value.strip() or fallback
        if normalized not in SUPPORTED_RUN_ENGINES:
            raise ValueError(f"지원되지 않는 엔진: {normalized}")
        return normalized

    @staticmethod
    def _validate_max_runners(value: Any) -> int:
        if not isinstance(value, int):
            raise ValueError("max_concurrent_runners는 정수여야 합니다.")
        if not (1 <= value <= 10):
            raise ValueError(f"max_concurrent_runners는 1~10 사이여야 합니다. (입력값: {value})")
        return value

    @classmethod
    def _default_settings(cls) -> DevRunnerSettings:
        return DevRunnerSettings(
            max_concurrent_runners=config.MAX_CONCURRENT_RUNNERS,
            default_engine=DEFAULT_ENGINE,
            default_fix_engine=DEFAULT_ENGINE,
        )

    def get(self) -> DevRunnerSettings:
        """현재 설정 반환. 파일 없거나 손상된 경우 config 기본값 사용."""
        defaults = self._default_settings()
        if not self._file.exists():
            return defaults

        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            max_runners = data.get("max_concurrent_runners", defaults.max_concurrent_runners)
            if not isinstance(max_runners, int):
                max_runners = defaults.max_concurrent_runners
            if not (1 <= max_runners <= 10):
                max_runners = defaults.max_concurrent_runners

            default_engine = self._normalize_engine(
                data.get("default_engine"),
                fallback=defaults.default_engine,
            )
            default_fix_engine = self._normalize_engine(
                data.get("default_fix_engine"),
                fallback=defaults.default_fix_engine,
            )

            return DevRunnerSettings(
                max_concurrent_runners=max_runners,
                default_engine=default_engine,
                default_fix_engine=default_fix_engine,
                updated_at=data.get("updated_at"),
            )
        except Exception:
            logger.warning(f"[settings_service] 설정 파일 읽기 실패, 기본값 사용: {self._file}")
            return defaults

    def update(self, payload: int | dict[str, Any]) -> DevRunnerSettings:
        """설정 저장. 기존 int 호출과 객체 payload 호출을 모두 지원."""
        current = self.get()

        if isinstance(payload, int):
            payload = {"max_concurrent_runners": payload}
        elif not isinstance(payload, dict):
            raise ValueError("settings payload는 int 또는 object여야 합니다.")

        max_runners = current.max_concurrent_runners
        if "max_concurrent_runners" in payload and payload.get("max_concurrent_runners") is not None:
            max_runners = self._validate_max_runners(payload.get("max_concurrent_runners"))

        default_engine = current.default_engine
        if "default_engine" in payload and payload.get("default_engine") is not None:
            default_engine = self._normalize_engine(payload.get("default_engine"), fallback=DEFAULT_ENGINE)

        default_fix_engine = current.default_fix_engine
        if "default_fix_engine" in payload and payload.get("default_fix_engine") is not None:
            default_fix_engine = self._normalize_engine(payload.get("default_fix_engine"), fallback=DEFAULT_ENGINE)

        settings = DevRunnerSettings(
            max_concurrent_runners=max_runners,
            default_engine=default_engine,
            default_fix_engine=default_fix_engine,
            updated_at=datetime.now().isoformat(),
        )

        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "[settings_service] 설정 저장: "
            f"max_concurrent_runners={max_runners}, "
            f"default_engine={default_engine}, default_fix_engine={default_fix_engine}"
        )

        return settings


# 싱글톤 인스턴스
settings_service = SettingsService()

__all__ = ["DevRunnerSettings", "SettingsService", "settings_service"]
