"""파일 분류기 파일 목록 API 테스트"""

import pytest


def test_files_empty(client):
    """데이터 없을 때 빈 목록"""
    res = client.get("/api/fc/files")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_files_list(seeded_client):
    """시드 데이터 목록 조회"""
    res = seeded_client.get("/api/fc/files")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 6
    assert len(data["items"]) == 6


def test_files_filter_by_group(seeded_client):
    """file_group 필터"""
    res = seeded_client.get("/api/fc/files?file_group=music")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["file_group"] == "music"


def test_files_filter_by_extension(seeded_client):
    """extension 필터"""
    res = seeded_client.get("/api/fc/files?extension=.zip")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["extension"] == ".zip"


def test_files_search(seeded_client):
    """파일명 검색"""
    res = seeded_client.get("/api/fc/files?search=report")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any("report" in item["file_name"] for item in data["items"])


def test_files_pagination(seeded_client):
    """페이지네이션"""
    res = seeded_client.get("/api/fc/files?page=1&page_size=2")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) <= 2
    assert data["page_size"] == 2
    assert data["total_pages"] >= 3


def test_file_detail(seeded_client):
    """파일 상세 조회"""
    # 먼저 목록에서 ID 가져오기
    list_res = seeded_client.get("/api/fc/files?file_group=music")
    file_id = list_res.json()["items"][0]["id"]

    res = seeded_client.get(f"/api/fc/files/{file_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == file_id
    assert data["file_group"] == "music"


def test_file_not_found(client):
    """존재하지 않는 파일"""
    res = client.get("/api/fc/files/99999")
    assert res.status_code == 404
