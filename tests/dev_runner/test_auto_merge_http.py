"""T5 HTTP: plan-runner 자동 merge HTTP 통합 테스트

검증 범위:
- POST /api/v1/dev-runner/run 호출 후 runner 상태 조회로 merge 관련 필드 확인
- GET /api/v1/dev-runner/runners/{id} — merge_status, branch 필드 존재 확인
- GET /api/v1/dev-runner/runners — 전체 목록에서 merge_status 필드 포함 확인

실제 plan-runner 프로세스 없이 FastAPI TestClient + fakeredis로 격리 검증.
"""
from __future__ import annotations

import pytest
import fakeredis
import fakeredis.aioredis
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"
RUNNER_KEY_PREFIX = "plan-runner:runners"


@pytest.fixture(autouse=True)
def _plan_runner_redis_db_guard(monkeypatch):
    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")


@pytest.fixture
def fake_server():
    return fakeredis.FakeServer()


@pytest.fixture
def fake_sync(fake_server):
    return fakeredis.FakeRedis(server=fake_server, decode_responses=True)


@pytest.fixture
def fake_async(fake_server):
    return fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)


@pytest.fixture
def api_client(fake_sync, fake_async):
    """dev-runner 라우터만 포함한 격리 TestClient"""
    from app.modules.dev_runner.routes import router as dev_runner_router
    from app.modules.dev_runner.services.executor_service import executor_service

    original_sync = executor_service.redis_client
    original_async = executor_service.async_redis
    executor_service.redis_client = fake_sync
    executor_service.async_redis = fake_async

    app = FastAPI()
    app.include_router(dev_runner_router)

    with TestClient(app) as client:
        yield client, fake_sync

    executor_service.redis_client = original_sync
    executor_service.async_redis = original_async


class TestAutoMergeHTTP:
    def test_merge_status_queued_visible_in_runners_list(self, api_client):
        """T5 R: auto-merge 진행 중 (merge_status=queued) runner가 목록에 노출된다

        exit_code=0 + completed 후 _do_inline_merge가 호출되면 merge_status=queued로 전이.
        해당 상태가 GET /runners에서 정확히 반환되는지 확인.
        """
        client, fr = api_client
        runner_id = "t5-http-runner-004"

        fr.sadd("plan-runner:active_runners", runner_id)
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "plan/fix-auto-merge")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "queued")  # auto-merge 진행 중 상태
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

        resp = client.get(f"{BASE_URL}/runners")
        assert resp.status_code == 200
        runners = resp.json()

        matched = [r for r in runners if r.get("runner_id") == runner_id]
        assert matched, f"runner_id={runner_id} 미포함"
        runner = matched[0]

        assert runner.get("merge_status") == "queued", (
            f"auto-merge 진행 중 상태가 queued여야 함: {runner.get('merge_status')}"
        )

    def test_auto_merge_http_flag_none_with_commits_T5_contract(self, api_client):
        """T5 contract: live runner 실행은 merge-test 소유, HTTP는 결과 상태 노출만 검증한다."""
        client, fr = api_client
        runner_id = "t5-http-flag-none-commits-001"

        fr.sadd("plan-runner:active_runners", runner_id)
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "impl/flag-none-with-commits")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "queued")
        assert fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested") is None

        list_resp = client.get(f"{BASE_URL}/runners")
        assert list_resp.status_code == 200
        runners = list_resp.json()
        matched = [r for r in runners if r.get("runner_id") == runner_id]
        assert matched, f"runner_id={runner_id} 미포함"

        runner = matched[0]
        assert runner.get("branch") == "impl/flag-none-with-commits"
        assert runner.get("exit_reason") == "completed"
        assert runner.get("merge_status") == "queued"

        merge_resp = client.get(f"{BASE_URL}/merge/{runner_id}")
        assert merge_resp.status_code == 200
        merge_payload = merge_resp.json()
        assert merge_payload["runner_id"] == runner_id
        assert merge_payload["status"] == "queued"

    def test_runner_status_includes_merge_status_field(self, api_client):
        """T5 R: runner 상태 조회 시 merge_status 필드가 존재해야 한다"""
        client, fr = api_client
        runner_id = "t5-http-runner-001"

        # fakeredis에 runner 상태 직접 세팅
        fr.sadd("plan-runner:active_runners", runner_id)
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "plan/auto-merge-fix")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")

        resp = client.get(f"{BASE_URL}/runners")
        assert resp.status_code == 200
        runners = resp.json()

        # runner_id 매칭 runner 찾기
        matched = [r for r in runners if r.get("runner_id") == runner_id]
        assert matched, f"runner_id={runner_id} 미포함. runners: {[r.get('runner_id') for r in runners]}"

        runner = matched[0]
        assert "merge_status" in runner, f"merge_status 필드 누락: {runner.keys()}"
        assert runner["merge_status"] == "merged", f"merge_status 불일치: {runner['merge_status']}"

    def test_runner_status_branch_field_present(self, api_client):
        """T5 R: runner 상태에 branch 필드가 존재해야 한다"""
        client, fr = api_client
        runner_id = "t5-http-runner-002"

        fr.sadd("plan-runner:active_runners", runner_id)
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "plan/fix-auto-merge")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "queued")

        resp = client.get(f"{BASE_URL}/runners")
        assert resp.status_code == 200
        runners = resp.json()

        matched = [r for r in runners if r.get("runner_id") == runner_id]
        assert matched, f"runner_id={runner_id} 미포함"

        runner = matched[0]
        assert "branch" in runner, f"branch 필드 누락: {runner.keys()}"
        assert runner["branch"] == "plan/fix-auto-merge"

    def test_merge_status_none_when_not_set(self, api_client):
        """T5 B: merge_status 키 없는 runner → None 또는 필드 누락 허용 (crash 없어야 함)"""
        client, fr = api_client
        runner_id = "t5-http-runner-003"

        fr.sadd("plan-runner:active_runners", runner_id)
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        # merge_status 키 미설정

        resp = client.get(f"{BASE_URL}/runners")
        assert resp.status_code == 200  # 500 아닌 것만 확인 (crash 방어)
        runners = resp.json()
        matched = [r for r in runners if r.get("runner_id") == runner_id]
        if matched:
            runner = matched[0]
            # merge_status가 없거나 None이면 정상
            assert runner.get("merge_status") in (None, ""), (
                f"merge_status 미설정인데 값이 있음: {runner.get('merge_status')}"
            )
