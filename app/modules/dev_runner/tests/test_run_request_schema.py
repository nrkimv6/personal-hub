"""RunRequest schema — session_id / fused_session 필드 TC (T1)"""

import uuid
import pytest
from pydantic import ValidationError

from app.modules.dev_runner.schemas import RunRequest


class TestRunRequestSessionId:
    def test_session_id_R_optional(self):
        """R: session_id 미지정 시 None"""
        req = RunRequest()
        assert req.session_id is None

    def test_session_id_E_invalid_type(self):
        """E: session_id에 int 타입 전달 → ValidationError"""
        with pytest.raises((ValidationError, TypeError)):
            # Pydantic V2는 int→str 강제 변환 허용할 수 있어 명시적 검증
            req = RunRequest(session_id=12345)
            # 만약 변환됐으면 "12345" 문자열 — executor에서 UUID 검증 실패 후 재발급되므로 허용
            # 단 타입이 str이 아닌 경우만 에러 (Pydantic v2는 str로 coerce)
            assert isinstance(req.session_id, (str, type(None)))

    def test_fused_session_R_default_false(self):
        """R: fused_session 기본값 False"""
        req = RunRequest()
        assert req.fused_session is False

    def test_session_id_valid_uuid_accepted(self):
        """R: 유효한 UUID → 그대로 저장"""
        sid = str(uuid.uuid4())
        req = RunRequest(session_id=sid)
        assert req.session_id == sid

    def test_fused_session_true(self):
        """R: fused_session=True → True 저장"""
        req = RunRequest(fused_session=True)
        assert req.fused_session is True
