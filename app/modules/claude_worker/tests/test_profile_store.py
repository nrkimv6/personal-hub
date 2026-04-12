"""profile_store.get_by_name 헬퍼 TC (T1/T2)"""

import pytest

from app.modules.claude_worker.services.profile_store import (
    LLM_PROFILES_FILE,
    get_by_name,
    get_selected,
    load_profiles,
    SUPPORTED_ENGINES,
)


@pytest.fixture(autouse=True)
def mock_profile_file(tmp_path, monkeypatch):
    """실제 파일 대신 tmp_path의 프로필 파일을 사용."""
    import app.modules.claude_worker.services.profile_store as ps

    profiles_path = tmp_path / "llm_profiles.json"
    # 테스트용 프로필 데이터 작성
    import json
    profiles_path.write_text(json.dumps({
        "selected": {"claude": "work", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": "/work/claude", "extra_env": {"CLAUDE_KEY": "wk"}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(ps, "LLM_PROFILES_FILE", profiles_path)
    yield


class TestGetByNameRight:
    def test_get_by_name_existing_profile(self):
        """R: 존재하는 프로필 정상 반환"""
        profile = get_by_name("claude", "work")
        assert profile.name == "work"
        assert profile.engine == "claude"
        assert profile.config_dir == "/work/claude"
        assert profile.extra_env == {"CLAUDE_KEY": "wk"}

    def test_get_by_name_default_profile(self):
        """R: default 프로필도 정상 반환"""
        profile = get_by_name("claude", "default")
        assert profile.name == "default"
        assert profile.config_dir is None

    def test_get_by_name_gemini_default(self):
        """R: gemini 엔진 프로필 조회"""
        profile = get_by_name("gemini", "default")
        assert profile.name == "default"
        assert profile.engine == "gemini"


class TestGetByNameError:
    def test_get_by_name_nonexistent_profile(self):
        """E: 존재하지 않는 프로필 이름 → ValueError"""
        with pytest.raises(ValueError, match="not found"):
            get_by_name("claude", "nonexistent")

    def test_get_by_name_unsupported_engine(self):
        """B: SUPPORTED_ENGINES 외 엔진 → ValueError"""
        with pytest.raises(ValueError, match="unsupported engine"):
            get_by_name("codex", "default")

    def test_get_by_name_codex_engine(self):
        """B: codex는 SUPPORTED_ENGINES에 없음 → ValueError"""
        with pytest.raises(ValueError):
            get_by_name("codex", "any")

    def test_get_by_name_empty_name_raises(self):
        """E: 존재하지 않는 이름(빈 문자열) → ValueError"""
        with pytest.raises(ValueError):
            get_by_name("claude", "")
