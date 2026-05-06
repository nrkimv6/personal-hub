from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.services.browser_worker_runtime import status_actions


def test_collect_worker_process_evidence_R_parses_worker_main_process():
    proc = MagicMock()
    proc.cmdline.return_value = ["python.exe", "-m", "app.worker.main"]
    proc.create_time.return_value = 1_715_000_000.0
    proc.is_running.return_value = True

    with patch("psutil.Process", return_value=proc), patch.object(
        status_actions,
        "get_worker_runtime_fingerprint_snapshot",
        return_value={"source_fingerprint": "source-hash", "source_files": [{"path": "app/worker/main.py"}]},
    ):
        evidence = status_actions.collect_worker_process_evidence(1234)

    assert evidence["pid"] == 1234
    assert evidence["alive"] is True
    assert evidence["matches_worker_main"] is True
    assert evidence["create_time"] == 1_715_000_000.0
    assert evidence["create_time_iso"] == "2024-05-06T12:53:20+00:00"
    assert evidence["source_fingerprint"] == "source-hash"
    assert evidence["source_files"] == ["app/worker/main.py"]


def test_collect_worker_process_evidence_E_reports_process_errors():
    with patch("psutil.Process", side_effect=RuntimeError("missing")), patch.object(
        status_actions,
        "get_worker_runtime_fingerprint_snapshot",
        return_value={"source_fingerprint": "source-hash", "source_files": []},
    ):
        evidence = status_actions.collect_worker_process_evidence(9999)

    assert evidence["alive"] is False
    assert evidence["matches_worker_main"] is False
    assert evidence["error"] == "RuntimeError: missing"
    assert evidence["source_fingerprint"] == "source-hash"


def test_evaluate_worker_restart_evidence_R_accepts_newer_replaced_worker():
    before = {
        "pid": 100,
        "alive": True,
        "create_time": 1_715_000_000.0,
        "matches_worker_main": True,
    }
    after = {
        "pid": 101,
        "alive": True,
        "create_time": 1_715_000_100.0,
        "matches_worker_main": True,
    }

    assert status_actions.evaluate_worker_restart_evidence(before, after) == {
        "ok": True,
        "reason": "worker_process_replaced",
    }


def test_evaluate_worker_restart_evidence_T_rejects_stale_worker_process():
    before = {
        "pid": 100,
        "alive": True,
        "create_time": 1_715_000_000.0,
        "matches_worker_main": True,
    }
    after = {
        "pid": 100,
        "alive": True,
        "create_time": 1_715_000_000.0,
        "matches_worker_main": True,
    }

    assert status_actions.evaluate_worker_restart_evidence(before, after) == {
        "ok": False,
        "reason": "stale_worker_process",
    }


def test_evaluate_worker_restart_evidence_E_rejects_cmdline_mismatch():
    after = {
        "pid": 101,
        "alive": True,
        "create_time": 1_715_000_100.0,
        "matches_worker_main": False,
    }

    assert status_actions.evaluate_worker_restart_evidence(None, after) == {
        "ok": False,
        "reason": "worker_cmdline_mismatch",
    }
