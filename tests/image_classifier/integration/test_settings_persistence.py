"""통합 테스트 Scenario 6: 설정 영속성

설정 저장 (스캔 폴더, AI 모드) → API 재시작 시뮬레이션
→ 설정 로드 → 이전 값 복원 확인
"""
import json
import pytest
from pathlib import Path


def test_settings_save_reload_cycle(tmp_path):
    """설정 저장 → 재로드 → 값 복원 확인"""
    from app.modules.image_classifier.config import ImageClassifierSettings

    settings_file = tmp_path / "settings.json"

    # 1. 기본 설정 생성 및 변경
    settings = ImageClassifierSettings()
    settings.SCAN_ROOT_FOLDERS = ["D:/Photos", "E:/사진"]
    settings.AI_MODE = "gemini_cli"
    settings.CLUSTER_GAP_MINUTES = 120
    settings.PHASH_DUPLICATE_THRESHOLD = 8
    settings.TARGET_ROOT_FOLDER = "D:/정리된사진"
    settings.CLI_MAX_WORKERS = 4

    # 2. 저장
    settings.save_settings_to_file(str(settings_file))
    assert settings_file.exists()

    # 저장된 JSON 확인
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["SCAN_ROOT_FOLDERS"] == ["D:/Photos", "E:/사진"]
    assert saved["AI_MODE"] == "gemini_cli"

    # 3. 새 인스턴스에서 로드 (API 재시작 시뮬레이션)
    new_settings = ImageClassifierSettings()
    assert new_settings.SCAN_ROOT_FOLDERS == []  # 기본값

    new_settings.load_settings_from_file(str(settings_file))

    # 4. 복원 확인
    assert new_settings.SCAN_ROOT_FOLDERS == ["D:/Photos", "E:/사진"]
    assert new_settings.AI_MODE == "gemini_cli"
    assert new_settings.CLUSTER_GAP_MINUTES == 120
    assert new_settings.PHASH_DUPLICATE_THRESHOLD == 8
    assert new_settings.TARGET_ROOT_FOLDER == "D:/정리된사진"
    assert new_settings.CLI_MAX_WORKERS == 4


def test_settings_partial_update_preserves_others(tmp_path):
    """일부 필드만 변경해도 나머지 유지"""
    from app.modules.image_classifier.config import ImageClassifierSettings

    settings_file = tmp_path / "settings.json"

    # 1. 전체 설정 저장
    s1 = ImageClassifierSettings()
    s1.SCAN_ROOT_FOLDERS = ["D:/Photos"]
    s1.AI_MODE = "claude_cli"
    s1.CLUSTER_GAP_MINUTES = 90
    s1.save_settings_to_file(str(settings_file))

    # 2. 다른 인스턴스에서 일부만 변경 후 재저장
    s2 = ImageClassifierSettings()
    s2.load_settings_from_file(str(settings_file))
    s2.AI_MODE = "gemini_cli"  # 이것만 변경
    s2.save_settings_to_file(str(settings_file))

    # 3. 다시 로드
    s3 = ImageClassifierSettings()
    s3.load_settings_from_file(str(settings_file))

    assert s3.AI_MODE == "gemini_cli"  # 변경됨
    assert s3.SCAN_ROOT_FOLDERS == ["D:/Photos"]  # 유지
    assert s3.CLUSTER_GAP_MINUTES == 90  # 유지


def test_settings_corrupted_file_fallback(tmp_path):
    """손상된 설정 파일 → 기본값 유지"""
    from app.modules.image_classifier.config import ImageClassifierSettings

    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{{invalid json", encoding="utf-8")

    settings = ImageClassifierSettings()
    settings.load_settings_from_file(str(settings_file))

    # 기본값 유지 (에러 없이)
    assert settings.SCAN_ROOT_FOLDERS == []
    assert settings.AI_MODE == "cli"
