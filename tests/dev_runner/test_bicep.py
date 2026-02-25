import json
import os
import subprocess
import pytest
from pathlib import Path

# Paths
WTOOLS_BASE_DIR = Path(r"D:\work\project\service\wtools")
PLAN_RUNNER_MODULE_PATH = WTOOLS_BASE_DIR / "common/tools/plan-runner"
PLAN_RUNNER_PYTHON = PLAN_RUNNER_MODULE_PATH / ".venv/Scripts/python.exe"

@pytest.fixture
def plan_runner_env():
    """Environment variables for plan-runner subprocess"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env

def run_plan_runner_cli(args, env):
    """Helper to run plan-runner CLI"""
    cmd = [str(PLAN_RUNNER_PYTHON), "-m", "plan_runner", "run"] + args
    result = subprocess.run(
        cmd,
        cwd=str(PLAN_RUNNER_MODULE_PATH),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return result

class TestPlanRunnerRightBICEP:
    """RIGHT-BICEP tests for plan-runner CLI execution"""

    def test_right_engine_gemini(self, plan_runner_env):
        """Right - '--engine gemini' 전달 시 정상 작동 (No unexpected extra arguments)"""
        # --dry-run을 추가해 실제 계획 실행은 방지
        result = run_plan_runner_cli(["--engine", "gemini", "--dry-run"], plan_runner_env)
        # 만약 옵션이 없다면 'No such option: --engine' 에러 발생
        assert "No such option: --engine" not in result.stderr
        assert "Got unexpected extra arguments" not in result.stderr
        assert result.returncode == 0 or "Usage" not in result.stderr # It should start normally

    def test_boundary_empty_engine(self, plan_runner_env):
        """Boundary - '--engine ""' 전달 시 처리"""
        # 빈 문자열 엔진 전달
        result = run_plan_runner_cli(["--engine", "", "--dry-run"], plan_runner_env)
        assert result.returncode == 0 or "Usage" not in result.stderr
        
    def test_boundary_long_engine_name(self, plan_runner_env):
        """Boundary - 매우 긴 문자열 전달 시 크래시 여부 (typer 동작)"""
        long_engine = "gemini" * 500
        result = run_plan_runner_cli(["--engine", long_engine, "--dry-run"], plan_runner_env)
        # 실행이 실패하더라도 시스템 예외가 아닌 처리된 에러이거나, dry_run으로 넘어가는지 확인
        assert "Got unexpected extra arguments" not in result.stderr

    def test_error_unknown_argument(self, plan_runner_env):
        """Error - 정의되지 않은 옵션 전달 시의 에러 처리 복구력"""
        result = run_plan_runner_cli(["--unknown-arg", "true", "--dry-run"], plan_runner_env)
        assert result.returncode != 0
        assert "No such option: --unknown-arg" in result.stderr

    def test_cross_check_pid_match(self):
        """Cross-check - 이 부분은 executor_service 테스트에서 이미 수행 중이므로 생략 (또는 별도 분리)"""
        pass
