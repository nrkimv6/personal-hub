"""settings_service 유닛 테스트"""

import pytest

from app.modules.dev_runner.services.settings_service import SettingsService
from app.modules.dev_runner.config import config


@pytest.fixture
def svc(tmp_path) -> SettingsService:
    """임시 설정 파일 경로를 사용하는 SettingsService 인스턴스"""
    return SettingsService(settings_file=tmp_path / "dev_runner_settings.json")


def test_settings_get_RIGHT_returns_default(svc):
    """파일 없을 때 config 기본값(MAX_CONCURRENT_RUNNERS) 반환"""
    result = svc.get()
    assert result.max_concurrent_runners == config.MAX_CONCURRENT_RUNNERS
    assert result.default_engine == "claude"
    assert result.default_fix_engine == "claude"
    assert result.updated_at is None


def test_settings_update_RIGHT_saves_and_reads(svc):
    """저장 후 재조회 시 갱신값 반환"""
    svc.update(5)
    result = svc.get()
    assert result.max_concurrent_runners == 5
    assert result.default_engine == "claude"
    assert result.default_fix_engine == "claude"
    assert result.updated_at is not None


def test_settings_update_RIGHT_partial_object_payload(svc):
    """객체 payload 부분 업데이트 시 나머지 필드 유지"""
    svc.update({"max_concurrent_runners": 4, "default_engine": "gemini", "default_fix_engine": "claude"})
    result = svc.update({"default_fix_engine": "codex"})
    assert result.max_concurrent_runners == 4
    assert result.default_engine == "gemini"
    assert result.default_fix_engine == "codex"


def test_settings_update_BOUNDARY_min_value(svc):
    """max_concurrent_runners=1 허용"""
    result = svc.update(1)
    assert result.max_concurrent_runners == 1


def test_settings_update_BOUNDARY_max_value(svc):
    """max_concurrent_runners=10 허용"""
    result = svc.update(10)
    assert result.max_concurrent_runners == 10


def test_settings_update_ERROR_below_min(svc):
    """0 입력 시 ValueError"""
    with pytest.raises(ValueError):
        svc.update(0)


def test_settings_update_ERROR_above_max(svc):
    """11 입력 시 ValueError"""
    with pytest.raises(ValueError):
        svc.update(11)


def test_settings_get_ERROR_corrupted_file(svc, tmp_path):
    """JSON 손상 시 기본값 fallback"""
    settings_file = tmp_path / "dev_runner_settings.json"
    settings_file.write_text("NOT_VALID_JSON", encoding="utf-8")

    result = svc.get()
    assert result.max_concurrent_runners == config.MAX_CONCURRENT_RUNNERS
    assert result.default_engine == "claude"
    assert result.default_fix_engine == "claude"


def test_settings_update_ERROR_invalid_default_engine(svc):
    """지원되지 않는 기본 엔진 입력 시 ValueError"""
    with pytest.raises(ValueError):
        svc.update({"default_engine": "unknown"})
