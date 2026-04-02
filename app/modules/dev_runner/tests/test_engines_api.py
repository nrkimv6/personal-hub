"""engines API 테스트"""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

import app.modules.dev_runner.routes.engines as engines_module
from app.modules.dev_runner.routes.engines import router as engines_router


@pytest.fixture
async def client(tmp_path: Path):
    """engines 라우트만 포함한 테스트 클라이언트"""
    app = FastAPI()
    app.include_router(engines_router, prefix="/api/v1/dev-runner/engines")

    engines_path = tmp_path / "engines.json"
    engines_path.write_text(
        json.dumps(
            {
                "claude": {
                    "default_model": "sonnet",
                    "flags": ["--dangerously-skip-permissions"],
                    "models": {"plan": "sonnet", "impl": "sonnet", "done": "haiku"},
                },
                "gemini": {
                    "default_model": "gemini-2.0-flash",
                    "flags": ["--yolo"],
                    "models": {"plan": "gemini-3.1-pro-preview", "impl": "gemini-3-flash-preview", "done": "gemini-3-flash-preview"},
                },
                "cc-codex": {
                    "default_model": "sonnet",
                    "flags": ["-p"],
                    "models": {"plan": "sonnet", "impl": "opus", "done": "haiku"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with patch.object(engines_module, "ENGINES_JSON_PATH", engines_path):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


class TestEnginesApi:
    async def test_get_engines_includes_cc_codex_key(self, client):
        response = await client.get("/api/v1/dev-runner/engines")
        assert response.status_code == 200

        data = response.json()
        assert "cc-codex" in data
        assert data["cc-codex"]["default_model"] == "sonnet"
        assert data["cc-codex"]["models"]["plan"] == "sonnet"
        assert data["cc-codex"]["models"]["impl"] == "opus"
        assert data["cc-codex"]["models"]["done"] == "haiku"

    async def test_get_engines_preserves_default_model_models_structure(self, client):
        response = await client.get("/api/v1/dev-runner/engines")
        assert response.status_code == 200

        data = response.json()
        for engine in ("claude", "gemini", "cc-codex"):
            assert engine in data
            assert "default_model" in data[engine]
            assert "models" in data[engine]
            assert isinstance(data[engine]["models"], dict)
