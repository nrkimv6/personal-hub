"""dev_runner 테스트 공통 fixtures"""

import pytest
import fakeredis
import fakeredis.aioredis
from fastapi import FastAPI
import httpx

from app.modules.dev_runner.routes.tasks import router as tasks_router
from app.modules.dev_runner.routes.runner import router as runner_router
from app.modules.dev_runner.routes.logs import router as logs_router
from app.modules.dev_runner.routes.plans import router as plans_router
from app.modules.dev_runner.services.state import get_state
from app.modules.dev_runner.services.event_service import EventService, FILE_POLL_TIMEOUT, FILE_POLL_INTERVAL
from app.modules.dev_runner.services.log_file_resolver import LogFileResolver
from app.modules.dev_runner.services.event_log_tailer import LogTailer
from app.modules.dev_runner.config import config as _dev_runner_config


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


# ─── EventService 공통 fixtures ─────────────────────────────────────────────

@pytest.fixture
def sync_redis():
    """fakeredis 동기 클라이언트"""
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    r.close()


@pytest.fixture
def async_redis():
    """fakeredis 비동기 클라이언트"""
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r


@pytest.fixture
def event_service(sync_redis, async_redis):
    """테스트용 EventService (fakeredis 주입, LogTailer 포함)"""
    svc = EventService.__new__(EventService)
    svc._sync = sync_redis
    svc._async = async_redis
    _log_resolver = LogFileResolver(_dev_runner_config, sync_redis)
    svc._log_tailer = LogTailer(sync_redis, _log_resolver)
    svc._file_poll_timeout = FILE_POLL_TIMEOUT
    svc._file_poll_interval_sec = FILE_POLL_INTERVAL
    return svc
