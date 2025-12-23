"""
pytest 설정 및 공통 픽스처

Windows에서 한글 출력 시 인코딩 문제 해결을 위한 설정 포함
워커 실행 중 프로덕션 DB 보호를 위한 안전장치 포함
"""

import sys
import os

# Windows에서 UTF-8 인코딩 강제 설정
if sys.platform == 'win32':
    # stdout/stderr를 UTF-8로 설정
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    # 환경 변수 설정
    os.environ['PYTHONIOENCODING'] = 'utf-8'


import pytest
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 워커 PID 파일 경로
WORKER_PID_PATH = PROJECT_ROOT / ".pids" / "worker.pid"


def is_worker_running() -> bool:
    """워커 프로세스가 실행 중인지 확인"""
    if not WORKER_PID_PATH.exists():
        return False
    try:
        import psutil
        pid = int(WORKER_PID_PATH.read_text().strip())
        return psutil.pid_exists(pid)
    except (ImportError, ValueError, FileNotFoundError):
        return False


@pytest.fixture(scope="session", autouse=True)
def warn_if_worker_running():
    """워커 실행 중이면 테스트 시작 시 경고 출력"""
    if is_worker_running():
        try:
            pid = WORKER_PID_PATH.read_text().strip()
            print(f"\n{'='*60}")
            print(f"  WARNING: Worker is running (PID: {pid})")
            print(f"  Some tests that access production DB will be skipped.")
            print(f"  To run all tests, stop the worker first:")
            print(f"    .\\scripts\\stop.ps1")
            print(f"{'='*60}\n")
        except:
            pass
