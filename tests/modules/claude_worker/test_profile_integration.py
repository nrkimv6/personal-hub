"""profile_store + profile_env + llm_service 통합 테스트.

mock 범위: subprocess.run / subprocess.Popen 만.
파일시스템 / os.environ / profile_store 는 실물 사용.
"""
import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import app.modules.claude_worker.services.profile_store as ps


@pytest.fixture(autouse=True)
def isolate_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "LLM_PROFILES_FILE", tmp_path / "llm_profiles.json")
    yield tmp_path


# ──────────────────────────────────────────
# T3-1: llm_service env 에 선택 profile config_dir 주입
# ──────────────────────────────────────────

def test_llm_service_env_uses_selected_profile(isolate_profiles):
    """llm_service 가 실행 시 선택된 profile 의 CLAUDE_CONFIG_DIR 를 env 에 주입하는지."""
    # work profile 저장 + 선택
    ps.save_profiles({
        "selected": {"claude": "work", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": str(isolate_profiles / ".claude-work"), "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    })

    captured_envs = []

    def capture_run(*args, **kwargs):
        captured_envs.append(kwargs.get("env", {}))
        m = MagicMock()
        m.returncode = 0
        m.stdout = "ok"
        m.stderr = ""
        return m

    with patch("subprocess.run", side_effect=capture_run):
        from app.modules.claude_worker.services.llm_service import LLMService
        from unittest.mock import MagicMock as MM
        svc = LLMService(MM())
        try:
            svc.execute_claude("test prompt", timeout=5)
        except Exception:
            pass  # 결과 파싱 실패는 무시

    assert len(captured_envs) > 0, "subprocess.run 이 호출되지 않음"
    env_used = captured_envs[0]
    assert "CLAUDE_CONFIG_DIR" in env_used, "CLAUDE_CONFIG_DIR 이 env 에 없음"
    assert str(isolate_profiles / ".claude-work") in env_used["CLAUDE_CONFIG_DIR"]


# ──────────────────────────────────────────
# T3-2: default profile(config_dir=null) 시 기존 env 와 동일 (회귀 방어)
# ──────────────────────────────────────────

def test_llm_service_env_regression_default_profile(isolate_profiles):
    """default profile(config_dir=null) 일 때 env 에 CLAUDE_CONFIG_DIR 없음."""
    # 파일 없는 상태 = default

    captured_envs = []

    def capture_run(*args, **kwargs):
        captured_envs.append(kwargs.get("env", {}))
        m = MagicMock()
        m.returncode = 0
        m.stdout = "ok"
        m.stderr = ""
        return m

    with patch("subprocess.run", side_effect=capture_run):
        from app.modules.claude_worker.services.llm_service import LLMService
        from unittest.mock import MagicMock as MM
        svc = LLMService(MM())
        try:
            svc.execute_claude("test prompt", timeout=5)
        except Exception:
            pass

    assert len(captured_envs) > 0
    env_used = captured_envs[0]
    assert "CLAUDE_CONFIG_DIR" not in env_used, "default profile 에서 CLAUDE_CONFIG_DIR 가 주입되어서는 안 됨"


# ──────────────────────────────────────────
# T3-3: 파일 없는 상태에서도 기존 동작 유지
# ──────────────────────────────────────────

def test_llm_profiles_json_missing_uses_default(isolate_profiles):
    """llm_profiles.json 미존재 → default profile 반환 + 파일 생성 안 함."""
    from app.modules.claude_worker.services.profile_env import build_cli_env
    env = build_cli_env("claude")
    assert "CLAUDE_CONFIG_DIR" not in env
    assert not (isolate_profiles / "llm_profiles.json").exists()


# ──────────────────────────────────────────
# T3-4: chat_executor base_env 보존 (Q4)
# ──────────────────────────────────────────

def test_chat_executor_env_preserves_filtered_base(isolate_profiles):
    """chat_executor 의 필터된 base_env 가 build_cli_env 호출 후에도 보존됨."""
    from app.modules.claude_worker.services.profile_env import build_cli_env

    # chat_executor 방식 재현
    filtered_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    original_keys = set(filtered_env.keys())

    env = build_cli_env("claude", base_env=filtered_env)

    # 원본 key 들이 보존되어야 함 (CLAUDE_CODE_SESSION 등 pop 된 것 제외)
    removed_by_design = {"CLAUDE_CODE_SESSION", "CLAUDE_CODE_ENTRYPOINT"}
    for k in original_keys - removed_by_design:
        assert k in env, f"base_env key {k!r} 가 env 에서 사라짐"
