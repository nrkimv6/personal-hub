"""profile_store.py 단위 테스트."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import app.modules.claude_worker.services.profile_store as ps


# ────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_profiles_file(tmp_path, monkeypatch):
    """각 테스트가 독립 profiles 파일을 사용하도록 monkeypatch."""
    profiles_path = tmp_path / "llm_profiles.json"
    monkeypatch.setattr(ps, "LLM_PROFILES_FILE", profiles_path)
    yield profiles_path


# ────────────────────────────────────────────
# load_profiles
# ────────────────────────────────────────────

def test_load_profiles_R_default_when_missing(isolate_profiles_file):
    """R: 파일 없을 때 default profile 2개(claude/gemini) 반환, 파일 생성 안 함."""
    result = ps.load_profiles()
    assert not isolate_profiles_file.exists(), "파일이 생성되어서는 안 됨"
    profile_engines = [p["engine"] for p in result["profiles"]]
    assert "claude" in profile_engines
    assert "gemini" in profile_engines
    assert result["selected"]["claude"] == "default"
    assert result["selected"]["gemini"] == "default"


# ────────────────────────────────────────────
# save_profiles / roundtrip
# ────────────────────────────────────────────

def test_save_profiles_R_roundtrip(isolate_profiles_file):
    """R: 저장 후 재로드 시 동일 값."""
    payload = {
        "selected": {"claude": "work", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": "C:/tmp/.claude-work", "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    saved = ps.save_profiles(payload)
    loaded = ps.load_profiles()
    assert loaded["selected"]["claude"] == "work"
    assert any(p["name"] == "work" and p["config_dir"] == "C:/tmp/.claude-work" for p in loaded["profiles"])


def test_save_profiles_B_empty_name(isolate_profiles_file):
    """B: 빈 이름 → ValueError."""
    payload = {
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [{"engine": "claude", "name": "", "config_dir": None, "extra_env": {}}],
    }
    with pytest.raises(ValueError, match="empty profile name"):
        ps.save_profiles(payload)


def test_save_profiles_B_whitespace_name(isolate_profiles_file):
    """B: 공백만 이름 → ValueError."""
    payload = {
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [{"engine": "claude", "name": "   ", "config_dir": None, "extra_env": {}}],
    }
    with pytest.raises(ValueError, match="empty profile name"):
        ps.save_profiles(payload)


def test_save_profiles_E_duplicate_name_in_same_engine(isolate_profiles_file):
    """E: 같은 engine 내 name 중복 → ValueError."""
    payload = {
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    with pytest.raises(ValueError, match="duplicate"):
        ps.save_profiles(payload)


# ────────────────────────────────────────────
# select
# ────────────────────────────────────────────

def _init_two_profiles(isolate_profiles_file):
    ps.save_profiles({
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": "C:/work/.claude", "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    })


def test_select_profile_R_valid(isolate_profiles_file):
    """R: 정상 선택 전환."""
    _init_two_profiles(isolate_profiles_file)
    saved = ps.select("claude", "work")
    assert saved["selected"]["claude"] == "work"


def test_select_profile_E_unknown_engine(isolate_profiles_file):
    """E: 미지원 engine → ValueError."""
    with pytest.raises(ValueError, match="unsupported engine"):
        ps.select("codex", "default")


def test_select_profile_E_unknown_name(isolate_profiles_file):
    """E: 존재하지 않는 name → ValueError."""
    _init_two_profiles(isolate_profiles_file)
    with pytest.raises(ValueError, match="not found"):
        ps.select("claude", "nonexistent")


# ────────────────────────────────────────────
# delete
# ────────────────────────────────────────────

def test_delete_profile_R_selected_fallback_to_default(isolate_profiles_file):
    """R: selected 이던 profile 삭제 시 default 로 fallback."""
    ps.save_profiles({
        "selected": {"claude": "work", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": "C:/work", "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    })
    saved = ps.delete("claude", "work")
    assert saved["selected"]["claude"] == "default"
    names = [p["name"] for p in saved["profiles"] if p["engine"] == "claude"]
    assert "work" not in names


def test_delete_profile_R_last_profile_fallback(isolate_profiles_file):
    """R: default 도 없을 때 첫 번째 profile 로 fallback."""
    ps.save_profiles({
        "selected": {"claude": "only", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "only", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "another", "config_dir": None, "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    })
    saved = ps.delete("claude", "only")
    remaining = [p["name"] for p in saved["profiles"] if p["engine"] == "claude"]
    assert saved["selected"]["claude"] in remaining


def test_save_profiles_Co_write_json_atomic_called(isolate_profiles_file):
    """Co: 저장이 write_json_atomic 사용 확인."""
    with patch("app.modules.claude_worker.services.profile_store.write_json_atomic",
               wraps=ps.write_json_atomic) as mock_write:
        ps.save_profiles({
            "selected": {"claude": "default", "gemini": "default"},
            "profiles": [
                {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
                {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
            ],
        })
        mock_write.assert_called_once()
