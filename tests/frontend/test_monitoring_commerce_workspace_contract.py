from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_commerce_workspaces_exist_and_standalone_routes_are_wrappers():
    coupang_route = FRONTEND / "routes" / "coupang"
    popply_route = FRONTEND / "routes" / "popply"

    assert (coupang_route / "CoupangWorkspace.svelte").exists()
    assert (popply_route / "PopplyWorkspace.svelte").exists()
    assert "CoupangWorkspace" in read(coupang_route / "+page.svelte")
    assert "PopplyWorkspace" in read(popply_route / "+page.svelte")


def test_monitoring_workspace_renders_commerce_workspaces():
    workspace = read(FRONTEND / "routes" / "monitoring" / "MonitoringWorkspace.svelte")

    assert "CoupangWorkspace" in workspace
    assert "PopplyWorkspace" in workspace
    assert "state.type === 'coupang'" in workspace
    assert "state.type === 'popply'" in workspace
    assert "view={state.view} sub={state.sub} unified" in workspace


def test_coupang_and_popply_detail_hrefs_use_unified_monitoring_routes():
    unified_api = read(FRONTEND / "lib" / "api" / "monitoringUnified.ts")
    monitoring_ts = read(FRONTEND / "lib" / "types" / "monitoring.ts")
    new_monitor = read(FRONTEND / "routes" / "monitoring" / "NewMonitorTypeSelector.svelte")
    list_view = read(FRONTEND / "routes" / "monitoring" / "MonitoringList.svelte")

    assert "type: 'coupang', view: 'schedules'" in unified_api
    assert "type: 'popply', view: 'schedules'" in unified_api
    assert "createHref: '/monitoring?type=coupang&view=create'" in monitoring_ts
    assert "createHref: '/monitoring?type=popply&view=create'" in monitoring_ts
    assert "handleSelect(meta.createHref)" in new_monitor
    assert "goto(item.detailHref)" in list_view


def test_commerce_workspaces_accept_unified_view_state():
    coupang = read(FRONTEND / "routes" / "coupang" / "CoupangWorkspace.svelte")
    popply = read(FRONTEND / "routes" / "popply" / "PopplyWorkspace.svelte")

    assert "unified?: boolean" in coupang
    assert "normalizeCoupangTab" in coupang
    assert "/monitoring?type=coupang&view=schedules" in coupang
    assert "/monitoring?type=coupang&view=history" in coupang
    assert "/monitoring?type=coupang&view=cancellation-history" in coupang
    assert "primaryUrlBased={unified}" in coupang
    assert "unified?: boolean" in popply
    assert "normalizePopplyTab" in popply
    assert "/monitoring?type=popply&view=schedules" in popply
    assert "/monitoring?type=popply&view=history" in popply
    assert "primaryUrlBased={unified}" in popply
