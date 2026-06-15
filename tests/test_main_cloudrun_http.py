"""app/main_cloudrun.py TestClient HTTP 통합 테스트 — *_http.py 패턴 준수."""
import pytest
from fastapi.testclient import TestClient

from app.main_cloudrun import app


class TestCloudRunHTTP:

    def test_root_http_200(self):
        """GET / → 200 + {"status": "ok", "version": "poc"} body assert"""
        with TestClient(app) as client:
            response = client.get("/")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["version"] == "poc"

    def test_healthz_http_200(self):
        """GET /healthz → 200 + {"healthy": True} body assert"""
        with TestClient(app) as client:
            response = client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["healthy"] is True
