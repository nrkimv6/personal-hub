"""
watchdog 중복 프로세스 감지/정리 T1 검증 테스트

시나리오:
  - "command-listener" cmdline 마커를 가진 더미 프로세스를 2개 실행
  - PID 파일에 프로세스 1을 정본(canonical)으로 기록
  - watchdog-utils.ps1의 Remove-DuplicateProcesses 동등 로직(Python/psutil)을 실행
  - 결과: 정본 프로세스는 살아있고, 중복 프로세스는 종료됨

포트 바인딩 없음 — Redis/API 서버 불필요 (worktree T1 허용)
"""
import os
import sys
import subprocess
import time
from pathlib import Path

import psutil
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 테스트용 고유 마커 (실제 command-listener와 겹치지 않도록)
_MARKER = "__watchdog_dup_cleanup_test_xyz9__"


# ─── Python equivalent of watchdog-utils.ps1 functions ───────────────────────

def _get_canonical_pids(canonical_pid: int | None) -> set[int]:
    """
    canonical_pid와 그 자식 프로세스 PID 집합을 반환.
    venv 래퍼가 실제 인터프리터를 자식으로 실행하는 경우를 처리.
    """
    if canonical_pid is None:
        return set()
    protected = {canonical_pid}
    try:
        parent = psutil.Process(canonical_pid)
        for child in parent.children(recursive=True):
            protected.add(child.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return protected


def _get_duplicate_processes(cmdline_pattern: str, canonical_pid: int | None):
    """
    Get-DuplicateProcesses 동등 로직.
    cmdline에 pattern이 포함된 프로세스 중 canonical_pid(및 그 자식들)를 제외한 목록 반환.

    주의: venv 래퍼 python.exe는 실제 인터프리터를 자식 프로세스로 실행한다.
    canonical의 자식들도 보호 대상에 포함해야 "정본 프로세스 그룹"이 안전하게 유지된다.
    """
    protected_pids = _get_canonical_pids(canonical_pid)
    duplicates = []
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = " ".join(proc.info['cmdline'] or [])
            if cmdline_pattern in cmdline:
                if proc.pid not in protected_pids:
                    duplicates.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return duplicates


def _remove_duplicate_processes(cmdline_pattern: str, pid_file: Path):
    """
    Remove-DuplicateProcesses 동등 로직.
    PID 파일의 PID를 정본으로 간주하고 나머지 중복 프로세스를 종료.
    반환값: 종료된 프로세스 수
    """
    canonical_pid = None
    if pid_file.exists():
        content = pid_file.read_text().strip()
        if content.isdigit():
            canonical_pid = int(content)

    duplicates = _get_duplicate_processes(cmdline_pattern, canonical_pid)
    killed = 0
    for proc in duplicates:
        try:
            proc.kill()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _kill_all_marker_procs():
    """테스트 격리: 마커 패턴의 잔여 프로세스를 모두 제거하고 완전히 종료될 때까지 기다린다."""
    victims = []
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = " ".join(proc.info['cmdline'] or [])
            if _MARKER in cmdline:
                proc.kill()
                victims.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    # 프로세스가 실제로 종료될 때까지 대기
    for proc in victims:
        try:
            proc.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass
    if victims:
        time.sleep(0.2)


@pytest.fixture
def two_listener_procs():
    """
    더미 프로세스 2개를 실행한다.
    cmdline에 _MARKER가 포함되어 있어 실제 command-listener와 구분됨.
    픽스처 시작/종료 시 잔여 마커 프로세스를 모두 정리한다.
    """
    _kill_all_marker_procs()  # 사전 정리 (이전 테스트 잔여 프로세스 제거)

    procs = []
    for _ in range(2):
        p = subprocess.Popen(
            [sys.executable, "-c",
             f"import time; x='{_MARKER}'; time.sleep(60)"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        procs.append(p)
    time.sleep(0.5)  # 프로세스 시작 대기
    yield procs
    # 테스트 후 남은 프로세스 정리 (완전히 종료될 때까지 대기)
    for p in procs:
        if p.poll() is None:
            p.kill()
    for p in procs:
        try:
            p.wait(timeout=5)
        except Exception:
            pass


@pytest.fixture
def pid_file(tmp_path):
    return tmp_path / "command_listener.pid"


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestWatchdogDuplicateCleanup:
    """
    Phase T1: listener를 수동으로 2개 띄운 상태에서 watchdog 실행 → 1개만 남는지 확인
    """

    def test_right_two_procs_one_survives(self, two_listener_procs, pid_file):
        """
        R(Right): 더미 프로세스 2개 중 정본 1개만 살아남는다.

        - PID 파일에 proc1을 정본으로 기록
        - Remove-DuplicateProcesses 실행 후 proc1은 살아있고 proc2는 종료됨
        """
        proc1, proc2 = two_listener_procs

        # 프로세스 1을 정본으로 PID 파일에 기록
        pid_file.write_text(str(proc1.pid))

        # watchdog의 Remove-DuplicateProcesses 동등 로직 실행
        _remove_duplicate_processes(_MARKER, pid_file)

        time.sleep(0.5)

        # 절대 카운트 대신 우리가 생성한 PID 기준으로 검증
        assert proc1.poll() is None, "정본 프로세스(proc1)는 살아있어야 함"
        assert proc2.poll() is not None, "중복 프로세스(proc2)는 종료되어야 함"

    def test_boundary_no_pid_file_kills_all(self, two_listener_procs, pid_file):
        """
        B(Boundary): PID 파일 없으면 canonical_pid=None → 우리가 띄운 프로세스 모두 정리.
        """
        proc1, proc2 = two_listener_procs

        # PID 파일 없음 (canonical 없음)
        assert not pid_file.exists()

        _remove_duplicate_processes(_MARKER, pid_file)

        time.sleep(0.3)

        # 우리가 띄운 두 프로세스가 모두 종료됐는지 확인
        assert proc1.poll() is not None, "proc1이 종료되어야 함 (PID 파일 없으면 canonical 없음)"
        assert proc2.poll() is not None, "proc2가 종료되어야 함 (PID 파일 없으면 canonical 없음)"

    def test_boundary_no_duplicates_kills_nothing(self, pid_file):
        """
        B(Boundary): 중복 없으면 0 반환, 아무 것도 종료하지 않는다.
        """
        # 이 마커로 실행 중인 프로세스 없음
        killed = _remove_duplicate_processes(_MARKER, pid_file)
        assert killed == 0

    def test_error_stale_pid_file_kills_extra(self, two_listener_procs, pid_file):
        """
        E(Error): PID 파일의 PID가 유효하지 않은 경우(죽은 프로세스),
        canonical이 None 처럼 동작 → 우리가 띄운 두 프로세스 모두 중복으로 처리.
        """
        proc1, proc2 = two_listener_procs

        # 존재하지 않는 PID를 정본으로 기록 (stale PID)
        pid_file.write_text("9999999")

        _remove_duplicate_processes(_MARKER, pid_file)

        time.sleep(0.3)

        # canonical PID가 실제 프로세스에 없으므로 둘 다 중복으로 간주
        assert proc1.poll() is not None, "proc1이 종료되어야 함 (stale PID 파일)"
        assert proc2.poll() is not None, "proc2가 종료되어야 함 (stale PID 파일)"

    def test_get_duplicate_processes_excludes_canonical(self, two_listener_procs):
        """
        Get-DuplicateProcesses: 정본 PID를 제외한 중복 목록 반환.
        """
        proc1, proc2 = two_listener_procs

        duplicates = _get_duplicate_processes(_MARKER, canonical_pid=proc1.pid)

        pids = [p.pid for p in duplicates]
        assert proc1.pid not in pids, "정본 PID는 중복 목록에 포함되면 안 됨"
        assert proc2.pid in pids, "proc2는 중복으로 감지되어야 함"

    def test_get_duplicate_processes_no_match_returns_empty(self):
        """
        패턴 매칭 없으면 빈 목록 반환.
        """
        duplicates = _get_duplicate_processes("__no_such_pattern_xyz__", None)
        assert duplicates == []
