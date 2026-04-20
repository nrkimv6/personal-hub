"""LLM 실행 → claude_session_id DB 저장 통합 검증 (Phase T3).

실제 Claude CLI 실행이 필요한 통합 테스트.
CI 환경에서는 스킵, 수동 실행 시에만 확인.
"""

import os
import shutil
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock, patch

# Claude CLI 설치 여부로 스킵
CLAUDE_AVAILABLE = shutil.which("claude") is not None

pytestmark = pytest.mark.skipif(
    not CLAUDE_AVAILABLE,
    reason="claude CLI 설치 필요 (npm install -g @anthropic-ai/claude-code)",
)


@pytest.fixture
def db():
    from app.models.base import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def svc(db):
    from app.modules.claude_worker.services.repositories import LLMRequestRepository
    from app.modules.claude_worker.services.llm_queue_service import LLMQueueService
    from unittest.mock import MagicMock

    repo = LLMRequestRepository(db)
    config_svc = MagicMock()
    config_svc.resolve_provider_model.return_value = ("claude", "")
    return LLMQueueService(repo, config_svc, db)


@pytest.mark.timeout(60)
def test_llm_request_saves_claude_session_id(db, svc):
    """실제 Claude CLI 실행 → llm_requests.claude_session_id NOT NULL 확인."""
    from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

    executor = ClaudeExecutor()
    result = executor.execute("echo '안녕'", parse_json=False, timeout=30)

    assert result.get("success") is True, f"CLI 실행 실패: {result.get('error')}"
    session_id = result.get("claude_session_id")
    assert session_id is not None, "claude_session_id가 None — --output-format json 미주입 가능성"
    assert len(session_id) == 36, f"UUID 형식이 아님: {session_id}"

    # DB 저장
    req = svc.enqueue("test_integration", "tc_1", "echo test", requested_by="test")
    svc.mark_completed(req.id, result.get("result", ""), result.get("raw_response", ""), session_id)
    db.refresh(req)
    assert req.claude_session_id == session_id


@pytest.mark.timeout(60)
def test_session_id_matches_jsonl_filename(db, svc):
    """저장된 session_id로 ~/.claude/projects/.../SESSION_ID.jsonl 파일 존재 확인."""
    from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

    executor = ClaudeExecutor()
    result = executor.execute("echo 'test'", parse_json=False, timeout=30)

    if result.get("success") is not True:
        pytest.skip(f"Claude CLI transient failure: {result.get('error')}")
    session_id = result.get("claude_session_id")
    if session_id is None:
        pytest.skip("session_id 없음 — CLI 버전에서 미지원")

    claude_projects_dir = Path.home() / ".claude" / "projects"
    matching = list(claude_projects_dir.rglob(f"{session_id}.jsonl"))
    assert len(matching) > 0, f"JSONL 파일 없음: {session_id}.jsonl (~/.claude/projects 하위)"


@pytest.mark.timeout(60)
def test_korean_prompt_roundtrip_smoke():
    """한글 JSON 응답이 direct stdin 경로에서 정상 roundtrip 되는지 smoke 검증."""
    from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

    executor = ClaudeExecutor()
    result = executor.execute(
        '다음 JSON만 그대로 반환하세요. 설명 없이 JSON만 출력하세요. {"tag":"이벤트","summary":"한글 라운드트립"}',
        timeout=30,
    )

    assert result.get("success") is True, f"CLI 실행 실패: {result.get('error')}"
    assert result["result"]["tag"] == "이벤트"
    assert result["result"]["summary"] == "한글 라운드트립"
