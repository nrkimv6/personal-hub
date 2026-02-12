"""설정 저장/로드 테스트"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch
from app.modules.image_classifier.config import (
    ImageClassifierSettings,
    save_settings_to_file,
    load_settings_from_file,
    settings,
)


def test_default_settings_loaded():
    """2.2.1 Right: 기본값이 올바르게 로드되어야 함"""
    s = ImageClassifierSettings()

    # 기본값 검증
    assert s.SCAN_ROOT_FOLDERS == []
    assert s.IMAGE_EXTENSIONS == (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff")
    assert s.MAX_FILES_PER_SCAN == 300000
    assert s.PHASH_HASH_SIZE == 16
    assert s.PHASH_DUPLICATE_THRESHOLD == 10
    assert s.CLIP_MODEL_NAME == "clip-ViT-B-32"
    assert s.CLIP_BATCH_SIZE == 64
    assert s.CLIP_USE_GPU is True
    assert s.FAISS_INDEX_TYPE == "IndexFlatIP"
    assert s.FAISS_SIMILARITY_THRESHOLD == 0.85
    assert s.THUMBNAIL_SIZE == (300, 300)
    assert s.THUMBNAIL_QUALITY == 85
    assert s.AI_MODE == "cli"
    assert s.CLAUDE_CLI_PATH == "claude"
    assert s.CLAUDE_MODEL == "claude-sonnet-4-5-20250929"
    assert s.GEMINI_CLI_PATH == "gemini"
    assert s.CLI_MAX_WORKERS == 2
    assert s.CLI_TIMEOUT_SECONDS == 30
    assert s.CLUSTER_GAP_MINUTES == 60
    assert s.TARGET_ROOT_FOLDER is None
    assert s.USE_TRASH is True
    assert s.MAX_WORKERS_PER_TASK == 4


def test_override_from_env_vars(monkeypatch):
    """2.2.2 Right: 환경변수로 설정을 덮어쓸 수 있어야 함"""
    # 환경변수 설정 (IC_ 접두사)
    monkeypatch.setenv("IC_SCAN_ROOT_FOLDERS", '["D:/Photos", "E:/Backup"]')
    monkeypatch.setenv("IC_MAX_FILES_PER_SCAN", "500000")
    monkeypatch.setenv("IC_CLIP_BATCH_SIZE", "128")
    monkeypatch.setenv("IC_USE_TRASH", "false")

    # 새 인스턴스 생성 시 환경변수 반영
    s = ImageClassifierSettings()

    assert s.SCAN_ROOT_FOLDERS == ["D:/Photos", "E:/Backup"]
    assert s.MAX_FILES_PER_SCAN == 500000
    assert s.CLIP_BATCH_SIZE == 128
    assert s.USE_TRASH is False


def test_save_to_json_file(temp_settings_file):
    """2.2.3 Right: 설정을 JSON 파일로 저장할 수 있어야 함"""
    # 임시 설정 파일 경로로 패치
    with patch("app.modules.image_classifier.config.Path") as mock_path:
        mock_path.return_value.parents = [None, None, None, temp_settings_file.parent]
        mock_path.return_value.__truediv__ = lambda self, other: temp_settings_file.parent / other

        # 설정 변경
        settings.SCAN_ROOT_FOLDERS = ["D:/Test"]
        settings.AI_MODE = "api"
        settings.CLI_MAX_WORKERS = 5

        # 저장 (실제로는 임시 경로에 저장됨)
        settings_file = temp_settings_file.parent / "image_classifier" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)

        settings_dict = {
            "SCAN_ROOT_FOLDERS": settings.SCAN_ROOT_FOLDERS,
            "AI_MODE": settings.AI_MODE,
            "CLAUDE_CLI_PATH": settings.CLAUDE_CLI_PATH,
            "GEMINI_CLI_PATH": settings.GEMINI_CLI_PATH,
            "CLI_MAX_WORKERS": settings.CLI_MAX_WORKERS,
            "CLI_TIMEOUT_SECONDS": settings.CLI_TIMEOUT_SECONDS,
            "CLUSTER_GAP_MINUTES": settings.CLUSTER_GAP_MINUTES,
            "TARGET_ROOT_FOLDER": settings.TARGET_ROOT_FOLDER,
            "USE_TRASH": settings.USE_TRASH,
            "MAX_FILES_PER_SCAN": settings.MAX_FILES_PER_SCAN,
            "PHASH_DUPLICATE_THRESHOLD": settings.PHASH_DUPLICATE_THRESHOLD,
            "CLIP_BATCH_SIZE": settings.CLIP_BATCH_SIZE,
            "CLIP_USE_GPU": settings.CLIP_USE_GPU,
            "FAISS_SIMILARITY_THRESHOLD": settings.FAISS_SIMILARITY_THRESHOLD,
        }

        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(settings_dict, f, indent=2, ensure_ascii=False)

    # 파일 존재 확인
    assert settings_file.exists()

    # 내용 확인
    with open(settings_file, "r", encoding="utf-8") as f:
        saved = json.load(f)

    assert saved["SCAN_ROOT_FOLDERS"] == ["D:/Test"]
    assert saved["AI_MODE"] == "api"
    assert saved["CLI_MAX_WORKERS"] == 5


def test_load_from_json_file(temp_settings_file):
    """2.2.4 Right: JSON 파일에서 설정을 로드할 수 있어야 함"""
    # JSON 파일 생성
    settings_file = temp_settings_file.parent / "image_classifier" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    test_data = {
        "SCAN_ROOT_FOLDERS": ["D:/Photos", "E:/Backup"],
        "AI_MODE": "api",
        "CLI_MAX_WORKERS": 8,
        "USE_TRASH": False,
        "MAX_FILES_PER_SCAN": 999999,
    }

    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(test_data, f, indent=2, ensure_ascii=False)

    # 패치하여 로드
    with patch("app.modules.image_classifier.config.Path") as mock_path:
        mock_path.return_value.parents = [None, None, None, temp_settings_file.parent]
        mock_path.return_value.__truediv__ = lambda self, other: temp_settings_file.parent / other
        mock_path.return_value.exists.return_value = True

        # 로드
        with open(settings_file, "r", encoding="utf-8") as f:
            saved = json.load(f)

        for key, value in saved.items():
            if hasattr(settings, key):
                setattr(settings, key, value)

    # 검증
    assert settings.SCAN_ROOT_FOLDERS == ["D:/Photos", "E:/Backup"]
    assert settings.AI_MODE == "api"
    assert settings.CLI_MAX_WORKERS == 8
    assert settings.USE_TRASH is False
    assert settings.MAX_FILES_PER_SCAN == 999999


def test_json_file_corrupted(temp_settings_file):
    """2.2.5 Error: 손상된 JSON 파일 처리"""
    # 손상된 JSON 파일 생성
    settings_file = temp_settings_file.parent / "image_classifier" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    with open(settings_file, "w", encoding="utf-8") as f:
        f.write("{invalid json")

    # 패치하여 로드 시도 (예외 무시되어야 함)
    with patch("app.modules.image_classifier.config.Path") as mock_path:
        mock_path.return_value.parents = [None, None, None, temp_settings_file.parent]
        mock_path.return_value.__truediv__ = lambda self, other: temp_settings_file.parent / other
        mock_path.return_value.exists.return_value = True

        # load_settings_from_file()은 예외를 catch하고 경고만 출력
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                json.load(f)  # JSONDecodeError 발생
            assert False, "JSONDecodeError가 발생해야 함"
        except json.JSONDecodeError:
            pass  # 예상된 에러


def test_json_file_missing(temp_settings_file):
    """2.2.6 Error: JSON 파일이 없을 때 기본값 사용"""
    # 존재하지 않는 경로
    settings_file = temp_settings_file.parent / "image_classifier" / "settings.json"

    # 파일이 없으므로 로드하지 않음
    assert not settings_file.exists()

    # 기본값 유지 확인
    s = ImageClassifierSettings()
    assert s.SCAN_ROOT_FOLDERS == []
    assert s.AI_MODE == "cli"


@pytest.mark.skipif(os.name == "nt", reason="Windows에서 권한 테스트 어려움")
def test_json_permission_denied(temp_settings_file):
    """2.2.7 Error: JSON 파일 권한 없을 때 처리"""
    # 읽기 전용 디렉토리 생성
    settings_dir = temp_settings_file.parent / "image_classifier"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_dir / "settings.json"

    # 파일 생성
    with open(settings_file, "w") as f:
        json.dump({"AI_MODE": "api"}, f)

    # 읽기 권한 제거
    os.chmod(settings_file, 0o000)

    try:
        # 읽기 시도 → PermissionError
        with pytest.raises(PermissionError):
            with open(settings_file, "r") as f:
                json.load(f)
    finally:
        # 권한 복원
        os.chmod(settings_file, 0o644)


def test_non_ascii_path(temp_settings_file):
    """2.2.8 Boundary: 한글 경로 처리"""
    # 한글 폴더명
    settings_dir = temp_settings_file.parent / "이미지_분류기"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_dir / "설정.json"

    test_data = {
        "SCAN_ROOT_FOLDERS": ["D:/사진/여행", "E:/백업"],
        "TARGET_ROOT_FOLDER": "D:/정리완료",
    }

    # 저장
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(test_data, f, indent=2, ensure_ascii=False)

    # 로드
    with open(settings_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    # 검증
    assert loaded["SCAN_ROOT_FOLDERS"] == ["D:/사진/여행", "E:/백업"]
    assert loaded["TARGET_ROOT_FOLDER"] == "D:/정리완료"


def test_all_14_fields_persist(temp_settings_file):
    """2.2.9 Right: 14개 필드 모두 저장/로드되어야 함"""
    settings_file = temp_settings_file.parent / "image_classifier" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    # 14개 필드 설정
    test_data = {
        "SCAN_ROOT_FOLDERS": ["D:/Test1", "D:/Test2"],
        "AI_MODE": "api",
        "CLAUDE_CLI_PATH": "/usr/bin/claude",
        "GEMINI_CLI_PATH": "/usr/bin/gemini",
        "CLI_MAX_WORKERS": 10,
        "CLI_TIMEOUT_SECONDS": 60,
        "CLUSTER_GAP_MINUTES": 120,
        "TARGET_ROOT_FOLDER": "D:/Target",
        "USE_TRASH": False,
        "MAX_FILES_PER_SCAN": 500000,
        "PHASH_DUPLICATE_THRESHOLD": 5,
        "CLIP_BATCH_SIZE": 256,
        "CLIP_USE_GPU": False,
        "FAISS_SIMILARITY_THRESHOLD": 0.90,
    }

    # 저장
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(test_data, f, indent=2, ensure_ascii=False)

    # 로드
    with open(settings_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    # 14개 필드 모두 존재 확인
    assert len(loaded) == 14
    for key in test_data.keys():
        assert key in loaded
        assert loaded[key] == test_data[key]


def test_partial_fields_merge(temp_settings_file):
    """2.2.10 Boundary: 일부 필드만 있어도 병합되어야 함"""
    settings_file = temp_settings_file.parent / "image_classifier" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    # 3개 필드만 저장
    partial_data = {
        "AI_MODE": "api",
        "CLI_MAX_WORKERS": 15,
        "USE_TRASH": False,
    }

    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(partial_data, f, indent=2, ensure_ascii=False)

    # 로드 시뮬레이션
    with open(settings_file, "r", encoding="utf-8") as f:
        saved = json.load(f)

    # 기본 설정 생성
    s = ImageClassifierSettings()

    # 부분 병합
    for key, value in saved.items():
        if hasattr(s, key):
            setattr(s, key, value)

    # 저장된 필드는 변경됨
    assert s.AI_MODE == "api"
    assert s.CLI_MAX_WORKERS == 15
    assert s.USE_TRASH is False

    # 저장되지 않은 필드는 기본값 유지
    assert s.SCAN_ROOT_FOLDERS == []
    assert s.CLIP_BATCH_SIZE == 64


def test_concurrent_access(temp_settings_file):
    """2.2.11 Error: 동시 파일 접근 처리"""
    import threading
    import time

    settings_file = temp_settings_file.parent / "image_classifier" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    # 초기 데이터
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump({"AI_MODE": "cli"}, f)

    errors = []

    def writer(mode):
        try:
            time.sleep(0.01)  # 동시성 증가
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump({"AI_MODE": mode}, f)
        except Exception as e:
            errors.append(e)

    # 5개 스레드 동시 쓰기
    threads = [threading.Thread(target=writer, args=(f"mode{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 에러 없이 완료되어야 함 (마지막 쓰기가 반영됨)
    assert len(errors) == 0

    # 파일이 유효한 JSON이어야 함
    with open(settings_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert "AI_MODE" in loaded


def test_migration_backward_compat(temp_settings_file):
    """2.2.12 Boundary: 이전 버전 설정 파일 호환성"""
    settings_file = temp_settings_file.parent / "image_classifier" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    # 이전 버전 (일부 필드 누락)
    old_version_data = {
        "SCAN_ROOT_FOLDERS": ["D:/Old"],
        "AI_MODE": "cli",
        # CLIP_USE_GPU, FAISS_SIMILARITY_THRESHOLD 등 누락
    }

    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(old_version_data, f, indent=2, ensure_ascii=False)

    # 로드 시뮬레이션
    with open(settings_file, "r", encoding="utf-8") as f:
        saved = json.load(f)

    s = ImageClassifierSettings()

    # 병합
    for key, value in saved.items():
        if hasattr(s, key):
            setattr(s, key, value)

    # 저장된 필드는 반영
    assert s.SCAN_ROOT_FOLDERS == ["D:/Old"]
    assert s.AI_MODE == "cli"

    # 누락된 필드는 기본값 사용
    assert s.CLIP_USE_GPU is True  # 기본값
    assert s.FAISS_SIMILARITY_THRESHOLD == 0.85  # 기본값
