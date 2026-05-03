"""Unit tests for SSE initial status retry/backoff behavior."""

import json

import pytest
import requests

from tests.dev_runner.sse_filter_helpers import (
    SSE_INITIAL_STATUS_MAX_RETRIES_ENV,
    SSE_INITIAL_STATUS_RETRY_DELAY_ENV,
    collect_initial_status_with_retry,
)


SSE_URL = "http://example.test/api/v1/dev-runner/events"


class FakeSseResponse:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def iter_lines(self, decode_unicode: bool = False):
        assert decode_unicode is True
        yield from self._lines


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        self.now += 0.01
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def _status_lines(runners: list[dict]) -> list[str]:
    return [
        "event: status",
        f"data: {json.dumps({'runners': runners})}",
        "",
    ]


def test_collect_initial_status_right_first_try_success():
    """R(Right): 첫 시도에서 runners 반환 → 즉시 성공, retry 안 함."""
    clock = FakeClock()
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeSseResponse(_status_lines([{"runner_id": "runner-1"}]))

    runners = collect_initial_status_with_retry(
        SSE_URL,
        request_get=fake_get,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert runners == [{"runner_id": "runner-1"}]
    assert len(calls) == 1
    assert calls[0][0] == SSE_URL
    assert calls[0][1]["stream"] is True
    assert clock.sleeps == []


def test_collect_initial_status_right_retry_success():
    """R(Right): 1~2회 status 없음 → 3회째 runners 반환 → 성공."""
    clock = FakeClock()
    responses = [
        FakeSseResponse(["event: message", "data: {}"]),
        FakeSseResponse([]),
        FakeSseResponse(_status_lines([{"runner_id": "runner-3"}])),
    ]
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return responses[len(calls) - 1]

    runners = collect_initial_status_with_retry(
        SSE_URL,
        max_retries=3,
        retry_delay=0.25,
        request_get=fake_get,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert runners == [{"runner_id": "runner-3"}]
    assert len(calls) == 3
    assert clock.sleeps == [0.25, 0.25]


def test_collect_initial_status_boundary_all_retries_fail():
    """B(Boundary): max_retries회 모두 status 없음 → 최종 빈 리스트 반환."""
    clock = FakeClock()
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeSseResponse(["event: message", "data: {}"])

    runners = collect_initial_status_with_retry(
        SSE_URL,
        max_retries=3,
        retry_delay=0.5,
        request_get=fake_get,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert runners == []
    assert len(calls) == 3
    assert clock.sleeps == [0.5, 0.5]


def test_collect_initial_status_error_connection_refused():
    """E(Error): requests.get ConnectionError → 예외 전파 없이 빈 리스트 반환."""
    clock = FakeClock()
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        raise requests.ConnectionError("connection refused")

    runners = collect_initial_status_with_retry(
        SSE_URL,
        max_retries=2,
        retry_delay=0.1,
        request_get=fake_get,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert runners == []
    assert len(calls) == 2
    assert clock.sleeps == [0.1]


def test_collect_initial_status_error_invalid_json_retries():
    """E(Error): status data JSON 파싱 실패는 해당 시도 실패로 보고 retry한다."""
    clock = FakeClock()
    calls = []
    responses = [
        FakeSseResponse(["event: status", "data: {broken-json", ""]),
        FakeSseResponse(_status_lines([{"runner_id": "runner-json"}])),
    ]

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return responses[len(calls) - 1]

    runners = collect_initial_status_with_retry(
        SSE_URL,
        max_retries=2,
        retry_delay=0.1,
        request_get=fake_get,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert runners == [{"runner_id": "runner-json"}]
    assert len(calls) == 2
    assert clock.sleeps == [0.1]


def test_collect_initial_status_empty_status_is_valid_filter_result():
    """R(Right): status 이벤트의 빈 runners는 필터 결과이므로 retry하지 않음."""
    clock = FakeClock()
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeSseResponse(_status_lines([]))

    runners = collect_initial_status_with_retry(
        SSE_URL,
        max_retries=3,
        request_get=fake_get,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert runners == []
    assert len(calls) == 1
    assert clock.sleeps == []


def test_collect_initial_status_http_assertion_not_hidden():
    """E(Error): HTTP 계약 실패 AssertionError는 retry로 숨기지 않음."""
    clock = FakeClock()

    def fake_get(url, **kwargs):
        return FakeSseResponse([], status_code=503)

    with pytest.raises(AssertionError, match="GET /events HTTP 503"):
        collect_initial_status_with_retry(
            SSE_URL,
            require_status_code=200,
            request_get=fake_get,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

    assert clock.sleeps == []


def test_collect_initial_status_env_retry_policy():
    """R(Right): 환경변수 retry 정책을 적용해 강제 retry를 빠르게 검증한다."""
    clock = FakeClock()
    calls = []
    responses = [
        FakeSseResponse([]),
        FakeSseResponse(_status_lines([{"runner_id": "runner-env"}])),
    ]

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return responses[len(calls) - 1]

    runners = collect_initial_status_with_retry(
        SSE_URL,
        request_get=fake_get,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        environ={
            SSE_INITIAL_STATUS_MAX_RETRIES_ENV: "2",
            SSE_INITIAL_STATUS_RETRY_DELAY_ENV: "0.05",
        },
    )

    assert runners == [{"runner_id": "runner-env"}]
    assert len(calls) == 2
    assert clock.sleeps == [0.05]
