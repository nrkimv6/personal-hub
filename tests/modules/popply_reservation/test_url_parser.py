from app.modules.popply_reservation.utils.url_parser import parse_popply_reservation_url


def test_parse_popply_url_RIGHT_extracts_store_type_hash():
    parsed = parse_popply_reservation_url(
        "https://popply.co.kr/popup/4727/reservation/pre/q%252Fabc%253D%253D"
    )

    assert parsed.store_id == "4727"
    assert parsed.reservation_type == "PRE"
    assert parsed.source_hash == "q%252Fabc%253D%253D"
    assert parsed.target_schedule_group == "q%2Fabc%3D%3D"
