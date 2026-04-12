"""
LLMService execute_llm() dispatch 단위 테스트 (RIGHT-BICEP)

테스트 대상: app/modules/claude_worker/services/llm_service.py :: LLMService.execute_llm()
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.modules.claude_worker.services.llm_service import LLMService


@pytest.fixture
def service(test_db_session):
    return LLMService(test_db_session)


# ─── RIGHT ─────────────────────────────────────────────────────────────────────

def test_execute_llm_R_claude_dispatches_to_execute_claude(service):
    """provider='claude' → execute_claude() 호출 (RIGHT)."""
    expected = {"success": True, "result": {}, "raw_response": "ok"}
    with patch.object(service, "execute_claude", return_value=expected) as mock_fn:
        result = service.execute_llm("test prompt", provider="claude", model="claude-opus-4-6")

    mock_fn.assert_called_once()
    assert result == expected


def test_execute_llm_R_gemini_dispatches_to_execute_gemini(service):
    """provider='gemini' → execute_gemini() 호출 (RIGHT)."""
    expected = {"success": True, "result": {}, "raw_response": "gemini-ok"}
    with patch.object(service, "execute_gemini", return_value=expected) as mock_fn:
        result = service.execute_llm("test prompt", provider="gemini")

    mock_fn.assert_called_once()
    assert result == expected


def test_execute_llm_R_codex_dispatches_to_execute_codex(service):
    """provider='codex' → execute_codex() 호출 (RIGHT)."""
    expected = {"success": False, "error": "codex provider 실행 경로 미구현 (B4)"}
    with patch.object(service, "execute_codex", return_value=expected) as mock_fn:
        result = service.execute_llm("test prompt", provider="codex")

    mock_fn.assert_called_once()
    assert result == expected


def test_execute_llm_R_cc_codex_dispatches_to_execute_cc_codex_not_codex(service):
    """provider='cc-codex' → execute_cc_codex() 호출, execute_codex()와 다른 경로 (RIGHT)."""
    cc_codex_result = {"success": False, "error": "cc-codex provider 실행 경로 미구현 (B4)"}
    with patch.object(service, "execute_codex") as mock_codex, \
         patch.object(service, "execute_cc_codex", return_value=cc_codex_result) as mock_cc_codex:
        result = service.execute_llm("test prompt", provider="cc-codex")

    mock_cc_codex.assert_called_once()
    mock_codex.assert_not_called()
    assert result == cc_codex_result


# ─── ERROR ─────────────────────────────────────────────────────────────────────

def test_execute_llm_E_unknown_provider_returns_error_no_fallback(service):
    """unknown provider → {"success": False, "error": ...}, fallback 없음 (ERROR)."""
    result = service.execute_llm("test prompt", provider="nonexistent_provider")

    assert result["success"] is False
    assert "error" in result
    # execute_claude/gemini가 호출되지 않음 — fallback 금지
    assert "claude" not in result.get("error", "").lower() or "지원" in result.get("error", "")


def test_execute_llm_E_disabled_openai_returns_error(service):
    """enabled=False인 provider(openai) → {"success": False, "error": ...} (ERROR)."""
    result = service.execute_llm("test prompt", provider="openai")

    assert result["success"] is False
    assert "error" in result


# ─── BOUNDARY ──────────────────────────────────────────────────────────────────

def test_execute_llm_B_empty_provider_returns_error(service):
    """빈 문자열 provider → {"success": False} (BOUNDARY)."""
    result = service.execute_llm("test prompt", provider="")

    assert result["success"] is False


def test_execute_llm_B_codex_and_cc_codex_use_separate_methods(service):
    """codex와 cc-codex는 서로 다른 메서드 — 코드 공유 없이 독립 경로 (BOUNDARY)."""
    # 두 메서드가 별도로 정의되어 있는지 확인
    assert hasattr(service, "execute_codex")
    assert hasattr(service, "execute_cc_codex")
    # 두 메서드가 동일 객체가 아닌지 확인 (unbound method 비교)
    assert LLMService.execute_codex is not LLMService.execute_cc_codex
