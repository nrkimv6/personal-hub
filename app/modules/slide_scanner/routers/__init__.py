"""Routers for slide scanner."""

from .gallery import router as gallery_router
from .health import router as health_router
from .scan import router as scan_router
from .slides import router as slides_router

__all__ = ["health_router", "slides_router", "scan_router", "gallery_router"]
