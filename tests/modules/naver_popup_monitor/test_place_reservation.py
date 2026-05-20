import json

from app.modules.naver_popup_monitor.services.place_reservation import (
    build_place_reservation_url,
    extract_place_reservation_state,
    extract_place_id,
)


def _html(apollo_state: dict) -> str:
    return (
        "<html><body><script>"
        f"window.__APOLLO_STATE__ = {json.dumps(apollo_state, ensure_ascii=False)};"
        "</script></body></html>"
    )


def _place_state(naver_booking: dict, tickets: dict | None = None) -> dict:
    detail = {
        "__typename": "PlaceDetail",
        "naverBooking": naver_booking,
        "tickets": tickets or {
            "__typename": "TicketItemsResult",
            "total": 0,
            "items": [],
            "moreBookingUrl": "",
        },
    }
    return {
        "ROOT_QUERY": {
            'placeDetail({"input":{"deviceType":"pc","id":"2003552546","isNx":false}})': detail
        }
    }


def test_extract_place_reservation_state_R_booking_button_name_only_is_not_available():
    state = extract_place_reservation_state(
        _html(
            _place_state(
                {
                    "__typename": "PlaceDetailNaverBooking",
                    "bookingBusinessId": None,
                    "naverBookingUrl": None,
                    "naverBookingHubUrl": None,
                    "bookingDisplayName": "방문",
                    "bookingButtonName": "예약",
                }
            )
        )
    )

    assert state.available is False
    assert state.signals == []
    assert state.booking_business_id is None
    assert state.booking_url is None


def test_extract_place_reservation_state_R_booking_url_available():
    state = extract_place_reservation_state(
        _html(
            _place_state(
                {
                    "__typename": "PlaceDetailNaverBooking",
                    "bookingBusinessId": None,
                    "naverBookingUrl": "https://booking.naver.com/booking/6/bizes/1643675/search",
                    "naverBookingHubUrl": None,
                    "bookingButtonName": "예약",
                }
            )
        )
    )

    assert state.available is True
    assert state.booking_url == "https://booking.naver.com/booking/6/bizes/1643675/search"
    assert any(signal.kind == "booking_url" for signal in state.signals)


def test_extract_place_reservation_state_R_booking_business_id_available():
    state = extract_place_reservation_state(
        _html(
            _place_state(
                {
                    "__typename": "PlaceDetailNaverBooking",
                    "bookingBusinessId": "1643675",
                    "naverBookingUrl": None,
                    "naverBookingHubUrl": None,
                    "bookingButtonName": "예약",
                }
            )
        )
    )

    assert state.available is True
    assert state.booking_business_id == "1643675"
    assert any(signal.kind == "booking_business_id" for signal in state.signals)


def test_extract_place_reservation_state_R_ticket_items_available():
    state = extract_place_reservation_state(
        _html(
            _place_state(
                {
                    "__typename": "PlaceDetailNaverBooking",
                    "bookingBusinessId": None,
                    "naverBookingUrl": None,
                    "naverBookingHubUrl": None,
                    "bookingButtonName": "예약",
                },
                tickets={
                    "__typename": "TicketItemsResult",
                    "total": 1,
                    "moreBookingUrl": "https://m.booking.naver.com/booking/5/bizes/1643675",
                    "items": [
                        {
                            "__typename": "TicketItem",
                            "bookingUrl": "https://m.booking.naver.com/booking/6/bizes/1643675/items/7627870",
                        }
                    ],
                },
            )
        )
    )

    assert state.available is True
    assert state.ticket_count == 1
    assert any(signal.kind == "ticket_items" for signal in state.signals)
    assert state.concrete_links == [
        "https://m.booking.naver.com/booking/6/bizes/1643675/items/7627870",
        "https://m.booking.naver.com/booking/5/bizes/1643675",
    ]


def test_extract_place_reservation_state_E_root_booking_config_url_ignored():
    state = extract_place_reservation_state(
        {},
        rendered_dom=[
            {
                "text": "예약",
                "href": "https://booking.naver.com",
                "visible": True,
            },
            {
                "text": "예약하기",
                "href": "https://m.booking.naver.com/",
                "visible": True,
            },
        ],
    )

    assert state.available is False
    assert state.concrete_links == []


def test_extract_place_reservation_state_B_empty_apollo_returns_unavailable():
    state = extract_place_reservation_state({})

    assert state.available is False
    assert state.to_dict() == {
        "available": False,
        "signals": [],
        "booking_business_id": None,
        "booking_url": None,
        "ticket_count": 0,
        "concrete_links": [],
    }


def test_extract_place_id_C_cross_check_naver_place_url_variants():
    assert extract_place_id("2015421037") == "2015421037"
    assert (
        extract_place_id("https://map.naver.com/p/entry/place/2015421037?c=15.00,0,0,0,dh")
        == "2015421037"
    )
    assert extract_place_id("https://pcmap.place.naver.com/place/2015421037/home") == "2015421037"
    assert (
        extract_place_id("https://m.place.naver.com/popupstore/2015421037/home")
        == "2015421037"
    )
    assert extract_place_id("https://example.com/not-place") is None


def test_build_place_reservation_url_C_canonical_popupstore_home():
    assert (
        build_place_reservation_url("2015421037")
        == "https://m.place.naver.com/popupstore/2015421037/home"
    )


def test_extract_place_reservation_state_R_2015421037_baseline_unavailable():
    state = extract_place_reservation_state(
        _html(
            _place_state(
                {
                    "__typename": "PlaceDetailNaverBooking",
                    "bookingBusinessId": None,
                    "naverBookingUrl": None,
                    "naverBookingHubUrl": None,
                    "bookingButtonName": "예약",
                    "bookingDisplayName": "사전예약",
                }
            )
        )
    )

    assert state.available is False
    assert state.ticket_count == 0
    assert state.concrete_links == []

