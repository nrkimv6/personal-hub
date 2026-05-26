from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.modules.dev_runner.services.log_file_resolver import LogFileResolver


def _resolver(log_dir):
    config = MagicMock()
    config.LOG_DIR = log_dir
    config.WTOOLS_BASE_DIR = log_dir
    return LogFileResolver(config, MagicMock())


def test_select_display_log_prefers_main_over_zero_byte_stream(tmp_path):
    stream_file = tmp_path / "plan-runner-stream-abc12345-20260505_230000.log"
    main_file = tmp_path / "plan-runner-abc12345-20260505_225900.log"
    stream_file.write_bytes(b"")
    main_file.write_text("[20:00:00] [INFO] populated log\n", encoding="utf-8")

    assert LogFileResolver.select_display_log(stream_file, main_file) == main_file


def test_find_filesystem_log_prefers_populated_previous_stream_over_latest_empty(tmp_path):
    runner_id = "abc12345"
    old_stream = tmp_path / f"plan-runner-stream-{runner_id}-20260505_225900.log"
    latest_stream = tmp_path / f"plan-runner-stream-{runner_id}-20260505_230000.log"
    old_stream.write_text("[20:00:00] [INFO] populated stream\n", encoding="utf-8")
    latest_stream.write_bytes(b"")

    assert _resolver(tmp_path).find_filesystem_log(runner_id) == old_stream


def test_find_filesystem_log_prefers_populated_main_over_latest_start_only_stream(tmp_path):
    runner_id = "abc12345"
    stream_file = tmp_path / f"plan-runner-stream-{runner_id}-20260505_230000.log"
    main_file = tmp_path / f"plan-runner-{runner_id}-20260505_225900.log"
    stream_file.write_text("[2026-05-05T23:00:00] START | log_path=main.log\n", encoding="utf-8")
    main_file.write_text("[20:00:00] [PLAN-RUNNER] populated main log\n", encoding="utf-8")

    assert _resolver(tmp_path).find_filesystem_log(runner_id) == main_file


def test_log_evidence_matrix_service_lock_merge_lines_count_as_runner_output_R(tmp_path):
    """R: service_lock/MERGE final lines are real runner output, not START-only noise."""
    runner_id = "approval-001"
    stream_file = tmp_path / f"plan-runner-stream-{runner_id}-20260513_120000.log"
    main_file = tmp_path / f"plan-runner-{runner_id}-20260513_115900.log"
    stream_file.write_text("[2026-05-13T12:00:00] START | log_path=main.log\n", encoding="utf-8")
    main_file.write_text(
        "MERGE_PRECHECK_FAILED[service_lock]: blocked\n"
        "[MERGE] approval_required service_lock\n",
        encoding="utf-8",
    )

    assert _resolver(tmp_path).find_filesystem_log(runner_id) == main_file


def test_runner_id_parser_does_not_treat_legacy_stream_prefix_as_runner_id():
    legacy = Path("plan-runner-stream-20260513_172900.log")
    assert LogFileResolver._runner_id_from_log_name(legacy) is None


def test_find_filesystem_log_right_fd_runner_pair_with_underscore_stream_timestamp(tmp_path):
    runner_id = "fd6be696"
    stream_file = tmp_path / f"plan-runner-stream-{runner_id}-20260523_215902.log"
    main_file = tmp_path / f"plan-runner-{runner_id}-20260523-215902.log"
    stream_file.write_text(
        "[TRIGGER] user | plan=fix-dev-runner.md | runner_id=fd6be696\n"
        "[RUN_META] started_at=2026-05-23T21:59:02 | execution_count=1 | plan_key=fix-dev-runner\n"
        "[MERGE] branch preflight\n"
        "[FAILURE] merge_failed\n",
        encoding="utf-8",
    )
    main_file.write_text("[STDERR] merge failed detail\n", encoding="utf-8")

    assert LogFileResolver._runner_id_from_log_name(stream_file) == runner_id
    assert LogFileResolver._runner_id_from_log_name(main_file) == runner_id
    assert _resolver(tmp_path).find_filesystem_log(runner_id) == stream_file


def test_select_display_log_keeps_stream_when_stream_has_merge_failure(tmp_path):
    stream_file = tmp_path / "plan-runner-stream-fd6be696-20260523_215902.log"
    main_file = tmp_path / "plan-runner-fd6be696-20260523-215902.log"
    stream_file.write_text("[MERGE] starting\n[FAILURE] merge_failed\n", encoding="utf-8")
    main_file.write_text("[STDERR] fallback detail\n", encoding="utf-8")

    assert LogFileResolver.select_display_log(stream_file, main_file) == stream_file
