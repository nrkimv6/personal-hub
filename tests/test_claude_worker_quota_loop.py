"""
worker.py quota loop registry 참조 TC (REFERENCE)

테스트 대상: LLMWorker._check_quota_resume() / _process_pending_requests()
provider_registry.get_quota_providers() 반환값이 루프에 사용되는지 검증.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_quota_loop_Re_uses_registry_not_hardcoded_list():
    """_check_quota_resume()이 provider_registry.get_quota_providers() 결과를 루프에 사용 (REFERENCE).

    mock provider_registry.get_quota_providers() 반환값을 ["testprov_a", "testprov_b"]로
    교체 후, get_provider_quota_pause가 해당 키들로 호출되는지 확인한다.
    """
    from app.modules.claude_worker.services.llm_service import LLMService

    fake_providers = ["testprov_a", "testprov_b"]

    mock_service = MagicMock(spec=LLMService)
    mock_service.get_provider_quota_pause.return_value = None
    mock_service.get_blocked_pending_count.return_value = 0

    with patch(
        "app.modules.claude_worker.worker.worker.provider_registry"
    ) as mock_registry, patch(
        "app.modules.claude_worker.worker.worker.LLMService",
        return_value=mock_service,
    ), patch(
        "app.modules.claude_worker.worker.worker.SessionLocal"
    ) as mock_session_local:
        mock_registry.get_quota_providers.return_value = fake_providers
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        # _check_quota_resume()은 async, asyncio.run으로 실행
        import asyncio
        from app.modules.claude_worker.worker.worker import LLMWorker

        worker = LLMWorker.__new__(LLMWorker)
        asyncio.run(worker._check_quota_resume())

    # registry가 호출됐는지 확인
    mock_registry.get_quota_providers.assert_called()

    # fake_providers 각각에 대해 get_provider_quota_pause가 호출됐는지 확인
    called_providers = [
        call.args[0] for call in mock_service.get_provider_quota_pause.call_args_list
    ]
    assert "testprov_a" in called_providers, f"testprov_a 호출 없음. 실제 호출: {called_providers}"
    assert "testprov_b" in called_providers, f"testprov_b 호출 없음. 실제 호출: {called_providers}"
    # 하드코딩된 "gemini", "claude"만 호출됐으면 안 됨
    assert called_providers == fake_providers or set(fake_providers).issubset(set(called_providers))


def test_quota_loop_Re_process_pending_uses_registry_quota_providers():
    """_process_pending_requests()도 provider_registry.get_quota_providers()를 사용 (REFERENCE).

    fake_providers 이외에 "gemini"/"claude" 하드코딩 잔여가 없는지 검증.
    """
    from app.modules.claude_worker.services.llm_service import LLMService

    fake_providers = ["custom_prov_x"]

    mock_service = MagicMock(spec=LLMService)
    mock_service.get_provider_quota_pause.return_value = None
    mock_service.get_blocked_pending_count.return_value = 0
    mock_service.get_next_request.return_value = None  # 처리할 요청 없음

    with patch(
        "app.modules.claude_worker.worker.worker.provider_registry"
    ) as mock_registry, patch(
        "app.modules.claude_worker.worker.worker.LLMService",
        return_value=mock_service,
    ), patch(
        "app.modules.claude_worker.worker.worker.SessionLocal"
    ) as mock_session_local:
        mock_registry.get_quota_providers.return_value = fake_providers
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        import asyncio
        from app.modules.claude_worker.worker.worker import LLMWorker

        worker = LLMWorker.__new__(LLMWorker)
        asyncio.run(worker._process_pending_requests())

    mock_registry.get_quota_providers.assert_called()

    called_providers = [
        call.args[0] for call in mock_service.get_provider_quota_pause.call_args_list
    ]
    # fake provider가 호출됐는지 확인
    assert "custom_prov_x" in called_providers
    # 하드코딩된 "gemini" 또는 "claude"가 *별도로* 추가 호출됐으면 안 됨
    # (fake_providers 외의 하드코딩 잔여 검증)
    for provider in called_providers:
        assert provider in fake_providers, (
            f"하드코딩 잔여 감지: '{provider}'는 fake_providers에 없음. "
            "worker.py에 하드코딩이 남아있을 수 있음."
        )
