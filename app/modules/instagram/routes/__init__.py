# Instagram routes
from .instagram import router as instagram_router
from .worker import router as worker_router
from .classification import router as classification_router
from .llm_classification import router as llm_classification_router
from .extension import router as extension_router
from .instagram_archive import router as archive_router

__all__ = [
    "instagram_router",
    "worker_router",
    "classification_router",
    "llm_classification_router",
    "extension_router",
    "archive_router",
]
