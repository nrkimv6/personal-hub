from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_retains_previous_lines_when_log_path_changes():
    source = (ROOT / "frontend/src/lib/components/dev-runner/LogViewer.svelte").read_text(encoding="utf-8")
    parser = (ROOT / "frontend/src/lib/dev-runner/log-parse.ts").read_text(encoding="utf-8")

    assert "extractLogIdentity" in source
    assert "function extractLogIdentity(parsed: ParsedLine[]): string | null" in parser
    assert "log_path=([^\\s]+)" in parser
    assert "shouldAppendSession" in source
    assert "buildSessionSeparator(nextIdentity)" in source
    assert "staleExisting" in source


def test_done_log_tag_is_not_runner_completion_boundary():
    log_viewer = (ROOT / "frontend/src/lib/components/dev-runner/LogViewer.svelte").read_text(encoding="utf-8")
    log_stream = (ROOT / "frontend/src/lib/dev-runner/log-stream.svelte.ts").read_text(encoding="utf-8")
    run_status = (ROOT / "frontend/src/lib/components/dev-runner/RunStatusBar.svelte").read_text(encoding="utf-8")

    assert "eventSource.addEventListener('completed'" in log_stream
    assert "injectCompleted(reason" in log_viewer
    assert "function resolveRunnerStateTitle(runner: RunnerTab): string" in run_status
    assert "[DONE]" not in run_status


def test_log_filter_is_display_only_and_copy_uses_raw_lines():
    source = (ROOT / "frontend/src/lib/components/dev-runner/LogViewer.svelte").read_text(encoding="utf-8")

    assert "let visibleLines = $derived(lines.filter((line) => !hiddenTags.has(line.tag)))" in source
    assert "logLines = lines" in source
    assert ".filter(l => l.tag !== 'NOISE')" in source


def test_logviewer_empty_recent_does_not_overwrite_existing_real_lines():
    source = (ROOT / "frontend/src/lib/components/dev-runner/LogViewer.svelte").read_text(encoding="utf-8")

    assert "sourceLines.length === 0 || isStartOnlyRecentLog(sourceLines)" in source
    assert "const parsedHasContent = parsed.some((line: ParsedLine) => !HEADER_ONLY_TAGS.has(line.tag))" in source
    assert "if (!parsedHasContent && hasLoadedLogContent())" in source
    assert "return;" in source


def test_logviewer_exhausted_managed_retry_shows_runner_stage_diagnostic():
    source = (ROOT / "frontend/src/lib/components/dev-runner/LogViewer.svelte").read_text(encoding="utf-8")

    assert "lastLogLoadStage" in source
    assert "log source not found runner_id=${runnerId} stage=${stage}" in source


def test_long_branch_preflight_rendering_is_truncated_safely():
    source = (ROOT / "frontend/src/lib/dev-runner/log-render.ts").read_text(encoding="utf-8")

    assert "export const MAX_RENDER_CHARS = 8 * 1024" in source
    assert "normalized.slice(0, MAX_RENDER_CHARS)" in source
    assert "chars truncated" in source
    assert "PREVIEW_CHAR_LIMIT = 600" in source
