"""T3: stream_log_path Redis 키 설정 검증

Phase 4 수정 검증: _launch_plan_runner_process 실행 후
'plan-runner:runners:{id}:stream_log_path' 키가 실제 파일 경로를 가져야 함.
(nil)이 아닌 실제 로그 파일 경로가 반환되는지 확인.

관련 plan: docs/plan/2026-03-05-logs-follow-runner-detection.md
Phase 5 T3 체크박스 검증 전용 테스트.
"""
import importlib.util
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import fakeredis

from tests.dev_runner._path_helpers import get_listener_script_path, get_repo_root, skip_if_missing


# ========== 스크립트 로드 ==========
# 현재 checkout의 scripts 경로를 사용한다.

_listener_mod = None
REPO_ROOT = get_repo_root()
SCRIPT_PATH = get_listener_script_path()


def _get_worktree_listener():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    skip_if_missing(SCRIPT_PATH, "Listener script")
    spec = importlib.util.spec_from_file_location(
        "dev_runner_command_listener_current", str(SCRIPT_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _listener_mod = mod
    return mod


@pytest.fixture(scope="module")
def wt_listener():
    return _get_worktree_listener()


@pytest.fixture
def fr():
    """fakeredis 격리 인스턴스"""
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


@pytest.fixture
def mock_popen():
    p = MagicMock()
    p.pid = 99999
    p.poll.return_value = None
    p.wait.return_value = 0
    return p


@pytest.fixture
def mock_worktree(wt_listener, tmp_path):
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()
    with patch.object(wt_listener.WorktreeManager, "create", return_value=(worktree_path, "runner/t3test")):
        yield worktree_path


@pytest.fixture(autouse=True)
def reset_globals(wt_listener):
    wt_listener._running_processes.clear()
    wt_listener._running_log_files.clear()
    wt_listener._stream_threads.clear()
    yield
    wt_listener._running_processes.clear()
    wt_listener._running_log_files.clear()
    wt_listener._stream_threads.clear()


RUNNER_ID = "t3test01"


class TestStreamLogPathT3:
    """T3: stream_log_path Redis 키 설정 검증 (Phase 4 fix)"""

    def test_loader_uses_repo_local_script(self, wt_listener):
        """R: 로더가 현재 checkout의 scripts 경로를 사용해야 함"""
        assert Path(wt_listener.__file__).resolve() == get_listener_script_path().resolve()

    def test_stream_log_path_is_set_not_nil(self, wt_listener, fr, mock_popen, tmp_path, mock_worktree):
        """T3 핵심: _launch_plan_runner_process 후 stream_log_path가 실제 경로로 저장됨

        Phase 4 수정 전: redis_client.delete(stream_log_path) → None 반환
        Phase 4 수정 후: redis_client.set(stream_log_path, log_file) → 실제 경로 반환
        """
        RKP = wt_listener.RUNNER_KEY_PREFIX
        command = {"action": "run", "runner_id": RUNNER_ID, "plan_file": "test.md"}

        with patch("_dr_plan_runner.LOG_DIR", tmp_path), \
             patch("_dr_plan_runner.threading.Thread") as mock_thread, \
             patch("_dr_plan_runner.subprocess.Popen", return_value=mock_popen):
            mock_thread.return_value = MagicMock()
            result = wt_listener._launch_plan_runner_process(
                command, fr, RUNNER_ID, mock_worktree, "test.md", None
            )

        assert result["success"] is True

        stream_log_path = fr.get(f"{RKP}:{RUNNER_ID}:stream_log_path")

        # T3 핵심: (nil)이 아닌 실제 경로
        assert stream_log_path is not None, (
            "stream_log_path가 Redis에 설정되지 않음 — Phase 4 fix가 미적용됨"
        )
        assert stream_log_path != "(nil)", "stream_log_path에 '(nil)' 문자열이 저장됨"
        assert stream_log_path != "", "stream_log_path가 빈 문자열임"

    def test_stream_log_path_equals_log_file_path(self, wt_listener, fr, mock_popen, tmp_path, mock_worktree):
        """stream_log_path가 log_file_path와 동일한 경로를 가져야 함 (Phase 4 fix)"""
        RKP = wt_listener.RUNNER_KEY_PREFIX
        command = {"action": "run", "runner_id": RUNNER_ID, "plan_file": "test.md"}

        with patch("_dr_plan_runner.LOG_DIR", tmp_path), \
             patch("_dr_plan_runner.threading.Thread") as mock_thread, \
             patch("_dr_plan_runner.subprocess.Popen", return_value=mock_popen):
            mock_thread.return_value = MagicMock()
            wt_listener._launch_plan_runner_process(
                command, fr, RUNNER_ID, mock_worktree, "test.md", None
            )

        stream_log_path = fr.get(f"{RKP}:{RUNNER_ID}:stream_log_path")
        log_file_path = fr.get(f"{RKP}:{RUNNER_ID}:log_file_path")

        assert stream_log_path is not None
        assert log_file_path is not None
        assert stream_log_path == log_file_path, (
            f"stream_log_path({stream_log_path!r})가 "
            f"log_file_path({log_file_path!r})와 달라야 하지 않음 — "
            "Phase 4: listener 단계에서 동일 경로로 설정해야 함"
        )

    def test_stream_log_path_contains_runner_id(self, wt_listener, fr, mock_popen, tmp_path, mock_worktree):
        """로그 파일 경로에 runner_id가 포함되어 있어야 함"""
        RKP = wt_listener.RUNNER_KEY_PREFIX
        command = {"action": "run", "runner_id": RUNNER_ID, "plan_file": "test.md"}

        with patch("_dr_plan_runner.LOG_DIR", tmp_path), \
             patch("_dr_plan_runner.threading.Thread") as mock_thread, \
             patch("_dr_plan_runner.subprocess.Popen", return_value=mock_popen):
            mock_thread.return_value = MagicMock()
            wt_listener._launch_plan_runner_process(
                command, fr, RUNNER_ID, mock_worktree, "test.md", None
            )

        stream_log_path = fr.get(f"{RKP}:{RUNNER_ID}:stream_log_path")
        assert stream_log_path is not None
        assert RUNNER_ID in stream_log_path, (
            f"로그 파일 경로에 runner_id({RUNNER_ID})가 없음: {stream_log_path!r}"
        )
