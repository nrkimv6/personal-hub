"""app/main_cloudrun.py 단위 테스트 — RIGHT-BICEP."""
import pathlib
import pytest
from fastapi.testclient import TestClient

from app.main_cloudrun import app


class TestCloudRunEntrypoint:

    def test_root_returns_200_with_status_ok(self):
        """R: GET / → 200 + {"status": "ok", "version": "poc"}"""
        with TestClient(app) as client:
            response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": "poc"}

    def test_healthz_returns_200_with_healthy_true(self):
        """R: GET /healthz → 200 + {"healthy": True}"""
        with TestClient(app) as client:
            response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"healthy": True}

    def test_app_title_is_poc(self):
        """C: FastAPI app title 확인"""
        assert app.title == "personal-hub Cloud Run PoC"

    def test_no_router_registry_import(self):
        """I: main_cloudrun.py에 router_registry import 0건"""
        src = pathlib.Path("app/main_cloudrun.py").read_text(encoding="utf-8")
        assert "router_registry" not in src

    def test_no_lifespan_import(self):
        """I: main_cloudrun.py에 lifespan import 0건"""
        src = pathlib.Path("app/main_cloudrun.py").read_text(encoding="utf-8")
        assert "lifespan" not in src

    def test_root_no_db_dependency(self):
        """E: DB/Redis env 미설정 상태에서 GET / → 200 (slim entrypoint는 DB 의존 없음)"""
        with TestClient(app) as client:
            response = client.get("/")
        assert response.status_code == 200
