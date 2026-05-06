"""dev-runner command listener 테스트

전체실행(parallel) 모드에서 plan_file 없이도 정상 동작하는지 검증.
"""
import json
from unittest.mock import MagicMock, patch, mock_open

import pytest

from tests.dev_runner.conftest import attach_default_redis_behaviors

# command listener는 스크립트이므로 함수를 직접 import하기 어려움 → 로직 재현 테스트


class TestStartDevRunnerValidation:
    """start_plan_runner 함수의 plan_file 검증 로직 테스트"""

    def _validate_plan_file(self, command: dict) -> dict | None:
        """command listener의 plan_file 검증 로직 재현"""
        plan_file = command.get("plan_file")
        is_parallel = command.get("parallel", False)
        if not plan_file and not is_parallel:
            return {"success": False, "message": "plan_file required (use parallel mode for batch execution)"}
        return None  # 검증 통과

    def test_single_mode_without_plan_file_returns_error(self):
        """단일 실행 모드에서 plan_file 없으면 에러"""
        command = {"action": "run"}
        result = self._validate_plan_file(command)
        assert result is not None
        assert result["success"] is False
        assert "plan_file required" in result["message"]

    def test_parallel_mode_without_plan_file_passes(self):
        """전체 실행(parallel) 모드에서는 plan_file 없어도 검증 통과"""
        command = {"action": "run", "parallel": True}
        result = self._validate_plan_file(command)
        assert result is None  # 검증 통과

    def test_single_mode_with_plan_file_passes(self):
        """단일 실행 모드에서 plan_file 있으면 검증 통과"""
        command = {"action": "run", "plan_file": "common/docs/plan/test.md"}
        result = self._validate_plan_file(command)
        assert result is None

    def test_parallel_mode_with_plan_file_passes(self):
        """parallel + plan_file 둘 다 있어도 통과"""
        command = {"action": "run", "plan_file": "test.md", "parallel": True}
        result = self._validate_plan_file(command)
        assert result is None

    def test_parallel_false_without_plan_file_returns_error(self):
        """parallel=False 명시 + plan_file 없으면 에러"""
        command = {"action": "run", "parallel": False}
        result = self._validate_plan_file(command)
        assert result is not None
        assert result["success"] is False


class TestCommandBuilding:
    """CLI 명령어 구성 테스트"""

    def _build_cmd(self, command: dict) -> list[str]:
        """command listener의 CLI 명령어 구성 로직 재현"""
        plan_file = command.get("plan_file")

        cmd = ["python", "-m", "plan_runner", "run"]

        if plan_file:
            cmd.extend(["--plan-file", plan_file])

        if command.get("max_cycles"):
            cmd.extend(["--max-cycles", str(command["max_cycles"])])

        if command.get("parallel"):
            cmd.append("--parallel")

        if command.get("projects"):
            cmd.extend(["--projects", command["projects"]])

        return cmd

    def test_single_mode_includes_plan_file_flag(self):
        """단일 모드: --plan-file 포함"""
        cmd = self._build_cmd({"plan_file": "test.md"})
        assert "--plan-file" in cmd
        assert "test.md" in cmd

    def test_parallel_mode_without_plan_file_no_plan_flag(self):
        """전체 실행: --plan-file 미포함, --parallel 포함"""
        cmd = self._build_cmd({"parallel": True})
        assert "--plan-file" not in cmd
        assert "--parallel" in cmd

    def test_parallel_with_projects(self):
        """전체 실행 + 프로젝트 지정"""
        cmd = self._build_cmd({"parallel": True, "projects": "memo-alarm,activity-hub"})
        assert "--parallel" in cmd
        assert "--projects" in cmd
        assert "memo-alarm,activity-hub" in cmd


class TestExecutorServiceCommand:
    """executor_service가 Redis에 보내는 command 구조 테스트"""

    def _build_command(self, plan_file=None, parallel=False, projects=None):
        """executor_service.start_plan_runner의 command 구성 로직 재현"""
        command = {
            "action": "run",
            "source": "monitor-page-api",
        }

        if plan_file:
            command["plan_file"] = plan_file

        if parallel:
            command["parallel"] = True

        if projects:
            command["projects"] = projects

        return command

    def test_all_mode_sends_parallel_true(self):
        """전체 실행 모드: parallel=True 포함"""
        cmd = self._build_command(parallel=True)
        assert cmd.get("parallel") is True
        assert "plan_file" not in cmd

    def test_single_mode_sends_plan_file(self):
        """단일 모드: plan_file 포함"""
        cmd = self._build_command(plan_file="test.md")
        assert cmd["plan_file"] == "test.md"
        assert "parallel" not in cmd

    def test_all_mode_plan_file_not_in_command(self):
        """전체 실행 시 plan_file 키가 command에 없어야 함"""
        cmd = self._build_command(parallel=True)
        assert "plan_file" not in cmd


SENTINEL = "__ALL_PLANS__"


