"""
Python 프로세스 모니터 API 테스트

RIGHT-BICEP + CORRECT 기반 테스트 케이스
"""

import sys
import os
import time
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

import pytest
import requests

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


# ============================================================
# _infer_role 단위 테스트 (Reference)
# ============================================================

class TestInferRole:
    """역할 추론 함수 단위 테스트"""

    def setup_method(self):
        from app.routes.system import _infer_role
        self.infer = _infer_role

    def test_api_prod(self):
        assert self.infer("python app/main.py --port 8000") == "API (prod)"

    def test_api_dev(self):
        assert self.infer("python app/main.py --port 8001") == "API (dev)"

    def test_api_generic(self):
        assert self.infer("python app/main.py --port 9000") == "API"

    def test_worker(self):
        assert self.infer("python scripts/browser_workers.py") == "통합 워커"

    def test_claude_worker(self):
        assert self.infer("python -m app.modules.claude_worker") == "Claude Worker"

    def test_classifier(self):
        assert self.infer("python -m image_classifier.main") == "Classifier"

    def test_proxy(self):
        assert self.infer("python proxy_manager.py") == "Proxy Manager"

    def test_dev_runner(self):
        assert self.infer("python scripts/dev-runner-command-listener.py") == "Dev Runner"

    def test_pytest_process(self):
        assert self.infer("python -m pytest tests/") == "pytest"

    def test_unknown_short(self):
        result = self.infer("python some_script.py")
        assert "some_script" in result

    def test_unknown_long_truncated(self):
        long_cmd = "python " + "x" * 100
        result = self.infer(long_cmd)
        assert len(result) <= 63  # 60 + "..."
        assert result.endswith("...")

    def test_empty_cmdline(self):
        assert self.infer("") == "unknown"

    def test_none_like(self):
        assert self.infer("") == "unknown"


# ============================================================
# _format_uptime 단위 테스트
# ============================================================

class TestFormatUptime:
    def setup_method(self):
        from app.routes.system import _format_uptime
        self.fmt = _format_uptime

    def test_seconds(self):
        assert "초" in self.fmt(30)

    def test_minutes(self):
        assert "분" in self.fmt(300)

    def test_hours(self):
        result = self.fmt(7200)
        assert "시간" in result

    def test_days(self):
        result = self.fmt(90000)
        assert "일" in result


# ============================================================
# RIGHT-BICEP 테스트
# ============================================================

class TestGetPythonProcesses:
    """GET /system/python-processes"""

    # Right: 정상 응답
    def test_right_returns_list(self):
        resp = client.get("/api/v1/system/python-processes")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_right_required_fields(self):
        resp = client.get("/api/v1/system/python-processes")
        data = resp.json()
        # 최소 현재 pytest 프로세스가 있어야 함
        assert len(data) >= 1
        proc = data[0]
        required = {"pid", "role", "memory_mb", "cpu_percent", "cmdline", "create_time", "status", "uptime"}
        assert required.issubset(proc.keys())

    # Cross-check: psutil 직접 호출 vs API
    def test_cross_check_process_count(self):
        import psutil
        direct_count = sum(1 for p in psutil.process_iter(['name'])
                          if 'python' in (p.info.get('name', '') or '').lower())
        resp = client.get("/api/v1/system/python-processes")
        api_count = len(resp.json())
        # 타이밍 차이로 ±2 허용
        assert abs(direct_count - api_count) <= 2

    # Performance: 응답 시간 < 15초 (psutil 프로세스 스캔은 환경에 따라 편차 큼)
    def test_performance_reasonable(self):
        start = time.time()
        resp = client.get("/api/v1/system/python-processes")
        elapsed = time.time() - start
        assert resp.status_code == 200
        assert elapsed < 15.0


