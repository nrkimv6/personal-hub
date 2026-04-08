"""profile_env.py 단위 테스트."""
import os
import sys
import pytest
from unittest.mock import patch

import app.modules.claude_worker.services.profile_store as ps
import app.modules.claude_worker.services.profile_env as pe


# ────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_profiles(tmp_path, monkeypatch):
    """각 테스트가 독립 profiles 파일 + 기본 profiles를 사용."""
    profiles_path = tmp_path / "llm_profiles.json"
    monkeypatch.setattr(ps, "LLM_PROFILES_FILE", profiles_path)
    # default profile 기본값 저장 (파일 없는 상태 = default)
    yield profiles_path


def _set_profile(engine: str, name: str, config_dir=None, extra_env=None):
    """테스트용 profile 저장 헬퍼."""
    profiles = [
        {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
        {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
    ]
    if engine == "claude" and name != "default":
        profiles.append({"engine": "claude", "name": name, "config_dir": config_dir, "extra_env": extra_env or {}})
    elif engine == "gemini" and name != "default":
        profiles.append({"engine": "gemini", "name": name, "config_dir": config_dir, "extra_env": extra_env or {}})

    ps.save_profiles({
        "selected": {engine: name, **({k: "default" for k in ps.SUPPORTED_ENGINES if k != engine})},
        "profiles": profiles,
    })


# ────────────────────────────────────────────
# build_cli_env — Claude 정상 케이스
# ────────────────────────────────────────────

def test_build_cli_env_R_claude_with_config_dir(isolate_profiles):
    """R: CLAUDE_CONFIG_DIR 주입 확인."""
    _set_profile("claude", "work", config_dir="C:/Users/test/.claude-work")
    env = pe.build_cli_env("claude")
    assert env.get("CLAUDE_CONFIG_DIR") == "C:/Users/test/.claude-work"


def test_build_cli_env_R_claude_null_config_dir_regression(isolate_profiles):
    """R: config_dir=null 일 때 CLAUDE_CONFIG_DIR 키 없음 (기존 동작 회귀 방어)."""
    env = pe.build_cli_env("claude")
    assert "CLAUDE_CONFIG_DIR" not in env


def test_build_cli_env_R_claude_pops_session_vars(isolate_profiles):
    """R: engine=claude 일 때 CLAUDECODE/CLAUDE_CODE_SESSION/CLAUDE_CODE_ENTRYPOINT 제거."""
    base = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION": "s", "CLAUDE_CODE_ENTRYPOINT": "e", "OTHER": "x"}
    env = pe.build_cli_env("claude", base_env=base)
    assert "CLAUDECODE" not in env
    assert "CLAUDE_CODE_SESSION" not in env
    assert "CLAUDE_CODE_ENTRYPOINT" not in env
    assert env.get("OTHER") == "x"


def test_build_cli_env_R_gemini_does_not_pop_claude_vars(isolate_profiles):
    """R: engine=gemini 일 때 Claude session var 보존."""
    base = {"CLAUDECODE": "1", "OTHER": "y"}
    env = pe.build_cli_env("gemini", base_env=base)
    assert env.get("CLAUDECODE") == "1"
    assert env.get("OTHER") == "y"


# ────────────────────────────────────────────
# build_cli_env — Boundary
# ────────────────────────────────────────────

def test_build_cli_env_B_empty_extra_env(isolate_profiles):
    """B: extra_env={} 정상 동작."""
    env = pe.build_cli_env("claude")
    assert isinstance(env, dict)


# ────────────────────────────────────────────
# build_cli_env — Cross-check
# ────────────────────────────────────────────

def test_build_cli_env_C_extra_env_merge(isolate_profiles):
    """C: 일반 key extra_env merge 성공."""
    _set_profile("claude", "work", config_dir=None, extra_env={"MY_TOKEN": "abc123"})
    env = pe.build_cli_env("claude")
    assert env.get("MY_TOKEN") == "abc123"


# ────────────────────────────────────────────
# build_cli_env — Error
# ────────────────────────────────────────────

def test_build_cli_env_E_forbidden_extra_env_PATH(isolate_profiles):
    """E: extra_env 에 PATH → ValueError (save 우회해 직접 파일 쓰기로 검증)."""
    import json
    # save_profiles 도 검증하므로 파일 직접 쓰기로 우회 (isolate_profiles = file path)
    bad_payload = {
        "selected": {"claude": "bad", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "bad", "config_dir": None, "extra_env": {"PATH": "/evil"}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    isolate_profiles.write_text(json.dumps(bad_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden env key"):
        pe.build_cli_env("claude")


def test_build_cli_env_E_forbidden_extra_env_HOME(isolate_profiles):
    """E: extra_env 에 HOME → ValueError (save 우회해 직접 파일 쓰기로 검증)."""
    import json
    bad_payload = {
        "selected": {"claude": "bad2", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "bad2", "config_dir": None, "extra_env": {"HOME": "/evil"}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    isolate_profiles.write_text(json.dumps(bad_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden env key"):
        pe.build_cli_env("claude")


def test_build_cli_env_E_unknown_engine(isolate_profiles):
    """E: 미지원 engine → ValueError."""
    with pytest.raises(ValueError, match="unsupported engine"):
        pe.build_cli_env("codex")


# ────────────────────────────────────────────
# build_cli_env — Inverse / Reference
# ────────────────────────────────────────────

def test_build_cli_env_I_home_userprofile_fallback(isolate_profiles):
    """I: HOME 미설정 시 USERPROFILE 로 보정 (Windows, base_env=None 일 때)."""
    if sys.platform != "win32":
        pytest.skip("Windows 전용 테스트")
    base_without_home = {k: v for k, v in os.environ.items() if k not in ("HOME",)}
    base_without_home.setdefault("USERPROFILE", "C:/Users/TestUser")
    with patch.dict(os.environ, base_without_home, clear=True):
        env = pe.build_cli_env("claude")
    if base_without_home.get("USERPROFILE"):
        assert env.get("HOME") == base_without_home["USERPROFILE"]


def test_build_cli_env_Re_base_env_preserved(isolate_profiles):
    """Re: base_env 전달 시 원본 key 전부 보존 (Q4 base_env 시맨틱)."""
    base = {"CUSTOM_KEY": "hello", "ANOTHER": "world"}
    env = pe.build_cli_env("claude", base_env=base)
    assert env.get("CUSTOM_KEY") == "hello"
    assert env.get("ANOTHER") == "world"
