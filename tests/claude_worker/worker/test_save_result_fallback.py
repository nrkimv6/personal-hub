import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.models.instagram_post import InstagramPost
from app.modules.claude_worker.worker.worker import LLMWorker

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
    worker = LLMWorker()
    worker._update_worker_state = MagicMock()
    worker._increment_processed = MagicMock()
    return worker

@pytest.mark.asyncio
async def test_save_instagram_failure_marks_failed(db, worker):
    """R: save_instagram_result가 False 반환 시 mark_failed 호출됨."""
    from app.modules.claude_worker.services.llm_service import LLMService
    service = MagicMock(spec=LLMService)
    service.resolve_provider_model.return_value = ("claude", "opus")
    service.execute_llm.return_value = {"success": True, "result": {"tag": "event"}}
    
    # 1. 유효한 post 존재
    post = InstagramPost(id=300, post_id="p300", account="acc", caption="Check this!")
    db.add(post)
    request = LLMRequest(id=10, caller_type="instagram", caller_id="300", prompt="test", status="pending")
    db.add(request)
    db.commit()
    
    # 2. save_instagram_result가 False를 반환하도록 Mock
    with patch("app.modules.claude_worker.worker.worker.save_instagram_result", return_value=False):
        await worker._execute_request(request, db, service)
    
    # 3. 검증
    service.mark_completed.assert_not_called()
    service.prepare_completed.assert_not_called()
    service.mark_failed.assert_called_once()
    args, _ = service.mark_failed.call_args
    assert "Save result failed" in args[1]

@pytest.mark.asyncio
async def test_save_writing_fallback_failure_marks_failed(db, worker):
    """R: JSON 파싱 실패 후 fallback save 실패 시 mark_failed 호출됨."""
    from app.modules.claude_worker.services.llm_service import LLMService
    service = MagicMock(spec=LLMService)
    service.resolve_provider_model.return_value = ("claude", "opus")
    
    # JSON 파싱 실패 상황 (success=False, raw_response 존재)
    service.execute_llm.return_value = {
        "success": False, 
        "error": "JSON parse error", 
        "raw_response": "Just some text"
    }
    
    request = LLMRequest(id=11, caller_type="writing_generate", caller_id="999", prompt="test", status="pending")
    db.add(request)
    db.commit()
    
    # save_writing_generate_result가 False 반환하도록 Mock
    with patch("app.modules.claude_worker.worker.worker.save_writing_generate_result", return_value=False):
        await worker._execute_request(request, db, service)
    
    # 3. 검증
    service.mark_completed.assert_called_once() # Fallback 경로에서 mark_completed 호출됨
    service.mark_failed.assert_called_once() # 하지만 save 실패로 mark_failed 호출
    args, _ = service.mark_failed.call_args
    assert "Save result failed" in args[1]
    assert "(fallback)" in args[1]


@pytest.mark.asyncio
async def test_save_instagram_missing_tag_marks_failed(db, worker):
    """B: tag 없는 payload는 save 실패 후 mark_failed."""
    from app.modules.claude_worker.services.llm_service import LLMService

    service = MagicMock(spec=LLMService)
    service.resolve_provider_model.return_value = ("claude", "opus")
    service.execute_llm.return_value = {"success": True, "result": {"summary": "missing tag"}}

    post = InstagramPost(id=301, post_id="p301", account="acc", caption="caption")
    request = LLMRequest(id=12, caller_type="instagram", caller_id="301", prompt="test", status="pending")
    db.add_all([post, request])
    db.commit()

    await worker._execute_request(request, db, service)

    service.prepare_completed.assert_not_called()
    service.mark_completed.assert_not_called()
    service.mark_failed.assert_called_once()
    args, _ = service.mark_failed.call_args
    assert "Save result failed" in args[1]


@pytest.mark.asyncio
async def test_save_instagram_unknown_tag_marks_failed(db, worker):
    """E: allowlist 밖 tag는 성공 처리하지 않는다."""
    from app.modules.claude_worker.services.llm_service import LLMService

    service = MagicMock(spec=LLMService)
    service.resolve_provider_model.return_value = ("claude", "opus")
    service.execute_llm.return_value = {
        "success": True,
        "result": {"tag": "미상태그", "summary": "unknown tag"},
    }

    post = InstagramPost(id=302, post_id="p302", account="acc", caption="caption")
    request = LLMRequest(id=13, caller_type="instagram", caller_id="302", prompt="test", status="pending")
    db.add_all([post, request])
    db.commit()

    await worker._execute_request(request, db, service)

    service.prepare_completed.assert_not_called()
    service.mark_completed.assert_not_called()
    service.mark_failed.assert_called_once()
    args, _ = service.mark_failed.call_args
    assert "Save result failed" in args[1]
