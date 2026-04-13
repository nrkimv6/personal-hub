"""Claude Sessions DB 연결 HTTP 통합 테스트 (Phase T5).

llm_requests.claude_session_id와 세션 목록 API 응답의 db_request_ids 연결을 검증한다.
TestClient 기반으로 실서버 없이 동작.
"""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 모델 등록을 위해 Base 이전에 LLMRequest import 필수
from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa: F401 — Base 등록
from app.database import get_db


@pytest.fixture
def db_session_and_app(tmp_path):
    """자체 SQLite 엔진 + TestClient 픽스처."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    _Session = sessionmaker(bind=engine)
    db = _Session()

    # JSONL 임시 세션 파일 구성
    projects_dir = tmp_path / "projects"
    mp_dir = projects_dir / "D--work-project-tools-monitor-page"
    mp_dir.mkdir(parents=True)

    session_uuid = "aaaabbbb-cccc-dddd-eeee-ffff00001111"
    session_data = [
        {"type": "summary", "summary": "test", "leafUuid": "x"},
        {"type": "user", "message": {"role": "user", "content": "hello"}, "cwd": "/test"},
    ]
    session_file = mp_dir / f"{session_uuid}.jsonl"
    with open(session_file, "w", encoding="utf-8") as f:
        for obj in session_data:
            f.write(json.dumps(obj) + "\n")

    # llm_requests에 claude_session_id 주입
    req = LLMRequest(
        caller_type="claude_session_summary",
        caller_id=session_uuid,
        prompt="test",
        requested_by="test",
        status="completed",
        claude_session_id=session_uuid,
        requested_at=datetime.now(),
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    req_id = req.id

    # FastAPI app + router
    from app.modules.claude_sessions.routes.session_routes import router as sessions_router
    app = FastAPI()
    app.include_router(sessions_router)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c, session_uuid, projects_dir, req_id

    db.close()
    engine.dispose()


@pytest.mark.http
def test_session_list_includes_db_request_ids(db_session_and_app):
    """GET /sessions → db_request_ids에 llm_requests ID 포함 확인."""
    client, session_uuid, projects_dir, req_id = db_session_and_app

    with patch("app.modules.claude_sessions.routes.session_routes.CLAUDE_PROJECTS_DIR", projects_dir):
        resp = client.get("/api/v1/claude-sessions/D--work-project-tools-monitor-page/sessions?limit=10")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1

    matched = [s for s in data if s["id"] == session_uuid]
    assert len(matched) == 1, f"세션 {session_uuid} 미발견"

    session = matched[0]
    assert "db_request_ids" in session
    assert req_id in session["db_request_ids"], (
        f"req_id {req_id} not in db_request_ids {session['db_request_ids']}"
    )


@pytest.mark.http
def test_db_source_type_matches_caller_type(db_session_and_app):
    """GET /sessions → db_source_type == llm_requests.caller_type."""
    client, session_uuid, projects_dir, req_id = db_session_and_app

    with patch("app.modules.claude_sessions.routes.session_routes.CLAUDE_PROJECTS_DIR", projects_dir):
        resp = client.get("/api/v1/claude-sessions/D--work-project-tools-monitor-page/sessions?limit=10")

    assert resp.status_code == 200
    data = resp.json()
    matched = [s for s in data if s["id"] == session_uuid]
    assert len(matched) == 1

    session = matched[0]
    assert session.get("db_source_type") == "claude_session_summary"
