"""Expo 배치도 업로드/조회 API 계약 테스트.

Phase T1: 권한 분리, 파일 검증, 메타 조회 fallback 케이스 검증.
Phase T3: 실제 파일시스템 기반 통합 테스트.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.database import get_db
from app.main import app


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_headers():
    token = create_access_token(email="admin@test.com", is_admin=True)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers():
    token = create_access_token(email="user@test.com", is_admin=False)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def patched_data_root(tmp_path):
    """expo_maps.py 의 DATA_ROOT를 tmp_path로 교체한다."""
    with patch("app.routes.expo_maps.DATA_ROOT", tmp_path):
        yield tmp_path


def _make_png_bytes() -> bytes:
    """1×1 최소 PNG 바이트를 반환한다."""
    # 실제 1×1 투명 PNG (137 bytes)
    return (
        b'\x89PNG\r\n\x1a\n'
        b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx'
        b'\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00'
        b'\x00\x00IEND\xaeB`\x82'
    )


# ---------------------------------------------------------------------------
# GET /api/v1/expo/maps/{slug} — public read
# ---------------------------------------------------------------------------


class TestGetExpoMapMeta:
    def test_returns_null_override_when_no_upload(self, client, patched_data_root):
        """override 없을 때 image_url=null 응답."""
        res = client.get("/api/v1/expo/maps/coffee-expo-2026")
        assert res.status_code == 200
        data = res.json()
        assert data["slug"] == "coffee-expo-2026"
        assert data["image_url"] is None

    def test_returns_meta_after_upload(self, client, patched_data_root, admin_headers):
        """업로드 후 GET에서 image_url이 반환된다."""
        png = _make_png_bytes()
        res = client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
            headers=admin_headers,
        )
        assert res.status_code == 200

        res2 = client.get("/api/v1/expo/maps/coffee-expo-2026")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["image_url"] is not None
        assert "coffee-expo-2026" in data2["image_url"]

    def test_unknown_slug_returns_404(self, client, patched_data_root):
        """허용 목록에 없는 slug → 404."""
        res = client.get("/api/v1/expo/maps/unknown-expo-2099")
        assert res.status_code == 404

    def test_no_auth_required(self, client, patched_data_root):
        """인증 없이도 GET 가능."""
        res = client.get("/api/v1/expo/maps/coffee-expo-2026")
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/expo/maps/{slug}/upload — admin only
# ---------------------------------------------------------------------------


class TestUploadExpoMap:
    def test_admin_upload_success(self, client, patched_data_root, admin_headers):
        """admin 계정으로 PNG 업로드 성공."""
        png = _make_png_bytes()
        res = client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
            headers=admin_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["slug"] == "coffee-expo-2026"
        assert data["image_url"] is not None
        assert data["uploaded_at"] is not None

    def test_public_user_cannot_upload(self, client, patched_data_root, user_headers):
        """비관리자 업로드 → 403."""
        png = _make_png_bytes()
        res = client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
            headers=user_headers,
        )
        assert res.status_code in (401, 403)

    def test_unauthenticated_cannot_upload(self, client, patched_data_root):
        """인증 없이 업로드 → 401 또는 403."""
        png = _make_png_bytes()
        res = client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
        )
        assert res.status_code in (401, 403)

    def test_invalid_extension_rejected(self, client, patched_data_root, admin_headers):
        """SVG 업로드 시도 → 422."""
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
        res = client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.svg", io.BytesIO(svg), "image/svg+xml")},
            headers=admin_headers,
        )
        assert res.status_code == 422

    def test_invalid_content_type_rejected(self, client, patched_data_root, admin_headers):
        """text/plain content-type → 422."""
        res = client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(b"hello"), "text/plain")},
            headers=admin_headers,
        )
        assert res.status_code == 422

    def test_unknown_slug_rejected(self, client, patched_data_root, admin_headers):
        """허용 목록에 없는 slug → 404."""
        png = _make_png_bytes()
        res = client.post(
            "/api/v1/expo/maps/unknown-expo-2099/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
            headers=admin_headers,
        )
        assert res.status_code == 404

    def test_second_upload_replaces_first(self, client, patched_data_root, admin_headers):
        """두 번째 업로드 시 이전 파일이 교체된다."""
        png = _make_png_bytes()

        res1 = client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
            headers=admin_headers,
        )
        assert res1.status_code == 200
        url1 = res1.json()["image_url"]

        # WebP로 교체
        res2 = client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.webp", io.BytesIO(b"RIFF\x00\x00\x00\x00WEBP"), "image/webp")},
            headers=admin_headers,
        )
        assert res2.status_code == 200
        url2 = res2.json()["image_url"]

        # 두 번째 업로드 URL은 동일한 /image 엔드포인트 경로여야 한다
        assert url2.endswith("/image"), f"image_url은 /image 엔드포인트여야 한다: {url2}"
        assert url1.endswith("/image"), f"image_url은 /image 엔드포인트여야 한다: {url1}"

        # 이전 PNG 파일이 남아있지 않아야 한다
        slug_dir = patched_data_root / "coffee-expo-2026"
        old_png = slug_dir / "map.png"
        assert not old_png.exists(), "이전 PNG 파일이 삭제되어야 한다"


# ---------------------------------------------------------------------------
# DELETE /api/v1/expo/maps/{slug} — admin only
# ---------------------------------------------------------------------------


class TestDeleteExpoMapOverride:
    def test_admin_can_delete(self, client, patched_data_root, admin_headers):
        """admin이 override를 삭제하면 GET에서 null 반환."""
        png = _make_png_bytes()
        client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
            headers=admin_headers,
        )

        del_res = client.delete(
            "/api/v1/expo/maps/coffee-expo-2026",
            headers=admin_headers,
        )
        assert del_res.status_code == 204

        get_res = client.get("/api/v1/expo/maps/coffee-expo-2026")
        assert get_res.json()["image_url"] is None

    def test_public_user_cannot_delete(self, client, patched_data_root, user_headers):
        """비관리자 삭제 → 403."""
        res = client.delete(
            "/api/v1/expo/maps/coffee-expo-2026",
            headers=user_headers,
        )
        assert res.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Phase T3: 파일시스템 통합 테스트
# ---------------------------------------------------------------------------


class TestExpoMapFilesystemIntegration:
    def test_meta_json_saved_correctly(self, client, patched_data_root, admin_headers):
        """업로드 후 meta JSON 파일이 올바르게 저장된다."""
        png = _make_png_bytes()
        client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
            headers=admin_headers,
        )

        meta_path = patched_data_root / "coffee-expo-2026" / "map_meta.json"
        assert meta_path.exists(), "map_meta.json이 생성되어야 한다"

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["slug"] == "coffee-expo-2026"
        assert meta["image_url"] is not None
        assert meta["uploaded_at"] is not None

    def test_image_file_saved(self, client, patched_data_root, admin_headers):
        """업로드 후 실제 이미지 파일이 저장된다."""
        png = _make_png_bytes()
        client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
            headers=admin_headers,
        )

        image_path = patched_data_root / "coffee-expo-2026" / "map.png"
        assert image_path.exists(), "map.png 파일이 저장되어야 한다"
        assert image_path.read_bytes() == png

    def test_get_returns_public_accessible_url(self, client, patched_data_root, admin_headers):
        """GET 응답의 image_url이 /api/v1/expo/maps/{slug}/image 엔드포인트 형식이다."""
        png = _make_png_bytes()
        client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
            headers=admin_headers,
        )

        res = client.get("/api/v1/expo/maps/coffee-expo-2026")
        url = res.json()["image_url"]
        assert url.startswith("/api/v1/expo/maps/"), f"image_url은 /api/v1/expo/maps/로 시작해야 한다: {url}"
        assert url.endswith("/image"), f"image_url은 /image로 끝나야 한다: {url}"
        assert "coffee-expo-2026" in url

    def test_delete_removes_meta_and_file(self, client, patched_data_root, admin_headers):
        """삭제 후 meta JSON과 이미지 파일이 사라진다."""
        png = _make_png_bytes()
        client.post(
            "/api/v1/expo/maps/coffee-expo-2026/upload",
            files={"file": ("map.png", io.BytesIO(png), "image/png")},
            headers=admin_headers,
        )

        client.delete("/api/v1/expo/maps/coffee-expo-2026", headers=admin_headers)

        slug_dir = patched_data_root / "coffee-expo-2026"
        meta_path = slug_dir / "map_meta.json"
        assert not meta_path.exists(), "meta JSON이 삭제되어야 한다"

        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            img = slug_dir / f"map{ext}"
            assert not img.exists(), f"이미지 파일 {ext}이 삭제되어야 한다"
