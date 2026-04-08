"""LLM Model Registry E2E — 워커 큐→resolve→DB 경계 검증.

실물 SQLite DB(in-memory) + monkeypatched registry/state 파일을 사용.
외부 CLI subprocess 호출 직전 경계까지만 검증 (T4 범위).
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.shared.llm_registry as reg_mod
import app.modules.claude_worker.services.llm_service as svc_mod
from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa: F401 (table registration)
from app.modules.claude_worker.services.llm_service import LLMService

SAMPLE_REGISTRY = {
    "steps": {
        "plan_expand": [
            {"provider": "claude", "model": "claude-opus-4-6"},
            {"provider": "gemini", "model": "gemini-3.1-pro", "oneshot": True},
        ],
        "implement": [
            {"provider": "claude", "model": "claude-sonnet-4-6"},
            {"provider": "openai", "model": "gpt-5.1-codex-mini"},
        ],
        "status_tracking": [
            {"provider": "claude", "model": "claude-haiku-4-5"},
            {"provider": "gemini", "model": "gemini-3-flash"},
        ],
    }
}

DEFAULT_LLM_DEFAULTS = {
    "global_default": {"provider": "claude", "model": "claude-sonnet-4-6"},
    "caller_defaults": {},
}


@pytest.fixture
def db_session(tmp_path):
    """인메모리 SQLite 세션 — 실물 스키마 사용."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def registry_env(tmp_path, monkeypatch):
    """registry/state/defaults 3개 파일 monkeypatch."""
    registry_file = tmp_path / "llm_model_registry.json"
    state_file = tmp_path / "llm_quota_state.json"
    defaults_file = tmp_path / "llm_defaults.json"

    registry_file.write_text(json.dumps(SAMPLE_REGISTRY), encoding="utf-8")
    state_file.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    defaults_file.write_text(json.dumps(DEFAULT_LLM_DEFAULTS), encoding="utf-8")

    monkeypatch.setattr(reg_mod, "REGISTRY_FILE", registry_file)
    monkeypatch.setattr(reg_mod, "QUOTA_STATE_FILE", state_file)
    monkeypatch.setattr(svc_mod, "LLM_DEFAULTS_FILE", defaults_file)

    return registry_file, state_file, defaults_file


@pytest.fixture
def llm_svc(db_session, registry_env):
    return LLMService(db=db_session)


@pytest.mark.e2e
def test_enqueue_with_auto_resolve_uses_picker(llm_svc, db_session):
    """워커 enqueue → resolve → DB: picker 결과가 DB에 저장되는지 확인.

    plan_archive_analyze → CALLER_TYPE_TO_STEP["plan_archive_analyze"] = "plan_expand"
    plan_expand 1순위: claude/claude-opus-4-6 (quota 없음 → 0%, 통과)
    """
    req = llm_svc.enqueue(
        caller_type="plan_archive_analyze",
        caller_id="test-e2e-001",
        prompt="테스트 프롬프트",
        requested_by="e2e_test",
        provider=None,
        model=None,
    )
    db_session.commit()

    assert req.provider == "claude"
    assert req.model == "claude-opus-4-6"
    assert req.caller_type == "plan_archive_analyze"
    assert req.status == "pending"


@pytest.mark.e2e
def test_enqueue_respects_explicit_override(llm_svc, db_session):
    """명시 provider/model 전달 시 picker 우회: DB에 명시값 그대로 저장."""
    req = llm_svc.enqueue(
        caller_type="plan_archive_analyze",
        caller_id="test-e2e-002",
        prompt="테스트 프롬프트 명시",
        requested_by="e2e_test",
        provider="gemini",
        model="gemini-3-flash",
    )
    db_session.commit()

    assert req.provider == "gemini"
    assert req.model == "gemini-3-flash"