class TestRedisStateSaving:
    """Redis 상태 저장 로직 테스트 (plan_file None → SENTINEL 변환)"""

    def _save_state(self, plan_file: str | None, redis_client: MagicMock) -> dict:
        """command listener Redis 저장 로직 재현"""
        state = {
            "pid": 12345,
            "plan_file": plan_file or SENTINEL,
            "log_file_path": "/tmp/test.log",
            "start_time": "2026-02-14T00:00:00",
            "status": "running",
        }
        redis_client.set("dev-runner:state:log_file_path", state["log_file_path"])
        redis_client.set("dev-runner:state:pid", state["pid"])
        redis_client.set("dev-runner:state:plan_file", plan_file or SENTINEL)
        redis_client.set("dev-runner:state:start_time", state["start_time"])
        redis_client.set("dev-runner:state:status", state["status"])
        return state

    def test_parallel_mode_saves_sentinel_as_plan_file(self):
        """parallel=True, plan_file=None → Redis에 "__ALL_PLANS__" sentinel 저장"""
        redis_client = attach_default_redis_behaviors(MagicMock())
        state = self._save_state(plan_file=None, redis_client=redis_client)

        # state dict 확인
        assert state["plan_file"] == SENTINEL

        # Redis 저장 확인
        redis_client.set.assert_any_call("dev-runner:state:plan_file", SENTINEL)

    def test_single_mode_saves_actual_plan_file(self):
        """plan_file="test.md" → Redis에 "test.md" 저장"""
        redis_client = attach_default_redis_behaviors(MagicMock())
        state = self._save_state(plan_file="test.md", redis_client=redis_client)

        assert state["plan_file"] == "test.md"
        redis_client.set.assert_any_call("dev-runner:state:plan_file", "test.md")

    def test_parallel_with_plan_file_saves_plan_file(self):
        """parallel=True + plan_file="test.md" → "test.md" 저장 (plan_file 우선)"""
        redis_client = attach_default_redis_behaviors(MagicMock())
        state = self._save_state(plan_file="test.md", redis_client=redis_client)

        assert state["plan_file"] == "test.md"
        redis_client.set.assert_any_call("dev-runner:state:plan_file", "test.md")

    def test_empty_string_plan_file_saves_sentinel(self):
        """plan_file="" (빈 문자열) → Redis에 "__ALL_PLANS__" sentinel 저장 (Boundary)

        빈 문자열은 Python의 `or` 연산자에서 falsy로 처리되므로 sentinel로 변환되어야 함.
        """
        redis_client = attach_default_redis_behaviors(MagicMock())
        state = self._save_state(plan_file="", redis_client=redis_client)

        # state dict 확인
        assert state["plan_file"] == SENTINEL, f"빈 문자열 plan_file은 '{SENTINEL}'로 변환되어야 함"

        # Redis 저장 확인
        redis_client.set.assert_any_call("dev-runner:state:plan_file", SENTINEL)


class TestStreamOutputMergeFlow:
    """_stream_output finally 블록의 merge_requested 플래그 분기 테스트 (T1)"""

    def _simulate_merge_branch(self, exit_code: int, merge_flag_value, runner_id: str = "test-runner"):
        """merge_requested 플래그 분기 로직 재현 (dev-runner-command-listener.py 로직 복사)"""
        _merge_requested = False
        if runner_id and exit_code == 0:
            _merge_requested = bool(merge_flag_value)
        return _merge_requested

    def test_stream_output_merge_flow(self):
        """exit_code 0 + merge_requested 있음 → merge 흐름 진입 (RIGHT)"""
        # merge_requested 플래그가 있을 때
        result = self._simulate_merge_branch(exit_code=0, merge_flag_value="1", runner_id="t-cmdlstn-abc")
        assert result is True, "merge_requested 플래그 있으면 _merge_requested=True여야 함"

    def test_stream_output_no_merge_flag(self):
        """exit_code 0 + merge_requested 없음 → 기존 cleanup (INVERSE)"""
        # merge_requested 플래그가 없을 때
        result = self._simulate_merge_branch(exit_code=0, merge_flag_value=None, runner_id="t-cmdlstn-abc")
        assert result is False, "merge_requested 플래그 없으면 _merge_requested=False여야 함"

    def test_stream_output_nonzero_exit_no_merge(self):
        """exit_code != 0 → merge 흐름 진입 안 함 (항상 False)"""
        result = self._simulate_merge_branch(exit_code=1, merge_flag_value="1", runner_id="t-cmdlstn-abc")
        assert result is False, "exit_code != 0이면 merge_requested 플래그 무관하게 False여야 함"

    def test_stream_output_empty_runner_id_no_merge(self):
        """runner_id 없음 → merge 흐름 진입 안 함"""
        result = self._simulate_merge_branch(exit_code=0, merge_flag_value="1", runner_id="")
        assert result is False, "runner_id 없으면 merge_requested 체크 안 함"
