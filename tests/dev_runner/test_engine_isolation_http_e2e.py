"""T5 HTTP: dev_runner SSE 스트림이 [engine-isolation] 토큰을 surface하는지 검증.

Token contract (wtools _todo-2):
    `[engine-isolation] engine={engine} mode={mode}`
    - claude → mode=true_subagent
    - codex/cc-codex/gemini → mode=process_only

본 _todo는 monitor-page 측 SSE/HTTP 표면에서 토큰이 흐르는지 관측만 한다.
helper 자체와 토큰 발생 로직은 wtools에 있으며 monitor-page는 직접 호출하지 않는다.

마커 운용:
    - `pytest.mark.http`: TestClient 기반, log_service.stream_log_file을 mock하여
      SSE bytes에서 토큰 표면화 검증 (실 plan-runner subprocess 불필요).
    - `pytest.mark.http_live`: 실서버 + 실 plan-runner 흐름. 환경 의존성이 커 별도
      conftest_e2e의 isolated_redis fixture와 함께만 의미 있음. 본 파일은 http
      마커로 안정 검증을 1차 책임으로 두고, http_live TC는 동일 토큰 contract를
      재확인하는 readiness용으로 mock-skipped 처리한다.
"""
from __future__ import annotations

import re
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.logs import router as logs_router

pytestmark = pytest.mark.http

TOKEN_PATTERN = re.compile(
    r"\[engine-isolation\] engine=(?P<engine>\S+) mode=(?P<mode>\S+)"
)


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(logs_router, prefix="/api/v1/dev-runner")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _make_stream(*lines: str):
    """log_service.stream_log_file 대역 — SSE data: 라인을 yield."""

    async def _stream(*args, **kwargs):
        for line in lines:
            yield f"data: {line}\n\n"

    return _stream


def _read_sse(response):
    """TestClient SSE 응답 본문에서 data: 라인 추출."""
    body = response.content.decode("utf-8", errors="replace")
    return [line[6:] for line in body.splitlines() if line.startswith("data: ")]


def test_claude_run_surfaces_true_subagent_token_via_sse(client):
    """SSE 스트림에 `engine=claude mode=true_subagent` 토큰이 그대로 흘러나와야 한다."""
    expected = "[engine-isolation] engine=claude mode=true_subagent"
    fake_stream = _make_stream(
        "stage=dispatch engine=claude",
        expected,
        "stage=running engine=claude",
    )
    with patch(
        "app.modules.dev_runner.routes.logs.log_service.stream_log_file",
        side_effect=fake_stream,
    ):
        resp = client.get("/api/v1/dev-runner/logs/stream", params={"runner_id": "claude-1"})

    assert resp.status_code == 200
    lines = _read_sse(resp)
    assert any(expected == ln for ln in lines), f"토큰 미surface: {lines!r}"

    match = TOKEN_PATTERN.search("\n".join(lines))
    assert match is not None
    assert match.group("engine") == "claude"
    assert match.group("mode") == "true_subagent"


def test_codex_run_surfaces_process_only_token_via_sse(client):
    """codex run에서 `mode=process_only` 토큰이 surface되어야 한다."""
    expected = "[engine-isolation] engine=codex mode=process_only"
    fake_stream = _make_stream(
        "stage=dispatch engine=codex fused_session=true",
        expected,
        "stage=running engine=codex",
    )
    with patch(
        "app.modules.dev_runner.routes.logs.log_service.stream_log_file",
        side_effect=fake_stream,
    ):
        resp = client.get("/api/v1/dev-runner/logs/stream", params={"runner_id": "codex-1"})

    assert resp.status_code == 200
    lines = _read_sse(resp)
    assert any(expected == ln for ln in lines), f"토큰 미surface: {lines!r}"

    match = TOKEN_PATTERN.search("\n".join(lines))
    assert match is not None
    assert match.group("engine") == "codex"
    assert match.group("mode") == "process_only"


def test_token_format_is_stable_across_runs(client):
    """같은 engine로 2회 연속 run 시 토큰 포맷이 byte-level identical."""
    token = "[engine-isolation] engine=claude mode=true_subagent"

    captures: list[str] = []
    for runner_id in ("claude-A", "claude-B"):
        fake_stream = _make_stream(token)
        with patch(
            "app.modules.dev_runner.routes.logs.log_service.stream_log_file",
            side_effect=fake_stream,
        ):
            resp = client.get("/api/v1/dev-runner/logs/stream", params={"runner_id": runner_id})
        assert resp.status_code == 200
        lines = _read_sse(resp)
        match = TOKEN_PATTERN.search("\n".join(lines))
        assert match is not None
        captures.append(f"[engine-isolation] engine={match.group('engine')} mode={match.group('mode')}")

    assert captures[0] == captures[1] == token, f"토큰 포맷 drift: {captures!r}"


def test_unknown_engine_falls_back_to_process_only_token(client):
    """알려지지 않은 engine도 wtools helper 폴백에 따라 process_only 토큰을 흘려야 한다."""
    expected = "[engine-isolation] engine=unknown mode=process_only"
    fake_stream = _make_stream(expected)
    with patch(
        "app.modules.dev_runner.routes.logs.log_service.stream_log_file",
        side_effect=fake_stream,
    ):
        resp = client.get("/api/v1/dev-runner/logs/stream", params={"runner_id": "unknown-1"})

    assert resp.status_code == 200
    lines = _read_sse(resp)
    match = TOKEN_PATTERN.search("\n".join(lines))
    assert match is not None
    assert match.group("mode") == "process_only"
