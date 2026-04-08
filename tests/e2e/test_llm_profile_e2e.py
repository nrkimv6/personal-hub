"""LLM Profile E2E — 저장→조회→select→실행까지 전체 흐름 검증.

mock 범위: subprocess.run / subprocess.Popen 만.
파일시스템 / os.environ / profile_store 는 실물 사용.
"""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import app.modules.claude_worker.services.profile_store as ps


@pytest.fixture(autouse=True)
def isolate_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "LLM_PROFILES_FILE", tmp_path / "llm_profiles.json")
    yield tmp_path


@pytest.mark.e2e
def test_profile_crud_flow_e2e(isolate_profiles):
    """저장 → 조회 → select → llm_service 실행 시 선택된 profile env 사용까지 전체 흐름."""
    # 1) profile 저장 (real fs write)
    ps.save_profiles({
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": str(isolate_profiles / ".claude-work"), "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    })

    # 2) select "work"
    ps.select("claude", "work")

    # 3) load 확인
    loaded = ps.load_profiles()
    assert loaded["selected"]["claude"] == "work"

    # 4) llm_service execute 시 env에 CLAUDE_CONFIG_DIR 주입
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
        svc = LLMService(MagicMock())
        try:
            svc.execute_claude("test prompt", timeout=5)
        except Exception:
            pass  # 결과 파싱 실패는 무시

    assert len(captured_envs) > 0, "subprocess.run 이 호출되지 않음"
    env_used = captured_envs[0]
    assert "CLAUDE_CONFIG_DIR" in env_used, "CLAUDE_CONFIG_DIR 이 env 에 없음"
    assert str(isolate_profiles / ".claude-work") in env_used["CLAUDE_CONFIG_DIR"]


@pytest.mark.e2e
def test_profile_delete_selected_fallback_e2e(isolate_profiles):
    """selected profile 삭제 후 default 로 전환되고 이후 실행에 반영."""
    # work profile 저장 + 선택
    ps.save_profiles({
        "selected": {"claude": "work", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": str(isolate_profiles / ".claude-work"), "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    })

    # 선택된 "work" 삭제
    saved = ps.delete("claude", "work")

    # default 로 fallback 됐는지 확인
    assert saved["selected"]["claude"] == "default"
    names = [p["name"] for p in saved["profiles"] if p["engine"] == "claude"]
    assert "work" not in names

    # 이후 실행 시 CLAUDE_CONFIG_DIR 없음 (default)
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
        svc = LLMService(MagicMock())
        try:
            svc.execute_claude("test prompt", timeout=5)
        except Exception:
            pass

    assert len(captured_envs) > 0
    env_used = captured_envs[0]
    assert "CLAUDE_CONFIG_DIR" not in env_used, "default profile 이후 CLAUDE_CONFIG_DIR 가 남아있음"
