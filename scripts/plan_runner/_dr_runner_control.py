"""_dr_runner_control.py — lifecycle control surface.

This module is intentionally small and patch-friendly: tests patch names on
`_dr_runner_control` and expect lifecycle functions to read those patched
helpers (e.g. `get_running_processes`).
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, Optional

import redis

from _dr_state import get_running_log_files, get_running_processes


def _cleanup_runner_state(runner_id: str, redis_client: redis.Redis) -> None:
    from _dr_plan_runner import _cleanup_process_state as cleanup_process_state

    cleanup_process_state(runner_id, redis_client)


def start_plan_runner(command: Dict[str, Any], redis_client: redis.Redis) -> Dict[str, Any]:
    runner_id = (command or {}).get("runner_id")
    if not runner_id:
        return {"success": False, "message": "runner_id is required"}

    # already running?
    if get_running_processes().get(runner_id):
        return {"success": False, "message": "Already running"}

    from _dr_plan_runner import _do_start_plan_runner

    _do_start_plan_runner(command, redis_client)
    return {"success": True, "message": "Started"}


def stop_plan_runner(runner_id: str, redis_client: redis.Redis) -> Dict[str, Any]:
    if not runner_id:
        return {"success": False, "message": "runner_id is required"}

    proc = get_running_processes().get(runner_id)
    if not proc or proc.poll() is not None:
        return {"success": False, "message": "Not running"}

    try:
        from _dr_plan_runner import _kill_process_tree

        _kill_process_tree(proc.pid)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc.pid)
            proc.kill()
            proc.wait()
    except Exception:
        pass
    _cleanup_runner_state(runner_id, redis_client)
    return {"success": True, "message": "Stopped successfully"}


def get_status(redis_client: redis.Redis) -> Dict[str, Any]:
    runners = []
    procs = get_running_processes()
    logs = get_running_log_files()
    for rid, proc in procs.items():
        if proc and getattr(proc, "poll", lambda: 0)() is None:
            runners.append({"runner_id": rid, "pid": getattr(proc, "pid", None), "log_file": logs.get(rid)})
    return {"success": True, "running": bool(runners), "runners": runners}


def force_stop_plan_runner(runner_id: str, redis_client: redis.Redis) -> Dict[str, Any]:
    proc = get_running_processes().get(runner_id)
    if proc and getattr(proc, "poll", lambda: 0)() is None:
        try:
            from _dr_plan_runner import _kill_process_tree

            _kill_process_tree(proc.pid)
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    _cleanup_runner_state(runner_id, redis_client)
    return {"success": True, "message": "Stopped"}


def force_kill_plan_runner(runner_id: str, redis_client: redis.Redis) -> Dict[str, Any]:
    if not runner_id:
        return {"success": False, "message": "runner_id is required"}

    proc = get_running_processes().get(runner_id)
    if proc and getattr(proc, "poll", lambda: 0)() is None:
        try:
            from _dr_plan_runner import _kill_process_tree

            _kill_process_tree(proc.pid)
            proc.kill()
        except Exception:
            pass
    _cleanup_runner_state(runner_id, redis_client)
    return {"success": True, "message": "Killed"}


def _launch_plan_runner_process(*args, **kwargs):
    from _dr_plan_runner import _launch_plan_runner_process as _impl

    return _impl(*args, **kwargs)


def _do_start_plan_runner(*args, **kwargs):
    from _dr_plan_runner import _do_start_plan_runner as _impl

    return _impl(*args, **kwargs)

