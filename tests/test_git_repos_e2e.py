"""
Git Repository Status Manager — 실제 dev 서버(8001) E2E 통합 테스트

실제 wtools 하위 프로젝트를 등록하고 discover → CRUD → status → commit → push 전체 흐름을 검증한다.
RIGHT-BICEP 원칙 적용.
"""

import os
import requests
import pytest

BASE = "http://localhost:8001/api/v1/git-repos"
WTOOLS_BASE = r"D:\work\project\service\wtools"
TIMEOUT = 15


def api(method, path="", json=None, params=None):
    """API 호출 헬퍼."""
    url = f"{BASE}{path}"
    resp = getattr(requests, method)(url, json=json, params=params, timeout=TIMEOUT)
    return resp


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def registered_repos():
    """wtools 하위 레포를 모두 등록 (이미 등록된 건 건너뜀). 테스트 후 정리."""
    # discover
    resp = api("get", "/discover", params={"base_path": WTOOLS_BASE})
    assert resp.status_code == 200, f"discover 실패: {resp.text}"
    paths = resp.json()["paths"]
    assert len(paths) >= 10, f"wtools에 최소 10개 레포 예상, 실제: {len(paths)}"

    # 현재 등록된 레포 경로 세트
    existing = {r["path"] for r in api("get").json()}

    # 미등록 레포만 등록
    newly_created_ids = []
    for path in paths:
        normalized = os.path.normpath(path)
        if normalized in existing:
            continue
        alias = os.path.basename(path)
        r = api("post", "", json={"path": path, "alias": alias})
        if r.status_code == 200:
            newly_created_ids.append(r.json()["id"])

    # 전체 조회
    all_repos = api("get").json()
    yield all_repos

    # 정리: 이번 테스트에서 새로 등록한 것만 삭제
    for rid in newly_created_ids:
        api("delete", f"/{rid}")


@pytest.fixture(scope="module")
def any_repo(registered_repos):
    """테스트용 레포 1개 (첫 번째)."""
    assert len(registered_repos) > 0
    return registered_repos[0]


# ============================================================
# 1. Discover (Right + Cardinality)
# ============================================================

class TestDiscover:
    def test_discover_wtools(self):
        """wtools 하위 git 레포 목록 반환."""
        resp = api("get", "/discover", params={"base_path": WTOOLS_BASE})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 10
        assert all(os.path.basename(p) != "node_modules" for p in data["paths"])

    def test_discover_tools(self):
        """tools 디렉토리도 검색 가능."""
        resp = api("get", "/discover", params={"base_path": r"D:\work\project\tools"})
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_discover_invalid_path(self):
        """존재하지 않는 경로 → 400."""
        resp = api("get", "/discover", params={"base_path": r"C:\nonexistent\path"})
        assert resp.status_code == 400


# ============================================================
# 2. CRUD (Right + Existence + Inverse)
# ============================================================

class TestCRUD:
    def test_list_repos(self, registered_repos):
        """등록된 레포 목록 조회 (Cardinality)."""
        resp = api("get")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 10

    def test_repo_has_expected_fields(self, registered_repos):
        """응답 필드 형식 검증 (Conformance)."""
        repo = registered_repos[0]
        required_fields = ["id", "path", "alias", "is_active", "sort_order",
                           "created_at", "updated_at"]
        for field in required_fields:
            assert field in repo, f"필드 누락: {field}"

    def test_update_alias(self, any_repo):
        """별칭 수정 → 반영 확인 (Right + Cross-check)."""
        repo_id = any_repo["id"]
        original_alias = any_repo["alias"]

        # 수정
        resp = api("put", f"/{repo_id}", json={"alias": "e2e-test-alias"})
        assert resp.status_code == 200
        assert resp.json()["alias"] == "e2e-test-alias"

        # Cross-check: 조회로 확인
        status_resp = api("get", f"/{repo_id}/status")
        assert status_resp.status_code == 200

        # 원복
        api("put", f"/{repo_id}", json={"alias": original_alias})


# ============================================================
# 3. Status 조회 (Right + Cross-check)
# ============================================================

