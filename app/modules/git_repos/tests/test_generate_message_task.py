from types import SimpleNamespace

import pytest

from app.modules.git_repos import routes, schemas


pytestmark = pytest.mark.http


class FakeDb:
    def __init__(self):
        self.committed = False
        self.refreshed = False

    def commit(self):
        self.committed = True

    def refresh(self, _obj):
        self.refreshed = True


class FakeRepoService:
    def get_repo(self, _db, repo_id):
        return SimpleNamespace(id=repo_id, path="D:/repo")


@pytest.mark.asyncio
async def test_generate_message_returns_request_id_without_polling(monkeypatch):
    class FakeGitCommandService:
        async def get_diff(self, _path, staged=False):
            return "diff --git a/file b/file\n+change"

    class FakeLlmService:
        def __init__(self, _db):
            pass

        def enqueue(self, **_kwargs):
            return SimpleNamespace(id=123, status="pending", raw_response=None)

    monkeypatch.setattr(routes, "GitRepoService", lambda: FakeRepoService())
    monkeypatch.setattr(
        "app.modules.git_repos.services.git_command.GitCommandService",
        FakeGitCommandService,
    )
    monkeypatch.setattr(
        "app.modules.claude_worker.services.llm_service.LLMService",
        FakeLlmService,
    )

    db = FakeDb()
    response = await routes.generate_commit_message(
        7,
        body=schemas.GenerateMessageRequest(provider="claude"),
        db=db,
    )

    assert response == {"message": "", "request_id": 123, "status": "pending"}
    assert db.committed is True
    assert db.refreshed is False


@pytest.mark.asyncio
async def test_generate_message_large_diff_still_returns_immediately(monkeypatch):
    class FakeGitCommandService:
        async def get_diff(self, _path, staged=False):
            return "diff --git a/file b/file\n" + ("+change\n" * 5000)

    class FakeLlmService:
        def __init__(self, _db):
            pass

        def enqueue(self, **kwargs):
            assert len(kwargs["prompt"]) < 4000
            return SimpleNamespace(id=124, status="pending", raw_response=None)

    monkeypatch.setattr(routes, "GitRepoService", lambda: FakeRepoService())
    monkeypatch.setattr(
        "app.modules.git_repos.services.git_command.GitCommandService",
        FakeGitCommandService,
    )
    monkeypatch.setattr(
        "app.modules.claude_worker.services.llm_service.LLMService",
        FakeLlmService,
    )

    response = await routes.generate_commit_message(
        7,
        body=schemas.GenerateMessageRequest(provider="claude"),
        db=FakeDb(),
    )

    assert response["request_id"] == 124
    assert response["status"] == "pending"


@pytest.mark.asyncio
async def test_generate_message_missing_diff_does_not_enqueue(monkeypatch):
    class FakeGitCommandService:
        async def get_diff(self, _path, staged=False):
            return ""

    class FailingLlmService:
        def __init__(self, _db):
            raise AssertionError("LLM should not be used without diff")

    monkeypatch.setattr(routes, "GitRepoService", lambda: FakeRepoService())
    monkeypatch.setattr(
        "app.modules.git_repos.services.git_command.GitCommandService",
        FakeGitCommandService,
    )
    monkeypatch.setattr(
        "app.modules.claude_worker.services.llm_service.LLMService",
        FailingLlmService,
    )

    with pytest.raises(routes.HTTPException) as exc:
        await routes.generate_commit_message(
            7,
            body=schemas.GenerateMessageRequest(provider="claude"),
            db=FakeDb(),
        )

    assert exc.value.status_code == 400
