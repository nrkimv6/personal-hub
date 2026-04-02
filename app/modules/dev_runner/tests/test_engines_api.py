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
                "codex": {
                    "default_model": "gpt-5.3-codex",
                    "flags": ["-c", "approval_policy=never", "-c", "sandbox_mode=danger-full-access"],
                    "models": {
                        "plan": "gpt-5.3-codex",
                        "impl": "gpt-5.3-codex",
                        "done": "gpt-5.3-codex",
                        "auto-verify": "gpt-5.3-codex",
                    },
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

    async def test_get_engines_includes_codex_key(self, client):
        response = await client.get("/api/v1/dev-runner/engines")
        assert response.status_code == 200

        data = response.json()
        assert "codex" in data
        assert data["codex"]["default_model"] == "gpt-5.3-codex"
        assert data["codex"]["models"]["plan"] == "gpt-5.3-codex"
        assert data["codex"]["models"]["auto-verify"] == "gpt-5.3-codex"

    async def test_get_engines_preserves_default_model_models_structure(self, client):
        response = await client.get("/api/v1/dev-runner/engines")
        assert response.status_code == 200

        data = response.json()
        for engine in ("claude", "gemini", "codex", "cc-codex"):
            assert engine in data
            assert "default_model" in data[engine]
            assert "models" in data[engine]
            assert isinstance(data[engine]["models"], dict)

    async def test_put_engines_partial_models_patch_preserves_existing_keys(self, client):
        response = await client.put(
            "/api/v1/dev-runner/engines/codex",
            json={"models": {"auto-verify": "gpt-5.4-codex"}},
        )
        assert response.status_code == 200

        data = (await client.get("/api/v1/dev-runner/engines")).json()
        codex_models = data["codex"]["models"]
        assert codex_models["plan"] == "gpt-5.3-codex"
        assert codex_models["impl"] == "gpt-5.3-codex"
        assert codex_models["done"] == "gpt-5.3-codex"
        assert codex_models["auto-verify"] == "gpt-5.4-codex"

    async def test_put_engines_rejects_non_dict_models_payload_and_keeps_file(self, client):
        before = json.loads(engines_module.ENGINES_JSON_PATH.read_text(encoding="utf-8-sig"))

        response = await client.put(
            "/api/v1/dev-runner/engines/codex",
            json={"models": []},
        )
        assert response.status_code == 400
        assert "'models' must be an object" in response.text

        after = json.loads(engines_module.ENGINES_JSON_PATH.read_text(encoding="utf-8-sig"))
        assert after == before

    async def test_put_engines_default_model_only_keeps_models_unchanged(self, client):
        before = (await client.get("/api/v1/dev-runner/engines")).json()["codex"]["models"]

        response = await client.put(
            "/api/v1/dev-runner/engines/codex",
            json={"default_model": "gpt-5.4-codex"},
        )
        assert response.status_code == 200

        data = (await client.get("/api/v1/dev-runner/engines")).json()
        assert data["codex"]["default_model"] == "gpt-5.4-codex"
        assert data["codex"]["models"] == before
