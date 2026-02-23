"""dev_runner 테스트 공통 fixtures"""

import pytest
from fastapi import FastAPI
import httpx

from app.modules.dev_runner.routes.tasks import router as tasks_router
from app.modules.dev_runner.routes.runner import router as runner_router
from app.modules.dev_runner.routes.logs import router as logs_router
from app.modules.dev_runner.routes.plans import router as plans_router
from app.modules.dev_runner.services.state import get_state


def _create_test_app() -> FastAPI:
    """테스트용 미니 FastAPI 앱"""
    test_app = FastAPI()
    prefix = "/api/v1/dev-runner"
    test_app.include_router(tasks_router, prefix=prefix)
    test_app.include_router(runner_router, prefix=prefix)
    test_app.include_router(logs_router, prefix=prefix)
    test_app.include_router(plans_router, prefix=prefix)
    return test_app


_test_app = _create_test_app()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=_test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def reset_state():
    state = get_state()
    state.reset()
    yield
    state.reset()
