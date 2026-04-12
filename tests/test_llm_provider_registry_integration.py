"""
Provider Registry 통합 TC — mock 최소화, 실제 registry + 실제 DB

테스트 대상:
- provider_registry 함수들이 실제 llm_registry.py와 연동되는지
- LLMRequestCreate pydantic 검증이 registry 기반으로 작동하는지
- unknown provider → 422, known provider → 통과
"""

from __future__ import annotations

import pytest

from app.modules.claude_worker.services import provider_registry


# ─── 실제 registry 통합 ────────────────────────────────────────────────────────

def test_integration_provider_registry_models_loads_from_real_json():
    """claude provider의 models가 실제 data/llm_model_registry.json에서 로드되는지 (통합)."""
    meta = provider_registry.get_provider("claude")
    assert meta is not None

    models = meta.models
    # 실제 JSON 파일에 claude provider가 있으면 최소 1개 이상 반환
    # (빈 경우는 파일 파싱 실패가 아닌 "해당 provider 없음"을 의미)
    # 여기서는 최소한 예외 없이 list를 반환하는지 확인
    assert isinstance(models, list)


def test_integration_provider_registry_quota_providers_matches_enabled_set():
    """get_quota_providers() 결과가 실제 registry와 일치하는지 (통합)."""
    quota_providers = provider_registry.get_quota_providers()

    # list 타입이어야 함
    assert isinstance(quota_providers, list)

    # 모든 반환 key가 enabled=True이고 supports_quota_pause=True인지
    for key in quota_providers:
        meta = provider_registry.get_provider(key)
        assert meta is not None
        assert meta.enabled is True
        assert meta.supports_quota_pause is True


def test_integration_provider_registry_list_enabled_excludes_disabled():
    """list_enabled()가 enabled=False인 provider를 제외하는지 (통합)."""
    enabled = provider_registry.list_enabled()

    for meta in enabled:
        assert meta.enabled is True

    # openai는 enabled=False
    openai = provider_registry.get_provider("openai")
    assert openai is not None
    assert openai.enabled is False
    assert openai not in enabled


# ─── LLMRequestCreate pydantic 검증 ────────────────────────────────────────────

def test_integration_pydantic_accepts_codex_provider(test_db_session):
    """LLMService.enqueue()가 provider=codex를 받아 DB에 저장하는지 (통합)."""
    from app.modules.claude_worker.services.llm_service import LLMService

    service = LLMService(test_db_session)

    # codex provider로 요청 생성 (model 명시 필수 — 빈 model은 resolve_provider_model 1순위 통과 불가)
    req = service.enqueue(
        caller_type="test",
        caller_id="integration_test_codex",
        prompt="test prompt",
        requested_by="test",
        provider="codex",
        model="gpt-5.1-codex-mini",
    )

    assert req is not None
    assert req.provider == "codex"


def test_integration_pydantic_accepts_cc_codex_provider(test_db_session):
    """LLMService.enqueue()가 provider=cc-codex를 받아 DB에 저장하는지 (통합)."""
    from app.modules.claude_worker.services.llm_service import LLMService

    service = LLMService(test_db_session)

    req = service.enqueue(
        caller_type="test",
        caller_id="integration_test_cc_codex",
        prompt="test prompt",
        requested_by="test",
        provider="cc-codex",
        model="gpt-5.3-codex",
    )

    assert req is not None
    assert req.provider == "cc-codex"


def test_integration_git_repos_schema_accepts_codex():
    """git_repos GenerateMessageRequest가 provider=codex를 허용하는지 (통합)."""
    from app.modules.git_repos.schemas import GenerateMessageRequest

    req = GenerateMessageRequest(provider="codex", model="")
    assert req.provider == "codex"


def test_integration_git_repos_schema_rejects_unknown():
    """git_repos GenerateMessageRequest가 unknown provider를 422로 거부하는지 (통합)."""
    from pydantic import ValidationError
    from app.modules.git_repos.schemas import GenerateMessageRequest

    with pytest.raises(ValidationError) as exc_info:
        GenerateMessageRequest(provider="unknown_provider_xyz", model="")

    errors = exc_info.value.errors()
    assert any("지원되지 않는 provider" in str(e) for e in errors)


# ─── execute_llm dispatch 경로 회귀 ────────────────────────────────────────────

def test_integration_execute_llm_unknown_no_fallback(test_db_session):
    """execute_llm(provider='unknown') → {"success": False}, execute_claude/gemini 미호출 (통합)."""
    from app.modules.claude_worker.services.llm_service import LLMService
    from unittest.mock import patch

    service = LLMService(test_db_session)

    with patch.object(service, "execute_claude") as mock_claude, \
         patch.object(service, "execute_gemini") as mock_gemini:
        result = service.execute_llm("prompt", provider="unknown_xyz")

    assert result["success"] is False
    mock_claude.assert_not_called()
    mock_gemini.assert_not_called()
