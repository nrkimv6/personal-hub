"""Routers for slide scanner."""

from .archive import router as archive_router
from .batch import router as batch_router
from .gallery import router as gallery_router
from .health import router as health_router
from .scan import router as scan_router
from .settings import router as settings_router
from .slides import router as slides_router

__all__ = [
    "health_router",
    "slides_router",
    "scan_router",
    "gallery_router",
    "batch_router",
    "archive_router",
    "settings_router",
]
