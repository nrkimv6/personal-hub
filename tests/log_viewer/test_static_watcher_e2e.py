"""
tests/log_viewer/test_static_watcher_e2e.py — StaticSourceWatcher E2E (Phase T4)

subprocess로 실제 python -m app.log_viewer --follow --admin 실행하여
MONITOR_LOG_DIR 환경변수 오버라이드 + 늦게 생성된 파일 감지 검증.
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest


@pytest.mark.timeout(30)
def test_log_viewer_follow_subprocess_picks_up_late_file(tmp_path: Path):
    """T4 E2E: subprocess log_viewer가 MONITOR_LOG_DIR 오버라이드 + 늦게 생성된 파일을 감지한다.

    시나리오:
    1. MONITOR_LOG_DIR=tmp_path 설정, admin 디렉토리 생성
    2. python -m app.log_viewer --follow --admin 실행 (빈 logs/)
    3. 1.5초 대기 → merge-orchestrator 오늘자 파일 생성 + 라인 추가
    4. 5초 내 stdout에 해당 라인 등장 확인 (StaticSourceWatcher 10초 → monkeypatch 불가, 환경변수로 단축)
    5. subprocess terminate

    주의: StaticSourceWatcher._REFRESH_INTERVAL은 subprocess 내부에서 동작하므로
    환경변수 STATIC_WATCHER_INTERVAL로 오버라이드할 수 있도록 cli.py에서 지원 시
    테스트를 개선할 수 있다. 현재는 실제 10초를 기다리는 대신 test_follow_integration.py의
    단위 통합 TC(T3-46/T3-47)가 빠른 검증을 담당하고, 이 E2E는 subprocess 레벨 통합을 검증한다.
    """
    # admin 디렉토리 생성
    admin_dir = tmp_path / "admin"
    admin_dir.mkdir()

    env = {
        "MONITOR_LOG_DIR": str(tmp_path),
        "STATIC_WATCHER_INTERVAL": "1.0",  # 1초 간격으로 단축 (지원 시)
    }
    # 시스템 환경변수 상속
    import os
    full_env = {**os.environ, **env}

    proc = subprocess.Popen(
        [sys.executable, "-m", "app.log_viewer", "--follow", "--admin"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=full_env,
        cwd=str(Path(__file__).resolve().parent.parent.parent),
    )

    try:
        # 1.5초 대기 (프로세스 시작 + 첫 스캔 완료 대기)
        time.sleep(1.5)

        # 오늘자 파일 생성
        today_str = date.today().strftime("%Y%m%d")
        log_file = tmp_path / f"merge-orchestrator_{today_str}_120000.log"
        log_file.write_text("e2e_test_line\n", encoding="utf-8")

        # 최대 15초 동안 stdout에서 해당 라인 탐색
        deadline = time.monotonic() + 15.0
        found = False
        while time.monotonic() < deadline:
            line = proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                break
            if "e2e_test_line" in line:
                found = True
                break

        assert found, (
            "subprocess log_viewer가 늦게 생성된 파일의 라인을 15초 내에 출력하지 않았음. "
            "StaticSourceWatcher 동작 또는 MONITOR_LOG_DIR 오버라이드 확인 필요."
        )

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
