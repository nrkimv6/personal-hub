import json
import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _json_response(payload: dict | list, status: int = 200) -> dict:
    return {
        "status": status,
        "content_type": "application/json",
        "body": json.dumps(payload, ensure_ascii=False),
    }


def _stub_file_search_bootstrap(page: Page) -> None:
    page.route(
        "**/api/v1/file-search/status",
        lambda route: route.fulfill(
            **_json_response(
                {
                    "everything_ok": True,
                    "ripgrep_ok": True,
                    "indexed_paths": [],
                    "last_indexed_at": None,
                }
            )
        ),
    )
    page.route("**/api/v1/file-search/history**", lambda route: route.fulfill(**_json_response({"items": []})))
    page.route("**/api/v1/file-search/frequent-combos**", lambda route: route.fulfill(**_json_response({"items": []})))
    page.route("**/api/v1/file-search/presets**", lambda route: route.fulfill(**_json_response({"items": []})))


def _stub_image_pdf_task_flow(page: Page) -> None:
    page.route(
        "**/api/v1/image-pdf/health",
        lambda route: route.fulfill(
            **_json_response(
                {
                    "supported_extensions": [".png", ".jpg", ".jpeg", ".webp"],
                    "heic_supported": True,
                    "pillow_version": "test",
                    "max_files": 50,
                    "max_per_file_mb": 25,
                    "max_total_mb": 200,
                }
            )
        ),
    )
    page.route(
        "**/api/v1/image-pdf/convert",
        lambda route: route.fulfill(
            **_json_response(
                {
                    "task_id": "e2e-task",
                    "status": "queued",
                    "artifact_url": "/api/v1/image-pdf/tasks/e2e-task/result",
                },
                status=202,
            )
        ),
    )
    page.route(
        "**/api/v1/image-pdf/tasks/e2e-task",
        lambda route: route.fulfill(
            **_json_response(
                {
                    "task_id": "e2e-task",
                    "status": "queued",
                    "source_names": ["sample.png"],
                    "file_count": 1,
                    "bw": False,
                    "white": 200,
                    "black": 80,
                    "quality": 85,
                    "preserve_dpi": False,
                    "download_filename": "sample.pdf",
                    "artifact_url": "/api/v1/image-pdf/tasks/e2e-task/result",
                    "error_message": None,
                    "created_at": "2026-05-11T00:00:00Z",
                    "started_at": None,
                    "completed_at": None,
                }
            )
        ),
    )


def test_image_pdf_task_acceptance_does_not_block_navigation(page: Page, frontend_url: str):
    _stub_file_search_bootstrap(page)
    _stub_image_pdf_task_flow(page)

    page.goto(f"{frontend_url}/file-search?tab=image-pdf")
    expect(page.get_by_text("이미지 업로드")).to_be_visible(timeout=10000)

    page.locator('input[type="file"]').set_input_files(
        {
            "name": "sample.png",
            "mimeType": "image/png",
            "buffer": b"\x89PNG\r\n\x1a\n",
        }
    )
    page.get_by_role("button", name="PDF로 변환").click()

    expect(page.get_by_role("heading", name="변환 작업")).to_be_visible()
    expect(page.get_by_text("대기 중")).to_be_visible()
    page.get_by_role("button", name="파일 검색").click()
    expect(page).to_have_url(re.compile(r".*[?&]tab=search"))
