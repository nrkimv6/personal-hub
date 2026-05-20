import copy
import json
from pathlib import Path

from app.modules.naver_popup_monitor.services.place_reservation import (
    extract_place_reservation_state,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _first_detail(state: dict) -> dict:
    root_query = state["ROOT_QUERY"]
    return next(value for key, value in root_query.items() if key.startswith("placeDetail("))


def test_place_fixture_available_RIGHT_detects_booking_signals():
    fixture = _load_fixture("place_2021908137_available.json")

    state = extract_place_reservation_state(
        fixture,
        rendered_dom=[
            {
                "text": "메르세데스-벤츠 스튜디오 : 전시 관람",
                "href": "https://m.booking.naver.com/booking/6/bizes/1643675/items/7627870?area=ple",
                "visible": True,
            }
        ],
    )

    assert state.available is True
    assert state.booking_business_id == "1643675"
    assert state.booking_url == "https://booking.naver.com/booking/6/bizes/1643675/search"
    assert state.ticket_count == 1
    assert any(signal.kind == "concrete_booking_link" for signal in state.signals)


def test_place_fixture_unavailable_E_ignores_booking_text_only():
    fixture = _load_fixture("place_unavailable_booking_button_only.json")

    state = extract_place_reservation_state(
        fixture,
        rendered_dom=[
            {
                "text": "예약",
                "href": "https://m.place.naver.com/popupstore/2003552546/booking",
                "visible": True,
            },
            {
                "text": "사전 예약",
                "href": "https://m.blog.naver.com/example",
                "visible": True,
            },
        ],
    )

    assert state.available is False
    assert state.signals == []
    assert state.concrete_links == []


def test_place_fixture_transition_R_url_injection_changes_to_available():
    fixture = _load_fixture("place_unavailable_booking_button_only.json")
    changed = copy.deepcopy(fixture)
    detail = _first_detail(changed)
    detail["naverBooking"]["naverBookingUrl"] = (
        "https://booking.naver.com/booking/6/bizes/1643675/search"
    )

    before = extract_place_reservation_state(fixture)
    after = extract_place_reservation_state(changed)

    assert before.available is False
    assert after.available is True
    assert after.booking_url == "https://booking.naver.com/booking/6/bizes/1643675/search"

