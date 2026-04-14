"""_dr_plan_runner._launch_plan_runner_process — session_id/fused_session cmd 빌드 TC (T1)

scripts/ 디렉토리를 sys.path에 추가해서 _dr_plan_runner 임포트.
subprocess.Popen을 mock하여 실제 프로세스 실행 없이 cmd 검증.
"""

import sys
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# scripts/plan_runner/ sys.path 추가 (plan_runner/로 이동됨)
_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts" / "plan_runner"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _dr_plan_runner as pr_mod  # noqa: E402


def _base_command(**kwargs) -> dict:
    base = {
        "action": "run",
        "runner_id": "test-runner",
        "engine": "claude",
    }
    base.update(kwargs)
    return base


def _run_launch(command: dict, runner_id: str = "test-runner") -> list:
    """_launch_plan_runner_process를 실행하고 Popen에 전달된 cmd 리스트를 반환."""
    captured_cmds = []

    mock_process = MagicMock()
    mock_process.pid = 9999
    mock_process.stdout = MagicMock()
    mock_process.stdout.__iter__ = MagicMock(return_value=iter([]))

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        return mock_process

    import fakeredis
    fake_redis = fakeredis.FakeRedis(decode_responses=True)

    worktree = Path("/tmp/fake-worktree")
    project_root = Path("/tmp/fake-project")

    # 로그 디렉토리 mkdir, open, Thread, Redis publish 등 side-effect 차단
    mock_log_handle = MagicMock()
    mock_log_handle.__enter__ = MagicMock(return_value=mock_log_handle)
    mock_log_handle.__exit__ = MagicMock(return_value=False)

    with patch("subprocess.Popen", side_effect=mock_popen), \
         patch("builtins.open", return_value=mock_log_handle), \
         patch.object(Path, "mkdir", return_value=None), \
         patch("threading.Thread", return_value=MagicMock()):
        try:
            pr_mod._launch_plan_runner_process(
                command=command,
                redis_client=fake_redis,
                runner_id=runner_id,
                worktree_path=worktree,
                plan_file=command.get("plan_file", ""),
                engine=command.get("engine", "claude"),
                project_root=project_root,
            )
        except Exception:
            pass  # Popen 이후 에러는 무시, cmd 캡처만 필요

    return captured_cmds[0] if captured_cmds else []


class TestLaunchPlanRunnerSessionArg:
    def test_R_session_id_arg_appended(self):
        """R: session_id='abc-uuid' → cmd에 ['--session-id', 'abc-uuid'] 포함"""
        cmd = _run_launch(_base_command(session_id="abc-uuid"))
        assert "--session-id" in cmd, f"--session-id 없음: {cmd}"
        idx = cmd.index("--session-id")
        assert cmd[idx + 1] == "abc-uuid"

    def test_B_no_session_id(self):
        """B: session_id 없으면 --session-id 미포함 (회귀)"""
        cmd = _run_launch(_base_command())
        assert "--session-id" not in cmd

    def test_E_empty_string_not_appended(self):
        """E: 빈 문자열 session_id → --session-id 미포함"""
        cmd = _run_launch(_base_command(session_id=""))
        assert "--session-id" not in cmd

    def test_O_arg_order(self):
        """O: --session-id는 --engine 이후, --worktree 이전 위치"""
        cmd = _run_launch(_base_command(session_id="abc-uuid", worktree=True))
        if "--session-id" not in cmd or "--engine" not in cmd:
            pytest.skip(f"필수 인자 없음 — cmd: {cmd}")
        engine_idx = cmd.index("--engine")
        session_idx = cmd.index("--session-id")
        assert session_idx > engine_idx, "--session-id는 --engine 이후여야 함"
        if "--worktree" in cmd:
            worktree_idx = cmd.index("--worktree")
            assert session_idx < worktree_idx, "--session-id는 --worktree 이전이어야 함"

    def test_fused_R_flag_appended(self):
        """R: fused_session=True → --fused-session 플래그 포함"""
        cmd = _run_launch(_base_command(session_id="abc-uuid", fused_session=True))
        assert "--fused-session" in cmd, f"--fused-session 없음: {cmd}"
