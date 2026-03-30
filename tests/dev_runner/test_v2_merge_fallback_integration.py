"""
TC: v2 merge 후처리 누락 fallback 통합 테스트 (Phase T3)

실물 Redis + 임시 git repo + 임시 파일로 재현/통합 검증:
- test_v2_merge_process_death_full_recovery: merge 성공 후 프로세스 사망 → fallback 후처리 실행
- test_v2_merge_reconnect_recovery: reconnect 경로에서 후처리 실행
"""
import re
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False
sys.modules["listener_noise_filter"] = _mock_noise


def _get_redis():
    """실물 Redis 연결 시도. 실패 시 skip."""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def _setup_git_repo(tmp_path: Path) -> Path:
    """임시 git repo 생성 + main 브랜치 구성."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    # initial commit
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True)
    return repo


def _create_merge_commit(repo: Path, branch: str) -> str:
    """branch를 main에 merge하는 커밋 생성 후 merge commit hash 반환."""
    # 브랜치 생성 + 커밋
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(repo), check=True, capture_output=True)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", f"feat: {branch}"], cwd=str(repo), check=True, capture_output=True)
    # main으로 돌아와서 merge
    subprocess.run(["git", "checkout", "main"], cwd=str(repo), check=True, capture_output=True)
    result = subprocess.run(
        ["git", "merge", "--no-ff", branch, "-m", f"Merge branch '{branch}' into main"],
        cwd=str(repo), check=True, capture_output=True,
    )
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=str(repo), capture_output=True, text=True)
    return log.stdout.strip().split()[0] if log.stdout.strip() else ""


@pytest.fixture
def redis_client():
    r = _get_redis()
    if r is None:
        pytest.skip("Redis 연결 불가 (localhost:6379 db=15)")
    yield r
    # 사용한 키 정리
    for key in r.scan_iter("plan-runner:runners:integration-*:*"):
        r.delete(key)
    r.srem("plan-runner:active_runners", "integration-runner1", "integration-runner2")


def test_v2_merge_process_death_full_recovery(tmp_path, redis_client):
    """통합 T3: merge 성공 후 프로세스 사망 → _stream_output finally else 분기에서 fallback 후처리 실행"""
    # 1. 임시 git repo + merge commit 생성
    repo = _setup_git_repo(tmp_path)
    branch = "plan/integration-test-fallback"
    _create_merge_commit(repo, branch)

    # 2. 임시 plan 파일 (머지대기 상태)
    plan = tmp_path / "2026-03-30_integration-test.md"
    plan.write_text("> 상태: 머지대기\n- [x] 항목1\n- [x] 항목2\n", encoding="utf-8")

    # 3. Redis 키 세팅
    runner_id = "integration-runner1"
    prefix = "plan-runner:runners"
    redis_client.set(f"{prefix}:{runner_id}:plan_file", str(plan))
    redis_client.set(f"{prefix}:{runner_id}:branch", branch)
    redis_client.set(f"{prefix}:{runner_id}:merge_status", "merged")
    redis_client.sadd("plan-runner:active_runners", runner_id)

    # 4. detect_merged_but_not_done 호출 (실물 Redis + 실물 git + 실물 파일)
    from _dr_merge import detect_merged_but_not_done
    result = None
    with patch("_dr_merge.PROJECT_ROOT", repo):
        result = detect_merged_but_not_done(runner_id, redis_client)

    assert result is not None, "merge 후처리 누락 감지 실패"
    assert result["plan_file"] == str(plan)
    assert result["branch"] == branch

    # 5. _handle_post_merge_done 호출 → plan 상태 전이 확인
    pub_calls = []
    from _dr_merge import _handle_post_merge_done

    with patch("plan_worktree_helpers.remove_plan_header_fields"), \
         patch("plan_worktree_helpers.get_plan_completion", return_value=(2, 2)), \
         patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp
        _handle_post_merge_done(str(plan), runner_id, pub_calls.append, redis_client)

    # plan 상태가 구현완료로 전이됐는지 확인
    updated_text = plan.read_text(encoding="utf-8")
    assert re.search(r">\s*상태:\s*구현완료", updated_text), \
        f"plan 상태 구현완료 전이 실패: {updated_text[:300]}"


def test_v2_merge_reconnect_recovery(tmp_path, redis_client):
    """통합 T3: reconnect 경로 — PID 없는 dead runner + merge commit 존재 → fallback 실행"""
    # 1. 임시 git repo + merge commit 생성
    repo = _setup_git_repo(tmp_path)
    branch = "plan/integration-reconnect-test"
    _create_merge_commit(repo, branch)

    # 2. 임시 plan 파일
    plan = tmp_path / "2026-03-30_reconnect-test.md"
    plan.write_text("> 상태: 머지대기\n- [x] 항목1\n", encoding="utf-8")

    # 3. Redis 키 세팅 (PID 없음 = 이미 사망한 runner)
    runner_id = "integration-runner2"
    prefix = "plan-runner:runners"
    redis_client.set(f"{prefix}:{runner_id}:plan_file", str(plan))
    redis_client.set(f"{prefix}:{runner_id}:branch", branch)
    # merge_status 없음 (v2에서 세팅 안 된 케이스)
    redis_client.sadd("plan-runner:active_runners", runner_id)

    # 4. detect_merged_but_not_done — git log 경로로 감지
    from _dr_merge import detect_merged_but_not_done
    with patch("_dr_merge.PROJECT_ROOT", repo):
        result = detect_merged_but_not_done(runner_id, redis_client)

    assert result is not None, f"reconnect 경로에서 merge 감지 실패 (branch={branch})"
    assert result["plan_file"] == str(plan)
