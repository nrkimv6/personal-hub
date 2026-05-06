"""LLM Engine Profile Store — CLI 계정 분리용 profile 저장/관리."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.shared.io import read_json, write_json_atomic

logger = logging.getLogger("claude_worker.profile_store")

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LLM_PROFILES_FILE = PROJECT_ROOT / "data" / "llm_profiles.json"

# 테스트 monkeypatch seam
LLM_PROFILES_FILE = DEFAULT_LLM_PROFILES_FILE

# Profile 관리가 필요한 엔진 (CLI config dir 기반 계정 분리)
# Codex/cc-codex 등 profile-less 실행 엔진은 여기에 포함하지 않는다.
# 실행 가능 provider 전체 목록은 provider_registry.py를 참조한다.
SUPPORTED_ENGINES = {"claude", "gemini"}
SECRET_EXTRA_ENV_RE = re.compile(r"(^|_)(API_KEY|TOKEN)$")
SECRET_EXTRA_ENV_KEYS = {"ANTHROPIC_API_KEY", "GOOGLE_API_KEY"}
PROFILE_STATES = {
    "available",
    "paused_by_quota",
    "paused_by_window",
    "disabled",
    "processing",
}


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            return None
    return None


def _dt_to_str(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None


def _is_secret_extra_env_key(key: str) -> bool:
    upper = key.upper()
    return upper in SECRET_EXTRA_ENV_KEYS or SECRET_EXTRA_ENV_RE.search(upper) is not None

# SUPPORTED_PROFILE_ENGINES — profile 저장/조회가 필요한 엔진 (SUPPORTED_ENGINES의 역할 명시)
SUPPORTED_PROFILE_ENGINES = SUPPORTED_ENGINES


@dataclass
class LLMProfile:
    engine: str
    name: str
    config_dir: Optional[str]
    extra_env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    priority: int = 0
    capacity: int = 1
    last_quota_pause_until: Optional[datetime] = None
    last_reset_at: Optional[datetime] = None
    last_state: Optional[str] = None
    last_error_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "name": self.name,
            "config_dir": self.config_dir,
            "extra_env": self.extra_env,
            "enabled": self.enabled,
            "priority": self.priority,
            "capacity": self.capacity,
            "last_quota_pause_until": _dt_to_str(self.last_quota_pause_until),
            "last_reset_at": _dt_to_str(self.last_reset_at),
            "last_state": self.last_state,
            "last_error_summary": self.last_error_summary,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LLMProfile":
        state = d.get("last_state")
        if state is not None and state not in PROFILE_STATES:
            state = None
        return LLMProfile(
            engine=str(d.get("engine", "")),
            name=str(d.get("name", "")),
            config_dir=d.get("config_dir"),
            extra_env=dict(d.get("extra_env") or {}),
            enabled=bool(d.get("enabled", True)),
            priority=int(d.get("priority") or 0),
            capacity=max(1, int(d.get("capacity") or 1)),
            last_quota_pause_until=_parse_dt(d.get("last_quota_pause_until")),
            last_reset_at=_parse_dt(d.get("last_reset_at")),
            last_state=state,
            last_error_summary=d.get("last_error_summary"),
        )


def _default_profiles_payload() -> Dict[str, Any]:
    return {
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [
            LLMProfile(engine="claude", name="default", config_dir=None).to_dict(),
            LLMProfile(engine="gemini", name="default", config_dir=None).to_dict(),
        ],
    }


def _resolve_profiles_path() -> Path:
    configured = Path(LLM_PROFILES_FILE)
    if configured.is_absolute():
        return configured
    return PROJECT_ROOT / configured


def load_profiles() -> Dict[str, Any]:
    """llm_profiles.json 로드. 없으면 기본값 in-memory 반환 (파일 생성 안 함)."""
    path = _resolve_profiles_path()
    if not path.exists():
        return _default_profiles_payload()
    try:
        data = read_json(path, default=None)
        if not isinstance(data, dict):
            raise ValueError("profiles payload is not an object")
        return _sanitize_payload(data)
    except Exception:
        logger.warning(f"[profile-store] 설정 파일 읽기 실패, 기본값 사용: {path}")
        return _default_profiles_payload()


def save_profiles(payload: Dict[str, Any]) -> Dict[str, Any]:
    """llm_profiles.json 원자적 저장."""
    # extra_env 금지 키 검증 (save 시점에 400-level 에러로 노출)
    from app.modules.claude_worker.services.profile_env import FORBIDDEN_EXTRA_ENV  # noqa: PLC0415
    for item in payload.get("profiles", []):
        if not isinstance(item, dict):
            continue
        extra_env = dict(item.get("extra_env") or {})
        for env_key in extra_env:
            if env_key in FORBIDDEN_EXTRA_ENV:
                raise ValueError(f"forbidden env key: {env_key!r}")

    clean = _sanitize_payload(payload)
    path = _resolve_profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, clean)
    return clean


def _sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """payload를 검증하고 정규화."""
    profiles_raw = payload.get("profiles", [])
    if not isinstance(profiles_raw, list):
        profiles_raw = []

    profiles: List[LLMProfile] = []
    seen: set[tuple[str, str]] = set()

    for item in profiles_raw:
        if not isinstance(item, dict):
            continue
        engine = str(item.get("engine", "")).strip()
        name = str(item.get("name", "")).strip()

        if not engine:
            raise ValueError("empty engine in profile")
        if not name:
            raise ValueError("empty profile name")
        if engine not in SUPPORTED_ENGINES:
            raise ValueError(f"unsupported engine: {engine!r}")
        key = (engine, name)
        if key in seen:
            raise ValueError(f"duplicate profile name {name!r} for engine {engine!r}")
        seen.add(key)
        item = dict(item)
        extra_env = dict(item.get("extra_env") or {})
        removed = [k for k in extra_env if _is_secret_extra_env_key(k)]
        for key_name in removed:
            extra_env.pop(key_name, None)
        if removed:
            logger.warning(
                "[profile-store] secret-like extra_env keys removed for %s/%s: %s",
                engine,
                name,
                sorted(removed),
            )
        item["extra_env"] = extra_env
        profiles.append(LLMProfile.from_dict(item))

    # selected 검증: 없으면 default
    selected_raw = payload.get("selected", {})
    if not isinstance(selected_raw, dict):
        selected_raw = {}
    selected: Dict[str, str] = {}
    for engine in SUPPORTED_ENGINES:
        sel = str(selected_raw.get(engine, "default")).strip()
        # 선택된 profile 이 존재하지 않으면 default 로 fallback
        engine_names = [p.name for p in profiles if p.engine == engine]
        if sel not in engine_names:
            sel = engine_names[0] if engine_names else "default"
        selected[engine] = sel

    return {
        "selected": selected,
        "profiles": [p.to_dict() for p in profiles],
    }


def get_selected(engine: str) -> LLMProfile:
    """현재 선택된 profile 반환. 없으면 config_dir=None 의 가상 default profile."""
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"unsupported engine: {engine!r}")
    payload = load_profiles()
    selected_name = payload.get("selected", {}).get(engine, "default")
    for item in payload.get("profiles", []):
        if item.get("engine") == engine and item.get("name") == selected_name:
            return LLMProfile.from_dict(item)
    # fallback: 첫 번째 해당 engine profile
    for item in payload.get("profiles", []):
        if item.get("engine") == engine:
            return LLMProfile.from_dict(item)
    # 최후 fallback: 빈 profile (기존 동작 유지)
    return LLMProfile(engine=engine, name="default", config_dir=None)


def get_by_name(engine: str, name: str) -> LLMProfile:
    """이름으로 지정된 profile 반환.

    Args:
        engine: 엔진 이름 (SUPPORTED_ENGINES 내에만 허용)
        name: 프로필 이름

    Returns:
        LLMProfile 인스턴스

    Raises:
        ValueError: engine 미지원 또는 name 미존재 시
    """
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"unsupported engine: {engine!r}")
    payload = load_profiles()
    for item in payload.get("profiles", []):
        if item.get("engine") == engine and item.get("name") == name:
            return LLMProfile.from_dict(item)
    raise ValueError(f"profile {name!r} not found for engine {engine!r}")


def list_profiles(engine: Optional[str] = None) -> List[LLMProfile]:
    payload = load_profiles()
    profiles = [LLMProfile.from_dict(item) for item in payload.get("profiles", [])]
    if engine is not None:
        profiles = [p for p in profiles if p.engine == engine]
    return profiles


def update_profile_state(
    engine: str,
    name: str,
    *,
    last_quota_pause_until: Optional[datetime] = None,
    last_reset_at: Optional[datetime] = None,
    last_state: Optional[str] = None,
    last_error_summary: Optional[str] = None,
) -> Dict[str, Any]:
    payload = load_profiles()
    found = False
    for item in payload.get("profiles", []):
        if item.get("engine") == engine and item.get("name") == name:
            found = True
            item["last_quota_pause_until"] = _dt_to_str(last_quota_pause_until)
            item["last_reset_at"] = _dt_to_str(last_reset_at)
            item["last_state"] = last_state
            item["last_error_summary"] = last_error_summary
            break
    if not found:
        raise ValueError(f"profile {name!r} not found for engine {engine!r}")
    return save_profiles(payload)


def select(engine: str, name: str) -> Dict[str, Any]:
    """engine 의 현재 선택 profile 변경 후 저장."""
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"unsupported engine: {engine!r}")
    payload = load_profiles()
    names = [
        p["name"]
        for p in payload["profiles"]
        if p.get("engine") == engine and p.get("enabled", True)
    ]
    if name not in names:
        raise ValueError(f"profile {name!r} not found or disabled for engine {engine!r}")
    payload["selected"][engine] = name
    return save_profiles(payload)


def delete(engine: str, name: str) -> Dict[str, Any]:
    """profile 삭제. selected 이던 profile 이면 default 또는 첫 번째 profile 로 fallback."""
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"unsupported engine: {engine!r}")
    payload = load_profiles()
    profiles = payload.get("profiles", [])
    new_profiles = [p for p in profiles if not (p.get("engine") == engine and p.get("name") == name)]
    if len(new_profiles) == len(profiles):
        raise ValueError(f"profile {name!r} not found for engine {engine!r}")

    payload["profiles"] = new_profiles

    # selected fallback
    if payload.get("selected", {}).get(engine) == name:
        remaining = [p["name"] for p in new_profiles if p.get("engine") == engine]
        fallback = "default" if "default" in remaining else (remaining[0] if remaining else "default")
        payload.setdefault("selected", {})[engine] = fallback

    return save_profiles(payload)
