"""
Git Repository Status Manager — RIGHT-BICEP + Correct 종합 테스트

RIGHT-BICEP:
  R - Right: 정상 케이스의 결과가 올바른가?
  I - Inverse: 역연산으로 검증 가능한가?
  C - Cross-check: 다른 방법으로 교차 검증 가능한가?
  E - Error: 에러/예외 상황이 올바르게 처리되는가?
  B - Boundary: 경계값이 올바르게 처리되는가?
  P - Performance: (이 테스트에서는 생략)

Correct:
  Conformance - 형식 준수
  Ordering - 정렬 순서
  Range - 값 범위
  Reference - 참조 무결성
  Existence - 존재/비존재
  Cardinality - 개수
  Time - 시간 순서
"""

import asyncio
import os
import subprocess
import tempfile
import shutil

import pytest
from fastapi.testclient import TestClient


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="session")
def temp_git_repo_base():
    """세션 레벨 임시 git 레포 베이스 디렉토리."""
    base = tempfile.mkdtemp(prefix="git_repos_test_")
    yield base
    shutil.rmtree(base, ignore_errors=True)


def _init_git_repo(path: str, initial_commit: bool = True):
    """헬퍼: 주어진 경로에 git repo를 초기화한다."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=path, capture_output=True)
    if initial_commit:
        readme = os.path.join(path, "README.md")
        with open(readme, "w") as f:
            f.write("# Test Repo\n")
        subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=path, capture_output=True)


@pytest.fixture
def temp_git_repo(temp_git_repo_base):
    """함수 레벨 임시 git 레포 (초기 커밋 포함)."""
    repo_path = tempfile.mkdtemp(dir=temp_git_repo_base)
    _init_git_repo(repo_path)
    yield repo_path
    shutil.rmtree(repo_path, ignore_errors=True)


@pytest.fixture
def temp_git_repo_dirty(temp_git_repo):
    """dirty 상태의 git 레포 (미커밋 변경사항 존재)."""
    with open(os.path.join(temp_git_repo, "dirty.txt"), "w") as f:
        f.write("dirty content\n")
    return temp_git_repo


@pytest.fixture
def temp_discover_base(temp_git_repo_base):
    """discover 테스트용: 하위에 여러 git 레포 포함."""
    discover_dir = os.path.join(temp_git_repo_base, "discover_test")
    os.makedirs(discover_dir, exist_ok=True)

    # 3개의 git 레포
    for name in ["repo-a", "repo-b", "repo-c"]:
        _init_git_repo(os.path.join(discover_dir, name))

    # 1개의 비-git 디렉토리
    os.makedirs(os.path.join(discover_dir, "not-a-repo"), exist_ok=True)

    yield discover_dir
    shutil.rmtree(discover_dir, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _ensure_git_repos_tables(test_db_engine):
    """git_repos 관련 테이블이 test DB에 생성되도록 보장."""
    from app.models.bootstrap import load_all_models
    from app.core.database import Base
    load_all_models()
    Base.metadata.create_all(bind=test_db_engine)


@pytest.fixture
def api_client(test_db_session):
    """FastAPI TestClient with DB dependency override."""
    from app.main import app
    from app.core.database import get_db

    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# ============================================================
# 1. GitCommandService — 단위 테스트
# ============================================================

class TestGitCommandServiceRight:
    """RIGHT: 정상 결과 검증."""

    async def test_get_status_clean(self, temp_git_repo):
        """clean 레포의 status가 정확한가."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()
        status = await git.get_status(temp_git_repo)

        assert status.status == "clean"
        assert status.branch == "master" or status.branch == "main"
        assert status.staged == []
        assert status.unstaged == []
        assert status.untracked == []

    async def test_get_status_dirty_untracked(self, temp_git_repo_dirty):
        """untracked 파일이 있으면 dirty이고 untracked 목록에 포함."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()
        status = await git.get_status(temp_git_repo_dirty)

        assert status.status == "dirty"
        assert "dirty.txt" in status.untracked

    async def test_get_status_staged(self, temp_git_repo):
        """staged 파일이 올바르게 분류되는가."""
        from app.modules.git_repos.services.git_command import GitCommandService

        staged_file = os.path.join(temp_git_repo, "staged.txt")
        with open(staged_file, "w") as f:
            f.write("staged\n")
        subprocess.run(["git", "add", "staged.txt"], cwd=temp_git_repo, capture_output=True)

        git = GitCommandService()
        status = await git.get_status(temp_git_repo)

        assert status.status == "dirty"
        assert "staged.txt" in status.staged

    async def test_get_diff(self, temp_git_repo):
        """diff 결과에 변경 내용이 포함되는가."""
        from app.modules.git_repos.services.git_command import GitCommandService

        readme = os.path.join(temp_git_repo, "README.md")
        with open(readme, "a") as f:
            f.write("new line\n")

        git = GitCommandService()
        diff = await git.get_diff(temp_git_repo)
        assert "+new line" in diff

    async def test_get_diff_staged(self, temp_git_repo):
        """--cached diff가 staged 변경만 반환하는가."""
        from app.modules.git_repos.services.git_command import GitCommandService

        f1 = os.path.join(temp_git_repo, "README.md")
        with open(f1, "a") as f:
            f.write("staged change\n")
        subprocess.run(["git", "add", "README.md"], cwd=temp_git_repo, capture_output=True)

        f2 = os.path.join(temp_git_repo, "unstaged.txt")
        with open(f2, "w") as f:
            f.write("not staged\n")

        git = GitCommandService()
        staged_diff = await git.get_diff(temp_git_repo, staged=True)
        assert "+staged change" in staged_diff
        assert "not staged" not in staged_diff

    async def test_get_file_diff(self, temp_git_repo):
        """특정 파일의 diff만 반환."""
        from app.modules.git_repos.services.git_command import GitCommandService

        # 2개 파일 변경
        for name, content in [("README.md", "change1\n"), ("other.txt", "change2\n")]:
            with open(os.path.join(temp_git_repo, name), "a" if name == "README.md" else "w") as f:
                f.write(content)
        subprocess.run(["git", "add", "other.txt"], cwd=temp_git_repo, capture_output=True)

        git = GitCommandService()
        file_diff = await git.get_file_diff(temp_git_repo, "README.md")
        assert "change1" in file_diff
        assert "change2" not in file_diff

    async def test_get_log(self, temp_git_repo):
        """커밋 로그가 올바른 형식으로 반환되는가."""
        from app.modules.git_repos.services.git_command import GitCommandService

        # 추가 커밋 2개
        for i in range(2):
            with open(os.path.join(temp_git_repo, f"file{i}.txt"), "w") as f:
                f.write(f"content{i}\n")
            subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"commit {i}"], cwd=temp_git_repo, capture_output=True)

        git = GitCommandService()
        logs = await git.get_log(temp_git_repo, n=5)

        # Cardinality: 3개 커밋 (initial + 2)
        assert len(logs) == 3
        # Conformance: LogEntry 필드 형식
        assert len(logs[0].hash) == 40
        assert len(logs[0].short_hash) == 7
        assert logs[0].author == "Tester"
        # Ordering: 최신 순
        assert logs[0].message == "commit 1"
        assert logs[1].message == "commit 0"
        assert logs[2].message == "initial commit"

    async def test_stage_and_commit(self, temp_git_repo):
        """stage → commit 워크플로우가 정상 작동하는가."""
        from app.modules.git_repos.services.git_command import GitCommandService

        with open(os.path.join(temp_git_repo, "new.txt"), "w") as f:
            f.write("hello\n")

        git = GitCommandService()

        # stage
        ok, _, _ = await git.stage_files(temp_git_repo, ["new.txt"])
        assert ok is True

        # commit
        ok, stdout, _ = await git.commit(temp_git_repo, "test: add new file")
        assert ok is True
        assert "test: add new file" in stdout or "1 file changed" in stdout

        # Cross-check: log에 반영되었는가
        logs = await git.get_log(temp_git_repo, n=1)
        assert logs[0].message == "test: add new file"

    async def test_stage_all(self, temp_git_repo_dirty):
        """stage_all이 모든 파일을 스테이징하는가."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()

        ok, _, _ = await git.stage_all(temp_git_repo_dirty)
        assert ok is True

        status = await git.get_status(temp_git_repo_dirty)
        assert "dirty.txt" in status.staged
        assert status.untracked == []

    async def test_unstage_files(self, temp_git_repo):
        """unstage가 staged → unstaged로 전환하는가 (Inverse)."""
        from app.modules.git_repos.services.git_command import GitCommandService

        with open(os.path.join(temp_git_repo, "x.txt"), "w") as f:
            f.write("x\n")

        git = GitCommandService()
        await git.stage_files(temp_git_repo, ["x.txt"])

        # 확인: staged
        s = await git.get_status(temp_git_repo)
        assert "x.txt" in s.staged

        # Inverse: unstage
        ok, _, _ = await git.unstage_files(temp_git_repo, ["x.txt"])
        assert ok is True

        s2 = await git.get_status(temp_git_repo)
        assert "x.txt" not in s2.staged
        assert "x.txt" in s2.untracked

    async def test_stash_save_and_pop(self, temp_git_repo):
        """stash save → pop이 변경사항을 보존하는가 (Inverse)."""
        from app.modules.git_repos.services.git_command import GitCommandService

        readme = os.path.join(temp_git_repo, "README.md")
        with open(readme, "a") as f:
            f.write("stash me\n")

        git = GitCommandService()

        # stash save
        ok, _, _ = await git.stash_save(temp_git_repo, "test stash")
        assert ok is True
        s = await git.get_status(temp_git_repo)
        assert s.status == "clean"

        # stash pop (Inverse)
        ok, _, _ = await git.stash_pop(temp_git_repo)
        assert ok is True
        s2 = await git.get_status(temp_git_repo)
        assert s2.status == "dirty"
        assert "README.md" in s2.unstaged


