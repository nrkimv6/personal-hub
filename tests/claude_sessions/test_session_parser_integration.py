"""세션 파서 통합 테스트 — 실제 ~/.claude/projects/ 파일 사용."""

import os
from pathlib import Path

import pytest

from app.modules.claude_sessions.session_parser import SessionParser, encode_project_path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
parser = SessionParser()

# 실제 프로젝트 경로
MONITOR_PAGE_PATH = r"D:\work\project\tools\monitor-page"
MONITOR_PAGE_ENCODED = encode_project_path(MONITOR_PAGE_PATH)


def _sessions_dir_exists() -> bool:
    return (CLAUDE_PROJECTS / MONITOR_PAGE_ENCODED).exists()


@pytest.mark.skipif(not _sessions_dir_exists(), reason="Claude 세션 디렉토리 없음")
def test_list_real_sessions_includes_user_type():
    """실제 디렉토리에서 user 타입 세션 ≥ 1개."""
    sessions = parser.list_sessions(MONITOR_PAGE_PATH, limit=50)
    assert len(sessions) >= 1, "세션이 하나도 없음"
    # user 타입이 있는지 확인
    user_sessions = [s for s in sessions if s.source_type == "user"]
    assert len(user_sessions) >= 1, f"user 타입 세션 없음. 실제 타입: {[s.source_type for s in sessions[:5]]}"


@pytest.mark.skipif(not _sessions_dir_exists(), reason="Claude 세션 디렉토리 없음")
def test_list_real_sessions_includes_agent_type():
    """agent 타입 세션이 있는지 확인 (plan-runner/dev-runner 세션)."""
    sessions = parser.list_sessions(MONITOR_PAGE_PATH, limit=100)
    agent_sessions = [s for s in sessions if s.source_type == "agent"]
    # agent 세션이 없을 수도 있으므로 로그만 출력
    if not agent_sessions:
        pytest.skip("agent 타입 세션 없음 (정상 — plan-runner가 최근 실행되지 않았을 수 있음)")
    assert len(agent_sessions) >= 1


@pytest.mark.skipif(not _sessions_dir_exists(), reason="Claude 세션 디렉토리 없음")
def test_classify_real_session_source():
    """실제 첫 번째 세션의 source_type이 유효한 값인지 확인."""
    sessions = parser.list_sessions(MONITOR_PAGE_PATH, limit=5)
    assert sessions, "세션 없음"
    valid_types = {"user", "agent", "llm-worker", "unknown"}
    for s in sessions:
        assert s.source_type in valid_types, f"유효하지 않은 source_type: {s.source_type}"


@pytest.mark.skipif(not _sessions_dir_exists(), reason="Claude 세션 디렉토리 없음")
def test_filter_by_source_type_reduces_count():
    """source_type 필터 적용 시 전체보다 개수가 같거나 작음."""
    all_sessions = parser.list_sessions(MONITOR_PAGE_PATH, limit=50)
    user_sessions = parser.list_sessions(MONITOR_PAGE_PATH, limit=50, source_type="user")
    assert len(user_sessions) <= len(all_sessions), "필터 결과가 전체보다 클 수 없음"
