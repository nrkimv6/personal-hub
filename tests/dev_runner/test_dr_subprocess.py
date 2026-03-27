import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

def test_make_plan_runner_env_base_keys_R():
    from _dr_subprocess import _make_plan_runner_env
    env = _make_plan_runner_env("runner-1")
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["PLAN_RUNNER_RUNNER_ID"] == "runner-1"
    assert "REDIS_DB" in env
    assert "CLAUDECODE" not in env

def test_make_plan_runner_env_extra_keys_R():
    from _dr_subprocess import _make_plan_runner_env
    env = _make_plan_runner_env("runner-1", PLAN_RUNNER_WORK_DIR="/some/path")
    assert env["PLAN_RUNNER_WORK_DIR"] == "/some/path"

def test_make_plan_runner_env_claudecode_removed_B():
    os.environ["CLAUDECODE"] = "1"
    from _dr_subprocess import _make_plan_runner_env
    env = _make_plan_runner_env("runner-1")
    assert "CLAUDECODE" not in env
    del os.environ["CLAUDECODE"]

def test_make_plan_runner_env_uses_get_redis_db_R():
    from _dr_constants import set_redis_db
    from _dr_subprocess import _make_plan_runner_env
    set_redis_db(15)
    env = _make_plan_runner_env("test-runner")
    assert env["REDIS_DB"] == "15"
    set_redis_db(0)
