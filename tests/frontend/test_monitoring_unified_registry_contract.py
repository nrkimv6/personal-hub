from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_monitor_type_meta_uses_unified_create_hrefs_and_views():
    monitoring_ts = read(FRONTEND / "lib" / "types" / "monitoring.ts")

    assert "defaultView" in monitoring_ts
    assert "views:" in monitoring_ts
    assert "MonitorViewMeta" in monitoring_ts
    assert "createHref: '/naver'" not in monitoring_ts
    assert "createHref: '/coupang'" not in monitoring_ts
    assert "createHref: '/popply'" not in monitoring_ts
    assert "createHref: '/kakao-monitor'" not in monitoring_ts
    assert "createHref: '/activity'" not in monitoring_ts
    assert "createHref: '/eventus'" not in monitoring_ts


def test_eventus_registry_is_distinct_from_event_and_uses_unified_url():
    monitoring_ts = read(FRONTEND / "lib" / "types" / "monitoring.ts")

    assert "'event'" in monitoring_ts
    assert "'eventus'" in monitoring_ts
    assert "eventus:" in monitoring_ts
    assert "createHref: '/monitoring?type=eventus&view=create'" in monitoring_ts
    assert "label: '이벤터스 잔여석'" in monitoring_ts
    assert "label: '이벤트'" in monitoring_ts
    assert "id: 'schedules', label: '일정'" in monitoring_ts
    assert "id: 'history', label: '실행내역'" in monitoring_ts


def test_monitoring_unified_detail_href_uses_unified_routes():
    unified_ts = read(FRONTEND / "lib" / "api" / "monitoringUnified.ts")

    assert "buildMonitoringHref" in unified_ts
    assert "type: 'naver', view: 'schedules'" in unified_ts
    assert "type: 'coupang', view: 'schedules'" in unified_ts
    assert "type: 'popply', view: 'schedules'" in unified_ts
    assert "type: 'kakao', view: 'settings'" in unified_ts
    assert "type: 'activity', view: 'centers'" in unified_ts
    assert "type: 'eventus', view: 'schedules'" in unified_ts
    assert "detailHref: '/naver'" not in unified_ts
    assert "detailHref: '/eventus'" not in unified_ts


def test_monitoring_shell_components_are_registered():
    page = read(FRONTEND / "routes" / "monitoring" / "+page.svelte")
    workspace = read(FRONTEND / "routes" / "monitoring" / "MonitoringWorkspace.svelte")

    assert "MonitoringTypeTabs" in page
    assert "MonitoringViewTabs" in page
    assert "MonitoringWorkspace" in page
    assert "routeState.view !== 'list'" in page
    assert "기존 작업면 열기" in workspace
