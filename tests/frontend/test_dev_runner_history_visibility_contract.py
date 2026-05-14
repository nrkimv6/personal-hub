"""Admin dev-runner history visibility source contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
API_FILE = ROOT / "frontend" / "src" / "lib" / "api" / "dev-runner.ts"
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
