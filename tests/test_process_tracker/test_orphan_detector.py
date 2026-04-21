"""OrphanDetector TC"""
import asyncio
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


@pytest.mark.asyncio
async def test_run_periodic_checks_memory_more_frequently_than_scan():
    """R: memory_check_interval < interval이면 pressure.check가 scan보다 더 자주 호출됨"""
    from app.shared.process.orphan_detector import OrphanDetector

    registry = make_registry({})
    detector = OrphanDetector(registry)
    detector.scan = AsyncMock(return_value=[])
    detector.cleanup = AsyncMock(return_value=[])

    fake_pressure = MagicMock()
    fake_pressure.check = AsyncMock(return_value="normal")

    with patch("app.shared.process.memory_pressure.MemoryPressureResponder", return_value=fake_pressure), \
         patch("app.shared.process.orphan_detector.settings.PROCESS_WATCH_CAPTURE_EVERY_LOOPS", 999):
        task = asyncio.create_task(
            detector.run_periodic(interval=0.20, memory_check_interval=0.05)
        )
        await asyncio.sleep(0.27)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert fake_pressure.check.await_count > detector.scan.await_count


@pytest.mark.asyncio
async def test_detect_orphan_test_worktrees_finds_stale_runner(tmp_path):
    """R: stale runner/t-* worktree + Redis 키 없음 → cleanup 후보 반환"""
    from app.shared.process.orphan_detector import OrphanDetector

    worktree = tmp_path / ".worktrees" / "t-stale-001"
    worktree.mkdir(parents=True)
    stale_time = time.time() - 1200
    import os
    os.utime(worktree, (stale_time, stale_time))

    detector = OrphanDetector(
        make_registry({}),
        repo_root=tmp_path,
        runner_key_exists=lambda _runner_id: False,
    )

    with patch.object(
        detector,
        "_iter_git_worktrees",
        return_value=[{"branch": "runner/t-stale-001", "worktree_path": str(worktree)}],
    ):
        branches = await detector.detect_orphan_test_worktrees()

    assert branches == ["runner/t-stale-001"]


@pytest.mark.asyncio
async def test_detect_orphan_test_worktrees_skips_non_test_prefix(tmp_path):
    """I: impl/* 브랜치는 후보에서 제외"""
    from app.shared.process.orphan_detector import OrphanDetector

    worktree = tmp_path / ".worktrees" / "impl-fix"
    worktree.mkdir(parents=True)
    stale_time = time.time() - 1200
    import os
    os.utime(worktree, (stale_time, stale_time))

    detector = OrphanDetector(make_registry({}), repo_root=tmp_path)

    with patch.object(
        detector,
        "_iter_git_worktrees",
        return_value=[{"branch": "impl/fix-foo", "worktree_path": str(worktree)}],
    ):
        branches = await detector.detect_orphan_test_worktrees()

    assert branches == []


@pytest.mark.asyncio
async def test_detect_orphan_test_worktrees_skips_active_runner(tmp_path):
    """I: runner 키가 남아 있으면 후보에서 제외"""
    from app.shared.process.orphan_detector import OrphanDetector

    worktree = tmp_path / ".worktrees" / "t-active-001"
    worktree.mkdir(parents=True)
    stale_time = time.time() - 1200
    import os
    os.utime(worktree, (stale_time, stale_time))

    detector = OrphanDetector(
        make_registry({}),
        repo_root=tmp_path,
        runner_key_exists=lambda _runner_id: True,
    )

    with patch.object(
        detector,
        "_iter_git_worktrees",
        return_value=[{"branch": "runner/t-active-001", "worktree_path": str(worktree)}],
    ):
        branches = await detector.detect_orphan_test_worktrees()

    assert branches == []


@pytest.mark.asyncio
async def test_detect_orphan_test_worktrees_respects_age_threshold(tmp_path):
    """B: 15분 경계 전후만 후보 여부가 갈려야 한다"""
    from app.shared.process.orphan_detector import OrphanDetector

    early = tmp_path / ".worktrees" / "t-early-001"
    exact = tmp_path / ".worktrees" / "t-exact-001"
    stale = tmp_path / ".worktrees" / "t-stale-001"
    for worktree in (early, exact, stale):
        worktree.mkdir(parents=True)

    now = time.time()
    import os

    os.utime(early, (now - 899, now - 899))
    os.utime(exact, (now - 900, now - 900))
    os.utime(stale, (now - 901, now - 901))

    detector = OrphanDetector(
        make_registry({}),
        repo_root=tmp_path,
        runner_key_exists=lambda _runner_id: False,
    )

    with patch.object(
        detector,
        "_iter_git_worktrees",
        return_value=[
            {"branch": "runner/t-early-001", "worktree_path": str(early)},
            {"branch": "runner/t-exact-001", "worktree_path": str(exact)},
            {"branch": "runner/t-stale-001", "worktree_path": str(stale)},
        ],
    ):
        branches = await detector.detect_orphan_test_worktrees()

    assert "runner/t-early-001" not in branches
    assert "runner/t-exact-001" in branches
    assert "runner/t-stale-001" in branches


@pytest.mark.asyncio
async def test_run_periodic_invokes_test_worktree_cleanup():
    """R: stale test worktree가 감지되면 cleanup callback까지 연결된다"""
    from app.shared.process.orphan_detector import OrphanDetector

    registry = make_registry({})
    cleanup_callback = AsyncMock(return_value=None)
    detector = OrphanDetector(registry, cleanup_callback=cleanup_callback)
    detector.scan = AsyncMock(return_value=[])
    detector.cleanup = AsyncMock(return_value=[])
    detector.detect_orphan_test_worktrees = AsyncMock(return_value=["runner/t-stale-002"])

    fake_pressure = MagicMock()
    fake_pressure.check = AsyncMock(return_value="normal")

    with patch("app.shared.process.memory_pressure.MemoryPressureResponder", return_value=fake_pressure), \
         patch("app.shared.process.orphan_detector.settings.PROCESS_WATCH_CAPTURE_EVERY_LOOPS", 999):
        task = asyncio.create_task(
            detector.run_periodic(interval=0.20, memory_check_interval=0.20)
        )
        await asyncio.sleep(0.22)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    cleanup_callback.assert_awaited_with(["runner/t-stale-002"])
