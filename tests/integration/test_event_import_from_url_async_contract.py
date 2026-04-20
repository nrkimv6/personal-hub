import pytest
from unittest.mock import MagicMock, patch

from app.models.event import Event
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.worker.worker import save_event_import_result
from app.schemas.event import EventImportFromUrl
from app.services.event_service import EventService
from app.services.page_extractor.base import ExtractedContent


pytestmark = pytest.mark.integration


@patch("app.modules.claude_worker.services.llm_service.LLMService.resolve_provider_model")
@patch("app.services.event_service.asyncio.get_event_loop")
def test_import_from_url_integration_creates_pending_llm_request(
    mock_get_event_loop, mock_resolve_provider_model, test_db_session
):
    service = EventService()
    mock_extracted = ExtractedContent(
        url="https://example.com/integration-event",
        page_type="generic",
        extraction_method="fallback",
        title="통합 테스트 이벤트",
        content="통합 테스트 본문",
        success=True,
    )
    mock_resolve_provider_model.return_value = ("claude", "sonnet-test")
    mock_get_event_loop.return_value.run_until_complete.return_value = mock_extracted

    with patch.object(
        service,
        "_extract_page_content",
        new=MagicMock(return_value=mock_extracted),
    ):
        response = service.import_from_url(
            test_db_session,
            EventImportFromUrl(url="https://example.com/integration-event", auto_save=False),
        )

    saved_request = (
        test_db_session.query(LLMRequest)
        .filter(LLMRequest.caller_type == "event_import")
        .filter(LLMRequest.caller_id == "https://example.com/integration-event")
        .one()
    )

    assert response.success is True
    assert response.request_id == saved_request.id
    assert saved_request.status == "pending"
    assert (
        test_db_session.query(Event)
        .filter(Event.source_url == "https://example.com/integration-event")
        .count()
        == 0
    )


def test_save_event_import_result_integration_creates_event_from_worker_result(test_db_session):
    request = LLMRequest(
        caller_type="event_import",
        caller_id="https://example.com/worker-event",
        prompt="test prompt",
        status="processing",
        requested_by="api",
        request_source="event_import",
        provider="claude",
        model="sonnet-test",
    )
    test_db_session.add(request)
    test_db_session.commit()
    test_db_session.refresh(request)

    result = {
        "result": {
            "is_event": True,
            "title": "워커 생성 이벤트",
            "summary": "워커 후처리로 생성됨",
            "organizer": "테스트 주최",
            "event_period": {
                "start": "2026-04-20",
                "end": "2026-04-27",
            },
            "announcement_date": "2026-04-30",
            "urls": [
                "https://example.com/landing",
                "https://example.com/detail",
            ],
            "prizes": ["상품권"],
            "winner_count": 3,
        }
    }

    assert save_event_import_result(test_db_session, request, result) is True

    saved_event = (
        test_db_session.query(Event)
        .filter(Event.source_url == "https://example.com/worker-event")
        .one()
    )

    assert saved_event.title == "워커 생성 이벤트"
    assert saved_event.event_url == "https://example.com/landing"
    assert saved_event.additional_urls == ["https://example.com/detail"]
    assert saved_event.source_type == "web"
    assert saved_event.input_source == "ai"
