"""GET /api/v1/ready HTTP 통합 테스트 — app.state 방식 ready 엔드포인트 검증."""
import os
import pytest
from fastapi.testclient import TestClient


class TestReadyEndpointExists:

    def test_ready_endpoint_exists_and_returns_200(self):
        """TESTING=1 환경에서 GET /api/v1/ready → HTTP 200 응답 확인 (RIGHT)"""
        assert os.environ.get("TESTING") == "1"
        from app.main import app

        with TestClient(app) as client:
            response = client.get("/api/v1/ready")

        assert response.status_code == 200, f"기대 200, 실제 {response.status_code}"

    def test_ready_returns_false_in_testing_env(self):
        """TESTING=1(lifespan skip)에서 GET /api/v1/ready → {ready: false} 확인 (BOUNDARY — getattr fallback)"""
        assert os.environ.get("TESTING") == "1"
        from app.main import app

        with TestClient(app) as client:
            response = client.get("/api/v1/ready")

        assert response.status_code == 200
        data = response.json()
        assert "ready" in data, f"응답에 ready 키 없음: {data}"
        assert data["ready"] is False, f"TESTING=1 환경에서 ready가 False여야 함, 실제: {data['ready']}"

    def test_ready_response_has_ready_key(self):
        """GET /api/v1/ready 응답이 JSON 객체이고 ready 키를 포함함 (RIGHT)"""
        assert os.environ.get("TESTING") == "1"
        from app.main import app

        with TestClient(app) as client:
            response = client.get("/api/v1/ready")

        assert response.headers["content-type"].startswith("application/json")
        data = response.json()
        assert isinstance(data, dict), f"응답이 dict가 아님: {type(data)}"
        assert "ready" in data
        assert isinstance(data["ready"], bool), f"ready 값이 bool이 아님: {type(data['ready'])}"
