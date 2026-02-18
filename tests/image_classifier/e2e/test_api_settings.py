"""설정 API 엔드포인트 테스트"""
import pytest


# ================================================
# Right: 기본 CRUD 동작
# ================================================

def test_get_settings_returns_all_fields(client):
    """1.1 Right: GET /settings → 모든 필드 존재"""
    response = client.get("/api/ic/settings")

    assert response.status_code == 200
    data = response.json()

    # 필수 필드 존재 확인
    required_fields = [
        "scan_root_folders",
        "image_extensions",
        "max_files_per_scan",
        "phash_hash_size",
        "phash_duplicate_threshold",
        "clip_model_name",
        "clip_batch_size",
        "clip_use_gpu",
        "faiss_similarity_threshold",
        "thumbnail_size",
        "thumbnail_quality",
        "ai_mode",
        "claude_cli_path",
        "gemini_cli_path",
        "cli_max_workers",
        "cli_timeout_seconds",
        "cluster_gap_minutes",
        "target_root_folder",
        "use_trash",
        "max_workers_per_task"
    ]

    for field in required_fields:
        assert field in data, f"필드 {field} 누락"


def test_update_settings_partial(client):
    """1.2 Right: PUT /settings (일부 필드만) → 해당 필드만 변경"""
    # 초기값 확인
    initial = client.get("/api/ic/settings").json()

    # 일부 필드만 업데이트
    response = client.put("/api/ic/settings", json={
        "cli_max_workers": 5,
        "cluster_gap_minutes": 120
    })

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "ok"

    # 업데이트된 값 확인
    updated = client.get("/api/ic/settings").json()
    assert updated["cli_max_workers"] == 5
    assert updated["cluster_gap_minutes"] == 120

    # 나머지 필드는 변경 안 됨
    assert updated["max_files_per_scan"] == initial["max_files_per_scan"]
    assert updated["ai_mode"] == initial["ai_mode"]


def test_update_settings_full(client):
    """1.3 Right: PUT /settings (전체 필드) → 전체 변경"""
    response = client.put("/api/ic/settings", json={
        "scan_root_folders": ["D:\\Test1", "D:\\Test2"],
        "max_files_per_scan": 100000,
        "phash_duplicate_threshold": 15,
        "clip_batch_size": 32,
        "clip_use_gpu": False,
        "faiss_similarity_threshold": 0.9,
        "ai_mode": "api",
        "cli_max_workers": 3,
        "cli_timeout_seconds": 60,
        "cluster_gap_minutes": 90,
        "target_root_folder": "D:\\Archive",
        "use_trash": False
    })

    assert response.status_code == 200

    updated = client.get("/api/ic/settings").json()
    assert updated["scan_root_folders"] == ["D:\\Test1", "D:\\Test2"]
    assert updated["max_files_per_scan"] == 100000
    assert updated["phash_duplicate_threshold"] == 15
    assert updated["clip_batch_size"] == 32
    assert updated["clip_use_gpu"] is False
    assert updated["faiss_similarity_threshold"] == 0.9
    assert updated["ai_mode"] == "api"
    assert updated["cli_max_workers"] == 3
    assert updated["cli_timeout_seconds"] == 60
    assert updated["cluster_gap_minutes"] == 90
    assert updated["target_root_folder"] == "D:\\Archive"
    assert updated["use_trash"] is False


def test_get_settings_after_update(client):
    """1.4 Right: PUT → GET → 값 반영 확인"""
    # 업데이트
    client.put("/api/ic/settings", json={
        "cli_max_workers": 4,
        "use_trash": True
    })

    # 재조회
    response = client.get("/api/ic/settings")
    data = response.json()

    assert data["cli_max_workers"] == 4
    assert data["use_trash"] is True


# ================================================
# Boundary: 경계값 테스트
# ================================================

def test_update_empty_body(client):
    """2.1 Boundary: PUT {} → 기존 값 유지"""
    initial = client.get("/api/ic/settings").json()

    response = client.put("/api/ic/settings", json={})
    assert response.status_code == 200

    # 값 변경 안 됨
    after = client.get("/api/ic/settings").json()
    assert after == initial


