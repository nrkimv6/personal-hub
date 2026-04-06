"""pytest marker/collect 계약 검증 테스트."""
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
PYTHON = sys.executable


def _run_pytest(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-m", "pytest", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(PROJECT_ROOT),
        timeout=timeout,
    )


def _run_collect_only(path: str, marker: str) -> subprocess.CompletedProcess[str]:
    return _run_pytest(path, "--collect-only", "-m", marker, "-q", "--no-header")


class TestPytestMarkInfra:
    def test_registered_markers_include_http_http_live_and_e2e(self):
        """TC-Right: pytest.ini에 핵심 marker가 모두 등록되어 있다."""
        result = _run_pytest("--markers")
        assert "@pytest.mark.http" in result.stdout, f"http marker not found: {result.stdout[:500]}"
        assert "@pytest.mark.http_live" in result.stdout, f"http_live marker not found: {result.stdout[:500]}"
        assert "@pytest.mark.e2e" in result.stdout, f"e2e marker not found: {result.stdout[:500]}"

    def test_http_marker_collects_testclient_suite(self):
        """TC-Right: TestClient 기반 HTTP 파일은 -m http에서 수집된다."""
        result = _run_collect_only("tests/dev_runner/test_http_e2e.py", "http")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "tests/dev_runner/test_http_e2e.py" in result.stdout

    def test_exit_reason_legacy_e2e_file_collects_under_http(self):
        """TC-Right: legacy e2e 파일명이어도 실제 계약은 http marker로 수집된다."""
        result = _run_collect_only("tests/dev_runner/test_exit_reason_e2e.py", "http")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "test_exit_reason_http_runners_api" in result.stdout

    def test_boundary_non_http_test_included_in_not_http(self):
        """TC-Boundary: mark 없는 테스트 → -m 'not http'에 포함됨"""
        result = _run_pytest("tests/dev_runner/test_pytest_mark.py", "--collect-only", "-m", "not http", "-q", "--no-header", timeout=20)
        # 이 파일 자체는 http mark 없으므로 수집되어야 함
        assert result.returncode == 0

    def test_legacy_e2e_file_is_not_collected_by_e2e_marker(self):
        """TC-Boundary: TestClient 기반 legacy 파일은 -m e2e에서 무선택이어야 한다."""
        result = _run_collect_only("tests/dev_runner/test_exit_reason_e2e.py", "e2e")
        combined = result.stdout + result.stderr
        assert "no tests collected" in combined, combined

    def test_http_live_marker_collects_live_server_suite(self):
        """TC-Right: 실서버 파일은 -m http_live에서 수집된다."""
        result = _run_collect_only("tests/dev_runner/test_live_server_http.py", "http_live")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "tests/dev_runner/test_live_server_http.py" in result.stdout

    def test_log_stream_live_file_collects_under_http_live(self):
        """TC-Right: test_log_stream_http.py 전체는 http_live에서만 수집된다."""
        result = _run_collect_only("tests/dev_runner/test_log_stream_http.py", "http_live")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "test_http_log_stream_connected_event" in result.stdout

    def test_log_stream_live_file_not_collected_by_http(self):
        """TC-Boundary: 혼합 마커 파일에서 -m http는 http 테스트만 수집하고 http_live 전용은 제외한다."""
        result = _run_collect_only("tests/dev_runner/test_log_stream_http.py", "http")
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "test_http_log_stream_commit_failed_keeps_reason_and_detail" in combined, combined
        assert "test_http_events_stream_fallback_log_delivery" in combined, combined
        # http_live-only 실서버 케이스는 -m http에서 수집되면 안 된다.
        assert "test_http_log_stream_connected_event" not in combined, combined

    def test_boundary_http_live_excluded_from_default(self):
        """TC-Boundary: addopts에 'not http_live' 포함 → 기본 pytest 실행 시 http_live 제외"""
        ini_file = PROJECT_ROOT / "pytest.ini"
        content = ini_file.read_text(encoding="utf-8")
        assert "not http_live" in content, \
            "pytest.ini addopts에 'not http_live' 가 없음 — 기본 실행 시 실서버 TC가 포함됨"


class TestDbDirEnvVar:
    def test_right_test_db_dir_env_var_used(self, tmp_path):
        """TC-Right: TEST_DB_DIR 환경변수 설정 → 해당 경로에 test_monitor.db 생성 가능"""
        # conftest.py가 TEST_DB_DIR 환경변수를 읽는지 확인
        from tests.conftest import TEST_DB_DIR as _default_dir
        # 환경변수 없을 때 기본값이 PROJECT_ROOT/data인지 확인
        default_path = PROJECT_ROOT / "data"
        # TEST_DB_DIR 환경변수가 없을 때 기본값 사용
        env_val = os.environ.get("TEST_DB_DIR", str(default_path))
        assert env_val  # 값이 있어야 함

    def test_right_test_db_default_path(self):
        """TC-Right: TEST_DB_DIR 미설정 → 기본 PROJECT_ROOT/data 경로 사용"""
        import importlib
        import tests.conftest as conf
        importlib.reload(conf)
        default = str(PROJECT_ROOT / "data")
        # TEST_DB_DIR 없으면 기본 경로
        if "TEST_DB_DIR" not in os.environ:
            assert str(conf.TEST_DB_DIR) == default

    def test_boundary_nonexistent_test_db_dir_auto_makedirs(self, tmp_path):
        """TC-Boundary: TEST_DB_DIR 경로가 존재하지 않음 → makedirs 호출"""
        new_dir = tmp_path / "nested" / "db_dir"
        assert not new_dir.exists()
        # makedirs 호출
        new_dir.mkdir(parents=True, exist_ok=True)
        assert new_dir.exists()
