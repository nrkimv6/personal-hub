"""
Provider Registry 단위 테스트 (RIGHT-BICEP + CORRECT)

테스트 대상: app/modules/claude_worker/services/provider_registry.py
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.modules.claude_worker.services import provider_registry
from app.modules.claude_worker.services.provider_registry import ProviderMeta


# ─── RIGHT ─────────────────────────────────────────────────────────────────────

def test_provider_registry_R_list_enabled_returns_configured_entries():
    """enabled=True인 provider만 반환 — openai는 제외, 나머지 4개 포함 (RIGHT)."""
    enabled = provider_registry.list_enabled()
    keys = {p.key for p in enabled}

    # enabled=True인 4개 포함
    assert "claude" in keys
    assert "gemini" in keys
    assert "codex" in keys
    assert "cc-codex" in keys

    # enabled=False인 openai 제외
    assert "openai" not in keys


def test_provider_registry_R_is_supported_returns_true_for_enabled():
    """enabled provider key는 is_supported == True (RIGHT)."""
    assert provider_registry.is_supported("claude") is True
    assert provider_registry.is_supported("gemini") is True
    assert provider_registry.is_supported("codex") is True
    assert provider_registry.is_supported("cc-codex") is True


def test_provider_registry_R_is_supported_returns_false_for_disabled():
    """enabled=False인 openai는 is_supported == False (RIGHT)."""
    assert provider_registry.is_supported("openai") is False


def test_provider_registry_R_get_provider_returns_meta_for_known_key():
    """알려진 key → ProviderMeta 반환 (RIGHT)."""
    meta = provider_registry.get_provider("claude")
    assert meta is not None
    assert isinstance(meta, ProviderMeta)
    assert meta.key == "claude"
    assert meta.display_name == "Claude"
    assert meta.executor_key == "claude"


# ─── BOUNDARY ──────────────────────────────────────────────────────────────────

def test_provider_registry_B_is_supported_edge_case_empty_string():
    """빈 문자열 → is_supported == False (BOUNDARY)."""
    assert provider_registry.is_supported("") is False


def test_provider_registry_B_is_supported_none_input():
    """None → is_supported == False (BOUNDARY)."""
    assert provider_registry.is_supported(None) is False  # type: ignore[arg-type]


def test_provider_registry_B_is_supported_whitespace_only():
    """공백만 있는 문자열 → is_supported == False (BOUNDARY)."""
    # 공백은 등록된 key가 아니므로 False
    assert provider_registry.is_supported("   ") is False


# ─── ERROR ─────────────────────────────────────────────────────────────────────

def test_provider_registry_E_get_provider_unknown_returns_none():
    """존재하지 않는 key → None 반환, 예외 없음 (ERROR)."""
    result = provider_registry.get_provider("nonexistent_provider_xyz")
    assert result is None


def test_provider_registry_E_get_provider_empty_string_returns_none():
    """빈 문자열 key → None 반환 (ERROR)."""
    result = provider_registry.get_provider("")
    assert result is None


# ─── REFERENCE ────────────────────────────────────────────────────────────────

def test_provider_registry_Re_get_quota_providers_matches_supports_quota_pause_true():
    """get_quota_providers() 결과가 supports_quota_pause=True이고 enabled=True인 항목과 정확히 일치 (REFERENCE)."""
    quota_keys = set(provider_registry.get_quota_providers())

    # Registry에서 직접 기대값 계산
    expected = {
        p.key
        for p in provider_registry._REGISTRY.values()
        if p.enabled and p.supports_quota_pause
    }

    assert quota_keys == expected


def test_provider_registry_Re_codex_not_in_quota_providers():
    """codex/cc-codex는 supports_quota_pause=False이므로 quota_providers에 없음 (REFERENCE)."""
    quota_keys = provider_registry.get_quota_providers()
    assert "codex" not in quota_keys
    assert "cc-codex" not in quota_keys


def test_provider_registry_Re_claude_and_gemini_in_quota_providers():
    """claude/gemini는 supports_quota_pause=True이므로 quota_providers에 포함 (REFERENCE)."""
    quota_keys = provider_registry.get_quota_providers()
    assert "claude" in quota_keys
    assert "gemini" in quota_keys


# ─── CONFORMANCE ───────────────────────────────────────────────────────────────

def test_provider_registry_Co_codex_and_cc_codex_have_distinct_executor_keys():
    """codex.executor_key != cc-codex.executor_key — dispatch 경로 혼용 방지 (CONFORMANCE)."""
    codex = provider_registry.get_provider("codex")
    cc_codex = provider_registry.get_provider("cc-codex")

    assert codex is not None
    assert cc_codex is not None
    assert codex.executor_key != cc_codex.executor_key


def test_provider_registry_Co_all_enabled_providers_have_non_empty_executor_key():
    """모든 enabled provider의 executor_key가 비어있지 않음 (CONFORMANCE)."""
    for meta in provider_registry.list_enabled():
        assert meta.executor_key, f"{meta.key}의 executor_key가 비어있음"


def test_provider_registry_Co_all_providers_have_non_empty_default_model():
    """모든 provider의 default_model이 비어있지 않음 (CONFORMANCE)."""
    for meta in provider_registry._REGISTRY.values():
        assert meta.default_model, f"{meta.key}의 default_model이 비어있음"


# ─── EXISTENCE ─────────────────────────────────────────────────────────────────

def test_provider_registry_E_models_field_lazy_loads_from_model_registry():
    """models 필드가 load_registry()를 통해 조회되는지 검증 — 직접 하드코딩 아님 (EXISTENCE)."""
    fake_registry = {
        "ideation": [
            type("SC", (), {"provider": "claude", "model": "claude-test-model"})(),
        ]
    }

    with patch(
        "app.modules.claude_worker.services.provider_registry._get_models_for_provider",
        return_value=["claude-test-model"],
    ) as mock_fn:
        meta = provider_registry.get_provider("claude")
        assert meta is not None
        models = meta.models
        mock_fn.assert_called_once_with("claude")
        assert "claude-test-model" in models


def test_provider_registry_E_models_returns_empty_list_on_registry_error():
    """load_registry() 예외 발생 시 models는 빈 리스트 반환 (EXISTENCE — graceful fallback)."""
    with patch(
        "app.shared.llm_registry.load_registry",
        side_effect=RuntimeError("registry file missing"),
    ):
        meta = provider_registry.get_provider("claude")
        assert meta is not None
        # 예외 발생해도 빈 리스트 반환, 예외 전파 없음
        assert meta.models == []


def test_provider_registry_E_list_enabled_returns_list_not_dict():
    """list_enabled()가 list[ProviderMeta]를 반환하는지 타입 검증 (EXISTENCE)."""
    result = provider_registry.list_enabled()
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, ProviderMeta)
