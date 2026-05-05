"""profile_routes.py 라우터 등록 단위 TC.

profile_routes.router가 올바른 APIRouter 인스턴스이며,
5개의 profile 엔드포인트가 정확히 등록되어 있는지 검증한다.
"""

import re

from fastapi import APIRouter
from fastapi.routing import APIRoute


def test_profile_routes_router_is_api_router():
    """profile_routes.router가 APIRouter 인스턴스임을 검증."""
    from app.modules.claude_worker.routes.profile_routes import router
    assert isinstance(router, APIRouter)


def _route_keys(router: APIRouter) -> set[tuple[str, str]]:
    """router의 직접 정의 경로에서 (method, path) set 반환."""
    keys = set()
    for route in router.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                keys.add((method.upper(), route.path))
    return keys


def test_profile_routes_has_capacity_pool_endpoints():
    """profile_routes.router에 profile pool 경로가 직접 등록되어 있음을 확인."""
    from app.modules.claude_worker.routes.profile_routes import router

    keys = _route_keys(router)

    assert ("GET", "/profiles") in keys, f"GET /profiles 없음. 등록된 경로: {keys}"
    assert ("PUT", "/profiles") in keys, f"PUT /profiles 없음. 등록된 경로: {keys}"
    assert ("POST", "/profiles/{engine}/select") in keys, (
        f"POST /profiles/{{engine}}/select 없음. 등록된 경로: {keys}"
    )
    assert ("DELETE", "/profiles/{engine}/{name}") in keys, (
        f"DELETE /profiles/{{engine}}/{{name}} 없음. 등록된 경로: {keys}"
    )
    assert ("POST", "/profiles/{engine}/{name}/launch-cli") in keys, (
        f"POST /profiles/{{engine}}/{{name}}/launch-cli 없음. 등록된 경로: {keys}"
    )
    assert ("GET", "/profiles/status") in keys, f"GET /profiles/status 없음. 등록된 경로: {keys}"
    assert ("GET", "/profiles/{engine}/{name}/assignments") in keys, (
        f"GET /profiles/{{engine}}/{{name}}/assignments 없음. 등록된 경로: {keys}"
    )
    assert ("POST", "/profiles/{engine}/{name}/pause") in keys, (
        f"POST /profiles/{{engine}}/{{name}}/pause 없음. 등록된 경로: {keys}"
    )
    assert ("DELETE", "/profiles/{engine}/{name}/pause") in keys, (
        f"DELETE /profiles/{{engine}}/{{name}}/pause 없음. 등록된 경로: {keys}"
    )


def test_llm_routes_has_no_direct_profiles_decorator():
    """llm_routes.py 소스코드에 @router.XXX("/profiles...") 직접 데코레이터가 없음을 확인.

    include_router 로 연결된 경로는 소스코드 레벨에서 나타나지 않으므로
    파일 파싱으로 '직접 정의 없음'을 검증한다.
    """
    import pathlib

    worktree_root = pathlib.Path(__file__).resolve().parents[3]
    llm_routes_path = (
        worktree_root
        / "app"
        / "modules"
        / "claude_worker"
        / "routes"
        / "llm_routes.py"
    )

    source = llm_routes_path.read_text(encoding="utf-8")

    # @router.get("/profiles"), @router.put("/profiles"), @router.post("/profiles/..."), @router.delete("/profiles/...")
    pattern = re.compile(r'@router\.(get|put|post|delete|patch)\s*\(\s*["\']\/profiles')
    matches = pattern.findall(source)
    assert not matches, (
        f"llm_routes.py에 profile 직접 데코레이터가 남아 있습니다: {matches}"
    )
