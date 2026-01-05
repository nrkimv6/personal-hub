"""Activity Routes."""

from app.modules.activity.routes.centers import router as centers_router
from app.modules.activity.routes.courses import router as courses_router
from app.modules.activity.routes.crawl import router as crawl_router
from app.modules.activity.routes.worker import router as worker_router

__all__ = [
    "centers_router",
    "courses_router",
    "crawl_router",
    "worker_router",
]
