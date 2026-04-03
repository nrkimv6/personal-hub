"""Dev Runner Settings Service — JSON 파일 기반 설정 읽기/쓰기"""

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
import logging
import os

from app.modules.dev_runner.config import config
from app.shared.io import read_json, write_json_atomic

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SETTINGS_FILE = PROJECT_ROOT / "data" / "dev_runner_settings.json"
LEGACY_SETTINGS_FILE = Path("data/dev_runner_settings.json")
SETTINGS_FILE = DEFAULT_SETTINGS_FILE
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
        self._file = Path(settings_file)
        self._default_file = Path(SETTINGS_FILE)

    @staticmethod
    def _normalize_path(path: Path) -> str:
        absolute = path if path.is_absolute() else (Path.cwd() / path)
        return os.path.normcase(os.path.normpath(str(absolute)))

    @classmethod
    def _same_path(cls, lhs: Path, rhs: Path) -> bool:
        return cls._normalize_path(lhs) == cls._normalize_path(rhs)

    def _resolve_settings_path(self) -> Path:
        if self._file.is_absolute():
            return self._file
        return PROJECT_ROOT / self._file

    def _is_default_settings_path(self, target_path: Path) -> bool:
        return self._same_path(target_path, self._default_file)

    def _migrate_legacy_settings_if_needed(self, target_path: Path) -> None:
        if not self._is_default_settings_path(target_path):
            logger.debug(f"[settings_service] 주입 경로 감지: 레거시 마이그레이션 스킵 ({target_path})")
            return
        if target_path.exists():
            logger.debug(f"[settings_service] 기본 경로 파일 존재: 레거시 마이그레이션 스킵 ({target_path})")
            return

        legacy_path = LEGACY_SETTINGS_FILE if LEGACY_SETTINGS_FILE.is_absolute() else (Path.cwd() / LEGACY_SETTINGS_FILE)
        if not legacy_path.exists():
            logger.debug(f"[settings_service] 레거시 파일 없음: 마이그레이션 스킵 ({legacy_path})")
            return
        if self._same_path(legacy_path, target_path):
            logger.debug(f"[settings_service] 레거시/기본 경로 동일: 마이그레이션 스킵 ({target_path})")
            return

        legacy_payload = read_json(legacy_path, default=None)
        if not isinstance(legacy_payload, dict):
            logger.warning(f"[settings_service] 레거시 설정 파일 손상: 마이그레이션 스킵 ({legacy_path})")
            return

        write_json_atomic(target_path, legacy_payload)
        logger.info(f"[settings_service] 레거시 설정 마이그레이션 완료: {legacy_path} -> {target_path}")

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
        target_path = self._resolve_settings_path()
        self._migrate_legacy_settings_if_needed(target_path)

        if not target_path.exists():
            return defaults

        try:
            data = read_json(target_path, default=None)
            if not isinstance(data, dict):
                raise ValueError("settings payload is not an object")

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
            logger.warning(f"[settings_service] 설정 파일 읽기 실패, 기본값 사용: {target_path}")
            return defaults

    def update(self, payload: int | dict[str, Any]) -> DevRunnerSettings:
        """설정 저장. 기존 int 호출과 객체 payload 호출을 모두 지원."""
        target_path = self._resolve_settings_path()
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

        write_json_atomic(target_path, asdict(settings))
        logger.info(
            "[settings_service] 설정 저장: "
            f"max_concurrent_runners={max_runners}, "
            f"default_engine={default_engine}, default_fix_engine={default_fix_engine}, file={target_path}"
        )

        return settings


# 싱글톤 인스턴스
settings_service = SettingsService()

__all__ = ["DevRunnerSettings", "SettingsService", "settings_service"]