class TestGitCommandServiceError:
    """ERROR: 에러 조건 처리."""

    async def test_dangerous_arg_rejected(self):
        """위험한 인자(--force, --hard 등)가 거부되는가."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()

        with pytest.raises(PermissionError, match="금지된 git 인자"):
            await git._run_git(".", "push", "--force")

        with pytest.raises(PermissionError, match="금지된 git 인자"):
            await git._run_git(".", "reset", "--hard")

        with pytest.raises(PermissionError, match="금지된 git 인자"):
            await git._run_git(".", "branch", "-D")

        with pytest.raises(PermissionError, match="금지된 git 인자"):
            await git._run_git(".", "clean")

    async def test_invalid_repo_path(self):
        """존재하지 않는 경로에서 git status가 에러를 반환하는가."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()
        status = await git.get_status("C:\\nonexistent\\path\\repo")
        assert status.status == "unknown"
        assert status.branch == "unknown"

    async def test_stage_empty_files(self, temp_git_repo):
        """빈 파일 목록으로 stage/unstage 시 적절한 에러."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()

        ok, _, stderr = await git.stage_files(temp_git_repo, [])
        assert ok is False
        assert "비어 있습니다" in stderr

        ok, _, stderr = await git.unstage_files(temp_git_repo, [])
        assert ok is False
        assert "비어 있습니다" in stderr

    async def test_commit_nothing_to_commit(self, temp_git_repo):
        """커밋할 것이 없을 때 실패 반환."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()
        ok, _, stderr = await git.commit(temp_git_repo, "empty commit")
        assert ok is False

    async def test_stash_pop_empty(self, temp_git_repo):
        """stash가 비어있을 때 pop 실패."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()
        ok, _, _ = await git.stash_pop(temp_git_repo)
        assert ok is False


class TestGitCommandServiceBoundary:
    """BOUNDARY: 경계값 테스트."""

    async def test_get_log_n_zero_returns_empty(self, temp_git_repo):
        """n=0으로 로그 조회 시 빈 목록."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()
        # git log -0 → 출력 없음
        logs = await git.get_log(temp_git_repo, n=0)
        assert logs == []

    async def test_get_log_exceeding_count(self, temp_git_repo):
        """실제 커밋보다 큰 n으로 조회해도 에러 없음."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()
        logs = await git.get_log(temp_git_repo, n=1000)
        assert len(logs) == 1  # initial commit만

    async def test_status_no_commits_yet(self, temp_git_repo_base):
        """커밋 없는 신규 레포에서 status 처리."""
        from app.modules.git_repos.services.git_command import GitCommandService
        repo_path = os.path.join(temp_git_repo_base, "empty-repo")
        _init_git_repo(repo_path, initial_commit=False)

        git = GitCommandService()
        status = await git.get_status(repo_path)
        # 브랜치는 있지만 커밋이 없는 상태
        assert status.status == "clean" or status.branch in ("master", "main", "초기 커밋 없음")

        shutil.rmtree(repo_path, ignore_errors=True)

    async def test_rename_file_parsing(self, temp_git_repo):
        """파일 이름 변경(rename) 시 status 파싱이 정확한가."""
        from app.modules.git_repos.services.git_command import GitCommandService

        # rename 시뮬레이션
        old_file = os.path.join(temp_git_repo, "README.md")
        new_file = os.path.join(temp_git_repo, "RENAMED.md")
        os.rename(old_file, new_file)
        subprocess.run(["git", "add", "-A"], cwd=temp_git_repo, capture_output=True)

        git = GitCommandService()
        status = await git.get_status(temp_git_repo)
        assert status.status == "dirty"
        # rename은 staged에 나타남
        assert len(status.staged) > 0

    async def test_special_chars_in_commit_message(self, temp_git_repo):
        """한글/특수문자 커밋 메시지가 정상 처리되는가."""
        from app.modules.git_repos.services.git_command import GitCommandService

        with open(os.path.join(temp_git_repo, "test.txt"), "w") as f:
            f.write("test\n")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True)

        git = GitCommandService()
        msg = "feat: 한글 커밋 메시지 & 특수문자 !@#$%"
        ok, _, _ = await git.commit(temp_git_repo, msg)
        assert ok is True

        logs = await git.get_log(temp_git_repo, n=1)
        assert "한글 커밋 메시지" in logs[0].message


# ============================================================
# 2. GitRepoService — 서비스 레벨 테스트
# ============================================================

class TestRepoServiceCRUD:
    """CRUD 정상 및 에러 케이스."""

    async def test_create_and_list(self, test_db_session, temp_git_repo):
        """등록 → 목록 조회 (Right + Existence)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()

        repo = await svc.create_repo(test_db_session, temp_git_repo, "test-alias")
        assert repo.path == os.path.normpath(temp_git_repo)
        assert repo.alias == "test-alias"
        assert repo.is_active is True

        repos = svc.list_repos(test_db_session)
        assert any(r.id == repo.id for r in repos)

    async def test_create_duplicate_rejected(self, test_db_session, temp_git_repo):
        """중복 경로 등록 시 ValueError (Error)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()

        await svc.create_repo(test_db_session, temp_git_repo)
        with pytest.raises(ValueError, match="이미 등록된"):
            await svc.create_repo(test_db_session, temp_git_repo)

    async def test_create_invalid_path_rejected(self, test_db_session):
        """존재하지 않는 경로 등록 시 ValueError (Error)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()

        with pytest.raises(ValueError, match="유효한 git 레포지토리가 아닙니다"):
            await svc.create_repo(test_db_session, "C:\\nonexistent\\path")

    async def test_update_repo(self, test_db_session, temp_git_repo):
        """수정 후 값이 반영되는가 (Right)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()

        repo = await svc.create_repo(test_db_session, temp_git_repo, "before")
        updated = svc.update_repo(test_db_session, repo.id, alias="after", sort_order=99)

        assert updated.alias == "after"
        assert updated.sort_order == 99

    async def test_update_nonexistent(self, test_db_session):
        """존재하지 않는 repo 수정 시 None 반환 (Existence)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()
        result = svc.update_repo(test_db_session, 99999, alias="x")
        assert result is None

    async def test_delete_and_cascade(self, test_db_session, temp_git_repo):
        """삭제 시 operation_logs도 cascade 삭제 (Reference)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        from app.modules.git_repos.models import GitOperationLog
        svc = GitRepoService()

        repo = await svc.create_repo(test_db_session, temp_git_repo)
        svc.log_operation(test_db_session, repo.id, "test", "success", "msg", "detail")

        # 로그 존재 확인
        logs = test_db_session.query(GitOperationLog).filter_by(repo_id=repo.id).all()
        assert len(logs) == 1

        # 삭제
        assert svc.delete_repo(test_db_session, repo.id) is True

        # cascade 확인
        logs = test_db_session.query(GitOperationLog).filter_by(repo_id=repo.id).all()
        assert len(logs) == 0

    async def test_delete_nonexistent(self, test_db_session):
        """존재하지 않는 repo 삭제 시 False (Existence)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()
        assert svc.delete_repo(test_db_session, 99999) is False


