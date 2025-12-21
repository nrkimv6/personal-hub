# Instagram routes
from .instagram import router as instagram_router
from .worker import router as worker_router
from .classification import router as classification_router

__all__ = ["instagram_router", "worker_router", "classification_router"]
