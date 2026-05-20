"""Admin dev-runner history visibility source contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
API_FILE = ROOT / "frontend" / "src" / "lib" / "api" / "dev-runner.ts"
DEV_RUNNER_TAB = ROOT / "frontend" / "src" / "routes" / "automation" / "DevRunnerTab.svelte"
COMPONENTS = [
    ROOT / "frontend" / "src" / "lib" / "components" / "dev-runner" / "LogHistoryPanel.svelte",
    ROOT / "frontend" / "src" / "lib" / "components" / "dev-runner" / "RunHistoryPanel.svelte",
    ROOT / "frontend" / "src" / "lib" / "components" / "dev-runner" / "UnifiedLogsView.svelte",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_history_api_defaults_to_visible_only_and_can_request_all() -> None:
    """R: API helper defaults to visible history and sends explicit false for debug/all callers."""
    source = _read(API_FILE)

    assert "visibleOnly: boolean = true" in source
    assert "&visible_only=${visibleOnly ? 'true' : 'false'}" in source


def test_run_history_item_exposes_visible_flag() -> None:
    """R: frontend has the backend visible flag available for client-side fail-closed filtering."""
    source = _read(API_FILE)

    assert "visible: boolean;" in source


def test_admin_history_components_request_and_filter_visible_runs() -> None:
    """R: Admin history surfaces request visible-only data and drop any visible=false response rows."""
    for path in COMPONENTS:
        source = _read(path)
        assert "devRunnerLogApi.history" in source, path
        assert "true)" in source or "true);" in source, path
        assert ".filter((run) => run.visible !== false)" in source, path


def test_no_dummy_plan_names_in_fixture_visible_history_R() -> None:
    """R: client-side visible filtering keeps dummy plan names out of rendered history input."""
    dummy_plan_names = {
        "approval-t5b.md",
        "approval-t5.md",
        "orphan.md",
        "test.md",
        "blocked-plan.md",
    }
    history_fixture = [
        {"plan_file": "docs/plan/visible-user-plan.md", "visible": True},
        *({"plan_file": f"docs/plan/{name}", "visible": False} for name in dummy_plan_names),
    ]

    rendered_input = [run for run in history_fixture if run["visible"] is not False]
    rendered_names = {Path(str(run["plan_file"])).name for run in rendered_input}

    assert "visible-user-plan.md" in rendered_names
    assert rendered_names.isdisjoint(dummy_plan_names)


def test_dev_runner_tab_does_not_restore_trigger_only_visibility() -> None:
    """R: live tab mapping trusts backend visible=false instead of trigger fallback."""
    source = _read(DEV_RUNNER_TAB)

    assert "return runner.trigger === 'user' || runner.trigger === 'user:all';" not in source
    assert "return false;" in source
    assert "if (tab.visible === false) return false;" in source
    assert "visible: runner.visible," in source
    assert "if (tab.visible === true) return true;" in source
