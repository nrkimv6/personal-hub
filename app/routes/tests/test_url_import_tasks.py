import pytest
from fastapi import BackgroundTasks

from app.modules.naver_booking.routes.business import (
    start_import_from_url_task as start_business_import_from_url_task,
)
from app.routes.events import start_import_from_url_task as start_event_import_from_url_task
from app.schemas.business import UrlImportRequest
from app.schemas.event import EventImportFromUrl
from app.services.import_task_store import get_import_task


pytestmark = pytest.mark.http


def test_event_import_from_url_start_defers_extraction_work():
    background_tasks = BackgroundTasks()

    response = start_event_import_from_url_task(
        EventImportFromUrl(url="https://example.com/event", auto_save=False),
        background_tasks=background_tasks,
        admin=object(),
    )

    task = get_import_task(response["task_id"])
    assert response["status"] == "pending"
    assert response["phase"] == "queued"
    assert task is not None
    assert task["kind"] == "event_url_import"
    assert task["url"] == "https://example.com/event"
    assert len(background_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_business_import_url_start_defers_network_work():
    background_tasks = BackgroundTasks()

    response = await start_business_import_from_url_task(
        UrlImportRequest(
            url="https://booking.naver.com/booking/6/bizes/123/items/456",
            fetch_details=True,
        ),
        background_tasks=background_tasks,
    )

    task = get_import_task(response["task_id"])
    assert response["status"] == "pending"
    assert response["phase"] == "queued"
    assert task is not None
    assert task["kind"] == "business_url_import"
    assert task["url"] == "https://booking.naver.com/booking/6/bizes/123/items/456"
    assert len(background_tasks.tasks) == 1
