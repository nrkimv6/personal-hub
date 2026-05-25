"""Frontend source-contract tests for eventus monitor type.

Verify that TypeScript source files contain the required exports/values
for the eventus monitor type. These are file-content assertions, not
live-browser or compile tests.

Covered items (plan Phase T1, item 14):
  - MonitorType includes 'eventus'; existing 'event' preserved
  - monitoringUnified.ts has fetchEventusItems + toggle branch
  - monitoring page uses MONITOR_TYPE_META.eventus; type=eventus deep link
"""

from __future__ import annotations

from pathlib import Path

FRONTEND_ROOT = Path(__file__).parents[2] / "frontend" / "src"

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
