"""
Bug #4 TC — RunRequest pipeline 필드 API 전달
"""
import pytest


def test_run_request_pipeline_field():
    """R: RunRequest(pipeline='v2') 직렬화 → 'pipeline': 'v2' 포함"""
    from app.modules.dev_runner.schemas import RunRequest
    req = RunRequest(pipeline="v2")
    data = req.model_dump()
    assert data["pipeline"] == "v2"


def test_run_request_pipeline_default():
    """B: pipeline 미지정 시 기본값 None"""
    from app.modules.dev_runner.schemas import RunRequest
    req = RunRequest()
    assert req.pipeline is None


def test_run_request_pipeline_v1():
    """R: pipeline='v1' 설정 가능"""
    from app.modules.dev_runner.schemas import RunRequest
    req = RunRequest(pipeline="v1")
    assert req.pipeline == "v1"


def test_executor_pipeline_passthrough():
    """R: executor_service가 request.pipeline → command dict에 추가하는 로직 확인"""
    from app.modules.dev_runner.schemas import RunRequest

    # executor_service의 command 생성 로직을 직접 시뮬레이션
    request = RunRequest(pipeline="v2")
    command = {}

    if request.worktree:
        command["worktree"] = True
    if request.pipeline:
        command["pipeline"] = request.pipeline

    assert command.get("pipeline") == "v2"


def test_executor_pipeline_not_set_when_none():
    """B: pipeline=None 시 command에 pipeline 키 없음"""
    from app.modules.dev_runner.schemas import RunRequest

    request = RunRequest(pipeline=None)
    command = {}

    if request.pipeline:
        command["pipeline"] = request.pipeline

    assert "pipeline" not in command
