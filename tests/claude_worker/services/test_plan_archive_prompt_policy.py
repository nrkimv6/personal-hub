"""Plan Archive prompt policy tests."""

from __future__ import annotations

from app.modules.claude_worker.services.plan_analyze_handler import build_plan_analyze_prompt
from app.modules.claude_worker.services.plan_archive_prompt_policy import (
    PromptPolicyContext,
    build_plan_archive_prompt,
    resolve_policy,
)


def _ctx(provider: str, model: str) -> PromptPolicyContext:
    return PromptPolicyContext(
        caller_type="plan_archive_analyze",
        provider=provider,
        model=model,
        filename="2026-05-06_sample.md",
        existing_categories=["infra", "common"],
    )


def test_resolve_policy_claude_returns_claude_id():
    policy = resolve_policy("claude", "claude-opus-4-7")

    assert "claude" in policy.id


def test_resolve_policy_gemini_returns_gemini_id():
    policy = resolve_policy("gemini", "gemini-3.1-pro-preview")

    assert "gemini" in policy.id


def test_resolve_policy_codex_returns_codex_id():
    policy = resolve_policy("codex", "gpt-5.2")

    assert "codex" in policy.id


def test_resolve_policy_unknown_model_falls_back_to_provider():
    policy = resolve_policy("gemini", "unknown-model")

    assert policy.id == "plan_archive.gemini.default"


def test_build_prompt_contains_common_trigger_rules():
    for provider, model in [
        ("claude", "claude-opus-4-6"),
        ("gemini", "gemini-3.1-pro-preview"),
        ("codex", "gpt-5.5"),
    ]:
        prompt, _policy_id, _version = build_plan_archive_prompt(_ctx(provider, model), "# Plan")

        assert "trigger 판정 규칙" in prompt
        assert "`bug_recurrence`" in prompt
        assert "`ux_improvement`" in prompt
        assert "`new_feature`" in prompt


def test_build_prompt_contains_common_tags_and_scope_rules():
    for provider, model in [
        ("claude", "claude-opus-4-6"),
        ("gemini", "gemini-3-flash-preview"),
        ("codex", "gpt-5.2"),
    ]:
        prompt, _policy_id, _version = build_plan_archive_prompt(_ctx(provider, model), "# Plan")

        assert "tags는 1~2개" in prompt
        assert "scope 우선순위는 변경 파일 경로 > 모듈명 > 기능명" in prompt
        assert "3~8개" in prompt


def test_legacy_build_plan_analyze_prompt_wrapper_compat():
    prompt = build_plan_analyze_prompt(
        file_content="# Legacy",
        filename="2026-05-06_legacy.md",
        existing_categories=["infra"],
    )

    assert "2026-05-06_legacy.md" in prompt
    for field in ["category", "tags", "summary", "superseded_by", "intent", "trigger", "scope"]:
        assert field in prompt
    assert "plan_archive.claude" not in prompt
