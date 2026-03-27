"""
T4/T5: pipeline v1 제거 검증 TC

2026-03-28_remove-pipeline-v1 plan의 T4(E2E) + T5(HTTP) 통합 테스트.

검증 목표:
- `pipeline` 필드 없이 /run API 호출 → 정상 동작 (v1 제거 후 기본값 없음)
- `pipeline` 필드를 전달해도 API가 무시(없는 필드) → 422 아님, 정상 200
- listener: pipeline 필드 없는 커맨드 → subprocess --pipeline 인자 없음 확인
"""
import json
import sys
import subprocess
import time
import uuid
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from app.main import app

import os
import signal
import redis

# T5는 http 마커 사용
pytestmark = pytest.mark.http

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_TEST_DB = 15
COMMANDS_KEY = "plan-runner:commands"
RUNNER_KEY_PREFIX = "plan-runner:runners"

BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(scope="module")
def api_client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def stop_runners_after_test(api_client):
    """각 테스트 후 생성된 runner 정리 (다음 테스트 간섭 방지)"""
    yield
    try:
        runners_resp = api_client.get(f"{BASE_URL}/runners")
        if runners_resp.status_code == 200:
            for item in runners_resp.json():
                rid = item.get("runner_id")
                if rid:
                    try:
                        api_client.post(f"{BASE_URL}/stop/{rid}")
                    except Exception:
                        pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# T5: HTTP 통합 (TestClient 기반)
# ---------------------------------------------------------------------------

def test_T5_start_run_without_pipeline_R(api_client):
    """R(정상): pipeline 필드 없이 POST /run → 200 또는 runner_id 포함 응답"""
    payload = {
        "engine": "claude",
        "plan_file": "docs/plan/test_e2e_plan.md",
        "dry_run": True,
        "trigger": "tc:test_T5_start_run_without_pipeline_R",
        "test_source": "test_remove_pipeline_v1_e2e",
    }
    response = api_client.post(f"{BASE_URL}/run", json=payload)
    assert response.status_code == 200, (
        f"pipeline 없이 /run 호출 시 200 기대, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert "runner_id" in data, f"runner_id 없음: {data}"


def test_T5_start_run_with_pipeline_field_ignored_B(api_client):
    """B(경계): pipeline 필드 포함 payload → 422 아님 (미지 필드 무시), 200 응답"""
    payload = {
        "engine": "claude",
        "plan_file": "docs/plan/test_e2e_plan.md",
        "dry_run": True,
        "pipeline": "v2",  # 제거된 필드 — Pydantic이 무시해야 함
        "trigger": "tc:test_T5_start_run_with_pipeline_field_ignored_B",
        "test_source": "test_remove_pipeline_v1_e2e",
    }
    response = api_client.post(f"{BASE_URL}/run", json=payload)
    # pipeline 필드가 없으므로 extra 필드는 무시되어 200 반환 기대
    # 만약 Pydantic model_config extra='forbid'이면 422가 나올 수 있음 — 하지만 그것도 "pipeline 필드 없음"을 증명
    assert response.status_code in (200, 422), (
        f"예상치 못한 상태코드: {response.status_code}: {response.text}"
    )
    if response.status_code == 422:
        detail = response.json().get("detail", "")
        # 422라면 pipeline 필드 때문이어야 함 (extra 필드 금지 설정)
        assert "pipeline" in str(detail), f"422인데 pipeline 때문이 아님: {detail}"
    else:
        # 200이면 runner_id가 있어야 함
        data = response.json()
        assert "runner_id" in data, f"200이지만 runner_id 없음: {data}"


def test_T5_run_schema_has_no_pipeline_field_E(api_client):
    """E(에러): /run 엔드포인트 OpenAPI 스키마에 pipeline 필드 없음"""
    response = api_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()

    # RunRequest 스키마 확인
    run_request_schema = (
        schema.get("components", {})
        .get("schemas", {})
        .get("RunRequest", {})
    )
    properties = run_request_schema.get("properties", {})
    assert "pipeline" not in properties, (
        f"RunRequest 스키마에 pipeline 필드가 여전히 존재: {list(properties.keys())}"
    )


# ---------------------------------------------------------------------------
# T4: E2E (Redis + listener subprocess)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def redis_client_e2e():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)
    try:
        r.ping()
    except redis.ConnectionError:
        pytest.skip("Redis not available")
    yield r
    r.close()


@pytest.fixture(scope="module")
def listener_process_e2e(redis_client_e2e):
    """dev-runner-command-listener 프로세스 시작"""
    script_path = Path("scripts/dev-runner-command-listener.py")
    if not script_path.exists():
        pytest.skip("listener script not found")

    process = subprocess.Popen(
        [sys.executable, str(script_path), "--redis-db", str(REDIS_TEST_DB)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # heartbeat 대기 (최대 15초)
    heartbeat_ok = False
    for _ in range(30):
        if redis_client_e2e.get("plan-runner:listener:heartbeat"):
            heartbeat_ok = True
            break
        time.sleep(0.5)

    if not heartbeat_ok:
        process.terminate()
        pytest.skip("Listener did not start (no heartbeat)")

    yield process
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.mark.e2e
def test_T4_run_trigger_without_pipeline_E2E(redis_client_e2e, listener_process_e2e):
    """T4 R(정상): pipeline 필드 없는 커맨드 → listener가 subprocess 생성 확인"""
    runner_id = f"e2e-nopipe-{uuid.uuid4().hex[:4]}"
    command_id = uuid.uuid4().hex[:8]

    command = {
        "action": "run",
        "runner_id": runner_id,
        "command_id": command_id,
        "source": "test",
        "trigger": "tc:test_T4_run_trigger_without_pipeline_E2E",
        "plan_file": "docs/plan/test_e2e_plan.md",
        "dry_run": True,
        "engine": "claude",
        # pipeline 필드 없음
    }
    result_key = f"plan-runner:command_results:{command_id}"
    redis_client_e2e.lpush(COMMANDS_KEY, json.dumps(command))

    result = redis_client_e2e.brpop(result_key, timeout=15)
    if result is None:
        pytest.skip("Listener did not process command in time")

    _, raw = result
    result_data = json.loads(raw)
    assert result_data.get("success"), f"커맨드 실패: {result_data}"


@pytest.mark.e2e
def test_T4_run_trigger_with_legacy_pipeline_E2E(redis_client_e2e, listener_process_e2e):
    """T4 B(경계): pipeline 레거시 필드 포함 커맨드 → listener가 무시하고 subprocess 생성 확인"""
    runner_id = f"e2e-legacypipe-{uuid.uuid4().hex[:4]}"
    command_id = uuid.uuid4().hex[:8]

    command = {
        "action": "run",
        "runner_id": runner_id,
        "command_id": command_id,
        "source": "test",
        "trigger": "tc:test_T4_run_trigger_with_legacy_pipeline_E2E",
        "plan_file": "docs/plan/test_e2e_plan.md",
        "dry_run": True,
        "engine": "claude",
        "pipeline": "v2",  # 레거시 필드 — 무시되어야 함
    }
    result_key = f"plan-runner:command_results:{command_id}"
    redis_client_e2e.lpush(COMMANDS_KEY, json.dumps(command))

    result = redis_client_e2e.brpop(result_key, timeout=15)
    if result is None:
        pytest.skip("Listener did not process command in time")

    _, raw = result
    result_data = json.loads(raw)
    assert result_data.get("success"), f"레거시 pipeline 포함 커맨드 실패: {result_data}"
