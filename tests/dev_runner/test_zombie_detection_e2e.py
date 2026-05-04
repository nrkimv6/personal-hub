"""T4 E2E: listener 기반 zombie heartbeat 감지 검증."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import psutil
import pytest
import redis as redis_lib

from tests.dev_runner._path_helpers import get_listener_script_path, get_project_python, load_listener_module

RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
REDIS_TEST_DB = 15


def _runner_key(runner_id: str, suffix: str) -> str:
    return f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"


def _hash_cmdline(cmdline: list[str]) -> str:
    payload = json.dumps([str(part) for part in cmdline], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _seed_process_identity(redis_client: redis_lib.Redis, runner_id: str, pid: int, *, mutate_create_time: bool = False) -> None:
    proc = psutil.Process(pid)
    create_time = proc.create_time()
    if mutate_create_time:
        create_time += 10_000
    redis_client.set(_runner_key(runner_id, "pid_create_time"), str(create_time))
    redis_client.set(_runner_key(runner_id, "process_cmdline_hash"), _hash_cmdline(proc.cmdline()))


def _wait_until(predicate, timeout: float = 20.0, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _terminate_process(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass


def _spawn_sleep_process(seconds: int = 120) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _seed_runner(
    redis_client: redis_lib.Redis,
    runner_id: str,
    pid: int,
    *,
    start_time: str,
    with_heartbeat: bool,
    log_file_path: Path | None = None,
    merge_status: str | None = None,
) -> None:
    redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)
    redis_client.set(_runner_key(runner_id, "status"), "running")
    redis_client.set(_runner_key(runner_id, "pid"), str(pid))
    redis_client.set(_runner_key(runner_id, "start_time"), start_time)
    if merge_status is not None:
        redis_client.set(_runner_key(runner_id, "merge_status"), merge_status)
    if with_heartbeat:
        redis_client.set(_runner_key(runner_id, "subprocess_heartbeat"), str(time.time()), ex=120)
    if log_file_path is not None:
        redis_client.set(_runner_key(runner_id, "log_file_path"), str(log_file_path))


def test_reconnect_attaches_actual_subprocess_after_heartbeat_gap(redis_db15, tmp_path):
    """T3: actual subprocess + heartbeat gap + identity match이면 reconnect가 attach한다."""
    runner_id = f"t3-reconnect-{uuid.uuid4().hex[:8]}"
    runner_proc = _spawn_sleep_process(seconds=180)
    log_file = tmp_path / f"{runner_id}.log"
    log_file.write_text("", encoding="utf-8")

    try:
        old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
        _seed_runner(
            redis_db15,
            runner_id,
            runner_proc.pid,
            start_time=old_start,
            with_heartbeat=True,
            log_file_path=log_file,
        )
        _seed_process_identity(redis_db15, runner_id, runner_proc.pid)
        redis_db15.delete(_runner_key(runner_id, "subprocess_heartbeat"))

        listener_mod = load_listener_module(f"dev_runner_command_listener_t3_{uuid.uuid4().hex}")
        listener_mod._reconnect_surviving_runners(redis_db15)

        assert redis_db15.get(_runner_key(runner_id, "status")) == "running", (
            f"identity match reconnect should keep runner running "
            f"(db={REDIS_TEST_DB}, key={_runner_key(runner_id, 'status')})"
        )
        assert redis_db15.get(_runner_key(runner_id, "subprocess_heartbeat")) is not None, (
            f"reconnect should republish subprocess_heartbeat "
            f"(db={REDIS_TEST_DB}, key={_runner_key(runner_id, 'subprocess_heartbeat')})"
        )
    finally:
        _terminate_process(runner_proc)


def test_reconnect_actual_subprocess_identity_mismatch_cleans(redis_db15, tmp_path):
    """T3: actual subprocess라도 stored create_time이 다르면 cleanup으로 분기한다."""
    runner_id = f"t3-mismatch-{uuid.uuid4().hex[:8]}"
    runner_proc = _spawn_sleep_process(seconds=180)
    log_file = tmp_path / f"{runner_id}.log"
    log_file.write_text("", encoding="utf-8")

    try:
        old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
        _seed_runner(
            redis_db15,
            runner_id,
            runner_proc.pid,
            start_time=old_start,
            with_heartbeat=True,
            log_file_path=log_file,
        )
        _seed_process_identity(redis_db15, runner_id, runner_proc.pid, mutate_create_time=True)
        redis_db15.delete(_runner_key(runner_id, "subprocess_heartbeat"))

        listener_mod = load_listener_module(f"dev_runner_command_listener_t3_{uuid.uuid4().hex}")
        listener_mod._reconnect_surviving_runners(redis_db15)

        assert not redis_db15.sismember(ACTIVE_RUNNERS_KEY, runner_id), (
            f"identity mismatch reconnect should cleanup runner "
            f"(db={REDIS_TEST_DB}, active_key={ACTIVE_RUNNERS_KEY})"
        )
    finally:
        _terminate_process(runner_proc)


@pytest.fixture
def redis_db15():
    try:
        r = redis_lib.Redis(host="localhost", port=6379, db=REDIS_TEST_DB, decode_responses=True)
        r.ping()
    except Exception:
        pytest.fail("Redis not available")
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.fixture
def listener_launcher(redis_db15):
    processes: list[subprocess.Popen] = []

    def _start(*, grace_seconds: int = 3) -> subprocess.Popen:
        redis_db15.delete(HEARTBEAT_KEY)
        listener_script = Path(get_listener_script_path())
        python_exe = Path(get_project_python())
        python_bin = str(python_exe) if python_exe.exists() else sys.executable
        env = os.environ.copy()
        env["DEV_RUNNER_ZOMBIE_GRACE_SECONDS"] = str(grace_seconds)
        proc = subprocess.Popen(
            [python_bin, str(listener_script), "--redis-db", str(REDIS_TEST_DB)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        processes.append(proc)

        if not _wait_until(lambda: redis_db15.get(HEARTBEAT_KEY) is not None, timeout=15, interval=0.5):
            _terminate_process(proc)
            pytest.fail("listener heartbeat not detected within 15 seconds")
        return proc

    yield _start

    for proc in processes:
        _terminate_process(proc)


@pytest.mark.e2e
def test_zombie_detection_e2e_with_listener(redis_db15, listener_launcher):
    """PID alive + heartbeat 없음 runner를 listener가 zombie로 정리한다."""
    runner_id = f"e2e-zombie-{uuid.uuid4().hex[:8]}"
    runner_proc = _spawn_sleep_process(seconds=180)

    try:
        old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
        _seed_runner(
            redis_db15,
            runner_id,
            runner_proc.pid,
            start_time=old_start,
            with_heartbeat=False,
        )

        listener_launcher(grace_seconds=3)

        cleaned = _wait_until(
            lambda: redis_db15.get(_runner_key(runner_id, "status")) == "stopped",
            timeout=20,
            interval=0.5,
        )
        assert cleaned, "zombie runner가 timeout 내 stopped로 정리되지 않음"
        assert not redis_db15.sismember(ACTIVE_RUNNERS_KEY, runner_id), "ACTIVE_RUNNERS에서 제거되어야 함"
    finally:
        _terminate_process(runner_proc)


@pytest.mark.e2e
def test_zombie_detection_e2e_healthy_runner_survives(redis_db15, listener_launcher, tmp_path):
    """heartbeat가 존재하는 runner는 listener 시작 후에도 살아남는다."""
    runner_id = f"e2e-healthy-{uuid.uuid4().hex[:8]}"
    runner_proc = _spawn_sleep_process(seconds=180)
    log_file = tmp_path / f"{runner_id}.log"
    log_file.write_text("", encoding="utf-8")

    try:
        old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
        _seed_runner(
            redis_db15,
            runner_id,
            runner_proc.pid,
            start_time=old_start,
            with_heartbeat=True,
            log_file_path=log_file,
        )
        _seed_process_identity(redis_db15, runner_id, runner_proc.pid)

        listener_launcher(grace_seconds=3)

        # listener heartbeat 루프 1회 이상 경과
        time.sleep(12)

        assert redis_db15.get(_runner_key(runner_id, "status")) == "running"
        assert redis_db15.sismember(ACTIVE_RUNNERS_KEY, runner_id), "healthy runner는 active 상태를 유지해야 함"
    finally:
        _terminate_process(runner_proc)
