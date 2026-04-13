"""Claude Sessions API HTTP 통합 테스트 (Phase T5).

TestClient 기반으로 실서버 없이 엔드포인트 동작을 검증한다.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.modules.claude_sessions.routes.session_routes import router as sessions_router

_test_app = FastAPI()
_test_app.include_router(sessions_router)


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    _test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(_test_app) as c:
        yield c
    _test_app.dependency_overrides.clear()


@pytest.fixture
def mock_claude_projects(tmp_path):
    """임시 ~.claude/projects/ 디렉토리 모킹."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # monitor-page 프로젝트 디렉토리 생성
    mp_dir = projects_dir / "D--work-project-tools-monitor-page"
    mp_dir.mkdir()

    # 샘플 세션 JSONL 파일 생성 (user 타입)
    session_data = [
        {"type": "summary", "summary": "test session", "leafUuid": "abc-uuid"},
        {"type": "user", "message": {"role": "user", "content": "test message"}, "cwd": "/test"},
    ]
    session_file = mp_dir / "test-session-1234.jsonl"
    with open(session_file, "w", encoding="utf-8") as f:
        for obj in session_data:
            f.write(json.dumps(obj) + "\n")

    return projects_dir


@pytest.mark.http
def test_list_projects_returns_monitor_page(client, mock_claude_projects):
    """GET /api/v1/claude-sessions/projects → monitor-page 포함."""
    with patch("app.modules.claude_sessions.routes.session_routes.CLAUDE_PROJECTS_DIR", mock_claude_projects):
        resp = client.get("/api/v1/claude-sessions/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    encoded_names = [p["encoded"] for p in data]
    assert "D--work-project-tools-monitor-page" in encoded_names


@pytest.mark.http
def test_list_sessions_default(client, mock_claude_projects):
    """GET .../sessions?limit=5 → ≥ 1개, source_type 필드 존재."""
    with patch("app.modules.claude_sessions.routes.session_routes.CLAUDE_PROJECTS_DIR", mock_claude_projects):
        resp = client.get("/api/v1/claude-sessions/D--work-project-tools-monitor-page/sessions?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "source_type" in data[0]
    assert "db_request_ids" in data[0]


@pytest.mark.http
def test_list_sessions_filter_source_type_user(client, mock_claude_projects):
    """source_type=user 필터 시 agent 세션 미포함."""
    with patch("app.modules.claude_sessions.routes.session_routes.CLAUDE_PROJECTS_DIR", mock_claude_projects):
        resp = client.get(
            "/api/v1/claude-sessions/D--work-project-tools-monitor-page/sessions?source_type=user&limit=20"
        )
    assert resp.status_code == 200
    data = resp.json()
    for session in data:
        assert session["source_type"] != "agent"


@pytest.mark.http
def test_summarize_recent_enqueues(client, mock_claude_projects):
    """POST .../summarize-recent?limit=2 → request_ids 반환."""
    with patch("app.modules.claude_sessions.routes.session_routes.CLAUDE_PROJECTS_DIR", mock_claude_projects):
        with patch("app.modules.claude_worker.services.llm_service.LLMService.enqueue") as mock_enqueue:
            mock_req = MagicMock()
            mock_req.id = 42
            mock_enqueue.return_value = mock_req
            resp = client.post(
                "/api/v1/claude-sessions/D--work-project-tools-monitor-page/summarize-recent?limit=2"
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "request_ids" in data
    assert "count" in data
    assert isinstance(data["request_ids"], list)


@pytest.mark.http
def test_get_summary_pending_or_completed(client, test_db_session):
    """GET /summary/{session_id} → 없으면 not_found, 있으면 pending/completed."""
    # 존재하지 않는 session_id
    resp = client.get("/api/v1/claude-sessions/summary/nonexistent-session-id")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "not_found"

    # llm_requests에 데이터 주입
    from app.modules.claude_worker.models.llm_request import LLMRequest
    from datetime import datetime
    req = LLMRequest(
        caller_type="claude_session_summary",
        caller_id="test-session-9999",
        prompt="test",
        requested_by="test",
        status="pending",
        requested_at=datetime.now(),
    )
    test_db_session.add(req)
    test_db_session.commit()

    resp2 = client.get("/api/v1/claude-sessions/summary/test-session-9999")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] in ("pending", "completed")
