from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Mount

from app.spa_routes import register_spa_routes


STALE_INDEX = "<html><body>stale admin static</body></html>"


def route_paths(app: FastAPI) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def test_admin_mode_does_not_register_spa_or_static_routes(tmp_path, monkeypatch):
    static_dir = tmp_path / "app" / "static"
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text(STALE_INDEX, encoding="utf-8")
    (static_dir / "_app").mkdir()
    (static_dir / "_app" / "stale.js").write_text("console.log('stale')", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    app = FastAPI()
    register_spa_routes(app, "admin")

    paths = route_paths(app)
    assert "/" not in paths
    assert "/events" not in paths
    assert "/booking" not in paths
    assert not any(isinstance(route, Mount) and route.path == "/_app" for route in app.routes)

    client = TestClient(app)
    for path in ("/", "/events", "/booking", "/_app/stale.js"):
        response = client.get(path)
        assert response.status_code == 404
        assert "stale admin static" not in response.text


def test_public_mode_serves_index_and_mounts_app_assets(tmp_path, monkeypatch):
    static_dir = tmp_path / "app" / "static"
    app_asset_dir = static_dir / "_app"
    app_asset_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text(STALE_INDEX, encoding="utf-8")
    (app_asset_dir / "entry.js").write_text("console.log('public asset')", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    app = FastAPI()
    register_spa_routes(app, "public")

    paths = route_paths(app)
    assert "/" in paths
    assert "/events" in paths
    assert "/booking" in paths
    assert any(isinstance(route, Mount) and route.path == "/_app" for route in app.routes)

    client = TestClient(app)
    index_response = client.get("/")
    assert index_response.status_code == 200
    assert index_response.text == STALE_INDEX

    asset_response = client.get("/_app/entry.js")
    assert asset_response.status_code == 200
    assert asset_response.text == "console.log('public asset')"
