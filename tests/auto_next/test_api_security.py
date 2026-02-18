"""Phase 8: API 경로 보안 테스트 - path traversal, base64 디코딩, 빈 경로"""

import base64
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.modules.auto_next.routes.plans import router, _decode_path


class TestDecodePathFunction:
    """_decode_path() 유틸 함수 테스트"""

    def test_valid_base64_decodes(self):
        """정상 base64 디코딩"""
        path = r"D:\work\project\test.md"
        encoded = base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")
        assert _decode_path(encoded) == path

    def test_with_padding(self):
        """패딩 포함 base64"""
        path = r"D:\work\project\test.md"
        encoded = base64.urlsafe_b64encode(path.encode()).decode()
        assert _decode_path(encoded) == path

    def test_invalid_base64_raises(self):
        """잘못된 base64 → 예외"""
        with pytest.raises(Exception):
            _decode_path("!!!not-valid-base64!!!")

    def test_special_chars_in_path(self):
        """특수문자 포함 경로"""
        path = r"D:\work\project\한글 경로\plan (1).md"
        encoded = base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")
        assert _decode_path(encoded) == path


class TestApiPathSecurity:
    """API 엔드포인트 보안 테스트"""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/auto-next")
        return TestClient(app)

    def _encode(self, path: str) -> str:
        return base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")

    def test_path_traversal_blocked(self, client):
        """path traversal 공격 차단 (403)"""
        malicious = self._encode(r"D:\work\project\..\..\Windows\System32\config")
        with patch("app.modules.auto_next.routes.plans.plan_service") as mock_ps:
            mock_ps.validate_external_path.return_value = False
            resp = client.get(f"/api/v1/auto-next/plans/{malicious}")
        assert resp.status_code == 403

    def test_invalid_base64_returns_400(self, client):
        """잘못된 base64 문자열 → 400"""
        resp = client.get("/api/v1/auto-next/plans/%%%invalid%%%")
        assert resp.status_code == 400

    def test_nonexistent_file_returns_404(self, client, tmp_path):
        """존재하지 않는 파일 경로 → 404"""
        fake_path = str(tmp_path / "nonexistent.md")
        encoded = self._encode(fake_path)
        with patch("app.modules.auto_next.routes.plans.plan_service") as mock_ps:
            mock_ps.validate_external_path.return_value = True
            resp = client.get(f"/api/v1/auto-next/plans/{encoded}")
        assert resp.status_code == 404

    def test_valid_path_returns_200(self, client, tmp_path):
        """정상 경로 → 200"""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("# Plan\n- [ ] task1", encoding="utf-8")
        encoded = self._encode(str(plan_file))
        with patch("app.modules.auto_next.routes.plans.plan_service") as mock_ps:
            mock_ps.validate_external_path.return_value = True
            mock_ps.get_plan_progress.return_value = {
                "done": 0, "total": 1, "percent": 0,
            }
            resp = client.get(f"/api/v1/auto-next/plans/{encoded}")
        assert resp.status_code == 200

    def test_items_path_traversal_blocked(self, client):
        """items 엔드포인트도 path traversal 차단"""
        malicious = self._encode(r"C:\Windows\System32\drivers\etc\hosts")
        with patch("app.modules.auto_next.routes.plans.plan_service") as mock_ps:
            mock_ps.validate_external_path.return_value = False
            resp = client.get(f"/api/v1/auto-next/plans/{malicious}/items")
        assert resp.status_code == 403

    def test_ignore_invalid_base64_returns_400(self, client):
        """ignore 엔드포인트 잘못된 base64 → 400"""
        resp = client.post("/api/v1/auto-next/plans/not!!valid/ignore")
        assert resp.status_code == 400

    def test_unignore_invalid_base64_returns_400(self, client):
        """unignore 엔드포인트 잘못된 base64 → 400"""
        resp = client.delete("/api/v1/auto-next/plans/not!!valid/ignore")
        assert resp.status_code == 400

    def test_empty_string_path_blocked(self, client):
        """빈 문자열 경로 → validate_external_path가 거부 → 403"""
        # base64("") == "" → URL이 /plans/와 동일해 list 엔드포인트 매칭
        # 대신 공백 경로로 테스트
        encoded = self._encode(" ")
        with patch("app.modules.auto_next.routes.plans.plan_service") as mock_ps:
            mock_ps.validate_external_path.return_value = False
            resp = client.get(f"/api/v1/auto-next/plans/{encoded}")
        assert resp.status_code == 403
