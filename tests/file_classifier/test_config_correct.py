"""
Config/Settings CORRECT TC
- Existence: 필수 설정 존재 확인
- Conformance: 형식 검증
- Range: 유효 범위 검증
- Reference: save/load 왕복
"""
import pytest
import json
from app.modules.file_classifier.config import (
    FileClassifierSettings,
    validate_settings,
    save_settings_to_file,
    load_settings_from_file,
    settings,
)

class TestConfigExistence:
    """C-Existence: 필수 설정 존재"""
    def test_obsidian_exclude_folders_present(self):
        """EXCLUDE_FOLDERS에 옵시디언 관련 폴더 포함"""
        exclude = settings.EXCLUDE_FOLDERS
        assert ".obsidian" in exclude, ".obsidian 제외 폴더 누락"
        assert ".smart-env" in exclude, ".smart-env 제외 폴더 누락"
        assert ".claude" in exclude, ".claude 제외 폴더 누락"

    def test_system_folders_excluded(self):
        exclude = settings.EXCLUDE_FOLDERS
        assert "node_modules" in exclude
        assert ".git" in exclude
        assert "__pycache__" in exclude

class TestConfigConformance:
    """C-Conformance: 형식 검증"""
    def test_exclude_folders_all_strings(self):
        for folder in settings.EXCLUDE_FOLDERS:
            assert isinstance(folder, str), f"EXCLUDE_FOLDERS 항목 {folder!r}이 문자열이 아님"

    def test_llm_mode_valid_value(self):
        assert settings.LLM_MODE in ("cli", "api"), f"LLM_MODE 유효하지 않음: {settings.LLM_MODE}"

    def test_scan_root_folders_is_list(self):
        assert isinstance(settings.SCAN_ROOT_FOLDERS, list)

class TestConfigRange:
    """C-Range: 유효 범위"""
    def test_max_files_default_positive(self):
        """기본 MAX_FILES_PER_SCAN은 양수"""
        assert settings.MAX_FILES_PER_SCAN > 0

    def test_llm_max_workers_positive_after_validate(self):
        validate_settings()
        assert settings.LLM_MAX_WORKERS > 0

    def test_archive_timeout_positive_after_validate(self):
        validate_settings()
        assert settings.ARCHIVE_TIMEOUT_SECONDS > 0

    def test_validate_corrects_invalid_llm_mode(self):
        """잘못된 LLM_MODE → validate_settings 후 교정"""
        original = settings.LLM_MODE
        settings.LLM_MODE = "invalid_mode"
        validate_settings()
        assert settings.LLM_MODE in ("cli", "api")
        settings.LLM_MODE = original  # 복원

class TestConfigReference:
    """C-Reference: save/load 왕복 일관성"""
    def test_save_load_roundtrip(self, tmp_path):
        """설정 저장 후 로드 → 값 동일"""
        s = FileClassifierSettings(
            SCAN_ROOT_FOLDERS=["D:/test", "C:/docs"],
            MAX_FILES_PER_SCAN=50000,
            LLM_MODE="cli",
            DRY_RUN_DEFAULT=False,
        )
        file_path = str(tmp_path / "test_settings.json")
        s.save_settings_to_file(file_path)

        # JSON 파일 내용 검증
        with open(file_path, encoding="utf-8") as f:
            saved = json.load(f)

        assert saved["SCAN_ROOT_FOLDERS"] == ["D:/test", "C:/docs"]
        assert saved["MAX_FILES_PER_SCAN"] == 50000
        assert saved["LLM_MODE"] == "cli"
        assert saved["DRY_RUN_DEFAULT"] == False

    def test_load_missing_file_no_error(self, tmp_path):
        """없는 파일 로드 → 오류 없음"""
        s = FileClassifierSettings()
        s.load_settings_from_file(str(tmp_path / "nonexistent.json"))
        # 오류 없이 기본값 유지
        assert s.MAX_FILES_PER_SCAN == 100000
