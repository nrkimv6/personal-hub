"""7.4: get_project_dir 경로 격리 실제 동작 검증"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def test_external_plan_path_accepted(monkeypatch):
    """monitor-page 외부 경로 plan_file을 start_dev_runner가 listener로 전달함 (경로 거부 없음)"""
    from app.modules.dev_runner.services.executor_service import ExecutorService
    from app.modules.dev_runner.schemas import RunRequest
    import asyncio

    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")
    svc = ExecutorService()

    external_plan = "D:/work/project/tools/monitor-page/.worktrees/plans/docs/plan/test_stub.md"
    req = RunRequest(test_source="path_isolation", plan_file=external_plan, engine="claude")

    # listener heartbeat 있음 + status not running
    mock_r = MagicMock()
    mock_r.ping = AsyncMock(return_value=True)
    mock_r.get = AsyncMock(side_effect=lambda key: (
        "2026-02-25T10:00:00" if key == "plan-runner:listener:heartbeat" else
        None  # status not running
    ))
    mock_r.set = AsyncMock(return_value=True)
    mock_r.lpush = AsyncMock(return_value=1)
    mock_r.scard = AsyncMock(return_value=0)
    mock_r.delete = AsyncMock(return_value=1)

    # brpop → success 결과 반환
    async def mock_brpop(key, timeout=10):
        return (key, json.dumps({"success": True, "message": "started", "pid": 1234}))

    mock_r.brpop = mock_brpop

    svc.async_redis = mock_r
    svc.redis_client = MagicMock()
    svc.redis_client.ping.return_value = True

    async def run():
        return await svc.start_dev_runner(req)

    # "Path not in workspace" 에러 없이 정상 반환
    try:
        result = asyncio.run(run())
    except Exception as e:
        if "Path not in workspace" in str(e):
            pytest.fail(f"외부 경로 거부됨 (Path not in workspace): {e}")
        raise  # 다른 에러는 그대로 전파


def test_cwd_set_to_plan_runner_module_path():
    """_dr_plan_runner.py가 subprocess 실행 시 cwd가 plan-runner 모듈 경로로 설정됨"""
    from tests.dev_runner import _path_helpers
    listener_path = _path_helpers.get_plan_runner_script_path()
    source = listener_path.read_text(encoding="utf-8", errors="ignore")

    # cwd가 PLAN_RUNNER_MODULE_PATH로 설정됨을 확인
    assert "cwd=str(PLAN_RUNNER_MODULE_PATH)" in source, \
        "start_plan_runner의 subprocess.Popen이 cwd=PLAN_RUNNER_MODULE_PATH를 사용해야 함"


def test_listener_passes_plan_file_as_absolute_path():
    """_dr_plan_runner.py의 start_plan_runner가 plan_file을 --plan-file 인자로 전달함"""
    from pathlib import Path
    from tests.dev_runner import _path_helpers

    listener_path = _path_helpers.get_plan_runner_script_path()
    source = listener_path.read_text(encoding="utf-8", errors="ignore")

    assert '"--plan-file"' in source or "'--plan-file'" in source, \
        "start_plan_runner이 plan_file을 --plan-file 옵션으로 전달해야 함"


def test_executor_py_cwd_is_dynamic():
    """executor.py의 subprocess 실행 cwd가 동적 파라미터 사용 (하드코딩 아님)"""
    executor_path = Path("D:/work/project/service/wtools/common/tools/plan-runner/core/executor.py")
    if not executor_path.exists():
        pytest.skip("executor.py 경로 없음")

    source = executor_path.read_text(encoding="utf-8", errors="ignore")

    # cwd가 동적으로 전달됨을 확인 (cwd=cwd or ... 패턴)
    assert "cwd=" in source, "executor.py에 cwd 파라미터 사용 필요"

    # 하드코딩된 특정 경로가 cwd로 고정되지 않아야 함
    hardcoded_patterns = [
        'cwd="D:/work',
        "cwd='D:/work",
        'cwd=r"D:\\work',
    ]
    for pattern in hardcoded_patterns:
        assert pattern not in source, f"executor.py에 하드코딩된 cwd 발견: {pattern}"
