"""LLMConfigService — LLM provider/model 결정, defaults 파일 I/O, 정규화.

DB 접근 없음 — 순수 함수형.
의존: provider_registry, llm_registry(pick_model)
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.modules.claude_worker.services import provider_registry
from app.shared.io import read_json, write_json_atomic
from app.shared.llm_registry import (
    CALLER_TYPE_TO_STEP,
    NoAvailableModelError,
    pick_model,
)

logger = logging.getLogger("claude_worker.llm_config_service")

# ── 경로 상수 ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LLM_DEFAULTS_FILE = PROJECT_ROOT / "data" / "llm_defaults.json"
LEGACY_LLM_DEFAULTS_FILE = Path("data/llm_defaults.json")
# monkeypatch seam — 테스트에서 이 모듈의 LLM_DEFAULTS_FILE을 패치한다
LLM_DEFAULTS_FILE = DEFAULT_LLM_DEFAULTS_FILE

# 설정 UI 노출용 caller_type 목록
KNOWN_CALLER_TYPES = [
    "instagram",
    "universal_crawl",
    "image_classify",
    "event_import",
    "report",
    "pytest_fix",
    "dev_runner",
    "git_repos",
    "topic_extract",
    "writing",
    "writing_generate",
    "writing_refine",
    "plan_archive_analyze",
    "plan_recurrence_check",
    "plan_recurrence_suggest",
]


# ── 경로 헬퍼 (모듈 레벨) ─────────────────────────────────────────────────────

def _normalize_path(path: Path) -> str:
    absolute = path if path.is_absolute() else (Path.cwd() / path)
    return os.path.normcase(os.path.normpath(str(absolute)))


def _same_path(lhs: Path, rhs: Path) -> bool:
    return _normalize_path(lhs) == _normalize_path(rhs)


def _resolve_llm_defaults_path() -> Path:
    """monkeypatch seam(LLM_DEFAULTS_FILE)을 유지하면서 경로를 해석."""
    configured = Path(LLM_DEFAULTS_FILE)
    if configured.is_absolute():
        return configured
    return PROJECT_ROOT / configured


def _is_default_llm_defaults_path(path: Path) -> bool:
    return _same_path(path, DEFAULT_LLM_DEFAULTS_FILE)


def _migrate_legacy_llm_defaults_if_needed(target_path: Path) -> None:
    if not _is_default_llm_defaults_path(target_path):
        logger.debug(f"[llm-defaults] 주입 경로 감지: 레거시 마이그레이션 스킵 ({target_path})")
        return
    if target_path.exists():
        logger.debug(f"[llm-defaults] 기본 경로 파일 존재: 레거시 마이그레이션 스킵 ({target_path})")
        return

    legacy_path = (
        LEGACY_LLM_DEFAULTS_FILE
        if LEGACY_LLM_DEFAULTS_FILE.is_absolute()
        else (Path.cwd() / LEGACY_LLM_DEFAULTS_FILE)
    )
    if not legacy_path.exists():
        logger.debug(f"[llm-defaults] 레거시 파일 없음: 마이그레이션 스킵 ({legacy_path})")
        return
    if _same_path(legacy_path, target_path):
        logger.debug(f"[llm-defaults] 레거시/기본 경로 동일: 마이그레이션 스킵 ({target_path})")
        return

    legacy_payload = read_json(legacy_path, default=None)
    if not isinstance(legacy_payload, dict):
        logger.warning(f"[llm-defaults] 레거시 설정 파일 손상: 마이그레이션 스킵 ({legacy_path})")
        return

    write_json_atomic(target_path, legacy_payload)
    logger.info(f"[llm-defaults] 레거시 설정 마이그레이션 완료: {legacy_path} -> {target_path}")


# ── Service 클래스 ─────────────────────────────────────────────────────────────

class LLMConfigService:
    """LLM provider/model 결정 + defaults 파일 I/O.

    DB 접근 없음. __init__ 파라미터 없음.
    """

    @staticmethod
    def get_supported_providers() -> List[str]:
        return sorted(p.key for p in provider_registry.list_enabled())

    @staticmethod
    def get_known_caller_types() -> List[str]:
        return sorted(KNOWN_CALLER_TYPES)

    @staticmethod
    def _normalize_provider(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_model(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        normalized = value.strip()
        return normalized or None

    @classmethod
    def _default_defaults_payload(cls) -> Dict[str, Any]:
        return {
            "global_default": {"provider": "claude", "model": ""},
            "caller_defaults": {},
        }

    def _sanitize_defaults_payload(self, raw: Any) -> Dict[str, Any]:
        payload = self._default_defaults_payload()
        if not isinstance(raw, dict):
            return payload

        raw_global = raw.get("global_default")
        if isinstance(raw_global, dict):
            provider = self._normalize_provider(raw_global.get("provider")) or "claude"
            if not provider_registry.is_supported(provider):
                provider = "claude"
            model = raw_global.get("model")
            if model is None:
                model = ""
            if not isinstance(model, str):
                model = str(model)
            payload["global_default"] = {
                "provider": provider,
                "model": model.strip(),
            }

        raw_callers = raw.get("caller_defaults")
        if not isinstance(raw_callers, dict):
            return payload

        caller_defaults: Dict[str, Dict[str, str]] = {}
        for caller_type, config in raw_callers.items():
            caller = str(caller_type).strip()
            if not caller or not isinstance(config, dict):
                continue

            provider = self._normalize_provider(config.get("provider"))
            if provider is None or not provider_registry.is_supported(provider):
                continue

            model = config.get("model")
            if model is None:
                model = ""
            if not isinstance(model, str):
                model = str(model)

            caller_defaults[caller] = {
                "provider": provider,
                "model": model.strip(),
            }

        payload["caller_defaults"] = caller_defaults
        return payload

    def load_llm_defaults(self) -> Dict[str, Any]:
        target_path = _resolve_llm_defaults_path()
        _migrate_legacy_llm_defaults_if_needed(target_path)

        if not target_path.exists():
            return self._default_defaults_payload()

        try:
            data = read_json(target_path, default=None)
            if not isinstance(data, dict):
                raise ValueError("llm defaults payload is not an object")
            return self._sanitize_defaults_payload(data)
        except Exception:
            logger.warning(f"[llm-defaults] 설정 파일 읽기 실패, 기본값 사용: {target_path}")
            return self._default_defaults_payload()

    def save_llm_defaults(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        defaults = self._sanitize_defaults_payload(payload)

        if isinstance(payload, dict) and isinstance(payload.get("caller_defaults"), dict):
            requested = payload.get("caller_defaults", {})
            caller_defaults: Dict[str, Dict[str, str]] = {}
            for caller_type, config in requested.items():
                caller = str(caller_type).strip()
                if not caller:
                    continue
                if not isinstance(config, dict):
                    continue
                provider = self._normalize_provider(config.get("provider"))
                if provider is None:
                    continue
                if not provider_registry.is_supported(provider):
                    raise ValueError(f"지원되지 않는 provider: {provider}")
                model = config.get("model")
                if model is None:
                    model = ""
                if not isinstance(model, str):
                    model = str(model)
                caller_defaults[caller] = {
                    "provider": provider,
                    "model": model.strip(),
                }
            defaults["caller_defaults"] = caller_defaults

        target_path = _resolve_llm_defaults_path()
        write_json_atomic(target_path, defaults)
        return defaults

    def resolve_provider_model(
        self,
        caller_type: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Tuple[str, str]:
        """우선순위 1-D:
        1순위: 호출자 명시 provider/model → 즉시 반환
        2순위: caller_defaults pin → 반환
        3순위: registry picker (step 기반)
        4순위: global_default (quota 차단이면 에러 전파)
        """
        defaults = self.load_llm_defaults()
        global_default = defaults.get("global_default", {})
        caller_defaults = defaults.get("caller_defaults", {})
        caller_default = caller_defaults.get(caller_type, {}) if isinstance(caller_defaults, dict) else {}

        # 1순위: 호출자 명시
        explicit_provider = self._normalize_provider(provider)
        explicit_model = self._normalize_model(model)
        if explicit_provider is not None and explicit_model is not None:
            return explicit_provider, explicit_model

        # 2순위: caller pin
        pin_provider = self._normalize_provider(caller_default.get("provider"))
        pin_model = self._normalize_model(caller_default.get("model"))
        if pin_provider and pin_model:
            try:
                from app.shared.llm_registry import load_registry
                registry = load_registry()
                for candidates in registry.values():
                    for cand in candidates:
                        if cand.oneshot and cand.provider == pin_provider and cand.model == pin_model:
                            logger.warning(
                                f"[resolve] caller_pin {pin_provider}/{pin_model}이 "
                                "oneshot 전용 registry 모델과 일치. 핑퐁 경로에서 호출됩니다."
                            )
                            break
            except Exception:
                pass
            return pin_provider, pin_model

        # 3순위: registry picker
        step = CALLER_TYPE_TO_STEP.get(caller_type)
        if step:
            try:
                picked_provider, picked_model = pick_model(step, oneshot=False)
                _quota_providers = set(provider_registry.get_quota_providers())
                if picked_provider not in _quota_providers:
                    logger.warning(
                        f"[resolve] picker가 {picked_provider}/{picked_model} 반환 "
                        f"(실행 불가, quota_providers={_quota_providers}). 재-pick."
                    )
                    _all_providers = {p.key for p in provider_registry.list_enabled()}
                    picked_provider, picked_model = pick_model(
                        step, oneshot=False, exclude_providers=_all_providers - _quota_providers
                    )
                return picked_provider, picked_model
            except NoAvailableModelError as e:
                logger.error(f"[resolve] picker 실패: {e}. global_default로 fallback.")
            except Exception as e:
                logger.error(f"[resolve] picker 예외: {e}. global_default로 fallback.")

        # 4순위: global_default
        gd_provider = self._normalize_provider(global_default.get("provider")) or "claude"
        gd_model = self._normalize_model(global_default.get("model")) or ""
        if gd_provider in set(provider_registry.get_quota_providers()):
            try:
                from app.shared.llm_registry import load_quota_state
                state = load_quota_state()
                key = f"{gd_provider}/{gd_model}" if gd_model else None
                if key and key in state:
                    quota = state[key]
                    from app.shared.llm_registry import _now_kst
                    now = _now_kst()
                    if quota.is_in_cooldown(now) or quota.is_weekly_exhausted():
                        raise NoAvailableModelError(
                            caller_type,
                            f"global_default {gd_provider}/{gd_model}도 quota 차단. 수동 보고 필요."
                        )
            except NoAvailableModelError:
                raise
            except Exception:
                pass
        return gd_provider, gd_model
