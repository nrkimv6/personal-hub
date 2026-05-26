from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_coupang_public_history_routes_are_preserved():
    assert (FRONTEND / "routes" / "coupang" / "history" / "+page.svelte").exists()
    assert (FRONTEND / "routes" / "coupang" / "history-legacy" / "+page.svelte").exists()


def test_public_history_navigation_remains_public_only():
    navigation = read(FRONTEND / "lib" / "navigation.ts")

    assert "{ href: '/coupang/history', label: '메가뷰티쇼 취소이력', public: true, publicOnly: true }" in navigation
    assert "/monitoring?type=coupang" not in navigation.split("메가뷰티쇼 취소이력")[0][-200:]


def test_coupang_admin_links_do_not_target_public_history():
    monitoring_ts = read(FRONTEND / "lib" / "types" / "monitoring.ts")
    unified_api = read(FRONTEND / "lib" / "api" / "monitoringUnified.ts")
    workspace = read(FRONTEND / "routes" / "coupang" / "CoupangWorkspace.svelte")

    assert "createHref: '/monitoring?type=coupang&view=create'" in monitoring_ts
    assert "type: 'coupang', view: 'schedules'" in unified_api
    assert "/coupang/history" not in workspace
    assert "/monitoring?type=coupang&view=cancellation-history" in workspace
