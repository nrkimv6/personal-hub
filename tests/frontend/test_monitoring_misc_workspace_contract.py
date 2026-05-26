from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_misc_workspaces_exist_after_standalone_routes_redirect():
    kakao_route = FRONTEND / "routes" / "kakao-monitor"
    activity_route = FRONTEND / "routes" / "activity"
    eventus_route = FRONTEND / "routes" / "eventus"

    assert (kakao_route / "KakaoMonitorWorkspace.svelte").exists()
    assert (activity_route / "ActivityWorkspace.svelte").exists()
    assert (eventus_route / "EventusWorkspace.svelte").exists()
    assert "/monitoring?type=kakao&view=dashboard" in read(kakao_route / "+page.svelte")
    assert "/monitoring?type=activity&view=centers" in read(activity_route / "+page.svelte")
    assert "/monitoring?type=eventus&view=schedules" in read(eventus_route / "+page.svelte")


def test_monitoring_workspace_renders_misc_workspaces_and_event_summary():
    workspace = read(FRONTEND / "routes" / "monitoring" / "MonitoringWorkspace.svelte")

    assert "KakaoMonitorWorkspace" in workspace
    assert "ActivityWorkspace" in workspace
    assert "EventusWorkspace" in workspace
    assert "state.type === 'kakao'" in workspace
    assert "state.type === 'activity'" in workspace
    assert "state.type === 'eventus'" in workspace
    assert "state.type === 'event'" in workspace
    assert "goto('/events')" in workspace
    assert "<iframe" not in workspace


def test_misc_workspaces_accept_unified_view_state():
    kakao = read(FRONTEND / "routes" / "kakao-monitor" / "KakaoMonitorWorkspace.svelte")
    activity = read(FRONTEND / "routes" / "activity" / "ActivityWorkspace.svelte")
    eventus = read(FRONTEND / "routes" / "eventus" / "EventusWorkspace.svelte")

    assert "unified?: boolean" in kakao
    assert "normalizeKakaoTab" in kakao
    assert "type: 'kakao', view: tab" in kakao
    assert "onTabChange={handleTabChange}" in kakao
    assert "unified?: boolean" in activity
    assert "normalizeActivityTab" in activity
    assert "type: 'activity', view: next" in activity
    assert "onTabChange={handleActivityTabChange}" in activity
    assert "unified?: boolean" in eventus
    assert "normalizeEventusTab" in eventus
    assert "type: 'eventus', view: 'schedules'" in eventus
    assert "primaryUrlBased={unified}" in eventus


def test_misc_detail_hrefs_and_create_hrefs_use_unified_monitoring_routes():
    unified_api = read(FRONTEND / "lib" / "api" / "monitoringUnified.ts")
    monitoring_ts = read(FRONTEND / "lib" / "types" / "monitoring.ts")

    assert "type: 'kakao', view: 'settings'" in unified_api
    assert "type: 'activity', view: 'centers'" in unified_api
    assert "type: 'eventus', view: 'schedules'" in unified_api
    assert "type: 'event', view: 'summary'" in unified_api
    assert "createHref: '/monitoring?type=kakao&view=create'" in monitoring_ts
    assert "createHref: '/monitoring?type=activity&view=centers'" in monitoring_ts
    assert "createHref: '/monitoring?type=eventus&view=create'" in monitoring_ts
    assert "createHref: '/monitoring?type=event&view=summary'" in monitoring_ts
