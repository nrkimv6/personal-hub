"""safe_close_pubsub import 정합성 검증 TC"""
import importlib
import sys
import pytest


def test_llm_routes_import_safe_close_pubsub():
    """R(Right): llm_routes 모듈이 safe_close_pubsub을 import한 상태로 로드 가능"""
    if "app.modules.claude_worker.routes.llm_routes" in sys.modules:
        del sys.modules["app.modules.claude_worker.routes.llm_routes"]
    mod = importlib.import_module("app.modules.claude_worker.routes.llm_routes")
    assert hasattr(mod, "safe_close_pubsub"), (
        "llm_routes should import safe_close_pubsub from sse_helpers"
    )


def test_plan_archive_listener_import_safe_close_pubsub():
    """R(Right): plan_archive_listener 모듈이 safe_close_pubsub을 참조 가능"""
    if "app.worker.plan_archive_listener" in sys.modules:
        del sys.modules["app.worker.plan_archive_listener"]
    mod = importlib.import_module("app.worker.plan_archive_listener")
    assert hasattr(mod, "safe_close_pubsub"), (
        "plan_archive_listener should import safe_close_pubsub from sse_helpers"
    )
