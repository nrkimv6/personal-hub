"""Routers for slide scanner."""

from .health import router as health_router
from .slides import router as slides_router

__all__ = ["health_router", "slides_router"]
