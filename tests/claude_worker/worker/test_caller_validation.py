import pytest
import asyncio
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.models.instagram_post import InstagramPost
from app.models.universal_crawl import CrawledPage
from app.modules.claude_worker.worker.worker import LLMWorker

@pytest.fixture
def db():
    # In-memory SQLite for testing
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

@pytest.fixture
def worker():
    worker = LLMWorker()
    # Mock methods that use SessionLocal internally to avoid real DB access
    worker._update_worker_state = MagicMock()
    worker._increment_processed = MagicMock()
    return worker

@pytest.mark.asyncio
async def test_validate_instagram_caller_boundary_no_post(db, worker):
    """B: 존재하지 않는 post_id -> mark_failed 호출, LLM executor 미호출."""
    from app.modules.claude_worker.services.llm_service import LLMService
    service = MagicMock(spec=LLMService)
    service.resolve_provider_model.return_value = ("claude", "opus")
    
    # 1. DB에 request만 있고 InstagramPost는 없는 상황
    request = LLMRequest(id=1, caller_type="instagram", caller_id="999", prompt="test", status="pending")
    db.add(request)
    db.commit()
    
    # 2. _execute_request 호출
    # service.execute_llm이 호출되지 않아야 함
    await worker._execute_request(request, db, service)
    
    # 3. 검증
    # mark_failed가 호출되었는지 확인
    service.mark_failed.assert_called_once()
    args, _ = service.mark_failed.call_args
    assert "Instagram post not found" in args[1]
    
    # execute_llm은 호출되지 않아야 함
    service.execute_llm.assert_not_called()

@pytest.mark.asyncio
async def test_validate_instagram_caller_boundary_no_caption(db, worker):
    """B: post 존재하지만 caption=None -> mark_failed 호출, LLM executor 미호출."""
    from app.modules.claude_worker.services.llm_service import LLMService
    service = MagicMock(spec=LLMService)
    service.resolve_provider_model.return_value = ("claude", "opus")
    
    # 1. post는 있지만 caption이 None
    post = InstagramPost(id=100, post_id="p100", account="acc", caption=None)
    db.add(post)
    request = LLMRequest(id=2, caller_type="instagram", caller_id="100", prompt="test", status="pending")
    db.add(request)
    db.commit()
    
    # 2. _execute_request 호출
    await worker._execute_request(request, db, service)
    
    # 3. 검증
    service.mark_failed.assert_called_once()
    args, _ = service.mark_failed.call_args
    assert "no caption" in args[1]
    service.execute_llm.assert_not_called()

@pytest.mark.asyncio
async def test_validate_instagram_caller_error_non_numeric(db, worker):
    """E: caller_id="abc" -> mark_failed 호출, ValueError 미전파."""
    from app.modules.claude_worker.services.llm_service import LLMService
    service = MagicMock(spec=LLMService)
    service.resolve_provider_model.return_value = ("claude", "opus")
    
    request = LLMRequest(id=3, caller_type="instagram", caller_id="abc", prompt="test", status="pending")
    db.add(request)
    db.commit()
    
    # ValueError가 전파되지 않고 처리되어야 함
    await worker._execute_request(request, db, service)
    
    service.mark_failed.assert_called_once()
    args, _ = service.mark_failed.call_args
    assert "Invalid caller_id" in args[1] or "not found" in args[1]
    service.execute_llm.assert_not_called()

@pytest.mark.asyncio
async def test_validate_universal_crawl_caller_boundary_no_page(db, worker):
    """B: CrawledPage 없음 -> mark_failed, LLM 미호출."""
    from app.modules.claude_worker.services.llm_service import LLMService
    service = MagicMock(spec=LLMService)
    service.resolve_provider_model.return_value = ("claude", "opus")
    
    request = LLMRequest(id=4, caller_type="universal_crawl", caller_id="777", prompt="test", status="pending")
    db.add(request)
    db.commit()
    
    await worker._execute_request(request, db, service)
    
    service.mark_failed.assert_called_once()
    args, _ = service.mark_failed.call_args
    assert "CrawledPage not found" in args[1]
    service.execute_llm.assert_not_called()

@pytest.mark.asyncio
async def test_validate_instagram_caller_right(db, worker):
    """R: 존재하는 post + caption 있음 -> 검증 통과, LLM executor 호출됨."""
    from app.modules.claude_worker.services.llm_service import LLMService
    service = MagicMock(spec=LLMService)
    service.resolve_provider_model.return_value = ("claude", "opus")
    # Mock execute_llm to return success
    service.execute_llm.return_value = {"success": True, "result": {"tag": "event"}}
    
    # 1. 유효한 post
    post = InstagramPost(id=200, post_id="p200", account="acc", caption="Check this out!")
    db.add(post)
    request = LLMRequest(id=5, caller_type="instagram", caller_id="200", prompt="test", status="pending")
    db.add(request)
    db.commit()
    
    # 2. _execute_request 호출
    # 여기서 save_instagram_result 등을 호출하려 할 텐데, 
    # mock_save를 통해 실제 DB 작업을 막거나 (이미 in-memory라 상관 없을 수도 있지만)
    # 일단 흐름이 LLM 호출까지 가는지 확인
    with patch("app.modules.claude_worker.worker.worker.save_instagram_result", return_value=True):
        await worker._execute_request(request, db, service)
    
    # 3. 검증
    service.execute_llm.assert_called_once()
    service.prepare_completed.assert_called_once()
    service.mark_completed.assert_not_called()