class TestRepoServiceDiscover:
    """discover_repos 테스트."""

    async def test_discover_finds_git_repos(self, temp_discover_base):
        """git 레포만 발견하는가 (Right + Cardinality)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()
        paths = await svc.discover_repos(temp_discover_base)

        assert len(paths) == 3
        basenames = [os.path.basename(p) for p in paths]
        assert "repo-a" in basenames
        assert "repo-b" in basenames
        assert "repo-c" in basenames
        assert "not-a-repo" not in basenames

    async def test_discover_sorted(self, temp_discover_base):
        """결과가 정렬되어 반환되는가 (Ordering)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()
        paths = await svc.discover_repos(temp_discover_base)
        assert paths == sorted(paths)

    async def test_discover_invalid_path(self):
        """존재하지 않는 경로로 discover 시 에러 (Error)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()
        with pytest.raises(ValueError, match="디렉토리가 존재하지 않습니다"):
            await svc.discover_repos("C:\\nonexistent\\path")


class TestRepoServiceOperations:
    """commit/push/pull 등 작업 실행 + 로그 기록."""

    async def test_commit_repo_with_log(self, test_db_session, temp_git_repo):
        """커밋 성공 시 OperationLog가 기록되는가 (Cross-check)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        from app.modules.git_repos.models import GitOperationLog
        svc = GitRepoService()

        repo = await svc.create_repo(test_db_session, temp_git_repo)

        # 파일 추가
        with open(os.path.join(temp_git_repo, "commit_test.txt"), "w") as f:
            f.write("test\n")

        result = await svc.commit_repo(test_db_session, repo, "test: commit log", stage_all=True)
        assert result.success is True

        # Cross-check: DB 로그
        logs = test_db_session.query(GitOperationLog).filter_by(repo_id=repo.id, operation="commit").all()
        assert len(logs) >= 1
        assert logs[0].status == "success"
        assert logs[0].message == "test: commit log"

    async def test_commit_nothing_fails(self, test_db_session, temp_git_repo):
        """커밋할 것이 없을 때 실패 + 로그 기록 (Error + Cross-check)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        from app.modules.git_repos.models import GitOperationLog
        svc = GitRepoService()

        repo = await svc.create_repo(test_db_session, temp_git_repo)
        result = await svc.commit_repo(test_db_session, repo, "empty")
        assert result.success is False

        logs = test_db_session.query(GitOperationLog).filter_by(repo_id=repo.id, operation="commit").all()
        assert any(l.status == "failure" for l in logs)

    async def test_refresh_status_updates_db(self, test_db_session, temp_git_repo):
        """refresh_status가 DB 캐시를 갱신하는가 (Cross-check)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()

        repo = await svc.create_repo(test_db_session, temp_git_repo)
        updated = await svc.refresh_status(test_db_session, repo)

        assert updated.last_status == "clean"
        assert updated.last_branch in ("master", "main")
        assert updated.last_checked_at is not None

    async def test_refresh_all_parallel(self, test_db_session, temp_git_repo_base):
        """refresh_all이 여러 레포를 병렬 갱신하는가 (Cardinality)."""
        from app.modules.git_repos.services.repo_service import GitRepoService
        svc = GitRepoService()

        repos = []
        for i in range(3):
            path = os.path.join(temp_git_repo_base, f"refresh_test_{i}")
            _init_git_repo(path)
            r = await svc.create_repo(test_db_session, path, f"refresh-{i}")
            repos.append(r)

        results = await svc.refresh_all(test_db_session)
        assert len(results) >= 3
        for r in results:
            assert r.last_status is not None

        # cleanup
        for path in [os.path.join(temp_git_repo_base, f"refresh_test_{i}") for i in range(3)]:
            shutil.rmtree(path, ignore_errors=True)


