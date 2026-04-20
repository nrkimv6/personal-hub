"""register_routers() 테스트 — 라우터 등록 검증."""
import os
import pytest
from fastapi import FastAPI


class TestRegisterRoutersAddsRoutes:

    def test_register_routers_adds_routes(self):
        """빈 FastAPI app에 register_routers 호출 후 라우트가 추가됨 확인 (RIGHT)"""
        assert os.environ.get("TESTING") == "1"
        from app.router_registry import register_routers

        app = FastAPI()
        before = len(app.routes)
        register_routers(app)
        after = len(app.routes)

        assert after > before, f"register_routers 후 라우트 수가 늘어나야 함 (before={before}, after={after})"

    def test_register_routers_idempotent_no_exception(self):
        """register_routers 2회 호출 시 예외 없이 통과 (ERROR — 중복 등록 방어)"""
        assert os.environ.get("TESTING") == "1"
        from app.router_registry import register_routers

        app = FastAPI()
        register_routers(app)
        try:
            register_routers(app)
        except Exception as e:
            pytest.fail(f"register_routers 2회 호출 시 예외 발생: {e}")

    def test_register_routers_registers_activity_v1_and_legacy_aliases(self):
        """Activity routes are exposed under both source-of-truth and legacy prefixes."""
        assert os.environ.get("TESTING") == "1"
        from app.router_registry import register_routers

        app = FastAPI()
        register_routers(app)

        paths = {route.path for route in app.routes}
        expected = {
            "/api/v1/activity/centers",
            "/api/activity/centers",
            "/api/v1/activity/courses",
            "/api/activity/courses",
            "/api/v1/activity/worker/status",
            "/api/activity/worker/status",
            "/api/v1/activity/crawl/sync-hub",
            "/api/activity/crawl/sync-hub",
            "/api/v1/expo/{slug}/pipeline-status",
            "/api/v1/expo/{slug}/collection-status",
            "/api/v1/expo/{slug}/published-status",
            "/api/v1/expo/{slug}/exports/record",
        }

        missing = expected - paths
        assert not missing, f"activity router prefixes missing: {sorted(missing)}"
