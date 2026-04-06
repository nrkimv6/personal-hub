import random

from app.modules.naver_popup_monitor.services.fetcher import (
    build_attempt_profiles,
    get_headers_for_profile,
)


def test_profile_headers_shape():
    headers_a = get_headers_for_profile("A")
    headers_b = get_headers_for_profile("B")
    headers_c = get_headers_for_profile("C")

    assert set(headers_a.keys()) == {"User-Agent", "Accept-Language", "Accept", "Referer"}
    assert set(headers_b.keys()) == {"User-Agent", "Accept-Language"}
    assert set(headers_c.keys()) == {"Accept-Language"}


def test_reinforce_profile_order_ring():
    assert build_attempt_profiles("A", "reinforce") == ["A", "B", "C"]
    assert build_attempt_profiles("B", "reinforce") == ["B", "C", "A"]
    assert build_attempt_profiles("C", "reinforce") == ["C", "A", "B"]


def test_random_rotate_includes_all_profiles():
    order = build_attempt_profiles("A", "random_rotate", rng=random.Random(7))
    assert sorted(order) == ["A", "B", "C"]
    assert len(set(order)) == 3