# ============================================================
# 3. API 라우트 — E2E 통합 테스트
# ============================================================

class TestAPIRouteCRUD:
    """API 레벨 CRUD 엔드포인트."""

    def test_list_repos_empty(self, api_client):
        """초기 상태에서 빈 목록 (Existence)."""
        resp = api_client.get("/api/v1/git-repos")
        assert resp.status_code == 200
        # 빈 배열이거나 이전 테스트 데이터 포함 가능
        assert isinstance(resp.json(), list)

    def test_create_repo(self, api_client, temp_git_repo):
        """레포 등록 → 201 (Right)."""
        resp = api_client.post("/api/v1/git-repos", json={
            "path": temp_git_repo,
            "alias": "api-test"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["alias"] == "api-test"
        assert data["is_active"] is True
        assert data["id"] > 0

    def test_create_duplicate_400(self, api_client, temp_git_repo):
        """중복 등록 → 400 (Error)."""
        api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        resp = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        assert resp.status_code == 400
        assert "이미 등록된" in resp.json()["detail"]

    def test_create_invalid_path_400(self, api_client):
        """잘못된 경로 → 400 (Error)."""
        resp = api_client.post("/api/v1/git-repos", json={"path": "C:\\no\\such\\path"})
        assert resp.status_code == 400

    def test_get_repo(self, api_client, temp_git_repo):
        """단건 조회 → 등록된 레포 데이터 반환 (Right)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo, "alias": "detail-test"})
        repo_id = create.json()["id"]

        resp = api_client.get(f"/api/v1/git-repos/{repo_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == repo_id
        assert data["alias"] == "detail-test"
        assert data["path"] == temp_git_repo

    def test_update_repo(self, api_client, temp_git_repo):
        """수정 → 값 반영 (Right)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.put(f"/api/v1/git-repos/{repo_id}", json={"alias": "updated", "sort_order": 5})
        assert resp.status_code == 200
        assert resp.json()["alias"] == "updated"
        assert resp.json()["sort_order"] == 5

    def test_update_nonexistent_404(self, api_client):
        """존재하지 않는 repo 수정 → 404 (Existence)."""
        resp = api_client.put("/api/v1/git-repos/99999", json={"alias": "x"})
        assert resp.status_code == 404

    def test_delete_repo(self, api_client, temp_git_repo):
        """삭제 → success (Right + Inverse)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.delete(f"/api/v1/git-repos/{repo_id}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Inverse: 다시 조회하면 404
        resp2 = api_client.get(f"/api/v1/git-repos/{repo_id}/status")
        assert resp2.status_code == 404

    def test_delete_nonexistent_404(self, api_client):
        """존재하지 않는 repo 삭제 → 404 (Existence)."""
        resp = api_client.delete("/api/v1/git-repos/99999")
        assert resp.status_code == 404


class TestAPIRouteDiscover:
    """discover 엔드포인트."""

    def test_discover(self, api_client, temp_discover_base):
        """git 레포 검색 결과 (Right + Cardinality)."""
        resp = api_client.get("/api/v1/git-repos/discover", params={"base_path": temp_discover_base})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert len(data["paths"]) == 3

    def test_discover_invalid_path(self, api_client):
        """존재하지 않는 경로 → 400 (Error)."""
        resp = api_client.get("/api/v1/git-repos/discover", params={"base_path": "C:\\no\\such\\path"})
        assert resp.status_code == 400


class TestAPIRouteStatus:
    """상태 조회 엔드포인트."""

    def test_get_status(self, api_client, temp_git_repo):
        """상세 상태 조회 (Right)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.get(f"/api/v1/git-repos/{repo_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "clean"
        assert data["branch"] in ("master", "main")
        assert isinstance(data["staged"], list)
        assert isinstance(data["unstaged"], list)
        assert isinstance(data["untracked"], list)

    def test_get_status_repeated_same_process(self, api_client, temp_git_repo):
        """첫 상태 조회와 동일 프로세스 재조회 모두 bootstrap 오류 없이 통과해야 한다."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        first = api_client.get(f"/api/v1/git-repos/{repo_id}/status")
        second = api_client.get(f"/api/v1/git-repos/{repo_id}/status")

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["status"] == "clean"
        assert second.json()["status"] == "clean"

    def test_get_diff(self, api_client, temp_git_repo):
        """diff 조회 (Right)."""
        # 파일 변경
        with open(os.path.join(temp_git_repo, "README.md"), "a") as f:
            f.write("diff test line\n")

        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.get(f"/api/v1/git-repos/{repo_id}/diff")
        assert resp.status_code == 200
        assert "+diff test line" in resp.json()["diff"]

    def test_get_log(self, api_client, temp_git_repo):
        """커밋 로그 조회 (Right + Conformance)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.get(f"/api/v1/git-repos/{repo_id}/log", params={"n": 10})
        assert resp.status_code == 200
        logs = resp.json()
        assert len(logs) >= 1
        assert "hash" in logs[0]
        assert "short_hash" in logs[0]
        assert "message" in logs[0]

    def test_refresh_single_returns_task(self, api_client, temp_git_repo):
        """단일 레포 refresh → task_id 즉시 반환 (비동기 전환 후)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.post(f"/api/v1/git-repos/{repo_id}/refresh")
        # Redis 미연결 시 503, 연결 시 200
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            data = resp.json()
            assert "task_id" in data
            assert data["status"] == "pending"

    def test_refresh_all_returns_task(self, api_client, temp_git_repo):
        """전체 refresh → task_id 즉시 반환 (비동기 전환 후)."""
        api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})

        resp = api_client.post("/api/v1/git-repos/refresh-all")
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            data = resp.json()
            assert "task_id" in data
            assert data["status"] == "pending"


def _assert_task_response(resp):
    """SLOW 엔드포인트는 task_id 즉시 반환 또는 503(Redis 미연결) 허용."""
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"
    return resp.status_code == 200


class TestAPIRouteOperations:
    """작업 실행 엔드포인트 — 비동기 큐 발행 방식."""

    def test_stage_files_returns_task(self, api_client, temp_git_repo):
        """파일 스테이징 → task_id 즉시 반환 (Right)."""
        with open(os.path.join(temp_git_repo, "stage_test.txt"), "w") as f:
            f.write("stage me\n")

        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.post(f"/api/v1/git-repos/{repo_id}/stage", json={"files": ["stage_test.txt"]})
        _assert_task_response(resp)

    def test_unstage_files_returns_task(self, api_client, temp_git_repo):
        """파일 언스테이징 → task_id 즉시 반환 (Right)."""
        with open(os.path.join(temp_git_repo, "unstage_test.txt"), "w") as f:
            f.write("unstage me\n")
        subprocess.run(["git", "add", "unstage_test.txt"], cwd=temp_git_repo, capture_output=True)

        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.post(f"/api/v1/git-repos/{repo_id}/unstage", json={"files": ["unstage_test.txt"]})
        _assert_task_response(resp)

    def test_commit_returns_task(self, api_client, temp_git_repo):
        """커밋 → task_id 즉시 반환 (Right)."""
        with open(os.path.join(temp_git_repo, "commit_api.txt"), "w") as f:
            f.write("commit via api\n")

        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.post(f"/api/v1/git-repos/{repo_id}/commit", json={
            "message": "test: api commit",
            "stage_all": True
        })
        _assert_task_response(resp)

    def test_push_returns_task(self, api_client, temp_git_repo):
        """푸시 → task_id 즉시 반환 (Right)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]
        resp = api_client.post(f"/api/v1/git-repos/{repo_id}/push")
        _assert_task_response(resp)

    def test_pull_returns_task(self, api_client, temp_git_repo):
        """풀 → task_id 즉시 반환 (Right)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]
        resp = api_client.post(f"/api/v1/git-repos/{repo_id}/pull")
        _assert_task_response(resp)

    def test_fetch_returns_task(self, api_client, temp_git_repo):
        """페치 → task_id 즉시 반환 (Right)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]
        resp = api_client.post(f"/api/v1/git-repos/{repo_id}/fetch")
        _assert_task_response(resp)

    def test_stash_returns_task(self, api_client, temp_git_repo):
        """스태시 → task_id 즉시 반환 (Right)."""
        with open(os.path.join(temp_git_repo, "README.md"), "a") as f:
            f.write("stash api test\n")
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]
        resp = api_client.post(f"/api/v1/git-repos/{repo_id}/stash", json={"message": "api stash"})
        _assert_task_response(resp)

    def test_stash_pop_returns_task(self, api_client, temp_git_repo):
        """스태시 복원 → task_id 즉시 반환 (Right)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]
        resp = api_client.post(f"/api/v1/git-repos/{repo_id}/stash-pop")
        _assert_task_response(resp)

    def test_operations_log(self, api_client, temp_git_repo):
        """작업 이력 조회 엔드포인트 응답 확인."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.get(f"/api/v1/git-repos/{repo_id}/operations", params={"limit": 50})
        assert resp.status_code == 200
        logs = resp.json()
        assert isinstance(logs, list)

    def test_task_result_pending(self, api_client):
        """존재하지 않는 task_id 조회 → pending 반환 (Existence)."""
        resp = api_client.get("/api/v1/git-repos/tasks/nonexistent-task-id-12345")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "nonexistent-task-id-12345"
        assert data["status"] == "pending"