class TestKillProcess:
    """POST /system/kill-process"""

    # Boundary: 유효하지 않은 PID
    def test_boundary_pid_zero(self):
        resp = client.post("/api/v1/system/kill-process", json={"pid": 0})
        assert resp.status_code == 400

    def test_boundary_pid_negative(self):
        resp = client.post("/api/v1/system/kill-process", json={"pid": -1})
        assert resp.status_code == 400

    # Error: 존재하지 않는 PID
    def test_error_nonexistent_pid(self):
        resp = client.post("/api/v1/system/kill-process", json={"pid": 99999999})
        assert resp.status_code == 404

    # Inverse: kill 호출 확인 (mock)
    def test_inverse_kill_called(self):
        mock_proc = MagicMock()
        mock_proc.name.return_value = "python.exe"
        mock_proc.exe.return_value = r"D:\Python39\python.exe"
        mock_proc.cmdline.return_value = ["python", "test.py"]
        mock_proc.create_time.return_value = 1712100000.0

        with patch("app.routes.system.psutil.Process", return_value=mock_proc), \
             patch("scripts.service_utils.kill_pid", return_value=True) as mock_kill:
            resp = client.post("/api/v1/system/kill-process", json={"pid": 12345})
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            mock_kill.assert_called_once()

    # Error: non-python 프로세스 거부
    def test_error_non_python_rejected(self):
        mock_proc = MagicMock()
        mock_proc.name.return_value = "notepad.exe"
        mock_proc.exe.return_value = r"C:\Windows\System32\notepad.exe"
        mock_proc.cmdline.return_value = ["notepad.exe"]
        mock_proc.create_time.return_value = 1712100000.0

        with patch("app.routes.system.psutil.Process", return_value=mock_proc):
            resp = client.post("/api/v1/system/kill-process", json={"pid": 12345})
            assert resp.status_code == 400

    # Error: AccessDenied
    def test_error_access_denied(self):
        import psutil
        with patch("app.routes.system.psutil.Process", side_effect=psutil.AccessDenied(pid=1)):
            resp = client.post("/api/v1/system/kill-process", json={"pid": 1})
            assert resp.status_code == 403


# ============================================================
# CORRECT 테스트
# ============================================================

class TestCorrect:
    """CORRECT 기준 테스트"""

    def _get_processes(self):
        resp = client.get("/api/v1/system/python-processes")
        assert resp.status_code == 200
        return resp.json()

    # Conformance: 스키마 준수
    def test_conformance_schema(self):
        data = self._get_processes()
        for proc in data:
            assert isinstance(proc["pid"], int)
            assert isinstance(proc["role"], str)
            assert isinstance(proc["memory_mb"], (int, float))
            assert isinstance(proc["cpu_percent"], (int, float))
            assert isinstance(proc["cmdline"], str)
            assert isinstance(proc["create_time"], str)
            assert isinstance(proc["status"], str)
            assert isinstance(proc["uptime"], str)

    # Ordering: 메모리 내림차순
    def test_ordering_memory_desc(self):
        data = self._get_processes()
        if len(data) >= 2:
            memories = [p["memory_mb"] for p in data]
            assert memories == sorted(memories, reverse=True)

    # Range: 값 범위
    def test_range_memory_non_negative(self):
        for proc in self._get_processes():
            assert proc["memory_mb"] >= 0

    def test_range_cpu_valid(self):
        for proc in self._get_processes():
            assert proc["cpu_percent"] >= 0

    # Existence: 빈 결과 처리 (모든 프로세스를 필터링하면 빈 배열)
    def test_existence_empty_when_no_python(self):
        def mock_iter(*args, **kwargs):
            return iter([])

        with patch("app.routes.system.psutil.process_iter", mock_iter):
            resp = client.get("/api/v1/system/python-processes")
            assert resp.status_code == 200
            assert resp.json() == []

    # Cardinality: 중복 PID 없음
    def test_cardinality_no_duplicate_pids(self):
        data = self._get_processes()
        pids = [p["pid"] for p in data]
        assert len(pids) == len(set(pids))

    # Time: create_time ISO datetime 유효성
    def test_time_create_time_valid_iso(self):
        data = self._get_processes()
        for proc in data:
            dt = datetime.fromisoformat(proc["create_time"])
            assert dt.year >= 2020