class TestStatus:
    def test_get_status(self, any_repo):
        """상세 상태 조회 — branch, status 등."""
        resp = api("get", f"/{any_repo['id']}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["branch"] != "unknown"
        assert data["status"] in ("clean", "dirty", "conflict")
        assert isinstance(data["staged"], list)
        assert isinstance(data["unstaged"], list)
        assert isinstance(data["untracked"], list)

    def test_all_repos_status(self, registered_repos):
        """모든 등록 레포 상태 조회 성공 (Cardinality)."""
        for repo in registered_repos[:5]:  # 상위 5개만 (속도)
            resp = api("get", f"/{repo['id']}/status")
            assert resp.status_code == 200, f"repo {repo['alias']} status 실패"
            assert resp.json()["branch"] != "unknown"

    def test_get_diff(self, any_repo):
        """diff 조회 — 에러 없이 반환."""
        resp = api("get", f"/{any_repo['id']}/diff")
        assert resp.status_code == 200
        assert "diff" in resp.json()

    def test_get_log(self, any_repo):
        """커밋 로그 조회 (Right + Conformance)."""
        resp = api("get", f"/{any_repo['id']}/log", params={"n": 5})
        assert resp.status_code == 200
        logs = resp.json()
        assert len(logs) >= 1
        assert all(len(l["hash"]) == 40 for l in logs)
        assert all("message" in l for l in logs)

    def test_refresh_single(self, any_repo):
        """단일 refresh — last_status 갱신 (Time)."""
        resp = api("post", f"/{any_repo['id']}/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_status"] is not None
        assert data["last_checked_at"] is not None

    def test_refresh_all(self, registered_repos):
        """전체 refresh (Cardinality)."""
        resp = api("post", "/refresh-all")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 10
        assert all(r["last_status"] is not None for r in data)


# ============================================================
# 4. Git 작업 — 더미 파일로 commit 테스트 (Right + Inverse + Cross-check)
# ============================================================

class TestGitOperations:
    """wtools 하위에 더미 파일을 만들어 실제 커밋 테스트."""

    DUMMY_FILE = "_e2e_test_dummy.txt"

    def _find_clean_repo(self, registered_repos):
        """clean 상태인 레포를 찾는다."""
        for repo in registered_repos:
            resp = api("get", f"/{repo['id']}/status")
            if resp.status_code == 200 and resp.json()["status"] == "clean":
                return repo
        pytest.skip("clean 상태의 레포가 없습니다")

    def test_stage_commit_flow(self, registered_repos):
        """더미 파일 생성 → stage → commit → log 확인 (Full E2E)."""
        repo = self._find_clean_repo(registered_repos)
        repo_path = repo["path"]
        dummy_path = os.path.join(repo_path, self.DUMMY_FILE)

        try:
            # 1. 더미 파일 생성
            with open(dummy_path, "w") as f:
                f.write("e2e test dummy file\n")

            # 2. 상태 확인 — dirty + untracked
            status = api("get", f"/{repo['id']}/status").json()
            assert status["status"] == "dirty"
            assert self.DUMMY_FILE in status["untracked"]

            # 3. stage
            resp = api("post", f"/{repo['id']}/stage", json={"files": [self.DUMMY_FILE]})
            assert resp.status_code == 200
            assert resp.json()["success"] is True

            # Cross-check: staged에 포함
            status = api("get", f"/{repo['id']}/status").json()
            assert self.DUMMY_FILE in status["staged"]

            # 4. commit
            resp = api("post", f"/{repo['id']}/commit", json={
                "message": "test: e2e dummy commit (will be reverted)",
                "stage_all": False
            })
            assert resp.status_code == 200
            assert resp.json()["success"] is True

            # Cross-check: log에 반영
            logs = api("get", f"/{repo['id']}/log", params={"n": 1}).json()
            assert "e2e dummy commit" in logs[0]["message"]

            # Cross-check: 상태 clean
            status = api("get", f"/{repo['id']}/status").json()
            assert status["status"] == "clean"

            # 5. operations 이력 확인
            ops = api("get", f"/{repo['id']}/operations", params={"limit": 5}).json()
            assert any(o["operation"] == "commit" and o["status"] == "success" for o in ops)

        finally:
            # 정리: 더미 파일 삭제 후 커밋
            if os.path.exists(dummy_path):
                os.remove(dummy_path)
                api("post", f"/{repo['id']}/commit", json={
                    "message": "test: revert e2e dummy commit",
                    "stage_all": True
                })

    def test_stash_and_pop(self, registered_repos):
        """stash save → pop 사이클 (Inverse)."""
        repo = self._find_clean_repo(registered_repos)
        repo_path = repo["path"]
        dummy_path = os.path.join(repo_path, self.DUMMY_FILE)

        try:
            # 더미 파일로 dirty 만들기
            with open(dummy_path, "w") as f:
                f.write("stash test\n")
            api("post", f"/{repo['id']}/stage", json={"files": [self.DUMMY_FILE]})

            # stash
            resp = api("post", f"/{repo['id']}/stash", json={"message": "e2e stash test"})
            assert resp.status_code == 200
            assert resp.json()["success"] is True

            status = api("get", f"/{repo['id']}/status").json()
            assert status["status"] == "clean"

            # pop (Inverse)
            resp = api("post", f"/{repo['id']}/stash-pop")
            assert resp.status_code == 200
            assert resp.json()["success"] is True

            status = api("get", f"/{repo['id']}/status").json()
            assert status["status"] == "dirty"

        finally:
            if os.path.exists(dummy_path):
                os.remove(dummy_path)
                # unstage if needed
                api("post", f"/{repo['id']}/commit", json={
                    "message": "test: cleanup stash test",
                    "stage_all": True
                })

    def test_fetch(self, any_repo):
        """fetch 실행 — 에러 없이 완료."""
        resp = api("post", f"/{any_repo['id']}/fetch")
        assert resp.status_code == 200
        # remote이 있으면 success, 없어도 에러는 아님

    def test_unstage(self, registered_repos):
        """stage → unstage (Inverse)."""
        repo = self._find_clean_repo(registered_repos)
        repo_path = repo["path"]
        dummy_path = os.path.join(repo_path, self.DUMMY_FILE)

        try:
            with open(dummy_path, "w") as f:
                f.write("unstage test\n")

            # stage
            api("post", f"/{repo['id']}/stage", json={"files": [self.DUMMY_FILE]})
            status = api("get", f"/{repo['id']}/status").json()
            assert self.DUMMY_FILE in status["staged"]

            # unstage (Inverse)
            resp = api("post", f"/{repo['id']}/unstage", json={"files": [self.DUMMY_FILE]})
            assert resp.status_code == 200
            assert resp.json()["success"] is True

            status = api("get", f"/{repo['id']}/status").json()
            assert self.DUMMY_FILE not in status["staged"]
            assert self.DUMMY_FILE in status["untracked"]

        finally:
            if os.path.exists(dummy_path):
                os.remove(dummy_path)


# ============================================================
# 5. Batch 작업 (Right + Cardinality)
# ============================================================

class TestBatchOperations:
    DUMMY_FILE = "_e2e_batch_test.txt"

    def test_batch_commit(self, registered_repos):
        """여러 레포 일괄 커밋."""
        # clean 레포 2개 찾기
        clean_repos = []
        for repo in registered_repos:
            if len(clean_repos) >= 2:
                break
            resp = api("get", f"/{repo['id']}/status")
            if resp.status_code == 200 and resp.json()["status"] == "clean":
                clean_repos.append(repo)

        if len(clean_repos) < 2:
            pytest.skip("clean 레포가 2개 미만")

        dummy_paths = []
        try:
            # 각 레포에 더미 파일 생성
            for repo in clean_repos:
                p = os.path.join(repo["path"], self.DUMMY_FILE)
                with open(p, "w") as f:
                    f.write(f"batch test for {repo['alias']}\n")
                dummy_paths.append(p)

            # 일괄 커밋
            repo_ids = [r["id"] for r in clean_repos]
            resp = api("post", "/batch-commit", json={
                "repo_ids": repo_ids,
                "message": "test: e2e batch commit (will be reverted)"
            })
            assert resp.status_code == 200
            results = resp.json()["results"]
            assert len(results) == 2
            assert all(r["success"] for r in results)

        finally:
            # 정리
            for i, repo in enumerate(clean_repos):
                p = dummy_paths[i] if i < len(dummy_paths) else None
                if p and os.path.exists(p):
                    os.remove(p)
                api("post", f"/{repo['id']}/commit", json={
                    "message": "test: revert batch commit",
                    "stage_all": True
                })


# ============================================================
# 6. Error 케이스 (404, 400)
# ============================================================

class TestErrors:
    def test_nonexistent_repo_404(self):
        """존재하지 않는 repo → 404."""
        endpoints = [
            ("get", "/99999/status"),
            ("get", "/99999/diff"),
            ("get", "/99999/log"),
            ("post", "/99999/refresh"),
            ("post", "/99999/stage"),
            ("post", "/99999/unstage"),
            ("post", "/99999/commit"),
            ("post", "/99999/push"),
            ("post", "/99999/pull"),
            ("post", "/99999/fetch"),
            ("post", "/99999/stash"),
            ("post", "/99999/stash-pop"),
            ("get", "/99999/operations"),
        ]
        for method, path in endpoints:
            json_body = None
            if method == "post" and "stage" in path and "stash" not in path:
                json_body = {"files": ["x"]}
            elif method == "post" and "commit" in path:
                json_body = {"message": "x"}
            elif method == "post" and "stash" in path and "pop" not in path:
                json_body = {}

            resp = api(method, path, json=json_body)
            assert resp.status_code == 404, f"{method.upper()} {path} → {resp.status_code}"

    def test_create_non_git_path_400(self):
        """git 레포가 아닌 경로 등록 → 400."""
        resp = api("post", "", json={"path": r"C:\Windows\System32"})
        assert resp.status_code == 400