def test_update_with_none_values(client):
    """2.2 Boundary: PUT {field: None} → None은 업데이트 스킵"""
    # 먼저 값을 설정
    client.put("/api/ic/settings", json={
        "target_root_folder": "D:\\Test"
    })

    initial = client.get("/api/ic/settings").json()

    # None으로 요청 (업데이트 스킵)
    response = client.put("/api/ic/settings", json={
        "target_root_folder": None
    })

    assert response.status_code == 200

    # None은 업데이트를 스킵하므로 이전 값 유지
    updated = client.get("/api/ic/settings").json()
    # API 구현: if request.field is not None: settings.FIELD = request.field
    # 따라서 None 전달 시 업데이트 안 됨
    assert updated["target_root_folder"] == initial["target_root_folder"]


def test_update_scan_folders_empty_list(client):
    """2.3 Boundary: PUT {scan_root_folders: []} → 빈 리스트 허용"""
    response = client.put("/api/ic/settings", json={
        "scan_root_folders": []
    })

    assert response.status_code == 200

    updated = client.get("/api/ic/settings").json()
    assert updated["scan_root_folders"] == []


def test_update_threshold_min_max(client):
    """2.4 Boundary: 경계값 (0, 1.0 등)"""
    # 최소값
    response = client.put("/api/ic/settings", json={
        "faiss_similarity_threshold": 0.0,
        "phash_duplicate_threshold": 0
    })
    assert response.status_code == 200

    updated = client.get("/api/ic/settings").json()
    assert updated["faiss_similarity_threshold"] == 0.0
    assert updated["phash_duplicate_threshold"] == 0

    # 최대값
    response = client.put("/api/ic/settings", json={
        "faiss_similarity_threshold": 1.0,
        "phash_duplicate_threshold": 64
    })
    assert response.status_code == 200

    updated = client.get("/api/ic/settings").json()
    assert updated["faiss_similarity_threshold"] == 1.0
    assert updated["phash_duplicate_threshold"] == 64


# ================================================
# Error: 오류 케이스
# ================================================

def test_update_invalid_ai_mode(client):
    """3.1 Error: PUT {ai_mode: "invalid"} → 무시 또는 에러"""
    initial = client.get("/api/ic/settings").json()

    # 잘못된 ai_mode
    response = client.put("/api/ic/settings", json={
        "ai_mode": "invalid_mode"
    })

    # 현재는 검증 없이 저장되므로 200 (향후 validation 추가 시 422로 변경 가능)
    assert response.status_code == 200

    updated = client.get("/api/ic/settings").json()
    assert updated["ai_mode"] == "invalid_mode"


def test_update_negative_workers(client):
    """3.2 Error: PUT {cli_max_workers: -1} → 음수 허용 여부"""
    response = client.put("/api/ic/settings", json={
        "cli_max_workers": -1
    })

    # 현재는 검증 없이 저장되므로 200
    assert response.status_code == 200

    updated = client.get("/api/ic/settings").json()
    assert updated["cli_max_workers"] == -1


def test_update_invalid_type(client):
    """3.3 Error: PUT {max_files_per_scan: "abc"} → 422"""
    response = client.put("/api/ic/settings", json={
        "max_files_per_scan": "abc"
    })

    # Pydantic validation error
    assert response.status_code == 422


# ================================================
# CrossCheck: 교차 검증
# ================================================

def test_settings_match_config_defaults(client, test_db):
    """4.1 CrossCheck: 변경 가능한 필드는 실제로 업데이트됨"""
    from app.modules.image_classifier.config import ImageClassifierSettings

    # 새 인스턴스 (기본값)
    default_settings = ImageClassifierSettings()

    # API 응답
    response = client.get("/api/ic/settings")
    api_settings = response.json()

    # 변경 불가능한 필드는 항상 기본값
    assert api_settings["phash_hash_size"] == default_settings.PHASH_HASH_SIZE
    assert api_settings["clip_model_name"] == default_settings.CLIP_MODEL_NAME
    assert api_settings["thumbnail_size"] == list(default_settings.THUMBNAIL_SIZE)
    assert api_settings["thumbnail_quality"] == default_settings.THUMBNAIL_QUALITY

    # 변경 가능한 필드는 이전 테스트에서 변경되었을 수 있음
    # 타입만 확인
    assert isinstance(api_settings["max_files_per_scan"], int)
    assert isinstance(api_settings["ai_mode"], str)
    assert isinstance(api_settings["cli_max_workers"], int)
