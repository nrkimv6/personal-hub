"""
시스템 메모리 API e2e 테스트

실제 psutil을 사용하여 GET /api/v1/system/memory 호출 및 스키마 검증
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestSystemMemoryE2E:
    """실제 시스템 데이터로 엔드포인트 검증"""

    def test_endpoint_returns_200(self):
        """200 응답 확인"""
        resp = client.get("/api/v1/system/memory")
        assert resp.status_code == 200

    def test_schema_structure(self):
        """응답 스키마 구조 완전 검증"""
        resp = client.get("/api/v1/system/memory")
        data = resp.json()

        # 최상위 필드
        assert set(data.keys()) >= {"ram", "pagefile", "top_processes", "danger_level"}

        # RAM
        ram = data["ram"]
        assert isinstance(ram["total_mb"], (int, float)) and ram["total_mb"] > 0
        assert isinstance(ram["used_mb"], (int, float)) and ram["used_mb"] >= 0
        assert isinstance(ram["available_mb"], (int, float)) and ram["available_mb"] >= 0
        assert isinstance(ram["percent"], (int, float))
        assert 0 <= ram["percent"] <= 100

        # PageFile
        pf = data["pagefile"]
        assert isinstance(pf["total_mb"], (int, float))
        assert isinstance(pf["used_mb"], (int, float))
        assert isinstance(pf["free_mb"], (int, float))
        assert isinstance(pf["percent"], (int, float))

        # danger_level
        assert data["danger_level"] in ("normal", "warning", "critical")

        # top_processes
        procs = data["top_processes"]
        assert isinstance(procs, list)
        assert len(procs) <= 15
        for p in procs:
            assert "name" in p
            assert "pid" in p
            assert "working_set_mb" in p
            assert "count" in p
            assert isinstance(p["count"], int) and p["count"] >= 1
            assert isinstance(p["working_set_mb"], (int, float)) and p["working_set_mb"] >= 0

    def test_processes_sorted_desc(self):
        """프로세스가 메모리 내림차순인지 확인"""
        resp = client.get("/api/v1/system/memory")
        procs = resp.json()["top_processes"]
        if len(procs) > 1:
            mbs = [p["working_set_mb"] for p in procs]
            assert mbs == sorted(mbs, reverse=True)
