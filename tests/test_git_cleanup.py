import pytest
from unittest.mock import MagicMock, patch
from app.modules.git_repos.cleanup_prompt import render_cleanup_prompt
from app.modules.git_repos.services.repo_service import GitRepoService
from app.modules.git_repos.models import GitRepo
from app.modules.claude_worker.models.llm_request import LLMRequest

def test_render_cleanup_prompt_right():
    """프롬프트 렌더링 확인."""
    repo_path = "D:/repo"
    date = "2026-03-05"
    patterns = ["tmp_*"]
    
    prompt = render_cleanup_prompt(repo_path, date, patterns)
    
    assert repo_path in prompt
    assert date in prompt
    assert '"tmp_*"' in prompt
    assert "git -C" in prompt

def test_auto_cleanup_repo_enqueues_chat_right():
    """mode=chat 로 enqueue 확인."""
    db = MagicMock()
    repo = GitRepo(id=1, path="D:/repo")
    patterns = ["tmp_*"]
    
    svc = GitRepoService()
    
    with patch("app.modules.git_repos.services.repo_service.LLMService") as mock_llm_svc_class:
        mock_llm_svc = mock_llm_svc_class.return_value
        mock_llm_svc.enqueue.return_value = LLMRequest(id=123, status="pending")
        
        req = svc.auto_cleanup_repo(db, repo, patterns)
        
        assert req.id == 123
        mock_llm_svc.enqueue.assert_called_once()
        args, kwargs = mock_llm_svc.enqueue.call_args
        assert kwargs["mode"] == "chat"
        assert kwargs["caller_type"] == "git_cleanup"
        assert "allowed_tools" in kwargs["cli_options"]

@pytest.mark.asyncio
async def test_cleanup_result_pending_right():
    """pending 상태 반환 확인."""
    from app.modules.git_repos.routes import get_cleanup_result
    
    db = MagicMock()
    repo_id = 1
    request_id = 123
    
    with patch("app.modules.claude_worker.services.llm_service.LLMService.get_request_by_id") as mock_get:
        mock_get.return_value = LLMRequest(id=request_id, status="processing")
        
        result = await get_cleanup_result(repo_id, request_id, db)
        assert result == {"status": "processing"}

@pytest.mark.asyncio
async def test_cleanup_result_completed_right():
    """완료 JSON 파싱 확인."""
    from app.modules.git_repos.routes import get_cleanup_result
    
    db = MagicMock()
    repo_id = 1
    request_id = 123
    raw_response = '{"success": true, "moved": ["tmp_1"], "commits": [{"files": ["a.txt"], "message": "feat: a"}]}'
    
    with patch("app.modules.claude_worker.services.llm_service.LLMService.get_request_by_id") as mock_get:
        mock_get.return_value = LLMRequest(id=request_id, status="completed", raw_response=raw_response)
        
        result = await get_cleanup_result(repo_id, request_id, db)
        assert result.success is True
        assert result.moved == ["tmp_1"]
        assert len(result.commits) == 1
        assert result.commits[0]["message"] == "feat: a"

@pytest.mark.asyncio
async def test_cleanup_result_completed_error_malformed_json():
    """raw_response JSON 오류 처리 확인."""
    from app.modules.git_repos.routes import get_cleanup_result
    
    db = MagicMock()
    repo_id = 1
    request_id = 123
    raw_response = "invalid json"
    
    with patch("app.modules.claude_worker.services.llm_service.LLMService.get_request_by_id") as mock_get:
        mock_get.return_value = LLMRequest(id=request_id, status="completed", raw_response=raw_response)
        
        result = await get_cleanup_result(repo_id, request_id, db)
        assert result.success is False
        assert "파싱 실패" in result.error
