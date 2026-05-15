from app.modules.popply_reservation.utils.hash_normalizer import normalize_schedule_group_hash


def test_hash_normalizer_BOUNDARY_double_encoded_input_matches_api_group():
    assert normalize_schedule_group_hash("q%252Fabc%253D%253D") == "q%2Fabc%3D%3D"


def test_hash_normalizer_RIGHT_already_decoded_input_idempotent():
    assert normalize_schedule_group_hash("q%2Fabc%3D%3D") == "q%2Fabc%3D%3D"
