from __future__ import annotations

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
