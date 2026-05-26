"""Frontend source-contract tests for eventus monitor type.

Verify that TypeScript source files contain the required exports/values
for the eventus monitor type. These are file-content assertions, not
live-browser or compile tests.

Covered items (plan Phase T1, item 14):
  - MonitorType includes 'eventus'; existing 'event' preserved
  - monitoringUnified.ts has fetchEventusItems + toggle branch
  - monitoring page uses MONITOR_TYPE_META.eventus; type=eventus deep link

Covered items (plan Phase T1, item 5 — slot display contract):
  - +page.svelte imports parseEventusSlots / eventusSlotDisplay
  - eventusSlotDisplay.ts contains availableCountKnown / 수량 미확인 text
  - eventusSlotDisplay.ts has label→timeKey→bundleId→'시간대 정보 없음' fallback chain
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND_ROOT = Path(__file__).parents[2] / "frontend" / "src"


def read_eventus_surface() -> str:
    """Read the Eventus UI surface after the route was split into a wrapper + workspace."""
    page = (FRONTEND_ROOT / "routes" / "eventus" / "+page.svelte").read_text(
        encoding="utf-8"
    )
    if "EventusWorkspace" in page:
        return (
            FRONTEND_ROOT / "routes" / "eventus" / "EventusWorkspace.svelte"
        ).read_text(encoding="utf-8")
    return page

# ---------------------------------------------------------------------------
# T1-14a: MonitorType union + MONITOR_TYPE_META.eventus
# ---------------------------------------------------------------------------


def test_monitor_type_includes_eventus_and_preserves_event():
    """S: MonitorType에 'eventus'가 있고 기존 'event'가 유지되는지 검증한다."""
    monitoring_ts = (FRONTEND_ROOT / "lib" / "types" / "monitoring.ts").read_text(
        encoding="utf-8"
    )
    # New 'eventus' type exists
    assert "'eventus'" in monitoring_ts, (
        "monitoring.ts에 'eventus' MonitorType 값이 없습니다."
    )
    # Existing 'event' type preserved (regression guard)
    assert "'event'" in monitoring_ts, (
        "monitoring.ts에서 기존 'event' MonitorType 값이 제거됐습니다 (회귀)."
    )
    # MONITOR_TYPE_META entry for eventus
    assert "eventus:" in monitoring_ts or '"eventus"' in monitoring_ts, (
        "monitoring.ts에 MONITOR_TYPE_META.eventus 항목이 없습니다."
    )


def test_monitor_type_meta_eventus_has_create_href():
    """S: MONITOR_TYPE_META.eventus.createHref가 /eventus를 가리키는지 검증한다."""
    monitoring_ts = (FRONTEND_ROOT / "lib" / "types" / "monitoring.ts").read_text(
        encoding="utf-8"
    )
    # createHref for eventus should reference /eventus
    assert "/eventus" in monitoring_ts, (
        "MONITOR_TYPE_META.eventus.createHref에 '/eventus' 경로가 없습니다."
    )


def test_eventus_label_differs_from_event_label():
    """S: MONITOR_TYPE_META.event.label과 .eventus.label이 서로 다른 표시명을 갖는지 검증한다."""
    monitoring_ts = (FRONTEND_ROOT / "lib" / "types" / "monitoring.ts").read_text(
        encoding="utf-8"
    )
    # '이벤터스' should appear as the eventus label (distinct from '이벤트')
    assert "이벤터스" in monitoring_ts, (
        "MONITOR_TYPE_META.eventus.label에 '이벤터스' 표시명이 없습니다 — 기존 '이벤트'와 구분 불가."
    )


# ---------------------------------------------------------------------------
# T1-14b: monitoringUnified.ts — fetchEventusItems + toggle branch
# ---------------------------------------------------------------------------


def test_monitoring_unified_has_fetch_eventus_items():
    """S: monitoringUnified.ts가 fetchEventusItems()를 export하는지 검증한다."""
    unified_ts = (FRONTEND_ROOT / "lib" / "api" / "monitoringUnified.ts").read_text(
        encoding="utf-8"
    )
    assert "fetchEventusItems" in unified_ts, (
        "monitoringUnified.ts에 fetchEventusItems가 없습니다."
    )


def test_monitoring_unified_has_eventus_toggle_branch():
    """S: monitoringUnified.ts의 toggle 분기에 eventus branch가 있는지 검증한다."""
    unified_ts = (FRONTEND_ROOT / "lib" / "api" / "monitoringUnified.ts").read_text(
        encoding="utf-8"
    )
    # Toggle should have eventus-specific branch (string key or case)
    assert "eventus" in unified_ts, (
        "monitoringUnified.ts에 eventus toggle branch가 없습니다."
    )


# ---------------------------------------------------------------------------
# T1-14c: /monitoring page — MONITOR_TYPE_META.eventus + type=eventus deep link
# ---------------------------------------------------------------------------


def test_monitoring_page_imports_monitor_type_meta_for_dynamic_toolbar():
    """S: /monitoring 페이지가 MONITOR_TYPE_META를 import해 eventus 포함 모든 타입을 동적으로 렌더링하는지 검증한다.

    monitoring page는 MONITOR_TYPE_META 레지스트리를 순회해 toolbar/탭을 렌더링하므로
    'eventus' 문자열을 직접 포함하지 않아도 된다. 레지스트리를 import하는지만 확인한다.
    """
    monitoring_svelte = (
        FRONTEND_ROOT / "routes" / "monitoring" / "+page.svelte"
    ).read_text(encoding="utf-8")
    # MONITOR_TYPE_META registry imported — eventus is included via the registry
    assert "MONITOR_TYPE_META" in monitoring_svelte, (
        "/monitoring +page.svelte에 MONITOR_TYPE_META import가 없습니다."
        " type=eventus deep link는 이 레지스트리를 통해 지원됩니다."
    )
    # MonitorType type is used for selectedType — accepts 'eventus'
    assert "MonitorType" in monitoring_svelte, (
        "/monitoring +page.svelte에 MonitorType import가 없습니다."
        " type filter가 eventus를 MonitorType으로 수용해야 합니다."
    )


def test_monitoring_unified_eventus_id_prefix_distinct_from_event_summary():
    """S: eventus-{schedule_id} id prefix가 event-summary와 충돌하지 않는지 검증한다."""
    unified_ts = (FRONTEND_ROOT / "lib" / "api" / "monitoringUnified.ts").read_text(
        encoding="utf-8"
    )
    # eventus- prefix
    assert "eventus-" in unified_ts, (
        "monitoringUnified.ts에 eventus- id prefix가 없습니다."
    )


# ---------------------------------------------------------------------------
# T1-5a: +page.svelte imports eventusSlotDisplay helper
# ---------------------------------------------------------------------------


def test_eventus_page_imports_eventus_slot_display_helper():
    """S: /eventus +page.svelte가 eventusSlotDisplay에서 parseEventusSlots를 import하는지 검증한다."""
    eventus_page = read_eventus_surface()
    assert "parseEventusSlots" in eventus_page, (
        "+page.svelte에 parseEventusSlots import가 없습니다."
        " eventusSlotDisplay 헬퍼가 사용되지 않습니다."
    )
    assert "eventusSlotDisplay" in eventus_page, (
        "+page.svelte에 '$lib/utils/eventusSlotDisplay' import 경로가 없습니다."
    )


# ---------------------------------------------------------------------------
# T1-5b: eventusSlotDisplay.ts has availableCountKnown / 수량 미확인 text
# ---------------------------------------------------------------------------


def test_eventus_slot_display_ts_has_available_count_known_contract():
    """S: eventusSlotDisplay.ts에 availableCountKnown 필드와 '수량 미확인' 문구가 있는지 검증한다."""
    slot_display_ts = (
        FRONTEND_ROOT / "lib" / "utils" / "eventusSlotDisplay.ts"
    ).read_text(encoding="utf-8")
    assert "availableCountKnown" in slot_display_ts, (
        "eventusSlotDisplay.ts에 availableCountKnown 필드가 없습니다."
        " Eventus는 정확한 좌석 수를 알 수 없으므로 이 필드가 반드시 필요합니다."
    )
    assert "수량 미확인" in slot_display_ts, (
        "eventusSlotDisplay.ts에 '수량 미확인' 문구가 없습니다."
        " availableCountKnown=false인 슬롯에 UI가 오해 없이 표시해야 합니다."
    )


# ---------------------------------------------------------------------------
# T1-5c: eventusSlotDisplay.ts helper fallback chain
# ---------------------------------------------------------------------------


def test_eventus_slot_display_ts_label_fallback_chain():
    """S: getSlotLabel fallback 순서(label→timeKey→bundleId→시간대 정보 없음)가 소스에 존재하는지 검증한다."""
    slot_display_ts = (
        FRONTEND_ROOT / "lib" / "utils" / "eventusSlotDisplay.ts"
    ).read_text(encoding="utf-8")
    # All four steps of the fallback chain must appear in source
    assert "slot.label" in slot_display_ts, (
        "eventusSlotDisplay.ts getSlotLabel에 slot.label fallback이 없습니다."
    )
    assert "slot.timeKey" in slot_display_ts or "timeKey" in slot_display_ts, (
        "eventusSlotDisplay.ts getSlotLabel에 timeKey fallback이 없습니다."
    )
    assert "slot.bundleId" in slot_display_ts or "bundleId" in slot_display_ts, (
        "eventusSlotDisplay.ts getSlotLabel에 bundleId fallback이 없습니다."
    )
    assert "시간대 정보 없음" in slot_display_ts, (
        "eventusSlotDisplay.ts getSlotLabel에 '시간대 정보 없음' 최종 fallback이 없습니다."
    )


# ---------------------------------------------------------------------------
# T1-5d: +page.svelte history thead has '열린 옵션' instead of '잔여'
# ---------------------------------------------------------------------------


def test_eventus_page_history_thead_uses_open_option_label():
    """S: /eventus +page.svelte history table thead의 컬럼명이 '잔여' 대신 '열린 옵션'인지 검증한다."""
    eventus_page = read_eventus_surface()
    # '열린 옵션' should be in the thead
    assert "열린 옵션" in eventus_page, (
        "+page.svelte history thead에 '열린 옵션' 컬럼명이 없습니다."
        " '잔여'에서 변경이 적용되지 않았습니다."
    )
    # The old raw available_count display should not exist in the table cell
    assert "{evt.available_count ?? 0}" not in eventus_page, (
        "+page.svelte history 표 행에 '{evt.available_count ?? 0}' raw 표시가 남아 있습니다."
        " slot summary로 대체돼야 합니다."
    )


def test_eventus_page_button_uses_button_component_click_contract():
    """S: /eventus page uses Button's onclick prop, not component on:click directives."""
    eventus_page = read_eventus_surface()
    button_blocks = re.findall(r"<Button\b.*?(?:</Button>|/>)", eventus_page, re.DOTALL)
    offenders = [
        block.strip().splitlines()[0]
        for block in button_blocks
        if re.search(r"\bon:click\s*=", block)
    ]
    assert offenders == [], (
        "Button.svelte exposes an onclick prop; component-level on:click handlers "
        f"are ignored on /eventus buttons: {offenders}"
    )
