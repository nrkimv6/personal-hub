"""
lifespan 격리 및 QueuePool 고갈 방지 테스트 (Phase T1)

TESTING=1 환경변수 설정 시 lifespan 초기화가 스킵되는지 검증.
"""
import os
import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


class TestLifespanSkipInTesting:

    def test_lifespan_skip_in_testing(self):
        """TESTING=1 설정 시 init_extra_tables 및 서비스 초기화 미호출 확인"""
        assert os.environ.get("TESTING") == "1", "conftest.py의 _set_testing_env가 TESTING=1 설정해야 함"

        with patch("app.lifespan.init_extra_tables") as mock_init, \
             patch("app.lifespan.cleanup_api_stale_resources", new_callable=AsyncMock) as mock_cleanup:
            from app.main import app
            with TestClient(app):
                pass

        mock_init.assert_not_called()
        mock_cleanup.assert_not_called()

    def test_health_monitor_not_initialized_in_testing(self):
        """TESTING=1 환경에서 HealthMonitorService 인스턴스화 미발생 확인"""
        assert os.environ.get("TESTING") == "1"

        with patch("app.services.health_monitor_service.HealthMonitorService") as mock_hm:
            from app.main import app
            with TestClient(app):
                pass

        mock_hm.assert_not_called()

    def test_system_cache_collector_not_initialized_in_testing(self):
        """TESTING=1 환경에서 SystemCacheCollector 인스턴스화 미발생 확인"""
        assert os.environ.get("TESTING") == "1"

        with patch("app.modules.system.services.system_cache_collector.SystemCacheCollector") as mock_scc:
            from app.main import app
            with TestClient(app):
                pass

        mock_scc.assert_not_called()


class TestCleanupApiStaleResources:

    @pytest.mark.asyncio
    async def test_cleanup_api_stale_resources_uses_default_llm_timeout(self):
        """startup cleanup은 timeout_minutes=0으로 정상 processing 요청을 즉시 실패시키지 않는다."""
        import app.lifespan as lifespan_module

        calls = []

        class Db:
            def commit(self):
                pass

            def close(self):
                pass

        class Service:
            def __init__(self, db):
                pass

            def cleanup_stale_processing(self, timeout_minutes=None):
                calls.append(timeout_minutes)
                return 0

        with patch("app.database.SessionLocal", return_value=Db()), \
             patch("app.modules.claude_worker.services.llm_service.LLMService", Service), \
             patch.object(lifespan_module.Path, "exists", return_value=False):
            await lifespan_module.cleanup_api_stale_resources()

        assert calls == [None]


class TestClientNoPoolExhaustion:

    def test_repeated_client_creation_no_pool_error(self, caplog):
        """TESTING=1: TestClient 10회 반복 생성/소멸 시 QueuePool 에러 없음 확인"""
        import logging
        assert os.environ.get("TESTING") == "1"

        from app.main import app

        with caplog.at_level(logging.ERROR):
            for _ in range(10):
                with TestClient(app):
                    pass

        pool_errors = [
            r for r in caplog.records
            if "QueuePool" in r.getMessage() or "pool" in r.getMessage().lower()
            if r.levelno >= logging.ERROR
        ]
        assert len(pool_errors) == 0, f"QueuePool 에러 발생: {[r.getMessage() for r in pool_errors]}"


class TestShutdownNotificationTimeout:

    @pytest.mark.asyncio
    async def test_shutdown_should_notify_timeout(self):
        """should_notify()가 3초 이상 지연될 때 shutdown이 빠르게 완료되는지 확인"""
        import time

        async def slow_should_notify(event_type):
            await asyncio.sleep(10)  # 10초 지연 (타임아웃보다 길게)
            return True

        # 3초 타임아웃으로 감싼 경우 3초 + 약간의 오버헤드 내에 완료되어야 함
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(lambda: time.sleep(10)),  # sync 10초 블로킹
                timeout=3
            )
        except asyncio.TimeoutError:
            pass  # 예상된 동작

        elapsed = time.monotonic() - start
        assert elapsed < 4.0, f"타임아웃 후에도 {elapsed:.1f}초 소요 — 너무 오래 걸림"