class TestAPIRouteBatch:
    """일괄 작업 엔드포인트 — 비동기 큐 발행 방식."""

    def test_batch_commit_returns_task(self, api_client, temp_git_repo_base):
        """일괄 커밋 → task_id 즉시 반환 (Right)."""
        repo_ids = []
        for i in range(2):
            path = os.path.join(temp_git_repo_base, f"batch_commit_{i}")
            _init_git_repo(path)
            create = api_client.post("/api/v1/git-repos", json={"path": path, "alias": f"batch-{i}"})
            repo_ids.append(create.json()["id"])

        resp = api_client.post("/api/v1/git-repos/batch-commit", json={
            "repo_ids": repo_ids,
            "message": "test: batch commit"
        })
        _assert_task_response(resp)

        # cleanup
        for i in range(2):
            shutil.rmtree(os.path.join(temp_git_repo_base, f"batch_commit_{i}"), ignore_errors=True)

    def test_batch_push_returns_task(self, api_client, temp_git_repo):
        """일괄 푸시 → task_id 즉시 반환 (Right)."""
        create = api_client.post("/api/v1/git-repos", json={"path": temp_git_repo})
        repo_id = create.json()["id"]

        resp = api_client.post("/api/v1/git-repos/batch-push", json={
            "repo_ids": [repo_id]
        })
        _assert_task_response(resp)


