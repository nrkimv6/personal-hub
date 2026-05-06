"""Admin API 서버 메인 모듈 — admin(:8001) 전용.

public app(app.main)과 동일한 라우터를 등록하고,
admin 전용 mutation route를 추가로 마운트한다.
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import traceback
import time

from app.startup_hooks import install_hooks
install_hooks()

from app.lifespan import lifespan
from app.openapi_tags import openapi_tags
from app.config import get_runtime_app_mode, settings, logger
from app.database import init_extra_tables
from app.core.database import DatabaseUnavailableError


app = FastAPI(
    title="모니터링 시스템 API (Admin)",
    version="2.0.0",
    default_response_class=JSONResponse,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=openapi_tags,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.core.middleware import ProductionModeMiddleware
app.add_middleware(ProductionModeMiddleware)


@app.middleware("http")
async def log_requests_and_responses(request: Request, call_next):
    request_method = request.method
    request_url = str(request.url)
    start_time = time.time()
    try:
        from app.core.death_log import set_last_request
        set_last_request(f"{request_method} {request.url.path}")
    except Exception:
        pass
    logger.debug(f"[ADMIN API] 요청: {request_method} {request_url}")
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.debug(f"[ADMIN API] 응답: {response.status_code} ({process_time:.3f}초)")
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"[ADMIN API] 오류: {str(e)} ({process_time:.3f}초)")
        raise


@app.exception_handler(DatabaseUnavailableError)
async def database_unavailable_exception_handler(request: Request, exc: DatabaseUnavailableError):
    retry_after = getattr(exc, "retry_after", 10)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        headers={"Retry-After": str(retry_after)},
        content={"detail": "Database temporarily unavailable", "retry_after": retry_after},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"[ADMIN API] 예외 발생: {str(exc)}")
    logger.error(f"[ADMIN API] 요청 URL: {request.url}")
    logger.error(f"[ADMIN API] 스택 트레이스: {traceback.format_exc()}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc)},
    )


from app.router_registry import register_routers
register_routers(app)

# Admin 전용 mutation routes
from app.modules.dev_runner.routes.plan_records import router_admin as _plan_records_admin_router
app.include_router(_plan_records_admin_router)


@app.get("/")
async def root_health():
    return {"status": "ok", "mode": "admin"}


@app.get("/api/v1/ready")
async def api_ready(request: Request):
    return {"ready": getattr(request.app.state, "api_ready", False)}

from app.spa_routes import register_spa_routes
register_spa_routes(app, get_runtime_app_mode(settings_app_mode=settings.APP_MODE))
