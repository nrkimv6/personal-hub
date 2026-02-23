"""파일 분류기 통계 API 테스트"""

import pytest


def test_stats_empty(client):
    """데이터 없을 때 통계"""
    res = client.get("/api/fc/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_files"] == 0
    assert data["total_size"] == 0
    assert data["by_group"] == []
    assert data["by_status"] == []


def test_stats_with_data(seeded_client):
    """시드 데이터 통계"""
    res = seeded_client.get("/api/fc/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_files"] == 6
    # file_group별 통계
    groups = {g["file_group"]: g["count"] for g in data["by_group"]}
    assert groups["music"] == 1
    assert groups["archive"] == 1
    assert groups["document"] == 1
    assert groups["installer"] == 1
    assert groups["game"] == 1
    assert groups["misc"] == 1


def test_pipeline_stats(client):
    """파이프라인 통계"""
    res = client.get("/api/fc/stats/pipeline")
    assert res.status_code == 200
    data = res.json()
    assert "total_files" in data
    assert "pipeline_stages" in data
    assert "recent_tasks" in data
    # 8개 파이프라인 단계 확인
    stages = [s["status"] for s in data["pipeline_stages"]]
    assert "pending" in stages
    assert "moved" in stages
