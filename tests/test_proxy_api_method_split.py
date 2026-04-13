from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.routes import proxy as proxy_routes
from app.schemas.proxy import ProxyDetailResponse, ProxyListResponse, ProxyResponse, ProxyStatsResponse


def _make_fake_proxy() -> SimpleNamespace:
    now = datetime.now()
    return SimpleNamespace(
        id=101,
        url="http://10.0.0.1:8080",
        protocol="http",
        host="10.0.0.1",
        port=8080,
        username=None,
        password=None,
        source="test",
        country="KR",
        tags=None,
        status="active",
        total_checks=1,
        success_count=1,
        fail_count=0,
        avg_response_time=0.42,
        priority_score=87.5,
        get_status="pending",
        post_status="active",
        get_total_checks=0,
        post_total_checks=1,
        get_success_count=0,
        post_success_count=1,
        get_fail_count=0,
        post_fail_count=0,
        get_avg_response_time=None,
        post_avg_response_time=0.42,
        get_min_response_time=None,
        post_min_response_time=0.42,
        get_max_response_time=None,
        post_max_response_time=0.42,
        get_priority_score=0.0,
        post_priority_score=87.5,
        first_seen_at=now,
        last_checked_at=now,
        last_success_at=now,
        last_seen_at=now,
    )


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.proxy_list = ["http://10.0.0.1:8080"]
        self.active_pool = ["http://10.0.0.1:8080"]
        self.blacklist = {}

    def get_status(self, request_method: str = "get") -> dict:
        self.calls.append(("get_status", request_method))
        return {
            "initialized": True,
            "request_method": request_method,
            "active_pool": 1,
            "blacklisted": 0,
        }

    async def check_and_reload(self, request_method: str = "get") -> None:
        self.calls.append(("check_and_reload", request_method))

    async def refresh_active_pool(self, request_method: str = "get") -> None:
        self.calls.append(("refresh_active_pool", request_method))


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.proxy = _make_fake_proxy()

    def get_stats(self, request_method: str = "get") -> ProxyStatsResponse:
        self.calls.append(("get_stats", request_method))
        return ProxyStatsResponse(
            total=1,
            active=1,
            pending=0,
            inactive=0,
            blacklisted=0,
            avg_response_time=0.42,
            overall_success_rate=100.0,
            by_protocol={"http": 1},
            by_country=[{"country": "KR", "count": 1}],
            today_checks=1,
            today_success_rate=100.0,
            request_method=request_method,
            by_method={
                "get": {
                    "total": 1,
                    "active": 0,
                    "pending": 1,
                    "inactive": 0,
                    "blacklisted": 0,
                    "avg_response_time": None,
                    "overall_success_rate": None,
                    "active_success_count": 0,
                    "active_total_checks": 0,
                    "priority_score_hint": 0.0,
                },
                "post": {
                    "total": 1,
                    "active": 1,
                    "pending": 0,
                    "inactive": 0,
                    "blacklisted": 0,
                    "avg_response_time": 0.42,
                    "overall_success_rate": 100.0,
                    "active_success_count": 1,
                    "active_total_checks": 1,
                    "priority_score_hint": 87.5,
                },
            },
        )

    def get_list(self, params) -> ProxyListResponse:
        self.calls.append(("get_list", params.request_method))
        item = ProxyResponse.from_proxy(self.proxy, request_method=params.request_method)
        return ProxyListResponse(items=[item], total=1, page=params.page, page_size=params.page_size, total_pages=1)

    def get_top_proxies(self, limit: int = 10, status: str = "active", request_method: str = "get"):
        self.calls.append(("get_top_proxies", request_method))
        return [self.proxy]

    def get_detail(self, proxy_id: int, history_limit: int = 50, request_method: str = "get") -> ProxyDetailResponse:
        self.calls.append(("get_detail", (proxy_id, history_limit, request_method)))
        detail = ProxyDetailResponse.from_proxy(self.proxy, request_method=request_method)
        detail.check_history = []
        return detail


def test_proxy_routes_forward_method_to_manager(monkeypatch):
    fake_manager = _FakeManager()
    monkeypatch.setattr(proxy_routes, "get_proxy_manager", lambda: fake_manager)

    with TestClient(app) as client:
        status_response = client.get("/api/v1/proxy/status", params={"method": "post"})
        refresh_response = client.post("/api/v1/proxy/refresh", params={"method": "post"})
        list_response = client.get("/api/v1/proxy/list", params={"method": "post"})

    assert status_response.status_code == 200
    assert status_response.json()["request_method"] == "post"

    assert refresh_response.status_code == 200
    assert fake_manager.calls[:3] == [
        ("get_status", "post"),
        ("check_and_reload", "post"),
        ("refresh_active_pool", "post"),
    ]
    assert refresh_response.json()["status"]["request_method"] == "post"

    assert list_response.status_code == 200
    assert list_response.json()["request_method"] == "post"


def test_proxy_db_routes_forward_method_to_service(monkeypatch):
    fake_service = _FakeService()
    monkeypatch.setattr(proxy_routes, "get_proxy_db_service", lambda db: fake_service)
    app.dependency_overrides[proxy_routes.get_proxy_db] = lambda: object()

    try:
        with TestClient(app) as client:
            stats_response = client.get("/api/v1/proxy/db/stats", params={"method": "post"})
            list_response = client.get("/api/v1/proxy/db/list", params={"method": "post"})
            top_response = client.get("/api/v1/proxy/db/top", params={"method": "post"})
            detail_response = client.get("/api/v1/proxy/db/101", params={"method": "post", "history_limit": 25})
    finally:
        app.dependency_overrides.clear()

    assert stats_response.status_code == 200
    assert stats_response.json()["request_method"] == "post"

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["request_method"] == "post"

    assert top_response.status_code == 200
    assert top_response.json()[0]["request_method"] == "post"

    assert detail_response.status_code == 200
    assert detail_response.json()["request_method"] == "post"

    assert fake_service.calls == [
        ("get_stats", "post"),
        ("get_list", "post"),
        ("get_top_proxies", "post"),
        ("get_detail", (101, 25, "post")),
    ]
