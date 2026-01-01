"""
워커 안정성 버그 수정 테스트

테스트 대상:
1. PROXY_ENABLED 설정 적용 (버그 1)

RIGHT-BICEP 원칙:
- Right: 올바른 결과 반환
- Boundary: 경계 조건 테스트
- Inverse: 반대 조건 테스트
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트 (해당시)
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock


class TestProxyEnabledSetting:
    """버그 1: PROXY_ENABLED 설정 테스트"""

    @pytest.mark.asyncio
    async def test_initialize_proxy_manager_disabled(self):
        """[Right] PROXY_ENABLED=False일 때 None 반환"""
        with patch("app.services.proxy_manager_factory.settings") as mock_settings:
            mock_settings.PROXY_ENABLED = False

            from app.services.proxy_manager_factory import initialize_proxy_manager

            result = await initialize_proxy_manager()

            assert result is None

    @pytest.mark.asyncio
    async def test_initialize_proxy_manager_enabled(self):
        """[Right] PROXY_ENABLED=True일 때 프록시 매니저 반환"""
        with patch("app.services.proxy_manager_factory.settings") as mock_settings, \
             patch("app.services.proxy_manager_factory.get_proxy_manager") as mock_get, \
             patch("app.services.proxy_manager_factory._proxy_manager_instance", None):

            mock_settings.PROXY_ENABLED = True
            mock_settings.PROXY_BACKEND = "file"
            mock_manager = MagicMock()
            mock_manager.is_available = True
            mock_get.return_value = mock_manager

            from app.services.proxy_manager_factory import initialize_proxy_manager

            result = await initialize_proxy_manager()

            assert result is not None
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_proxy_manager_logs_disabled_message(self):
        """[Right] PROXY_ENABLED=False일 때 로그 메시지 출력"""
        with patch("app.services.proxy_manager_factory.settings") as mock_settings, \
             patch("app.services.proxy_manager_factory.logger") as mock_logger:

            mock_settings.PROXY_ENABLED = False

            from app.services.proxy_manager_factory import initialize_proxy_manager

            await initialize_proxy_manager()

            mock_logger.info.assert_called_with("PROXY_ENABLED=False, 프록시 매니저 비활성화")