class TestAPIRouteNonexistent:
    """존재하지 않는 repo에 대한 엔드포인트 응답 검증 (Existence).

    SLOW 엔드포인트는 repo 검증 후 큐 발행하므로 404 반환.
    Redis 미연결 시 503 반환 가능.
    """

    def test_get_repo_404(self, api_client):
        assert api_client.get("/api/v1/git-repos/99999").status_code == 404

    def test_status_404(self, api_client):
        assert api_client.get("/api/v1/git-repos/99999/status").status_code == 404

    def test_diff_404(self, api_client):
        assert api_client.get("/api/v1/git-repos/99999/diff").status_code == 404

    def test_log_404(self, api_client):
        assert api_client.get("/api/v1/git-repos/99999/log").status_code == 404

    def test_refresh_404(self, api_client):
        assert api_client.post("/api/v1/git-repos/99999/refresh").status_code == 404

    def test_stage_404(self, api_client):
        assert api_client.post("/api/v1/git-repos/99999/stage", json={"files": ["x"]}).status_code == 404

    def test_unstage_404(self, api_client):
        assert api_client.post("/api/v1/git-repos/99999/unstage", json={"files": ["x"]}).status_code == 404

    def test_commit_404(self, api_client):
        assert api_client.post("/api/v1/git-repos/99999/commit", json={"message": "x"}).status_code == 404

    def test_push_404(self, api_client):
        assert api_client.post("/api/v1/git-repos/99999/push").status_code == 404

    def test_pull_404(self, api_client):
        assert api_client.post("/api/v1/git-repos/99999/pull").status_code == 404

    def test_fetch_404(self, api_client):
        assert api_client.post("/api/v1/git-repos/99999/fetch").status_code == 404

    def test_stash_404(self, api_client):
        assert api_client.post("/api/v1/git-repos/99999/stash", json={}).status_code == 404

    def test_stash_pop_404(self, api_client):
        assert api_client.post("/api/v1/git-repos/99999/stash-pop").status_code == 404

    def test_operations_404(self, api_client):
        assert api_client.get("/api/v1/git-repos/99999/operations").status_code == 404


