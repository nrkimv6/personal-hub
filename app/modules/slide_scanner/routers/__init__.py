"""Routers for slide scanner."""

from .health import router as health_router
from .mobile_review import router as mobile_review_router
from .mobile_sync import router as mobile_sync_router
from .slides import router as slides_router

__all__ = [
    "health_router",
    "mobile_review_router",
    "mobile_sync_router",
    "slides_router",
]
