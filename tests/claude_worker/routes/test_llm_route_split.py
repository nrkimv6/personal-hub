"""LLM route split registration tests."""

import pathlib
import re

from fastapi import APIRouter
from fastapi.routing import APIRoute


def _route_keys(router: APIRouter) -> set[tuple[str, str]]:
    keys = set()
    for route in router.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                keys.add((method.upper(), route.path))
    return keys


def test_llm_routes_aggregate_registers_key_route_groups():
    """Aggregate router keeps the historical prefixed API surface."""
    from app.modules.claude_worker.routes.llm_routes import router

    keys = _route_keys(router)

    assert ("GET", "/api/v1/llm/providers") in keys
    assert ("GET", "/api/v1/llm/defaults") in keys
    assert ("PUT", "/api/v1/llm/defaults") in keys
    assert ("GET", "/api/v1/llm/requests") in keys
    assert ("POST", "/api/v1/llm/requests") in keys
    assert ("GET", "/api/v1/llm/worker/status") in keys
    assert ("POST", "/api/v1/llm/cleanup") in keys
    assert ("GET", "/api/v1/llm/chat/{request_id}/stream") in keys
    assert ("GET", "/api/v1/llm/quota") in keys
    assert ("POST", "/api/v1/llm/quota/report") in keys


def test_split_modules_own_direct_route_decorators():
    """llm_routes.py should only aggregate subrouters after the split."""
    worktree_root = pathlib.Path(__file__).resolve().parents[3]
    route_dir = worktree_root / "app" / "modules" / "claude_worker" / "routes"
    aggregate_source = (route_dir / "llm_routes.py").read_text(encoding="utf-8")

    direct_decorators = re.findall(r"@router\.(get|put|post|delete|patch)\s*\(", aggregate_source)
    assert direct_decorators == []

    split_modules = [
        "llm_provider_routes.py",
        "llm_request_routes.py",
        "llm_status_routes.py",
        "llm_chat_routes.py",
        "llm_quota_routes.py",
    ]
    for module_name in split_modules:
        source = (route_dir / module_name).read_text(encoding="utf-8")
        assert re.search(r"@router\.(get|put|post|delete|patch)\s*\(", source), (
            f"{module_name} has no direct route decorator"
        )
