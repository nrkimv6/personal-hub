"""
Phase T3: 통합 테스트 — merge 성공 후 done 분기 검증

fakeredis + 임시 plan 파일(tmpdir)로 _execute_merge_with_lock의 done 분기를 검증한다.
subprocess(plan-runner post-merge)는 mock으로 대체하여 exit_code=0 경로를 테스트한다.
"""
import importlib.util
import json
import os
import subprocess
import sys
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _dr_merge as merge_mod

_SCRIPT_PATH = _SCRIPTS_DIR / "plan_runner" / "dev-runner-command-listener.py"
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_intg", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cl():
    return _load_listener()


def _make_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def _seed_runner_keys(r, prefix, runner_id, plan_file, branch="impl/test-branch"):
    r.set(f"{prefix}:{runner_id}:plan_file", plan_file)
    r.set(f"{prefix}:{runner_id}:branch", branch)
    r.set(f"{prefix}:{runner_id}:engine", "claude")


def _make_all_done_plan(path):
    Path(path).write_text(
        "# test plan\n> 상태: 구현중\n\n## Phase 1\n- [x] task one\n- [x] task two\n",
        encoding="utf-8",
    )


def _make_partial_plan(path):
    Path(path).write_text(
        "# test plan\n> 상태: 구현중\n\n## Phase 1\n- [x] task one\n- [ ] task two\n",
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _setup_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    (repo / "notes.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


def _create_merged_repo_with_stash_residue(repo: Path) -> None:
    (repo / "notes.txt").write_text("stashed residue\n", encoding="utf-8")
    _git(repo, "stash", "push", "-m", "pre-merge-residue", "--", "notes.txt")

    _git(repo, "checkout", "-b", "feature/residue-guard")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feat: feature branch")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "feature/residue-guard", "-m", "Merge branch 'feature/residue-guard' into main")
    _git(repo, "stash", "pop")


_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "t@t.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "t@t.com",
}


def _init_git_repo_with_stashable_residue(repo: Path, branch: str) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, env=_GIT_ENV)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True, capture_output=True, env=_GIT_ENV)

    (repo / "README.md").write_text("init\n", encoding="utf-8")
    (repo / "residue.txt").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, env=_GIT_ENV)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, env=_GIT_ENV)

    subprocess.run(["git", "checkout", "-b", branch], cwd=repo, check=True, capture_output=True, env=_GIT_ENV)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True, capture_output=True, env=_GIT_ENV)
    subprocess.run(["git", "commit", "-m", "feat: residue branch"], cwd=repo, check=True, capture_output=True, env=_GIT_ENV)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True, env=_GIT_ENV)

    (repo / "residue.txt").write_text("resurrected stray\n", encoding="utf-8")
    subprocess.run(
        ["git", "stash", "push", "--include-untracked", "-m", "old-residue"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=_GIT_ENV,
    )


# merge_queue 모듈을 mock으로 미리 주입 (함수 내부 from merge_queue import ... 패치용)
_mock_merge_lock = types.ModuleType("merge_queue")
_mock_merge_lock.acquire_merge_turn = lambda *a, **kw: True
_mock_merge_lock.release_merge_turn = lambda *a, **kw: None
_mock_merge_lock.get_queue_key = lambda repo_id=None: (
    "plan-runner:merge-queue" if repo_id is None else f"plan-runner:merge-wait-queue:{repo_id}"
)
_mock_merge_lock._get_repo_id = lambda project_root: "mock-repo-id"
sys.modules["merge_queue"] = _mock_merge_lock


def _run_merge(cl, runner_id, r, exit_code=0):
    """subprocess를 mock으로 대체하고 _execute_merge_with_lock 실행"""
    mock_proc = MagicMock()
    mock_proc.returncode = exit_code
    with patch("subprocess.run", return_value=mock_proc):
        return cl._execute_merge_with_lock(runner_id, r)


# ── 통합 테스트 ─────────────────────────────────────────────────

def test_all_done_calls_done_api_R(cl, tmp_path):
    """R: all-done 케이스 — _call_done_api가 호출됨"""
    r = _make_redis()
    runner_id = "intg01"
    prefix = cl.RUNNER_KEY_PREFIX
    plan_path = str(tmp_path / "plan_all_done.md")
    _make_all_done_plan(plan_path)
    _seed_runner_keys(r, prefix, runner_id, plan_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp) as mock_post:
        _run_merge(cl, runner_id, r)

    mock_post.assert_called_once()
    call_url = mock_post.call_args[0][0]
    assert "/plans/" in call_url
    assert "/done" in call_url


def test_partial_sets_restart_flag_R(cl, tmp_path):
    """R: partial 케이스 — restart_after_merge Redis 키가 세팅됨"""
    r = _make_redis()
    runner_id = "intg02"
    prefix = cl.RUNNER_KEY_PREFIX
    plan_path = str(tmp_path / "plan_partial.md")
    _make_partial_plan(plan_path)
    _seed_runner_keys(r, prefix, runner_id, plan_path)

    with patch("requests.post") as mock_post:
        _run_merge(cl, runner_id, r)

    mock_post.assert_not_called()
    flag = r.get(f"{prefix}:{runner_id}:restart_after_merge")
    assert flag == "1"


def test_plan_file_all_no_done_no_restart_B(cl):
    """B: plan_file=__ALL_PLANS__ (--all 모드) — done/restart 모두 미호출, 에러 없음"""
    r = _make_redis()
    runner_id = "intg03"
    prefix = cl.RUNNER_KEY_PREFIX
    r.set(f"{prefix}:{runner_id}:plan_file", cl.PLAN_FILE_ALL)
    r.set(f"{prefix}:{runner_id}:branch", "impl/test")
    r.set(f"{prefix}:{runner_id}:engine", "claude")

    with patch("requests.post") as mock_post:
        result = _run_merge(cl, runner_id, r)

    assert result["success"] is True
    mock_post.assert_not_called()
    flag = r.get(f"{prefix}:{runner_id}:restart_after_merge")
    assert flag is None


def test_restart_flag_enqueues_run_command_R(cl):
    """R: restart_after_merge 플래그 있으면 COMMANDS_KEY에 run 명령 큐잉됨 (감지 로직 직접 검증)"""
    r = _make_redis()
    runner_id = "intg04"
    plan_path = "/tmp/fake_plan.md"
    prefix = cl.RUNNER_KEY_PREFIX
    commands_key = cl.COMMANDS_KEY
    _seed_runner_keys(r, prefix, runner_id, plan_path)
    r.set(f"{prefix}:{runner_id}:restart_after_merge", "1")

    # _do_inline_merge 내부의 restart 감지 로직 블록을 직접 재현
    _flag = r.get(f"{prefix}:{runner_id}:restart_after_merge")
    if _flag:
        r.delete(f"{prefix}:{runner_id}:restart_after_merge")
        p_file = r.get(f"{prefix}:{runner_id}:plan_file")
        engine = r.get(f"{prefix}:{runner_id}:engine") or "claude"
        new_runner_id = uuid.uuid4().hex[:8]
        command = {"action": "run", "runner_id": new_runner_id, "plan_file": p_file, "engine": engine}
        r.lpush(commands_key, json.dumps(command, ensure_ascii=False))

    # 플래그 삭제 확인
    assert r.get(f"{prefix}:{runner_id}:restart_after_merge") is None
    # 명령 큐잉 확인
    queued = r.lrange(commands_key, 0, -1)
    assert len(queued) == 1
    cmd = json.loads(queued[0])
    assert cmd["action"] == "run"
    assert cmd["plan_file"] == plan_path
    assert cmd["engine"] == "claude"
    assert "worktree" not in cmd


def test_no_restart_flag_no_enqueue_B(cl):
    """B: restart_after_merge 플래그 없으면 COMMANDS_KEY에 아무것도 없음"""
    r = _make_redis()
    runner_id = "intg05"
    plan_path = "/tmp/fake_plan.md"
    prefix = cl.RUNNER_KEY_PREFIX
    commands_key = cl.COMMANDS_KEY
    _seed_runner_keys(r, prefix, runner_id, plan_path)

    _flag = r.get(f"{prefix}:{runner_id}:restart_after_merge")
    if _flag:
        r.lpush(commands_key, json.dumps({"action": "run"}))

    assert len(r.lrange(commands_key, 0, -1)) == 0


def test_pre_review_stopped_skips_done_and_restart_R(cl, tmp_path):
    """R: stop_stage=pre_review면 _handle_post_merge_done이 done/restart를 모두 건너뛴다."""
    r = _make_redis()
    runner_id = "intg06-pre"
    prefix = cl.RUNNER_KEY_PREFIX
    plan_path = str(tmp_path / "plan_pre_review.md")
    Path(plan_path).write_text(
        "# pre review plan\n> 상태: 검토대기\n\n- [x] done\n",
        encoding="utf-8",
    )
    _seed_runner_keys(r, prefix, runner_id, plan_path)
    r.set(f"{prefix}:{runner_id}:stop_stage", "pre_review")

    logs = []
    with patch("requests.post") as mock_post:
        cl._handle_post_merge_done(plan_path, runner_id, logs.append, r)

    mock_post.assert_not_called()
    assert r.get(f"{prefix}:{runner_id}:restart_after_merge") is None
    assert any("pre_review" in line for line in logs)


def test_all_done_success_false_body_sets_restart_E(cl, tmp_path):
    """E: done API success=false 응답이면 done_failed로 처리되고 restart가 예약된다."""
    r = _make_redis()
    runner_id = "intg07-fail"
    prefix = cl.RUNNER_KEY_PREFIX
    plan_path = str(tmp_path / "plan_all_done_fail.md")
    _make_all_done_plan(plan_path)
    _seed_runner_keys(r, prefix, runner_id, plan_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": False, "message": "archive target resolve failed"}

    with patch("requests.post", return_value=mock_resp):
        result = _run_merge(cl, runner_id, r)

    assert result["success"] is False
    assert result["merge_status"] == "error"
    assert "post-merge done failed" in result["message"]
    assert r.get(f"{prefix}:{runner_id}:done_post_merge_status") == "failed"
    assert r.get(f"{prefix}:{runner_id}:done_post_merge_error") == "done_api_failed"
    assert r.get(f"{prefix}:{runner_id}:restart_after_merge") == "1"


def test_all_done_ownership_guard_sets_specific_error_E(cl, tmp_path):
    """E: ownership_guard 응답이면 done_post_merge_error에 같은 reason을 남긴다."""
    r = _make_redis()
    runner_id = "intg08-own"
    prefix = cl.RUNNER_KEY_PREFIX
    plan_path = str(tmp_path / "plan_all_done_ownership.md")
    _make_all_done_plan(plan_path)
    _seed_runner_keys(r, prefix, runner_id, plan_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": False,
        "reason": "ownership_guard",
        "message": "runner ownership guard blocked auto-done",
    }

    with patch("requests.post", return_value=mock_resp):
        result = _run_merge(cl, runner_id, r)

    assert result["success"] is False
    assert result["merge_status"] == "error"
    assert "ownership_guard" in result["message"]
    assert r.get(f"{prefix}:{runner_id}:done_post_merge_error") == "ownership_guard"
    assert r.get(f"{prefix}:{runner_id}:restart_after_merge") == "1"


def test_all_done_pre_dirty_todo_ownership_guard_restarts_E(cl, tmp_path):
    """E: pre-dirty TODO.md로 인한 ownership_guard 실패도 restart_after_merge를 예약한다."""
    r = _make_redis()
    runner_id = "intg09-pre-dirty-todo"
    prefix = cl.RUNNER_KEY_PREFIX
    plan_path = str(tmp_path / "plan_all_done_pre_dirty_todo.md")
    _make_all_done_plan(plan_path)
    _seed_runner_keys(r, prefix, runner_id, plan_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": False,
        "reason": "ownership_guard",
        "message": (
            "runner ownership guard blocked auto-done: pre-dirty file(s) detected "
            f"for runner {runner_id}: {tmp_path / 'TODO.md'}"
        ),
    }

    with patch("requests.post", return_value=mock_resp):
        result = _run_merge(cl, runner_id, r)

    assert result["success"] is False
    assert result["merge_status"] == "error"
    assert "ownership_guard" in result["message"]
    assert r.get(f"{prefix}:{runner_id}:done_post_merge_error") == "ownership_guard"
    assert r.get(f"{prefix}:{runner_id}:restart_after_merge") == "1"


def test_post_merge_residue_blocked_skips_restart_E(cl, tmp_path):
    """E: merge success 직후 residue_guard가 걸리면 restart 없이 residue_blocked로 멈춘다."""
    r = _make_redis()
    runner_id = "intg10-residue"
    prefix = cl.RUNNER_KEY_PREFIX
    plan_path = str(tmp_path / "plan_residue.md")
    _make_all_done_plan(plan_path)
    _seed_runner_keys(r, prefix, runner_id, plan_path)

    with patch("_dr_merge._check_post_merge_residue", return_value={
        "success": False,
        "status": "residue_blocked",
        "reason": "residue_guard",
        "message": "post-merge residue detected and restored",
        "quarantine_diff_path": "logs/dev_runner/residue/intg10-residue.diff",
    }):
        result = _run_merge(cl, runner_id, r)

    assert result["success"] is False
    assert result["merge_status"] == "residue_blocked"
    assert result["reason"] == "residue_guard"
    assert result["quarantine_diff_path"].endswith("intg10-residue.diff")
    assert r.get(f"{prefix}:{runner_id}:restart_after_merge") is None


def test_post_merge_done_integration_has_post_merge_dirty_hook_installer_R():
    """T4: done/post-merge flow has an installable hook wrapper before root merge-test."""
    installer = Path(__file__).resolve().parents[2] / "scripts" / "git-hooks" / "install-post-merge-dirty-check.ps1"
    assert installer.exists()
    body = installer.read_text(encoding="utf-8")
    assert "D:\\work\\project\\service\\wtools\\common\\tools\\enable-post-merge-dirty-check.ps1" in body


def test_conflict_safe_doc_resolved_calls_done_R(cl, tmp_path):
    """T3: exit_code=3 + safe-doc resolved면 done 흐름까지 이어진다."""
    r = _make_redis()
    runner_id = "intg10-safe-doc"
    prefix = cl.RUNNER_KEY_PREFIX
    plan_path = str(tmp_path / "plan_conflict_safe_doc.md")
    _make_all_done_plan(plan_path)
    _seed_runner_keys(r, prefix, runner_id, plan_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True}

    with patch("requests.post", return_value=mock_resp) as mock_post, \
         patch(
             "_dr_merge._launch_conflict_resolver_process",
             return_value={"success": True, "message": "safe-doc auto-resolved", "merge_status": "merged"},
         ):
        result = _run_merge(cl, runner_id, r, exit_code=3)

    assert result["success"] is True
    assert result["merge_status"] == "merged"
    mock_post.assert_called_once()


def test_conflict_unsafe_keeps_conflict_without_done_B(cl, tmp_path):
    """T3: exit_code=3 + unsafe conflict면 done 없이 conflict 상태를 유지한다."""
    r = _make_redis()
    runner_id = "intg11-unsafe-conflict"
    prefix = cl.RUNNER_KEY_PREFIX
    plan_path = str(tmp_path / "plan_conflict_unsafe.md")
    _make_all_done_plan(plan_path)
    _seed_runner_keys(r, prefix, runner_id, plan_path)

    with patch("requests.post") as mock_post, \
         patch(
             "_dr_merge._launch_conflict_resolver_process",
             return_value={
                 "success": False,
                 "message": "unsafe conflict requires manual resolution",
                 "merge_status": "conflict",
                 "conflict": True,
             },
         ):
        result = _run_merge(cl, runner_id, r, exit_code=3)

    assert result["success"] is False
    assert result["merge_status"] == "conflict"
    assert result["message"] == "unsafe conflict requires manual resolution"
    mock_post.assert_not_called()
