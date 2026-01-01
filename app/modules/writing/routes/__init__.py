"""Writing Routes Module."""

from app.modules.writing.routes.writing_routes import router as writing_router
from app.modules.writing.routes.keyword_routes import router as keyword_router

__all__ = ["writing_router", "keyword_router"]
