"""
FastAPI routers for image classifier module
"""

from .stats import router as stats_router

__all__ = ["stats_router"]
