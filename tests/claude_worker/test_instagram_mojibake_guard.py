import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.event import Event
from app.models.instagram_post import InstagramPost
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.worker.worker import (
    LLMWorker,
    instagram_payload_has_mojibake,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def worker():
    instance = LLMWorker()
    instance._update_worker_state = MagicMock()
    instance._increment_processed = MagicMock()
    return instance


def test_payload_contains_mojibake_replacement_char_R():
    payload = {
        "tag": "\ufffd\u013a\u00ba\uFFFD\u01AE",
        "summary": "깨진 응답",
        "prizes": [],
        "purchase_required": "아니오",
    }

    assert instagram_payload_has_mojibake(payload) is True


def test_payload_contains_mojibake_false_for_valid_korean_B():
    payload = {
        "tag": "이벤트",
        "summary": "정상 한글 응답",
        "prizes": ["경품"],
        "purchase_required": "아니오",
    }

    assert instagram_payload_has_mojibake(payload) is False


@pytest.mark.asyncio
async def test_execute_request_marks_instagram_mojibake_failed_E(db, worker):
    post = InstagramPost(
        id=7101,
        post_id="p7101",
        account="broken",
        url="https://instagram.com/p/7101",
        caption="caption",
        images=[{"src": "https://example.com/thumb.jpg"}],
    )
    request = LLMRequest(
        id=7102,
        caller_type="instagram",
        caller_id="7101",
        prompt="test",
        status="pending",
    )
    db.add_all([post, request])
    db.commit()

    service = LLMService(db)
    service.resolve_provider_model = MagicMock(return_value=("claude", "claude-haiku-4-5"))
    service.execute_llm = MagicMock(
        return_value={
            "success": True,
            "result": {
                "tag": "\ufffd\u013a\u00ba\uFFFD\u01AE",
                "summary": "깨진 요약",
                "urls": [],
                "event_period": {"start": "2026-04-17", "end": "2026-04-17"},
                "prizes": [],
                "winner_count": None,
                "purchase_required": "\ufffd\u01b4\u03f5\u00bf",
            },
            "raw_response": json.dumps(
                {
                    "type": "result",
                    "result": {
                        "tag": "\ufffd\u013a\u00ba\uFFFD\u01AE",
                        "summary": "깨진 요약",
                    },
                },
                ensure_ascii=False,
            ),
            "claude_session_id": "session-mojibake",
        }
    )

    await worker._execute_request(request, db, service)

    db.refresh(request)
    db.refresh(post)
    assert request.status == "failed"
    assert request.error_message == "encoding_mojibake"
    assert post.classified_type is None
    assert db.query(Event).filter(Event.source_instagram_post_id == 7101).count() == 0
    worker._increment_processed.assert_not_called()
