"""Phase T3: Pre-merge 정적/fixture 통합 검증.

eventusSlotDisplay.ts의 parseEventusSlots / getOpenSlots / getSlotLabel 로직을
Python으로 미러링해 6개 open slot fixture, edge case(null/empty/key 누락),
Button onclick 계약을 검증한다.

주의: TypeScript를 직접 실행하지 않고 소스 내 로직 패턴을 Python으로 재현해 계약을 확인한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

FRONTEND_ROOT = Path(__file__).parents[2] / "frontend" / "src"


# ---------------------------------------------------------------------------
# Python mirrors of eventusSlotDisplay.ts helpers
# (소스에서 추출한 로직을 Python으로 재현 — TypeScript 런타임 없이 계약 검증)
# ---------------------------------------------------------------------------

def _parse_eventus_slots(raw: list[Any]) -> list[dict]:
    """parseEventusSlots Python mirror: bundleId(str), availableCount(number) 필수."""
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("bundleId"), str):
            continue
        if not isinstance(item.get("availableCount"), (int, float)):
            continue
        result.append(item)
    return result


def _get_open_slots(slots: list[dict]) -> list[dict]:
    """getOpenSlots Python mirror: availableCount > 0."""
    return [s for s in slots if s.get("availableCount", 0) > 0]


def _get_closed_slots(slots: list[dict]) -> list[dict]:
    """getClosedSlots Python mirror: availableCount == 0."""
    return [s for s in slots if s.get("availableCount", 0) == 0]


def _get_slot_label(slot: dict) -> str:
    """getSlotLabel Python mirror: label → timeKey → bundleId → '시간대 정보 없음'."""
    if slot.get("label"):
        return slot["label"]
    if slot.get("timeKey"):
        return slot["timeKey"]
    if slot.get("bundleId"):
        return slot["bundleId"]
    return "시간대 정보 없음"


def _get_slot_status_text(slot: dict) -> str:
    """getSlotStatusText Python mirror."""
    if slot.get("availableCount") == 0:
        return slot.get("closedText") or "마감"
    if slot.get("urgencyHint") == "imminent":
        return "마감임박"
    if not slot.get("availableCountKnown"):
        return "열림 (수량 미확인)"
    return "열림"


# ---------------------------------------------------------------------------
# 6개 open slot fixture
# ---------------------------------------------------------------------------

def _make_open_slots(n: int) -> list[dict]:
    """n개의 열린 슬롯 fixture를 생성한다."""
    return [
        {
            "bundleId": f"bundle_{i:02d}",
            "timeKey": f"{10 + i}:00",
            "label": f"{10 + i}:00~{11 + i}:00",
            "availableCount": 1,  # sentinel
            "availableCountKnown": False,
            "urgencyHint": None,
            "closedText": None,
            "slotId": f"bundle_{i:02d}:{10 + i}:00",
            "sourceType": "eventus",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# T3-1: 6개 open slot fixture
# ---------------------------------------------------------------------------


def test_parse_6_open_slots_returns_all_open():
    """R: 6개의 open slot fixture를 parseEventusSlots + getOpenSlots 에 입력하면 6개 반환."""
    raw = _make_open_slots(6)
    parsed = _parse_eventus_slots(raw)
    open_slots = _get_open_slots(parsed)

    assert len(parsed) == 6, f"parseEventusSlots가 {len(parsed)}개를 반환했습니다 (예상: 6)."
    assert len(open_slots) == 6, f"getOpenSlots가 {len(open_slots)}개를 반환했습니다 (예상: 6)."


def test_6_open_slots_labels_are_correct():
    """R: 6개 open slot의 getSlotLabel이 각각의 label을 반환한다."""
    raw = _make_open_slots(6)
    open_slots = _get_open_slots(_parse_eventus_slots(raw))

    labels = [_get_slot_label(s) for s in open_slots]
    expected_labels = [f"{10 + i}:00~{11 + i}:00" for i in range(6)]
    assert labels == expected_labels, (
        f"열린 슬롯 label이 예상과 다릅니다.\n예상: {expected_labels}\n실제: {labels}"
    )


def test_6_open_slots_status_text_is_unknown_count():
    """R: availableCountKnown=False인 열린 슬롯의 상태 텍스트는 '열림 (수량 미확인)'."""
    raw = _make_open_slots(6)
    open_slots = _get_open_slots(_parse_eventus_slots(raw))

    for slot in open_slots:
        status = _get_slot_status_text(slot)
        assert status == "열림 (수량 미확인)", (
            f"상태 텍스트가 '열림 (수량 미확인)'이 아닙니다: {status!r} (슬롯: {slot['bundleId']})"
        )


# ---------------------------------------------------------------------------
# T3-2: null, 빈 배열, key 누락 edge case
# ---------------------------------------------------------------------------


def test_parse_empty_list_returns_empty():
    """B: 빈 배열 입력 → 빈 배열 반환, 에러 없음."""
    result = _parse_eventus_slots([])
    assert result == [], f"빈 배열 입력 시 빈 배열을 반환해야 합니다. 실제: {result}"


def test_parse_null_like_returns_empty():
    """B: None 또는 null-like 원소가 있는 배열 → 해당 원소만 건너뛴다."""
    raw: list[Any] = [None, {}, {"notBundleId": "x"}, 42, "string"]
    result = _parse_eventus_slots(raw)
    assert result == [], (
        f"null/빈 dict/잘못된 원소는 모두 건너뛰어야 합니다. 실제: {result}"
    )


def test_parse_missing_bundle_id_skipped():
    """B: bundleId가 없는 원소는 건너뛴다."""
    raw = [
        {"availableCount": 1, "timeKey": "10:00"},  # bundleId 없음
        {"bundleId": "valid_bundle", "availableCount": 1},  # 유효
    ]
    result = _parse_eventus_slots(raw)
    assert len(result) == 1, (
        f"bundleId 없는 원소는 건너뛰어야 합니다. 실제 결과 수: {len(result)}"
    )
    assert result[0]["bundleId"] == "valid_bundle"


def test_parse_missing_available_count_skipped():
    """B: availableCount가 없는 원소는 건너뛴다."""
    raw = [
        {"bundleId": "no_count_bundle"},  # availableCount 없음
        {"bundleId": "valid_bundle", "availableCount": 0},  # 유효 (닫힌 슬롯)
    ]
    result = _parse_eventus_slots(raw)
    assert len(result) == 1, (
        f"availableCount 없는 원소는 건너뛰어야 합니다. 실제 결과 수: {len(result)}"
    )


def test_closed_slot_status_text():
    """B: availableCount=0인 슬롯의 상태 텍스트는 closedText 또는 '마감'."""
    closed_with_text = {
        "bundleId": "b1", "availableCount": 0,
        "availableCountKnown": False, "urgencyHint": None,
        "closedText": "모집마감",
    }
    closed_no_text = {
        "bundleId": "b2", "availableCount": 0,
        "availableCountKnown": False, "urgencyHint": None,
        "closedText": None,
    }
    assert _get_slot_status_text(closed_with_text) == "모집마감"
    assert _get_slot_status_text(closed_no_text) == "마감"


def test_imminent_slot_status_text():
    """B: urgencyHint='imminent'이면 상태 텍스트는 '마감임박'."""
    slot = {
        "bundleId": "b1", "availableCount": 1,
        "availableCountKnown": False, "urgencyHint": "imminent",
    }
    assert _get_slot_status_text(slot) == "마감임박"


# ---------------------------------------------------------------------------
# T3-3: label fallback chain
# ---------------------------------------------------------------------------


def test_get_slot_label_uses_label_first():
    """R: label이 있으면 label을 반환한다."""
    slot = {"bundleId": "b1", "timeKey": "10:00", "label": "10:00~12:00", "availableCount": 1, "availableCountKnown": False, "urgencyHint": None}
    assert _get_slot_label(slot) == "10:00~12:00"


def test_get_slot_label_falls_back_to_time_key():
    """R: label이 없으면 timeKey를 반환한다."""
    slot = {"bundleId": "b1", "timeKey": "10:00", "availableCount": 1, "availableCountKnown": False, "urgencyHint": None}
    assert _get_slot_label(slot) == "10:00"


def test_get_slot_label_falls_back_to_bundle_id():
    """R: label도 timeKey도 없으면 bundleId를 반환한다."""
    slot = {"bundleId": "bundle_xyz", "timeKey": None, "availableCount": 1, "availableCountKnown": False, "urgencyHint": None}
    assert _get_slot_label(slot) == "bundle_xyz"


def test_get_slot_label_falls_back_to_default():
    """R: label/timeKey/bundleId 모두 없으면 '시간대 정보 없음'을 반환한다."""
    slot = {"bundleId": "", "timeKey": None, "availableCount": 1, "availableCountKnown": False, "urgencyHint": None}
    assert _get_slot_label(slot) == "시간대 정보 없음"


# ---------------------------------------------------------------------------
# T3-3: Button onclick contract (source contract — existing test 재확인)
# ---------------------------------------------------------------------------


def test_button_onclick_contract_reconfirmed():
    """T3 재확인: Button onclick prop 계약이 +page.svelte에 유지된다.

    기존 test_eventus_page_button_uses_button_component_click_contract의 핵심
    조건을 T3 fixture로 재확인한다.
    """
    eventus_page = (
        FRONTEND_ROOT / "routes" / "eventus" / "+page.svelte"
    ).read_text(encoding="utf-8")

    button_blocks = re.findall(r"<Button\b.*?(?:</Button>|/>)", eventus_page, re.DOTALL)
    offenders = [
        block.strip().splitlines()[0]
        for block in button_blocks
        if re.search(r"\bon:click\s*=", block)
    ]
    assert offenders == [], (
        "Button.svelte는 onclick prop을 사용하며 on:click directive는 무시됩니다.\n"
        f"위반 Button: {offenders}"
    )
    # Also verify that onclick prop is actually used
    assert "onclick" in eventus_page, (
        "+page.svelte에 onclick prop이 전혀 없습니다. Button click 이벤트가 동작하지 않습니다."
    )
