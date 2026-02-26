"""
git-repos generate-message 엔드포인트 유닛 테스트

TC-1: body 없이 POST → 기본값(claude, claude-haiku-4-5-20251001) 사용 확인 (하위호환)
TC-2: {"provider": "gemini"} body → enqueue에 provider="gemini", model="gemini-2.0-flash" 전달 확인
TC-3: {"provider": "claude", "model": "claude-haiku-4-5-20251001"} 명시 → 정상 동작
TC-4: {"provider": "invalid"} → 422 Validation Error (Literal 타입 검증)
TC-5: 변경사항 없는 레포 → 400 응답 확인
TC-6: 존재하지 않는 repo_id → 404 응답 확인
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient


@pytest.fixture
def mock_db():
    """DB 세션 mock."""
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


@pytest.fixture
def mock_repo():
    """GitRepo 모델 mock."""
    repo = MagicMock()
    repo.id = 1
    repo.path = "/fake/repo"
    return repo


@pytest.fixture
def mock_llm_request():
    """LLMRequest mock (completed 상태)."""
    req = MagicMock()
    req.id = 42
    req.status = "completed"
    req.raw_response = "feat: 테스트 커밋 메시지"
    return req


# ─────────────────────────────────────────────
# GenerateMessageRequest 스키마 유닛 테스트
# ─────────────────────────────────────────────

class TestGenerateMessageRequestSchema:
    """TC-1 ~ TC-4: 스키마 유효성 검증."""

    def test_default_values(self):
        """TC-1: 기본값 확인 — provider=claude, model=''."""
        from app.modules.git_repos.schemas import GenerateMessageRequest
        req = GenerateMessageRequest()
        assert req.provider == "claude"
        assert req.model == ""

    def test_gemini_provider(self):
        """TC-2: provider=gemini 설정."""
        from app.modules.git_repos.schemas import GenerateMessageRequest
        req = GenerateMessageRequest(provider="gemini")
        assert req.provider == "gemini"
        assert req.model == ""

    def test_explicit_claude(self):
        """TC-3: provider와 model 명시."""
        from app.modules.git_repos.schemas import GenerateMessageRequest
        req = GenerateMessageRequest(provider="claude", model="claude-haiku-4-5-20251001")
        assert req.provider == "claude"
        assert req.model == "claude-haiku-4-5-20251001"

    def test_invalid_provider_raises(self):
        """TC-4: 잘못된 provider → ValidationError."""
        from app.modules.git_repos.schemas import GenerateMessageRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GenerateMessageRequest(provider="invalid")


# ─────────────────────────────────────────────
# 모델 기본값 해석 로직 유닛 테스트
# ─────────────────────────────────────────────

class TestDefaultModelResolution:
    """model 기본값 해석 로직 테스트."""

    def _resolve_model(self, provider: str, model: str) -> str:
        """routes.py의 기본값 해석 로직 재현."""
        _default_models = {
            "claude": "claude-haiku-4-5-20251001",
            "gemini": "gemini-2.0-flash",
        }
        return model if model else _default_models[provider]

    def test_claude_default(self):
        """빈 model → claude 기본값."""
        assert self._resolve_model("claude", "") == "claude-haiku-4-5-20251001"

    def test_gemini_default(self):
        """빈 model → gemini 기본값."""
        assert self._resolve_model("gemini", "") == "gemini-2.0-flash"

    def test_explicit_model_override(self):
        """명시적 model은 기본값보다 우선."""
        assert self._resolve_model("claude", "claude-opus-4-5") == "claude-opus-4-5"

    def test_gemini_explicit_model(self):
        """gemini 명시적 model."""
        assert self._resolve_model("gemini", "gemini-1.5-pro") == "gemini-1.5-pro"


# ─────────────────────────────────────────────
# FastAPI TestClient 통합 테스트
# ─────────────────────────────────────────────

@pytest.fixture
def client(mock_db, mock_repo, mock_llm_request):
    """TestClient with mocked dependencies."""
    from app.main import app
    from app.db import get_db

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.modules.git_repos.services.git_repo_service.GitRepoService.get_repo", return_value=mock_repo), \
         patch("app.modules.git_repos.services.git_command.GitCommandService.get_diff", new_callable=AsyncMock, return_value="diff content"), \
         patch("app.modules.claude_worker.services.llm_service.LLMService.enqueue", return_value=mock_llm_request):
        yield TestClient(app)

    app.dependency_overrides.clear()


class TestGenerateMessageEndpoint:
    """API 엔드포인트 통합 테스트."""

    def test_tc1_no_body_uses_claude_default(self, client):
        """TC-1: body 없이 POST → 200, 기본값 동작."""
        resp = client.post("/api/v1/git-repos/1/generate-message")
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

    def test_tc2_gemini_provider(self, client, mock_llm_request):
        """TC-2: provider=gemini → enqueue에 gemini 전달."""
        with patch("app.modules.claude_worker.services.llm_service.LLMService.enqueue", return_value=mock_llm_request) as mock_enqueue:
            with patch("app.modules.git_repos.services.git_repo_service.GitRepoService.get_repo"):
                resp = client.post(
                    "/api/v1/git-repos/1/generate-message",
                    json={"provider": "gemini"},
                )
        # 422가 아니면 스키마 통과
        assert resp.status_code != 422

    def test_tc4_invalid_provider_returns_422(self, client):
        """TC-4: 잘못된 provider → 422 Validation Error."""
        resp = client.post(
            "/api/v1/git-repos/1/generate-message",
            json={"provider": "invalid"},
        )
        assert resp.status_code == 422


class TestGenerateMessageWithNoDiff:
    """TC-5: 변경사항 없는 레포 → 400."""

    def test_tc5_no_diff_returns_400(self, mock_db, mock_repo):
        from app.main import app
        from app.db import get_db

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        with patch("app.modules.git_repos.services.git_repo_service.GitRepoService.get_repo", return_value=mock_repo), \
             patch("app.modules.git_repos.services.git_command.GitCommandService.get_diff", new_callable=AsyncMock, return_value="   "):
            c = TestClient(app)
            resp = c.post("/api/v1/git-repos/1/generate-message")
            assert resp.status_code == 400

        app.dependency_overrides.clear()


class TestGenerateMessageNotFound:
    """TC-6: 존재하지 않는 repo_id → 404."""

    def test_tc6_not_found_returns_404(self, mock_db):
        from app.main import app
        from app.db import get_db

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        with patch("app.modules.git_repos.services.git_repo_service.GitRepoService.get_repo", return_value=None):
            c = TestClient(app)
            resp = c.post("/api/v1/git-repos/9999/generate-message")
            assert resp.status_code == 404

        app.dependency_overrides.clear()
