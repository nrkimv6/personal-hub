"""파일 분류기 스캔 API 테스트"""

import pytest


def test_scan_status_not_running(client):
    """초기 상태: 스캔 안 함"""
    res = client.get("/api/fc/scan/status")
    assert res.status_code == 200
    data = res.json()
    assert data["is_running"] is False


def test_scan_stop_when_not_running(client):
    """스캔 중이 아닐 때 stop 요청"""
    res = client.post("/api/fc/scan/stop")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "not_running"


def test_scan_start_no_folders(client):
    """폴더 미지정 + settings 비어있으면 에러"""
    from app.modules.file_classifier import config as fc_config
    fc_config.settings.SCAN_ROOT_FOLDERS = []

    res = client.post("/api/fc/scan/start", json={"root_folders": []})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
