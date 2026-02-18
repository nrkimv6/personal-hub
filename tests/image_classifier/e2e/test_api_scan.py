"""스캔 API 엔드포인트 테스트"""
import pytest


# ================================================
# Right: 기본 동작
# ================================================

def test_get_scan_status_initial(client):
    """1.1 Right: GET /scan/status → 초기 상태 (idle/stopped)"""
    response = client.get("/api/ic/scan/status")

    assert response.status_code == 200
    data = response.json()

    # 초기 상태 확인
    assert "is_running" in data
    assert "total_folders" in data
    assert "scanned_folders" in data
    assert "total_files" in data
    assert "scanned_files" in data
    assert "progress_percent" in data
    assert "current_folder" in data
    assert "error" in data

    # 초기값
    assert data["is_running"] is False
    assert data["progress_percent"] == 0.0


def test_get_folders_list_empty(client):
    """1.2 Right: GET /scan/folders → 빈 폴더 목록"""
    response = client.get("/api/ic/scan/folders")

    assert response.status_code == 200
    data = response.json()

    assert "folders" in data
    assert "skip" in data
    assert "limit" in data
    assert "total" in data

    # 초기에는 빈 목록
    assert data["folders"] == []
    assert data["skip"] == 0
    assert data["limit"] == 100
    assert data["total"] == 0


def test_get_folders_with_pagination(client, seeded_db):
    """1.3 Right: GET /scan/folders?skip=1&limit=2 → 페이지네이션"""
    response = client.get("/api/ic/scan/folders?skip=1&limit=2")

    assert response.status_code == 200
    data = response.json()

    assert data["skip"] == 1
    assert data["limit"] == 2
    assert len(data["folders"]) <= 2


def test_get_folders_filter_by_status(client, seeded_db):
    """1.4 Right: GET /scan/folders?folder_status=unknown → 필터링"""
    response = client.get("/api/ic/scan/folders?folder_status=unknown")

    assert response.status_code == 200
    data = response.json()

    # 모든 폴더가 unknown 상태여야 함
    for folder in data["folders"]:
        assert folder["folder_status"] == "unknown"


# ================================================
# Boundary: 경계값 테스트
# ================================================

def test_start_scan_no_folders_configured(client, monkeypatch):
    """2.1 Boundary: POST /scan/start (폴더 미설정) → 400 에러"""
    from app.modules.image_classifier.config import settings

    # settings.SCAN_ROOT_FOLDERS를 빈 리스트로 설정
    monkeypatch.setattr(settings, "SCAN_ROOT_FOLDERS", [])

    response = client.post("/api/ic/scan/start", json={})

    assert response.status_code == 400
    assert "스캔 대상 폴더가 설정되지 않았습니다" in response.json()["detail"]


def test_start_scan_with_explicit_folders(client, tmp_path, monkeypatch):
    """2.2 Boundary: POST /scan/start {root_folders: [...]} → 명시적 폴더 지정"""
    from app.modules.image_classifier.config import settings
    monkeypatch.setattr(settings, "SCAN_ROOT_FOLDERS", [])

    # 임시 폴더 생성
    test_folder = tmp_path / "test_scan"
    test_folder.mkdir()

    response = client.post("/api/ic/scan/start", json={
        "root_folders": [str(test_folder)]
    })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "started"
    assert str(test_folder) in data["root_folders"]


def test_get_folders_pagination_edge_case(client, seeded_db):
    """2.3 Boundary: skip > total → 빈 목록"""
    response = client.get("/api/ic/scan/folders?skip=1000&limit=10")

    assert response.status_code == 200
    data = response.json()

    # skip이 전체 개수보다 크면 빈 목록
    assert data["folders"] == []


# ================================================
# Error: 오류 케이스
# ================================================

def test_start_scan_invalid_params(client):
    """3.1 Error: POST /scan/start {root_folders: "string"} → 422"""
    response = client.post("/api/ic/scan/start", json={
        "root_folders": "not_a_list"
    })

    # Pydantic validation error
    assert response.status_code == 422


def test_start_scan_while_running(client, tmp_path, monkeypatch):
    """3.2 Error: POST /scan/start (이미 실행 중) → 409"""
    from app.modules.image_classifier.config import settings
    from app.modules.image_classifier.routers.scan import scan_state

    monkeypatch.setattr(settings, "SCAN_ROOT_FOLDERS", [])

    # 스캔 상태를 실행 중으로 설정
    scan_state["is_running"] = True

    test_folder = tmp_path / "test_scan"
    test_folder.mkdir()

    response = client.post("/api/ic/scan/start", json={
        "root_folders": [str(test_folder)]
    })

    assert response.status_code == 409
    assert "이미 실행 중" in response.json()["detail"]

    # 원복
    scan_state["is_running"] = False


def test_get_folders_invalid_status_filter(client):
    """3.3 Error: GET /scan/folders?folder_status=invalid → 빈 목록 (검증 없음)"""
    response = client.get("/api/ic/scan/folders?folder_status=invalid_status")

    assert response.status_code == 200
    data = response.json()

    # 현재는 검증 없이 쿼리만 실행하므로 빈 목록
    assert data["folders"] == []
