"""
Integration Test 전용 pytest 설정

테스트 서버를 자동으로 시작/종료하는 fixture 제공
"""

import pytest
import subprocess
import time
import os
import sys
from pathlib import Path

# requests는 optional dependency
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_DB_PATH = PROJECT_ROOT / "data" / "test_integration_monitor.db"
TEST_SERVER_PORT = 8001


@pytest.fixture(scope="session")
def integration_server():
    """
    Integration Test용 테스트 서버 자동 실행

    - 별도 포트(8001)에서 실행
    - 테스트용 DB 사용 (프로덕션 DB 격리)
    - 테스트 종료 시 자동 정리
    """
    if not HAS_REQUESTS:
        pytest.skip("requests 모듈이 필요합니다: pip install requests")

    # 1. 기존 테스트 DB 삭제 (깨끗한 상태로 시작)
    if TEST_DB_PATH.exists():
        os.remove(TEST_DB_PATH)

    # 2. 테스트 서버 실행 (별도 포트, 새 DB)
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    # Windows에서는 python.exe 사용
    python_exe = sys.executable

    proc = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "app.main:app", "--port", str(TEST_SERVER_PORT)],
        env=env,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 3. 서버 준비 대기 (health check)
    base_url = f"http://localhost:{TEST_SERVER_PORT}"
    max_wait = 15

    for i in range(max_wait):
        try:
            resp = requests.get(f"{base_url}/health", timeout=1)
            if resp.status_code == 200:
                break
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    else:
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"테스트 서버 시작 실패\n"
            f"stdout: {stdout.decode('utf-8', errors='replace')}\n"
            f"stderr: {stderr.decode('utf-8', errors='replace')}"
        )

    yield base_url

    # 4. 정리
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    if TEST_DB_PATH.exists():
        os.remove(TEST_DB_PATH)
