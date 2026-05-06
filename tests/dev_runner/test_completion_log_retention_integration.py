from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_retains_previous_lines_when_log_path_changes():
    source = (ROOT / "frontend/src/lib/components/dev-runner/LogViewer.svelte").read_text(encoding="utf-8")

    assert "function extractLogIdentity(parsed: ParsedLine[]): string | null" in source
    assert "log_path=([^\\s]+)" in source
    assert "shouldAppendSession" in source
    assert "buildSessionSeparator(nextIdentity)" in source
    assert "staleExisting" in source


def test_done_log_tag_is_not_runner_completion_boundary():
    log_viewer = (ROOT / "frontend/src/lib/components/dev-runner/LogViewer.svelte").read_text(encoding="utf-8")
    run_status = (ROOT / "frontend/src/lib/components/dev-runner/RunStatusBar.svelte").read_text(encoding="utf-8")

    assert "eventSource.addEventListener('completed'" in log_viewer
    assert "injectCompleted(reason" in log_viewer
    assert "function resolveRunnerStateTitle(runner: RunnerTab): string" in run_status
    assert "[DONE]" not in run_status


def test_log_filter_is_display_only_and_copy_uses_raw_lines():
    source = (ROOT / "frontend/src/lib/components/dev-runner/LogViewer.svelte").read_text(encoding="utf-8")

    assert "let visibleLines = $derived(lines.filter((line) => !hiddenTags.has(line.tag)))" in source
    assert "const logLines = lines" in source
    assert ".filter(l => !l.isStale && l.tag !== 'NOISE')" in source
