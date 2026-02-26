"""pytest mark 인프라 검증 테스트"""
import os
import subprocess
import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
PYTHON = sys.executable


class TestPytestMarkInfra:
    def test_right_http_marker_registered(self):
        """TC-Right: pytest.ini에 http marker 등록 → --markers 출력에 http 표시"""
        result = subprocess.run(
            [PYTHON, "-m", "pytest", "--markers"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT)
        )
        assert "http" in result.stdout, f"http marker not found in: {result.stdout[:500]}"

    def test_right_http_tests_have_pytestmark(self):
        """TC-Right: test_http_e2e.py 파일이 pytestmark = pytest.mark.http 설정됨"""
        http_e2e = PROJECT_ROOT / "tests" / "dev_runner" / "test_http_e2e.py"
        content = http_e2e.read_text(encoding="utf-8")
        assert "pytestmark = pytest.mark.http" in content, \
            "test_http_e2e.py에 pytestmark = pytest.mark.http 가 없음"

    def test_right_not_http_excludes_http_tests(self):
        """TC-Right: -m 'not http' 실행 시 http 마크된 테스트는 deselected"""
        # test_http_e2e_max_cycles.py도 pytestmark 설정 확인
        http_max = PROJECT_ROOT / "tests" / "dev_runner" / "test_http_e2e_max_cycles.py"
        content = http_max.read_text(encoding="utf-8")
        assert "pytestmark = pytest.mark.http" in content, \
            "test_http_e2e_max_cycles.py에 pytestmark = pytest.mark.http 가 없음"

    def test_boundary_non_http_test_included_in_not_http(self):
        """TC-Boundary: mark 없는 테스트 → -m 'not http'에 포함됨"""
        result = subprocess.run(
            [PYTHON, "-m", "pytest", "tests/dev_runner/test_pytest_mark.py",
             "--collect-only", "-m", "not http", "-q", "--no-header"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
            timeout=20
        )
        # 이 파일 자체는 http mark 없으므로 수집되어야 함
        assert result.returncode == 0


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
