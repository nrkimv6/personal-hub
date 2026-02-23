"""파일 분류기 헬스체크 API 테스트"""

import pytest


def test_health_ok(client):
    """헬스체크 정상 응답"""
    res = client.get("/api/fc/health")
    assert res.status_code == 200
    data = res.json()
    assert data["module"] == "file_classifier"
    assert data["version"] == "0.1.0"
    assert data["database"] == "ok"
    # 주요 테이블 확인
    for table in ["fc_files", "fc_categories", "fc_rules", "fc_task_progress"]:
        assert data["tables"][table] == "ok"


def test_diagnostic(client):
    """진단 엔드포인트"""
    res = client.get("/api/fc/diagnostic")
    assert res.status_code == 200
    data = res.json()
    assert "overall" in data
    assert "modules" in data
    assert "settings" in data["modules"]
    assert "database" in data["modules"]
    assert "scan" in data["modules"]
