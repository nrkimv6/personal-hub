import os
from textwrap import dedent
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.event import Event
from app.models.instagram_post import InstagramPost
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor
from app.modules.claude_worker.worker.worker import LLMWorker


@pytest.fixture
def fake_claude_env(tmp_path, monkeypatch):
    fake_py = tmp_path / "fake_claude.py"
    fake_py.write_text(
        dedent(
            """
            import json
            import os

            mode = os.environ.get("CLAUDE_FAKE_MODE", "ok")
            if mode == "mojibake":
                payload = {
                    "type": "result",
                    "session_id": "fake-session-mojibake",
                    "result": {
                        "tag": "\\ufffd\\u013a\\u00ba\\ufffd\\u01ae",
                        "summary": "깨진 응답",
                        "urls": [],
                        "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
                        "prizes": [],
                        "winner_count": None,
                        "purchase_required": "아니오",
                    },
                }
            else:
                payload = {
                    "type": "result",
                    "session_id": "fake-session-ok",
                    "result": {
                        "tag": "이벤트",
                        "summary": "한글 보존",
                        "urls": [],
                        "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
                        "prizes": [],
                        "winner_count": None,
                        "purchase_required": "아니오",
                    },
                }
            print(json.dumps(payload, ensure_ascii=False))
            """
        ).strip(),
        encoding="utf-8",
    )

    fake_cmd = tmp_path / "claude.cmd"
    fake_cmd.write_text(f'@echo off\r\npython "{fake_py}"\r\n', encoding="utf-8")

    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    return tmp_path


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_utf8_korean_payload_preserved(fake_claude_env):
    executor = ClaudeExecutor()

    result = executor.execute("한글 prompt", timeout=10)

    assert result["success"] is True
    assert result["result"]["tag"] == "이벤트"
    assert result["result"]["summary"] == "한글 보존"
    assert result["claude_session_id"] == "fake-session-ok"


@pytest.mark.asyncio
async def test_mojibake_payload_marks_failed_e2e(fake_claude_env, db, monkeypatch):
    monkeypatch.setenv("CLAUDE_FAKE_MODE", "mojibake")

    post = InstagramPost(
        id=9901,
        post_id="p9901",
        account="broken",
        url="https://instagram.com/p/9901",
        caption="caption",
        images=[],
    )
    request = LLMRequest(
        id=9902,
        caller_type="instagram",
        caller_id="9901",
        prompt="test",
        status="pending",
    )
    db.add_all([post, request])
    db.commit()

    worker = LLMWorker()
    worker._update_worker_state = MagicMock()
    worker._increment_processed = MagicMock()

    service = LLMService(db)
    service.resolve_provider_model = MagicMock(return_value=("claude", "claude-haiku-4-5"))

    await worker._execute_request(request, db, service)

    db.refresh(request)
    assert request.status == "failed"
    assert request.error_message == "encoding_mojibake"
    assert db.query(Event).filter(Event.source_instagram_post_id == 9901).count() == 0
