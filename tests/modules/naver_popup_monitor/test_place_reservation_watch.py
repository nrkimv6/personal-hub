from datetime import datetime, timedelta

import pytest

from scripts.monitors.naver_place_reservation_watch import (
    KST,
    build_alert_message,
    build_place_url,
    compute_watch_window,
    parse_until,
    should_alert,
    state_from_payload,
)


def test_watch_deadline_R_defaults_to_18_hours_from_started_at():
    started_at = datetime(2026, 5, 20, 9, 0, 0, tzinfo=KST)

    window = compute_watch_window(started_at=started_at)

    assert window.started_at == started_at
    assert window.deadline == started_at + timedelta(hours=18)
    assert window.duration_hours == 18.0
    assert window.timezone == "Asia/Seoul"


def test_watch_deadline_R_until_overrides_duration():
    started_at = datetime(2026, 5, 20, 9, 0, 0, tzinfo=KST)

    window = compute_watch_window(
        started_at=started_at,
        duration_hours=18,
        until="2026-05-20T12:30:00+09:00",
    )

    assert window.deadline == datetime(2026, 5, 20, 12, 30, 0, tzinfo=KST)
    assert window.duration_hours == 3.5


def test_watch_deadline_E_past_until_rejected():
    now = datetime(2026, 5, 20, 9, 0, 0, tzinfo=KST)

    with pytest.raises(ValueError, match="future"):
        parse_until("2026-05-20T08:59:59+09:00", now=now)


def test_build_place_url_R_uses_mobile_popupstore_canonical():
    assert (
        build_place_url("2003552546")
        == "https://m.place.naver.com/popupstore/2003552546/home"
    )


def test_state_from_payload_R_preserves_signal_detail_for_alert_message():
    state = state_from_payload(
        {
            "available": True,
            "booking_business_id": "1643675",
            "booking_url": "https://booking.naver.com/booking/6/bizes/1643675/search",
            "ticket_count": 1,
            "concrete_links": [
                "https://m.booking.naver.com/booking/6/bizes/1643675/items/7627870"
            ],
            "signals": [
                {
                    "kind": "booking_url",
                    "path": "placeDetail[0].naverBooking.naverBookingUrl",
                    "value": "https://booking.naver.com/booking/6/bizes/1643675/search",
                    "url": "https://booking.naver.com/booking/6/bizes/1643675/search",
                }
            ],
        }
    )

    message = build_alert_message("https://m.place.naver.com/popupstore/2021908137/home", state)

    assert state.available is True
    assert state.signals[0].kind == "booking_url"
    assert "bookingBusinessId: 1643675" in message
    assert "booking_url: https://booking.naver.com/booking/6/bizes/1643675/search" in message


def test_should_alert_R_only_unavailable_to_available_transition():
    state = state_from_payload({"available": True, "signals": []})

    assert should_alert({"available": False}, state) is True
    assert should_alert({"available": True}, state) is False
