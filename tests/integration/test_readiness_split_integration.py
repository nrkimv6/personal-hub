"""readiness-vs-feature-health 분리 재현 통합 TC

이번 2026-04-22 merge-test 실패 형태를 코드로 고정한다:
  - API 프로세스 살아 있음 + Redis 다운 조합에서
    /system/liveness  → 200  (readiness OK)
    /dev-runner/runners → 503  (Redis 장애, readiness 와 무관)

두 엔드포인트는 독립적이어야 하며, runners 503이 readiness 판정을 막아서는 안 된다.

TestClient 기반 (실서버 불필요, worktree에서 실행 가능).
"""
from unittest.mock import AsyncMock, patch

import pytest
import redis
from fastapi.testclient import TestClient

from app.main import app
from app.modules.dev_runner.services.executor_service import executor_service


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


class TestReadinessSplitIntegration:
    """Redis 불능 + API 생존 조합 계약 고정"""

    def test_liveness_200_and_runners_503_are_simultaneous(self, client):
        """R: Redis down 조합 — /system/liveness 200, /dev-runner/runners 503 동시 검증.

        이번 실패 형태: merge-test 가 runners 503 을 'API 미기동' 으로 오판.
        이 계약이 깨지면 merge-test 가 다시 Redis 단일 장애로 전체 블록된다.
        """
        with patch.object(
            executor_service,
            "get_all_runners",
            new=AsyncMock(side_effect=redis.ConnectionError("test")),
        ):
            live_resp = client.get("/api/v1/system/liveness")
            runners_resp = client.get("/api/v1/dev-runner/runners")

        # liveness: Redis/DB 무관, API 프로세스 생존 판정
        assert live_resp.status_code == 200, (
            f"liveness must be 200 even when Redis is down (got {live_resp.status_code})"
        )
        assert live_resp.json()["status"] == "ok"

        # runners: Redis 장애 → 503, detail 계약 고정
        assert runners_resp.status_code == 503, (
            f"runners must be 503 on Redis down (got {runners_resp.status_code})"
        )
        assert runners_resp.json().get("detail") == "Redis 연결 실패"

    def test_merge_test_polling_simulation_liveness_ok_despite_runners_503(self, client):
        """R: merge-test polling 시뮬레이션 — liveness 200 → readiness 통과, runners 503 무관.

        실패 재현: merge-test 는 liveness 만 polling 하면 된다.
        runners 503 이 readiness gate 를 막지 않음을 순서대로 호출하며 검증.
        """
        with patch.object(
            executor_service,
            "get_all_runners",
            new=AsyncMock(side_effect=redis.ConnectionError("redis down")),
        ):
            # Step 1: merge-test readiness gate — liveness polling 결과
            poll_resp = client.get("/api/v1/system/liveness")

            # Step 2: 이후 기능 헬스 — runners (별도 문제)
            feature_resp = client.get("/api/v1/dev-runner/runners")

        # readiness 통과 조건: liveness 200
        assert poll_resp.status_code == 200, (
            "merge-test polling: liveness must return 200 regardless of Redis state"
        )
        assert poll_resp.json()["status"] == "ok", (
            "merge-test polling: liveness body must have status='ok'"
        )

        # 기능 헬스는 별도: 503이어도 readiness에 영향 없음
        assert feature_resp.status_code == 503, (
            "runners 503 is expected when Redis is down — "
            "this is a separate feature health signal, NOT a readiness failure"
        )
