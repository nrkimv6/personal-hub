import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.diagnostics import memory_snapshot


def _make_process(pid: int, name: str, memory_mb: float, cmdline: list[str]):
    proc = MagicMock()
    mem = MagicMock()
    mem.rss = int(memory_mb * 1024 * 1024)
    proc.info = {"pid": pid, "name": name, "memory_info": mem}
    proc.cmdline.return_value = cmdline
    return proc


def test_collect_snapshot_R_returns_dict_with_required_keys():
    vm = MagicMock()
    vm.available = 900 * 1024 * 1024
    vm.total = 16000 * 1024 * 1024

    with patch("scripts.diagnostics.memory_snapshot.psutil.virtual_memory", return_value=vm), \
         patch(
             "scripts.diagnostics.memory_snapshot.psutil.process_iter",
             return_value=[_make_process(1, "python.exe", 512.4, ["python", "app/main.py"])],
         ):
        result = memory_snapshot.collect_snapshot()

    assert set(result.keys()) == {"timestamp", "available_mb", "total_mb", "top_processes"}
    assert result["available_mb"] == 900.0
    assert result["total_mb"] == 16000.0
    assert isinstance(result["top_processes"], list)


def test_collect_snapshot_B_top_n_zero_returns_empty_list():
    vm = MagicMock()
    vm.available = 900 * 1024 * 1024
    vm.total = 16000 * 1024 * 1024

    with patch("scripts.diagnostics.memory_snapshot.psutil.virtual_memory", return_value=vm), \
         patch(
             "scripts.diagnostics.memory_snapshot.psutil.process_iter",
             return_value=[_make_process(1, "python.exe", 512.4, ["python", "app/main.py"])],
         ):
        result = memory_snapshot.collect_snapshot(top_n=0)

    assert result["top_processes"] == []


def test_collect_snapshot_B_top_n_default_returns_5():
    vm = MagicMock()
    vm.available = 900 * 1024 * 1024
    vm.total = 16000 * 1024 * 1024
    processes = [
        _make_process(idx, f"proc-{idx}.exe", 1000 - idx, [f"proc-{idx}.exe"])
        for idx in range(10)
    ]

    with patch("scripts.diagnostics.memory_snapshot.psutil.virtual_memory", return_value=vm), \
         patch("scripts.diagnostics.memory_snapshot.psutil.process_iter", return_value=processes):
        result = memory_snapshot.collect_snapshot()

    assert len(result["top_processes"]) == 5


def test_collect_snapshot_E_negative_top_n_raises():
    with pytest.raises(ValueError):
        memory_snapshot.collect_snapshot(top_n=-1)


def test_extract_script_path_R_finds_py():
    assert memory_snapshot._extract_script_path(["python", "scripts/worker.py"]) == "scripts/worker.py"


def test_extract_script_path_E_no_match_returns_none():
    assert memory_snapshot._extract_script_path(["chrome.exe", "--headless"]) is None


def test_main_O_outputs_valid_json_to_stdout():
    script_path = Path("scripts/diagnostics/memory_snapshot.py")
    result = subprocess.run(
        [sys.executable, str(script_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "top_processes" in payload


def test_collect_snapshot_integration_real_system():
    snapshot = memory_snapshot.collect_snapshot(top_n=200)
    pids = {item["pid"] for item in snapshot["top_processes"]}
    assert snapshot["available_mb"] > 0
    assert snapshot["total_mb"] > 0
    assert "timestamp" in snapshot
    assert os.getpid() in pids


def test_main_integration_subprocess_returns_zero_exit():
    script_path = Path("scripts/diagnostics/memory_snapshot.py")
    result = subprocess.run(
        [sys.executable, str(script_path), "--json", "--top", "10"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload["top_processes"], list)
