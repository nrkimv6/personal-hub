"""Aggregate Claude Worker LLM router.

This module keeps the historical import surface (`router`) while route groups live in
smaller modules by responsibility.
"""

from fastapi import APIRouter

from app.modules.claude_worker.routes import (
    llm_chat_routes,
    llm_provider_routes,
    llm_quota_routes,
    llm_request_routes,
    llm_status_routes,
)
from app.modules.claude_worker.routes.llm_chat_routes import safe_close_pubsub
from app.modules.claude_worker.routes.llm_schemas import _parse_json_field, _to_response
from app.modules.claude_worker.routes.llm_schemas import *  # noqa: F403

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])
router.include_router(llm_provider_routes.router)
router.include_router(llm_request_routes.router)
router.include_router(llm_status_routes.router)
router.include_router(llm_chat_routes.router)
router.include_router(llm_quota_routes.router)

_redis_async = llm_chat_routes._redis_async


async def _chat_sse_generator(request_id: int):
    """Compatibility wrapper for tests and callers that patched llm_routes directly."""
    llm_chat_routes._redis_async = _redis_async
    async for event in llm_chat_routes._chat_sse_generator(request_id):
        yield event
