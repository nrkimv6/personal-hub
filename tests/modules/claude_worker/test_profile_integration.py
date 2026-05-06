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


def test_claude_executor_uses_direct_stdin_with_profile_env(isolate_profiles):
    """ClaudeExecutor도 profile env 주입 상태에서 argv + stdin 경로를 유지한다."""
    ps.save_profiles({
        "selected": {"claude": "work", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": str(isolate_profiles / ".claude-work"), "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    })

    captured = {}

    def capture_run(*args, **kwargs):
        captured["args"] = args[0]
        captured["kwargs"] = kwargs
        m = MagicMock()
        m.returncode = 0
        m.stdout = json.dumps({"type": "result", "session_id": "profile-id", "result": "ok"})
        m.stderr = ""
        return m

    with patch("subprocess.run", side_effect=capture_run):
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

        executor = ClaudeExecutor()
        executor.execute("한글 prompt", parse_json=False)

    assert captured["args"][0] == "claude"
    assert captured["kwargs"]["stdin"].encoding.lower() == "utf-8"
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["env"]["CLAUDE_CONFIG_DIR"] == str(isolate_profiles / ".claude-work")


def test_claude_executor_keeps_schema_file_arg_with_profile_env(isolate_profiles):
    """profile env 경유 single mode json_schema도 @schema_file argv를 유지한다."""
    captured = {}

    def capture_run(*args, **kwargs):
        captured["args"] = args[0]
        m = MagicMock()
        m.returncode = 0
        m.stdout = json.dumps({"type": "result", "session_id": "schema-id", "result": "ok"})
        m.stderr = ""
        return m

    with patch("subprocess.run", side_effect=capture_run):
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

        executor = ClaudeExecutor()
        executor.execute(
            "prompt",
            parse_json=False,
            cli_options={"json_schema": {"type": "object"}},
        )

    schema_index = captured["args"].index("--json-schema")
    assert captured["args"][schema_index + 1].startswith("@")


def test_gemini_executor_uses_direct_stdin_with_profile_env(isolate_profiles):
    """GeminiExecutor도 profile 선택 상태에서 argv + UTF-8 stdin 경로를 유지한다."""
    ps.save_profiles({
        "selected": {"claude": "default", "gemini": "work"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "gemini", "name": "work", "config_dir": str(isolate_profiles / ".gemini-work"), "extra_env": {}},
        ],
    })

    captured = {}

    def capture_run(*args, **kwargs):
        captured["args"] = args[0]
        captured["kwargs"] = kwargs
        m = MagicMock()
        m.returncode = 0
        m.stdout = '{"ok": true}'
        m.stderr = ""
        return m

    with patch("subprocess.run", side_effect=capture_run):
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor

        executor = GeminiExecutor()
        executor.execute("한글 prompt", parse_json=False)

    assert captured["args"] == ["gemini"]
    assert captured["kwargs"]["input"] == "한글 prompt"
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert captured["kwargs"]["shell"] is False
    assert "GEMINI_CONFIG_DIR" not in captured["kwargs"]["env"]


def test_gemini_executor_keeps_image_path_arg_with_profile_env(isolate_profiles):
    """profile env 경유에서도 Gemini image_path argv가 유지된다."""
    captured = {}

    def capture_run(*args, **kwargs):
        captured["args"] = args[0]
        captured["kwargs"] = kwargs
        m = MagicMock()
        m.returncode = 0
        m.stdout = '{"ok": true}'
        m.stderr = ""
        return m

    with patch("subprocess.run", side_effect=capture_run):
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor

        executor = GeminiExecutor()
        executor.execute(
            "prompt",
            parse_json=False,
            cli_options={"image_path": "C:/tmp/profile-image.png"},
        )

    assert captured["args"] == ["gemini", "@C:/tmp/profile-image.png"]
    assert captured["kwargs"]["input"] == "prompt"