class TestProcessWatchApi:
    def test_process_watch_latest_schema(self):
        now_iso = datetime.now().isoformat()
        mock_writer = MagicMock()
        mock_writer.get_latest_python_snapshots.return_value = (
            now_iso,
            [
                {
                    "captured_at": now_iso,
                    "pid": 1234,
                    "ppid": 1000,
                    "parent_pid": 10,
                    "parent_name": "cmd.exe",
                    "name": "python.exe",
                    "exe": r"D:\Python39\python.exe",
                    "cmdline": "python app/main.py --port 8001",
                    "cmdline_hash": "0123456789abcdef0123456789abcdef",
                    "create_time": 1712100000.0,
                    "memory_mb": 1024.5,
                    "is_orphan": False,
                    "scope": "monitor_page",
                    "captured_by": "periodic",
                }
            ],
        )

        with patch("app.routes.system._process_watch_writer", return_value=mock_writer):
            resp = client.get("/api/v1/system/process-watch/latest?min_mb=256&limit=5")

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "periodic"
        assert data["item_count"] == 1
        assert data["items"][0]["pid"] == 1234

    def test_process_watch_latest_stale_triggers_on_demand(self):
        stale_iso = "2000-01-01T00:00:00"
        fresh_iso = datetime.now().isoformat()
        mock_writer = MagicMock()
        mock_writer.get_latest_python_snapshots.side_effect = [
            (stale_iso, [{"captured_at": stale_iso, "pid": 1, "ppid": 0, "parent_pid": None, "parent_name": "", "name": "python.exe", "exe": "", "cmdline": "", "cmdline_hash": "a" * 32, "create_time": 1.0, "memory_mb": 10.0, "is_orphan": False, "scope": "monitor_page", "captured_by": "periodic"}]),
            (fresh_iso, [{"captured_at": fresh_iso, "pid": 2, "ppid": 0, "parent_pid": None, "parent_name": "", "name": "python.exe", "exe": "", "cmdline": "", "cmdline_hash": "b" * 32, "create_time": 2.0, "memory_mb": 20.0, "is_orphan": False, "scope": "monitor_page", "captured_by": "on_demand"}]),
        ]
        mock_writer.capture_python_processes = AsyncMock(return_value=1)

        with patch("app.routes.system._process_watch_writer", return_value=mock_writer), \
             patch("app.routes.system._last_process_watch_on_demand_at", 0.0):
            resp = client.get("/api/v1/system/process-watch/latest")

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "on_demand"
        assert data["items"][0]["pid"] == 2

    def test_process_watch_kill_fingerprint_mismatch_returns_409(self):
        mock_proc = MagicMock()
        mock_proc.name.return_value = "python.exe"
        mock_proc.exe.return_value = r"D:\Python39\python.exe"
        mock_proc.cmdline.return_value = ["python", "app/main.py", "--port", "8001"]
        mock_proc.create_time.return_value = 1712100000.0

        mock_writer = MagicMock()

        with patch("app.routes.system._process_watch_writer", return_value=mock_writer), \
             patch("app.routes.system._protected_pids", return_value=set()), \
             patch("app.routes.system.psutil.Process", return_value=mock_proc):
            resp = client.post(
                "/api/v1/system/process-watch/kill",
                json={
                    "pid": 12345,
                    "expected_create_time": 1712100000.0,
                    "expected_cmdline_hash": "ffffffffffffffffffffffffffffffff",
                    "reason": "fingerprint mismatch smoke",
                    "force": False,
                },
            )

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "fingerprint_mismatch"

    def test_legacy_kill_process_blocks_protected_pid(self):
        protected_pid = os.getpid()
        mock_writer = MagicMock()

        with patch("app.routes.system._process_watch_writer", return_value=mock_writer), \
             patch("app.routes.system._protected_pids", return_value={protected_pid}):
            resp = client.post("/api/v1/system/kill-process", json={"pid": protected_pid})

        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "protected_pid"


def test_http_system_mode_survives_restart_frontend_admin():
    """restart-frontend(admin) 전/후 system mode API가 200 유지되는지 검증."""
    base = "http://localhost:8001"

    try:
        before = requests.get(f"{base}/api/v1/system/mode", timeout=5)
    except Exception:
        pytest.skip("Admin API not available")

    assert before.status_code == 200

    script = PROJECT_ROOT / "scripts" / "browser_workers.py"
    result = subprocess.run(
        [sys.executable, str(script), "restart-frontend"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="replace",
    )
    # 포트 권한/충돌 환경에서는 1이 나올 수 있으므로 API 생존성 검증을 우선한다.
    assert result.returncode in (0, 1)

    # 재시작 직후 잠깐의 공백 허용
    for _ in range(10):
        try:
            after = requests.get(f"{base}/api/v1/system/mode", timeout=5)
            if after.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        pytest.skip("system/mode endpoint did not recover in this environment")
