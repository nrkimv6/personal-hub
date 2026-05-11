import json

from app.modules.naver_popup_monitor.services.diff_service import calculate_popup_diff
from app.modules.naver_popup_monitor.services.popup_parser import parse_popup_items_from_html


def _build_apollo_html() -> str:
    apollo = {
        "ROOT_QUERY": {
            "popupStoreList": ["PopupStore:1", "PopupStore:2"],
        },
        "PopupStore:1": {
            "__typename": "PopupStore",
            "popupId": "p-1",
            "title": "테스트 팝업 1",
            "placeName": "성수",
            "startDate": "2026-04-10",
            "endDate": "2026-04-20",
            "bookingUrl": "https://example.com/popup/1",
        },
        "PopupStore:2": {
            "__typename": "PopupStore",
            "popupId": "p-2",
            "title": "테스트 팝업 2",
            "placeName": "홍대",
            "startDate": "2026-04-12",
            "endDate": "2026-04-25",
        },
    }
    return (
        "<html><head></head><body><script>"
        f"window.__APOLLO_STATE__ = {json.dumps(apollo, ensure_ascii=False)}"
        "</script></body></html>"
    )


def test_popup_parser_extracts_items():
    result = parse_popup_items_from_html(_build_apollo_html())

    assert result.has_apollo_state is True
    assert result.parse_error is None
    assert len(result.items) == 2
    assert any(item.popup_id == "p-1" for item in result.items)
    assert any(item.title == "테스트 팝업 2" for item in result.items)


def test_popup_parser_handles_missing_apollo():
    result = parse_popup_items_from_html("<html><body>hello</body></html>")
    assert result.has_apollo_state is False
    assert result.parse_error == "apollo_state_not_found"
    assert result.items == []


def test_popup_parser_apollo_parse_error_keeps_partial_diff_empty():
    result = parse_popup_items_from_html(
        '<html><body><script>window.__APOLLO_STATE__ = {"ROOT_QUERY": ]}</script></body></html>'
    )

    assert result.has_apollo_state is True
    assert result.parse_error.startswith("apollo_json_decode_error:")
    assert result.items == []

    diff = calculate_popup_diff([], [item.to_dict() for item in result.items])
    assert diff.new_items == []
    assert diff.updated_items == []
    assert diff.removed_items == []
    assert diff.new_count == 0
    assert diff.has_new is False


def test_diff_service_new_updated_removed():
    previous = [
        {
            "item_key": "id:p-1",
            "title": "팝업A",
            "place_name": "성수",
            "start_date": "2026-04-10",
            "end_date": "2026-04-20",
            "status": None,
            "reservation_url": None,
        },
        {
            "item_key": "id:p-2",
            "title": "팝업B",
            "place_name": "홍대",
            "start_date": "2026-04-11",
            "end_date": "2026-04-21",
            "status": None,
            "reservation_url": None,
        },
    ]
    current = [
        {
            "item_key": "id:p-2",
            "title": "팝업B(수정)",
            "place_name": "홍대",
            "start_date": "2026-04-11",
            "end_date": "2026-04-21",
            "status": None,
            "reservation_url": None,
        },
        {
            "item_key": "id:p-3",
            "title": "팝업C",
            "place_name": "잠실",
            "start_date": "2026-04-12",
            "end_date": "2026-04-22",
            "status": None,
            "reservation_url": None,
        },
    ]

    diff = calculate_popup_diff(previous, current)

    assert diff.new_count == 1
    assert diff.has_new is True
    assert len(diff.updated_items) == 1
    assert len(diff.removed_items) == 1
    assert diff.new_items[0]["item_key"] == "id:p-3"
