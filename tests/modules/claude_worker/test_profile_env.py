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


# ────────────────────────────────────────────
# FORBIDDEN_EXTRA_ENV 집합 대칭성 검증
# ────────────────────────────────────────────

def test_forbidden_env_superset_of_subprocess_C_symmetric():
    """C: profile_env.FORBIDDEN_EXTRA_ENV 가 _dr_subprocess._FORBIDDEN_EXTRA_ENV 를 완전히 포함함을 검증.

    저장 시점 검증(profile_env)이 실행 시점 검증(_dr_subprocess)보다 엄격하거나 동일해야
    "저장 성공 → 실행 실패" 경로가 소멸된다.
    """
    import importlib.util
    from pathlib import Path

    # scripts/_dr_subprocess.py 를 직접 로드 (scripts/ 는 app import 불가 구조)
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    spec = importlib.util.spec_from_file_location(
        "_dr_subprocess", scripts_dir / "_dr_subprocess.py"
    )
    dr_sub = importlib.util.module_from_spec(spec)

    # _dr_subprocess imports redis, _dr_constants 등 실행환경 의존 → sys.modules mock
    import sys
    from unittest.mock import MagicMock

    # 필요한 stub 모듈 준비
    stub_names = ["redis", "_dr_constants", "_dr_state"]
    stubs = {}
    for mod_name in stub_names:
        if mod_name not in sys.modules:
            stub = MagicMock()
            sys.modules[mod_name] = stub
            stubs[mod_name] = stub

    try:
        spec.loader.exec_module(dr_sub)
    finally:
        # stub 모듈 정리
        for mod_name, stub in stubs.items():
            if sys.modules.get(mod_name) is stub:
                del sys.modules[mod_name]

    subprocess_forbidden: set = dr_sub._FORBIDDEN_EXTRA_ENV
    assert subprocess_forbidden <= pe.FORBIDDEN_EXTRA_ENV, (
        f"profile_env.FORBIDDEN_EXTRA_ENV 에 누락된 키: "
        f"{subprocess_forbidden - pe.FORBIDDEN_EXTRA_ENV}"
    )


# ────────────────────────────────────────────
# 신규 forbidden key — PYTHONIOENCODING / PYTHONUTF8 / PYTHONUNBUFFERED
# ────────────────────────────────────────────

def test_build_cli_env_E_forbidden_PYTHONIOENCODING(isolate_profiles):
    """E: extra_env 에 PYTHONIOENCODING → ValueError (파일 직접 쓰기 우회)."""
    import json
    bad_payload = {
        "selected": {"claude": "bad", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "bad", "config_dir": None,
             "extra_env": {"PYTHONIOENCODING": "ascii"}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    isolate_profiles.write_text(json.dumps(bad_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden env key"):
        pe.build_cli_env("claude")


def test_build_cli_env_E_forbidden_PYTHONUTF8(isolate_profiles):
    """E: extra_env 에 PYTHONUTF8 → ValueError."""
    import json
    bad_payload = {
        "selected": {"claude": "bad", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "bad", "config_dir": None,
             "extra_env": {"PYTHONUTF8": "1"}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    isolate_profiles.write_text(json.dumps(bad_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden env key"):
        pe.build_cli_env("claude")


def test_build_cli_env_E_forbidden_PYTHONUNBUFFERED(isolate_profiles):
    """E: extra_env 에 PYTHONUNBUFFERED → ValueError."""
    import json
    bad_payload = {
        "selected": {"claude": "bad", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "bad", "config_dir": None,
             "extra_env": {"PYTHONUNBUFFERED": "1"}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    isolate_profiles.write_text(json.dumps(bad_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden env key"):
        pe.build_cli_env("claude")
