"""OrphanDetector TC"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_registry(procs: dict):
    """Mock ProcessRegistry."""
    registry = MagicMock()
    registry.get_all = AsyncMock(return_value=procs)
    registry.unregister = AsyncMock(return_value=True)
    return registry


def make_entry(pid: int, ppid: int, name: str = "worker") -> dict:
    return {
        "pid": str(pid),
        "ppid": str(ppid),
        "name": name,
        "exe": "python.exe",
        "role": "worker",
    }


@pytest.mark.asyncio
async def test_scan_finds_dead_parent():
    """R: ppid 죽은 프로세스 1개 등록 → scan() → orphan 1건 반환"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=1001, ppid=9999)
    registry = make_registry({1001: entry})

    def pid_exists(pid):
        if pid == 9999:
            return False  # ppid 죽음
        if pid == 1001:
            return True   # 자식은 살아있음
        return False

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", side_effect=pid_exists):
        detector = OrphanDetector(registry)
        orphans = await detector.scan()

    assert len(orphans) == 1
    assert orphans[0]["pid"] == "1001"


@pytest.mark.asyncio
async def test_scan_ignores_alive_parent():
    """I: ppid 살아있는 프로세스 → scan() → orphan 0건"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=2001, ppid=1000)
    registry = make_registry({2001: entry})

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=True):
        detector = OrphanDetector(registry)
        orphans = await detector.scan()

    assert len(orphans) == 0


@pytest.mark.asyncio
async def test_cleanup_grace_period_not_elapsed():
    """B: 감지 직후(0초) cleanup() → 정리 안 됨 (빈 리스트)"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=3001, ppid=9999)
    registry = make_registry({3001: entry})
    detector = OrphanDetector(registry, grace_period=30)

    # 방금 등록
    detector._orphan_first_seen[3001] = time.time()

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False):
        cleaned = await detector.cleanup([entry])

    assert len(cleaned) == 0


@pytest.mark.asyncio
async def test_cleanup_grace_period_elapsed():
    """R: _orphan_first_seen 30초 전으로 설정 → cleanup() → 정리됨"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=4001, ppid=9999)
    registry = make_registry({4001: entry})
    detector = OrphanDetector(registry, grace_period=30)

    # 31초 전으로 설정
    detector._orphan_first_seen[4001] = time.time() - 31

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False), \
         patch("app.shared.process.orphan_detector.kill_pid", return_value=True):
        cleaned = await detector.cleanup([entry])

    assert len(cleaned) == 1
    assert cleaned[0]["pid"] == "4001"


@pytest.mark.asyncio
async def test_cleanup_force_ignores_grace():
    """R: 감지 직후 cleanup(force=True) → 즉시 정리"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=5001, ppid=9999)
    registry = make_registry({5001: entry})
    detector = OrphanDetector(registry, grace_period=30)

    # 방금 등록
    detector._orphan_first_seen[5001] = time.time()

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", return_value=False), \
         patch("app.shared.process.orphan_detector.kill_pid", return_value=True):
        cleaned = await detector.cleanup([entry], force=True)

    assert len(cleaned) == 1


@pytest.mark.asyncio
async def test_scan_removes_dead_processes():
    """E: pid 자체가 죽은 항목 → scan()에서 unregister 호출"""
    from app.shared.process.orphan_detector import OrphanDetector

    entry = make_entry(pid=6001, ppid=1000)
    registry = make_registry({6001: entry})
    detector = OrphanDetector(registry)

    def pid_exists(pid):
        if pid == 6001:
            return False  # 자신도 죽음
        return True

    with patch("app.shared.process.orphan_detector.psutil.pid_exists", side_effect=pid_exists):
        await detector.scan()

    registry.unregister.assert_called_with(6001)
