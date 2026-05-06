"""
LLMWorker Provider Registry — Provider 레이어 단일 책임 구현.

레이어 경계 (docs/dev-guide/llm-provider-layering.md 참조):
  - Provider 레이어: 실행 엔진 메타 (어떤 외부 툴/API로 실행하는가)
  - Model 레이어:   provider 내부 모델 변형 단위 (app/shared/llm_registry.py)
  - Engine Profile: 실행 환경 분리 (profile_store.py) — 이 파일과 교차 참조 금지

이 파일의 역할:
  - Provider 목록/메타 관리
  - 실행 가능 여부 (enabled) 관리
  - quota 적용 대상 여부 (supports_quota_pause) 관리
  - dispatch 분기를 위한 executor_key 노출
  - models 필드 → Model Registry 조회(lazy)로 레이어 경계 유지

사용:
    from app.modules.claude_worker.services import provider_registry

    if not provider_registry.is_supported("claude"):
        raise ValueError("unsupported provider")
    providers = provider_registry.list_enabled()
    quota_providers = provider_registry.get_quota_providers()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderMeta:
    """Provider 메타데이터.

    models 필드는 lazy loader를 통해 Model Registry에서 조회된다.
    직접 하드코딩하지 않으며, Registry 파일 변경이 즉시 반영된다.
    """

    key: str
    display_name: str
    default_model: str
    supports_chat: bool
    supports_quota_pause: bool
    enabled: bool
    executor_key: str
    # models는 lazy 조회 — 직접 설정하지 말 것 (레이어 경계)
    _models: list[str] = field(default_factory=list, repr=False, compare=False)

    @property
    def models(self) -> list[str]:
        """Model Registry에서 이 provider에 속한 모델 목록을 lazy 조회."""
        return _get_models_for_provider(self.key)


def _get_models_for_provider(provider_key: str) -> list[str]:
    """Model Registry에서 특정 provider의 모델 목록 조회 (중복 제거, 등장 순서 유지)."""
    try:
        from app.shared.llm_registry import load_registry

        registry = load_registry()
        seen: set[str] = set()
        models: list[str] = []
        for candidates in registry.values():
            for c in candidates:
                if c.provider == provider_key and c.model not in seen:
                    seen.add(c.model)
                    models.append(c.model)
        return models
    except Exception:
        return []


# ─── Provider 등록 ────────────────────────────────────────────────────────────

_REGISTRY: dict[str, ProviderMeta] = {
    "claude": ProviderMeta(
        key="claude",
        display_name="Claude",
        default_model="claude-opus-4-6",
        supports_chat=True,
        supports_quota_pause=True,
        enabled=True,
        executor_key="claude",
    ),
    "gemini": ProviderMeta(
        key="gemini",
        display_name="Gemini",
        default_model="gemini-3.1-pro",
        supports_chat=False,
        supports_quota_pause=True,
        enabled=True,
        executor_key="gemini",
    ),
    "codex": ProviderMeta(
        key="codex",
        display_name="Codex",
        default_model="gpt-5.5",
        supports_chat=False,
        supports_quota_pause=False,
        enabled=True,
        executor_key="codex",
    ),
    "cc-codex": ProviderMeta(
        key="cc-codex",
        display_name="CC-Codex",
        default_model="gpt-5.3-codex",
        supports_chat=False,
        supports_quota_pause=False,
        enabled=True,
        executor_key="cc-codex",
    ),
    "openai": ProviderMeta(
        key="openai",
        display_name="OpenAI",
        default_model="gpt-5.4",
        supports_chat=False,
        supports_quota_pause=False,
        enabled=False,  # 현재 실행 경로 미구현 (O-2)
        executor_key="openai",
    ),
}


# ─── 조회 유틸 ────────────────────────────────────────────────────────────────


def list_enabled() -> list[ProviderMeta]:
    """enabled=True인 provider 목록 반환 (등록 순서 유지)."""
    return [p for p in _REGISTRY.values() if p.enabled]


def is_supported(key: str) -> bool:
    """enabled provider 중 해당 key가 있으면 True. 빈 문자열/None → False."""
    if not key:
        return False
    meta = _REGISTRY.get(key)
    return meta is not None and meta.enabled


def get_provider(key: str) -> Optional[ProviderMeta]:
    """key로 provider 조회. 없으면 None 반환 (예외 없음)."""
    return _REGISTRY.get(key)


def get_quota_providers() -> list[str]:
    """supports_quota_pause=True이고 enabled=True인 provider key 목록 반환."""
    return [p.key for p in _REGISTRY.values() if p.enabled and p.supports_quota_pause]
