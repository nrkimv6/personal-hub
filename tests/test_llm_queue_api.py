"""
LLM Multi-Queue API HTTP 테스트 (TestClient)

FastAPI TestClient를 사용하여 실제 HTTP 요청/응답을 검증합니다.
무거운 의존성(playwright 등)을 피하기 위해 LLM 라우터만 포함한 minimal app 사용.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.routes.llm_routes import router as llm_router

# LLM 라우터만 포함하는 minimal test app (playwright 등 무거운 의존성 제외)
app = FastAPI()
app.include_router(llm_router)


@pytest.fixture
def client(test_db_session):
    """테스트 DB 세션을 사용하는 TestClient."""
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def cleanup(test_db_session):
    """각 테스트 전 LLM 요청 정리."""
    test_db_session.query(LLMRequest).delete()
    test_db_session.commit()
    yield
    test_db_session.query(LLMRequest).delete()
    test_db_session.commit()


class TestCreateRequestQueueName:
    """POST /api/v1/llm/requests — queue_name 파라미터 테스트."""

    def test_create_system_queue_returns_queue_name(self, client):
        """queue_name='system' → 201(또는 200), response에 queue_name='system' 포함."""
        response = client.post("/api/v1/llm/requests", json={
            "caller_type": "test",
            "caller_id": "api-sys-1",
            "prompt": "hello system",
            "queue_name": "system",
        })
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["queue_name"] == "system"

    def test_create_default_queue_is_utility(self, client):
        """queue_name 생략 → queue_name='utility' 기본값."""
        response = client.post("/api/v1/llm/requests", json={
            "caller_type": "test",
            "caller_id": "api-default-1",
            "prompt": "hello default",
        })
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["queue_name"] == "utility"

    def test_create_explicit_utility_queue(self, client):
        """queue_name='utility' 명시 → utility 저장."""
        response = client.post("/api/v1/llm/requests", json={
            "caller_type": "test",
            "caller_id": "api-util-1",
            "prompt": "hello utility",
            "queue_name": "utility",
        })
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["queue_name"] == "utility"


class TestListRequestsQueueFilter:
    """GET /api/v1/llm/requests?queue_name= — 큐 필터 테스트."""

    def test_filter_by_system_queue(self, client):
        """?queue_name=system → system 큐 요청만 반환."""
        # system 1건 생성
        client.post("/api/v1/llm/requests", json={
            "caller_type": "test", "caller_id": "filter-sys-1",
            "prompt": "sys", "queue_name": "system",
        })
        # utility 1건 생성
        client.post("/api/v1/llm/requests", json={
            "caller_type": "test", "caller_id": "filter-util-1",
            "prompt": "util", "queue_name": "utility",
        })

        response = client.get("/api/v1/llm/requests?queue_name=system")
        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert len(items) >= 1
        assert all(item["queue_name"] == "system" for item in items)

    def test_filter_by_utility_queue(self, client):
        """?queue_name=utility → utility 큐 요청만 반환."""
        client.post("/api/v1/llm/requests", json={
            "caller_type": "test", "caller_id": "filter-sys-2",
            "prompt": "sys", "queue_name": "system",
        })
        client.post("/api/v1/llm/requests", json={
            "caller_type": "test", "caller_id": "filter-util-2",
            "prompt": "util", "queue_name": "utility",
        })

        response = client.get("/api/v1/llm/requests?queue_name=utility")
        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert len(items) >= 1
        assert all(item["queue_name"] == "utility" for item in items)

    def test_no_filter_returns_all(self, client):
        """queue_name 필터 없으면 전체 반환."""
        client.post("/api/v1/llm/requests", json={
            "caller_type": "test", "caller_id": "all-sys-1",
            "prompt": "sys", "queue_name": "system",
        })
        client.post("/api/v1/llm/requests", json={
            "caller_type": "test", "caller_id": "all-util-1",
            "prompt": "util", "queue_name": "utility",
        })

        response = client.get("/api/v1/llm/requests")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 2


class TestCliOptionsPassthrough:
    """cli_options 파라미터 passthrough 및 계획서 작성 시나리오 테스트."""

    def test_create_llm_request_with_cli_options(self, client, test_db_session):
        """Right: cli_options 포함 요청 → 200, cli_options DB 저장 확인."""
        import json as _json
        response = client.post("/api/v1/llm/requests", json={
            "caller_type": "test",
            "caller_id": "cli-opt-1",
            "prompt": "hello",
            "queue_name": "system",
            "cli_options": {"cwd": "D:/work/project/service/wtools"},
        })
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["caller_id"] == "cli-opt-1"

        # DB에서 cli_options 필드 확인
        req = test_db_session.query(LLMRequest).filter_by(caller_id="cli-opt-1").first()
        assert req is not None
        assert req.cli_options is not None
        stored = _json.loads(req.cli_options)
        assert stored["cwd"] == "D:/work/project/service/wtools"

    def test_create_llm_request_without_cli_options(self, client, test_db_session):
        """Boundary: cli_options 생략 → 기존 동작 회귀 없음."""
        response = client.post("/api/v1/llm/requests", json={
            "caller_type": "test",
            "caller_id": "cli-opt-none-1",
            "prompt": "hello no cli",
        })
        assert response.status_code in (200, 201)

        req = test_db_session.query(LLMRequest).filter_by(caller_id="cli-opt-none-1").first()
        assert req is not None
        assert req.cli_options is None

    def test_plan_preset_conformance(self, client, test_db_session):
        """Conformance: 계획서 작성 프리셋 전체 파라미터 통합 검증."""
        import json as _json
        date_str = "20260225120000"
        response = client.post("/api/v1/llm/requests", json={
            "caller_type": "test",
            "caller_id": f"plan-{date_str}",
            "prompt": f"/plan 메모 내용 테스트",
            "queue_name": "system",
            "provider": "claude",
            "model": "opus",
            "cli_options": {"cwd": "D:/work/project/service/wtools"},
        })
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["caller_type"] == "test"
        assert data["caller_id"] == f"plan-{date_str}"
        assert data["queue_name"] == "system"

        req = test_db_session.query(LLMRequest).filter_by(caller_id=f"plan-{date_str}").first()
        assert req is not None
        assert req.provider == "claude"
        assert req.model == "opus"
        stored = _json.loads(req.cli_options)
        assert stored["cwd"] == "D:/work/project/service/wtools"
        assert req.prompt.startswith("/plan")


class TestQueueStats:
    """GET /api/v1/llm/queue-stats — 큐 통계 엔드포인트 테스트."""

    def test_queue_stats_structure(self, client):
        """큐 통계 응답 구조 검증 — system/utility 키와 pending 카운트."""
        client.post("/api/v1/llm/requests", json={
            "caller_type": "test", "caller_id": "stats-sys-1",
            "prompt": "sys", "queue_name": "system",
        })
        client.post("/api/v1/llm/requests", json={
            "caller_type": "test", "caller_id": "stats-util-1",
            "prompt": "util", "queue_name": "utility",
        })

        response = client.get("/api/v1/llm/queue-stats")
        assert response.status_code == 200
        data = response.json()

        assert "system" in data
        assert "utility" in data
        assert "pending" in data["system"]
        assert "pending" in data["utility"]
        assert isinstance(data["system"]["pending"], int)
        assert isinstance(data["utility"]["pending"], int)

    def test_queue_stats_counts_match_requests(self, client):
        """큐 통계 pending 카운트가 실제 생성한 요청 수와 일치."""
        # system 2건, utility 3건
        for i in range(2):
            client.post("/api/v1/llm/requests", json={
                "caller_type": "test", "caller_id": f"match-sys-{i}",
                "prompt": "sys", "queue_name": "system",
            })
        for i in range(3):
            client.post("/api/v1/llm/requests", json={
                "caller_type": "test", "caller_id": f"match-util-{i}",
                "prompt": "util", "queue_name": "utility",
            })

        response = client.get("/api/v1/llm/queue-stats")
        data = response.json()

        assert data["system"]["pending"] == 2
        assert data["utility"]["pending"] == 3
