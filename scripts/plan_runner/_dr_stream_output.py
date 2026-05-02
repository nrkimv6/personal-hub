"""_dr_stream_output.py — stream loop extracted from _dr_plan_runner.

Tests patch this module (`_dr_stream_output.get_wf_manager`, etc.), so the
public entrypoint must live here.
"""

import logging
import subprocess
import threading
import time
from typing import IO, Optional

import psutil
import redis

from _dr_constants import LOG_CHANNEL_PREFIX
from _dr_log_framing import MultilineFrameBuffer
from _dr_runtime_utils import _publish_with_retry
from _dr_state import get_running_log_files, get_wf_manager
from _dr_stream_cleanup import (
    _StreamCleanupCtx,
    _determine_merge_requested,
    _drain_stdout_log,
    _process_error_details,
    _resolve_exit_status,
    _update_workflow_and_execute_cleanup,
)

logger = logging.getLogger(__name__)

try:
    from listener_noise_filter import is_noise_line as _is_noise_line
except ImportError:
    def _is_noise_line(_line: str) -> bool:
        return False


def _stream_output(
    process: subprocess.Popen,
    log_handle,
    redis_client: redis.Redis,
    runner_id: str = "",
    stderr_handle: Optional[IO] = None,
):
    """Read process stdout line-by-line, write to log, and publish to Redis."""
    logger.info(f"[_stream_output] 시작 runner_id={runner_id!r}")
    _running_log_files = get_running_log_files()
    _wf_manager = get_wf_manager()

    _start_time = time.time()
    log_channel_init = f"{LOG_CHANNEL_PREFIX}:{runner_id}" if runner_id else LOG_CHANNEL_PREFIX

    # Early-exit diagnostic: don't return; continue into cleanup path.
    _initial_poll = process.poll()
    if _initial_poll is not None:
        _elapsed = time.time() - _start_time
        _early_msg = f"[EARLY_EXIT] exit_code={_initial_poll}, elapsed={_elapsed:.1f}s (진입 즉시 감지)"
        logger.warning(f"[_stream_output] {_early_msg} runner_id={runner_id!r}")
        try:
            log_handle.write(_early_msg + "\n")
            log_handle.flush()
        except Exception:
            pass
        try:
            _publish_with_retry(redis_client, log_channel_init, _early_msg)
        except Exception:
            pass

    if _initial_poll is None:
        for _ in range(10):
            time.sleep(0.05)
            polled = process.poll()
            if polled is not None:
                _elapsed = time.time() - _start_time
                _early_msg2 = f"[EARLY_EXIT] exit_code={polled}, elapsed={_elapsed:.1f}s (readline 진입 전 감지)"
                logger.warning(f"[_stream_output] {_early_msg2} runner_id={runner_id!r}")
                try:
                    log_handle.write(_early_msg2 + "\n")
                    log_handle.flush()
                except Exception:
                    pass
                try:
                    _publish_with_retry(redis_client, log_channel_init, _early_msg2)
                except Exception:
                    pass
                break

    suppressed_count = 0
    _last_flushed_pos: int = 0

    last_line = ""
    repeat_count = 0
    repeat_start = 0.0
    burst_window = 0.5
    burst_limit = 10

    _line_count = 0
    framer = MultilineFrameBuffer(max_chars=8192)

    _stderr_thread: Optional[threading.Thread] = None

    def _drain_stderr(stderr_fh) -> None:
        try:
            for sline in stderr_fh:
                stripped = (sline or "").rstrip("\n")
                if not stripped:
                    continue
                msg = f"[STDERR] {stripped}"
                try:
                    log_handle.write(msg + "\n")
                    log_handle.flush()
                except Exception:
                    pass
                try:
                    _publish_with_retry(redis_client, log_channel_init, msg)
                except Exception:
                    pass
        except Exception:
            return None

    if stderr_handle is not None:
        _stderr_thread = threading.Thread(target=_drain_stderr, args=(stderr_handle,), daemon=True)
        _stderr_thread.start()

    def _publish_frame(frame_text: str) -> None:
        nonlocal suppressed_count, last_line, repeat_count, repeat_start
        if not frame_text:
            return

        now = time.time()
        if frame_text == last_line:
            if now - repeat_start <= burst_window:
                repeat_count += 1
            else:
                repeat_start = now
                repeat_count = 1
        else:
            last_line = frame_text
            repeat_start = now
            repeat_count = 1

        if repeat_count > burst_limit and (now - repeat_start) <= burst_window:
            suppressed_count += 1
            return

        try:
            _publish_with_retry(redis_client, log_channel_init, frame_text)
        except Exception:
            pass

    try:
        for raw_line in process.stdout:
            _line_count += 1
            line = (raw_line or "").rstrip("\n")
            if not line:
                continue
            try:
                log_handle.write(line + "\n")
                log_handle.flush()
            except Exception:
                pass

            # noise lines are still written to log, but not published
            if _is_noise_line(line):
                suppressed_count += 1
                continue

            ready_frames, overflow = framer.push_line(line)
            if overflow:
                # buffer overrun; frames already flushed by framer
                pass
            for frame in ready_frames:
                _publish_frame(frame)

    finally:
        try:
            process.wait(timeout=2)
        except Exception:
            pass

        exit_code = process.returncode
        elapsed_total = time.time() - _start_time

        if _line_count == 0 and exit_code not in (0, None):
            diag_parts = [f"[DIAG] lines=0, exit_code={exit_code}, elapsed={elapsed_total:.1f}s"]
            try:
                vmem = psutil.virtual_memory()
                diag_parts.append(
                    f"mem_available={vmem.available // (1024*1024)}MB, mem_total={vmem.total // (1024*1024)}MB"
                )
            except Exception:
                pass
            diag_msg = " | ".join(diag_parts)
            try:
                log_handle.write(diag_msg + "\n")
                log_handle.flush()
            except Exception:
                pass
            try:
                _publish_with_retry(redis_client, log_channel_init, diag_msg)
            except Exception:
                pass

        tail = framer.flush()
        if tail:
            _publish_frame(tail)

        log_file_path = _running_log_files.get(runner_id) if runner_id else None
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}" if runner_id else LOG_CHANNEL_PREFIX
        ctx = _StreamCleanupCtx(
            runner_id=runner_id,
            redis_client=redis_client,
            log_channel=log_channel,
            exit_code=exit_code,
            wf_manager=_wf_manager,
            suppressed_count=suppressed_count,
        )
        _resolve_exit_status(ctx)
        tail_lines = _drain_stdout_log(ctx, log_file_path, _last_flushed_pos, _publish_frame)
        _process_error_details(ctx, log_file_path, tail_lines)
        merge_requested = _determine_merge_requested(ctx)
        _update_workflow_and_execute_cleanup(ctx, merge_requested)