# ============================================================
# Smart Push 테스트
# ============================================================

@pytest.mark.asyncio
class TestPullRebase:
    """pull_rebase 메서드 테스트."""

    async def test_pull_rebase_success(self, temp_git_repo):
        """pull_rebase: 동일 레포(origin 없음) — origin 없을 때 실패 반환."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()
        ok, stdout, stderr = await git.pull_rebase(temp_git_repo)
        # origin이 없으므로 실패하지만, 메서드 자체가 정상 동작해야 함
        assert isinstance(ok, bool)
        assert isinstance(stdout, str)
        assert isinstance(stderr, str)

    async def test_stash_save_include_untracked(self, temp_git_repo):
        """include_untracked=True 시 untracked 파일도 stash 됨."""
        from app.modules.git_repos.services.git_command import GitCommandService
        git = GitCommandService()

        # untracked 파일 생성
        new_file = os.path.join(temp_git_repo, "untracked.txt")
        with open(new_file, "w") as f:
            f.write("untracked\n")

        s_before = await git.get_status(temp_git_repo)
        assert "untracked.txt" in s_before.untracked

        ok, _, _ = await git.stash_save(temp_git_repo, "test", include_untracked=True)
        assert ok is True

        s_after = await git.get_status(temp_git_repo)
        assert s_after.status == "clean"
        assert "untracked.txt" not in s_after.untracked

        # stash pop으로 복원 확인
        ok_pop, _, _ = await git.stash_pop(temp_git_repo)
        assert ok_pop is True
        s_restored = await git.get_status(temp_git_repo)
        assert "untracked.txt" in s_restored.untracked


@pytest.mark.asyncio
class TestSmartPushRepo:
    """smart_push_repo 서비스 테스트."""

    def _make_repo_mock(self, path: str):
        from unittest.mock import MagicMock
        repo = MagicMock()
        repo.id = 1
        repo.path = path
        return repo

    def _make_db_mock(self):
        from unittest.mock import MagicMock
        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        return db

    async def test_smart_push_direct_success(self, temp_git_repo):
        """push 첫 시도 성공 시 바로 반환 (재시도 없음)."""
        from unittest.mock import AsyncMock, patch
        from app.modules.git_repos.services.repo_service import GitRepoService

        svc = GitRepoService()
        repo = self._make_repo_mock(temp_git_repo)
        db = self._make_db_mock()

        with patch.object(svc._git, "push", new=AsyncMock(return_value=(True, "ok", ""))) as mock_push, \
             patch.object(svc, "log_operation"), \
             patch.object(svc, "refresh_status", new=AsyncMock()):
            result = await svc.smart_push_repo(db, repo)

        assert result.success is True
        mock_push.assert_called_once()

    async def test_smart_push_non_rebaseable_error(self, temp_git_repo):
        """rejected/fetch first 없는 에러 → 재시도 없이 에러 반환."""
        from unittest.mock import AsyncMock, patch
        from app.modules.git_repos.services.repo_service import GitRepoService

        svc = GitRepoService()
        repo = self._make_repo_mock(temp_git_repo)
        db = self._make_db_mock()

        with patch.object(svc._git, "push", new=AsyncMock(return_value=(False, "", "some unrelated error"))), \
             patch.object(svc, "log_operation"):
            result = await svc.smart_push_repo(db, repo)

        assert result.success is False

    async def test_smart_push_clean_rebase(self, temp_git_repo):
        """push 실패(rejected) → clean 상태 → pull_rebase → push 성공."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.modules.git_repos.services.repo_service import GitRepoService
        from app.modules.git_repos.schemas import RepoStatus

        svc = GitRepoService()
        repo = self._make_repo_mock(temp_git_repo)
        db = self._make_db_mock()

        clean_status = RepoStatus(branch="main", status="clean")

        push_calls = [
            (False, "", "rejected: failed to push some refs"),
            (True, "pushed", ""),
        ]
        push_mock = AsyncMock(side_effect=push_calls)

        with patch.object(svc._git, "push", new=push_mock), \
             patch.object(svc._git, "get_status", new=AsyncMock(return_value=clean_status)), \
             patch.object(svc._git, "pull_rebase", new=AsyncMock(return_value=(True, "rebased", ""))) as mock_rebase, \
             patch.object(svc, "log_operation"), \
             patch.object(svc, "refresh_status", new=AsyncMock()):
            result = await svc.smart_push_repo(db, repo)

        assert result.success is True
        mock_rebase.assert_called_once()
        assert push_mock.call_count == 2

    async def test_smart_push_dirty_stash_rebase(self, temp_git_repo):
        """push 실패(rejected) → dirty → stash → pull_rebase → stash_pop → push 성공."""
        from unittest.mock import AsyncMock, patch
        from app.modules.git_repos.services.repo_service import GitRepoService
        from app.modules.git_repos.schemas import RepoStatus

        svc = GitRepoService()
        repo = self._make_repo_mock(temp_git_repo)
        db = self._make_db_mock()

        dirty_status = RepoStatus(branch="main", status="dirty")

        push_calls = [
            (False, "", "fetch first"),
            (True, "pushed", ""),
        ]
        push_mock = AsyncMock(side_effect=push_calls)

        with patch.object(svc._git, "push", new=push_mock), \
             patch.object(svc._git, "get_status", new=AsyncMock(return_value=dirty_status)), \
             patch.object(svc._git, "stash_save", new=AsyncMock(return_value=(True, "stashed", ""))) as mock_stash, \
             patch.object(svc._git, "pull_rebase", new=AsyncMock(return_value=(True, "rebased", ""))) as mock_rebase, \
             patch.object(svc._git, "stash_pop", new=AsyncMock(return_value=(True, "popped", ""))) as mock_pop, \
             patch.object(svc, "log_operation"), \
             patch.object(svc, "refresh_status", new=AsyncMock()):
            result = await svc.smart_push_repo(db, repo)

        assert result.success is True
        mock_stash.assert_called_once()
        mock_rebase.assert_called_once()
        mock_pop.assert_called_once()
        assert push_mock.call_count == 2

    async def test_smart_push_rebase_conflict(self, temp_git_repo):
        """pull_rebase 실패 → rebase_abort + stash_pop 호출 후 에러 반환."""
        from unittest.mock import AsyncMock, patch
        from app.modules.git_repos.services.repo_service import GitRepoService
        from app.modules.git_repos.schemas import RepoStatus

        svc = GitRepoService()
        repo = self._make_repo_mock(temp_git_repo)
        db = self._make_db_mock()

        dirty_status = RepoStatus(branch="main", status="dirty")

        with patch.object(svc._git, "push", new=AsyncMock(return_value=(False, "", "rejected: non-fast-forward"))), \
             patch.object(svc._git, "get_status", new=AsyncMock(return_value=dirty_status)), \
             patch.object(svc._git, "stash_save", new=AsyncMock(return_value=(True, "stashed", ""))), \
             patch.object(svc._git, "pull_rebase", new=AsyncMock(return_value=(False, "", "conflict"))) as mock_rebase, \
             patch.object(svc._git, "rebase_abort", new=AsyncMock(return_value=(True, "", ""))) as mock_abort, \
             patch.object(svc._git, "stash_pop", new=AsyncMock(return_value=(True, "popped", ""))) as mock_pop, \
             patch.object(svc, "log_operation"):
            result = await svc.smart_push_repo(db, repo)

        assert result.success is False
        mock_rebase.assert_called_once()
        mock_abort.assert_called_once()
        mock_pop.assert_called_once()
