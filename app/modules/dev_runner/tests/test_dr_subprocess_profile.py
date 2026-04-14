"""_make_plan_runner_env profile 관련 TC (T3)

scripts/_dr_subprocess.py의 _make_plan_runner_env 함수를
직접 import하여 profile env 주입/merge 동작을 검증한다.
"""

import os
import sys
import pytest

# scripts/ 디렉토리를 sys.path에 추가 (app import 불가 환경 시뮬레이션)
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__),  # app/modules/dev_runner/tests/
    "../../../../scripts",
)
_SCRIPTS_DIR = os.path.abspath(_SCRIPTS_DIR)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


@pytest.fixture(autouse=True)
def clean_plan_runner_env(monkeypatch):
    """PLAN_RUNNER_* 환경변수를 테스트 전후 초기화."""
    # 기존 PLAN_RUNNER_* 키 제거 (stale 오염 방지)
    for key in list(os.environ.keys()):
        if key.startswith("PLAN_RUNNER_"):
            monkeypatch.delenv(key, raising=False)
    # CLAUDE_CONFIG_DIR도 제거 (기존 값 오염 방지)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield


class TestMakePlanRunnerEnvProfileConfigDir:
    """test_make_plan_runner_env_profile_config_dir_injection (T3)"""

    def test_profile_config_dir_injected(self):
        """R: profile_env_key + profile_config_dir → env에 해당 키 주입"""
        from _dr_subprocess import _make_plan_runner_env

        env = _make_plan_runner_env(
            "r1",
            profile_env_key="CLAUDE_CONFIG_DIR",
            profile_config_dir="/test/path",
        )
        assert env.get("CLAUDE_CONFIG_DIR") == "/test/path"
        assert env.get("PLAN_RUNNER_RUNNER_ID") == "r1"

    def test_profile_config_dir_none_removes_key(self, monkeypatch):
        """R: profile_env_key 있고 config_dir=None → 해당 env 키 제거"""
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/some/old/path")
        from _dr_subprocess import _make_plan_runner_env

        env = _make_plan_runner_env(
            "r1",
            profile_env_key="CLAUDE_CONFIG_DIR",
            profile_config_dir=None,
        )
        assert "CLAUDE_CONFIG_DIR" not in env

    def test_plan_runner_runner_id_set(self):
        """R: PLAN_RUNNER_RUNNER_ID가 runner_id로 설정됨"""
        from _dr_subprocess import _make_plan_runner_env

        env = _make_plan_runner_env("r1", profile_env_key="CLAUDE_CONFIG_DIR", profile_config_dir="/x")
        assert env.get("PLAN_RUNNER_RUNNER_ID") == "r1"


class TestMakePlanRunnerEnvProfileExtraEnv:
    """test_make_plan_runner_env_profile_extra_env_merge (T3)"""

    def test_extra_env_merged(self):
        """R: profile_extra_env → env에 merge됨"""
        from _dr_subprocess import _make_plan_runner_env

        env = _make_plan_runner_env(
            "r1",
            profile_extra_env={"GEMINI_API_KEY": "test123"},
        )
        assert env.get("GEMINI_API_KEY") == "test123"

    def test_extra_env_multiple_keys(self):
        """R: profile_extra_env 여러 키 동시 merge"""
        from _dr_subprocess import _make_plan_runner_env

        env = _make_plan_runner_env(
            "r1",
            profile_extra_env={"KEY_A": "val_a", "KEY_B": "val_b"},
        )
        assert env.get("KEY_A") == "val_a"
        assert env.get("KEY_B") == "val_b"


class TestMakePlanRunnerEnvBackwardCompat:
    """test_make_plan_runner_env_profile_none_backward_compat (T3)"""

    def test_no_profile_args_backward_compat(self):
        """R: profile 인자 없이 호출 시 기존 동작 유지 (하위 호환)"""
        from _dr_subprocess import _make_plan_runner_env

        env = _make_plan_runner_env("r1")
        assert env.get("PLAN_RUNNER_RUNNER_ID") == "r1"
        # profile 키 없음 (inject 없이 호출)
        assert "CLAUDE_CONFIG_DIR" not in env

    def test_pythonioencoding_set(self):
        """R: PYTHONIOENCODING은 반드시 utf-8로 설정됨"""
        from _dr_subprocess import _make_plan_runner_env

        env = _make_plan_runner_env("r1")
        assert env.get("PYTHONIOENCODING") == "utf-8"
        assert env.get("PYTHONUTF8") == "1"
        assert env.get("PYTHONUNBUFFERED") == "1"

    def test_plan_runner_keys_cleaned(self):
        """R: 부모 env의 PLAN_RUNNER_* 키는 제거됨"""
        os.environ["PLAN_RUNNER_STALE_KEY"] = "stale_value"
        try:
            from _dr_subprocess import _make_plan_runner_env
            env = _make_plan_runner_env("r1")
            # PLAN_RUNNER_RUNNER_ID는 새로 주입, 나머지 stale 키는 제거됨
            assert env.get("PLAN_RUNNER_RUNNER_ID") == "r1"
            assert "PLAN_RUNNER_STALE_KEY" not in env
        finally:
            os.environ.pop("PLAN_RUNNER_STALE_KEY", None)


class TestMakePlanRunnerEnvForbiddenKeys:
    """test_make_plan_runner_env_forbidden_extra_env (T3)"""

    def test_forbidden_path_raises(self):
        """E: PATH 키를 profile_extra_env에 포함 → ValueError"""
        from _dr_subprocess import _make_plan_runner_env

        with pytest.raises(ValueError, match="forbidden"):
            _make_plan_runner_env("r1", profile_extra_env={"PATH": "/evil"})

    def test_forbidden_pythonioencoding_raises(self):
        """E: PYTHONIOENCODING 키를 profile_extra_env에 포함 → ValueError"""
        from _dr_subprocess import _make_plan_runner_env

        with pytest.raises(ValueError, match="forbidden"):
            _make_plan_runner_env("r1", profile_extra_env={"PYTHONIOENCODING": "ascii"})

    def test_forbidden_pythonutf8_raises(self):
        """E: PYTHONUTF8 키를 profile_extra_env에 포함 → ValueError"""
        from _dr_subprocess import _make_plan_runner_env

        with pytest.raises(ValueError, match="forbidden"):
            _make_plan_runner_env("r1", profile_extra_env={"PYTHONUTF8": "0"})

    def test_forbidden_pythonunbuffered_raises(self):
        """E: PYTHONUNBUFFERED 키를 profile_extra_env에 포함 → ValueError"""
        from _dr_subprocess import _make_plan_runner_env

        with pytest.raises(ValueError, match="forbidden"):
            _make_plan_runner_env("r1", profile_extra_env={"PYTHONUNBUFFERED": "0"})
