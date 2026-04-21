"""고아 프로세스 감지 및 정리 모듈.

부모 프로세스가 죽었지만 자식 프로세스가 살아있는 경우(고아 프로세스)를
감지하고, grace period 경과 후 자동으로 정리한다.
"""
import asyncio
import sys
import time
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

import psutil

from app.core.config import settings, logger
from app.shared.process.registry import ProcessRegistry
from app.shared.process.worktree_residue_monitor import WorktreeResidueMonitor

if TYPE_CHECKING:
    pass

# kill_pid 동적 임포트 (scripts/services/service_utils.py)
def kill_pid(pid: int, timeout: int = 5) -> bool:
    """scripts.service_utils.kill_pid 위임 래퍼."""
    try:
        scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
        services_dir = str(Path(__file__).resolve().parents[3] / "scripts" / "services")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        if services_dir not in sys.path:
            sys.path.insert(0, services_dir)
        from service_utils import kill_pid as _kp  # type: ignore
        return _kp(pid, timeout)
    except Exception as exc:
        import logging as _l
        _l.getLogger(__name__).warning("kill_pid 실패 (pid=%s): %s", pid, exc)
        return False

class OrphanDetector:
    """고아 프로세스 감지 및 정리 클래스."""

    def __init__(
        self,
        registry: ProcessRegistry,
        grace_period: int = 30,
        *,
        repo_root: Path | None = None,
        runner_key_exists: Optional[Callable[[str], bool]] = None,
        cleanup_callback: Optional[Callable[[list[str]], Awaitable[object]]] = None,
        test_worktree_grace_period_seconds: int = 900,
    ) -> None:
        """초기화.

        Args:
            registry: ProcessRegistry 인스턴스
            grace_period: 고아 감지 후 정리까지 대기 시간 (초)
        """
        self.registry = registry
        self.grace_period = grace_period
        self._orphan_first_seen: dict[int, float] = {}  # pid → 최초 감지 시각
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
        self.runner_key_exists = runner_key_exists
        self.cleanup_callback = cleanup_callback
        self.test_worktree_grace_period_seconds = test_worktree_grace_period_seconds

    async def scan(self) -> list[dict]:
        """고아 프로세스를 스캔한다.

        Returns:
            고아 프로세스 정보 리스트
        """
        all_procs = await self.registry.get_all()
        orphans: list[dict] = []

        for pid, entry in all_procs.items():
            # 프로세스 자체가 이미 죽었으면 Registry에서 제거
            if not psutil.pid_exists(pid):
                await self.registry.unregister(pid)
                self._orphan_first_seen.pop(pid, None)
                continue

            # 부모 프로세스가 죽었으면 고아
            try:
                ppid_str = entry.get("ppid")
                if ppid_str is None:
                    continue
                ppid = int(ppid_str)
            except (ValueError, TypeError):
                continue

            if not psutil.pid_exists(ppid):
                orphans.append(entry)
                if pid not in self._orphan_first_seen:
                    self._orphan_first_seen[pid] = time.time()
                    logger.warning(
                        "고아 프로세스 감지: pid=%s name=%s role=%s (ppid=%s 사망)",
                        pid,
                        entry.get("name"),
                        entry.get("role"),
                        ppid,
                    )

        return orphans

    def _is_monitor_page_process(self, pid: int) -> bool:
        """monitorpage- 계열 프로세스인지 확인한다."""
        try:
            return psutil.Process(pid).name().startswith("monitorpage-")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def _iter_git_worktrees(self) -> list[dict]:
        """git worktree list --porcelain 결과를 파싱한다."""
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self.repo_root),
            timeout=15,
        )
        if result.returncode != 0:
            logger.warning("[orphan-worktree] git worktree list 실패: %s", result.stderr.strip())
            return []

        parsed: list[dict] = []
        current: dict[str, str | bool] | None = None
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current:
                    parsed.append(current)
                current = {"worktree_path": line[9:], "branch": "", "locked": False}
            elif current is not None and line.startswith("branch "):
                current["branch"] = line[7:].replace("refs/heads/", "")
            elif current is not None and line.startswith("locked"):
                current["locked"] = True

        if current:
            parsed.append(current)
        return parsed

    def _runner_keys_exist(self, runner_id: str) -> bool:
        if self.runner_key_exists is not None:
            return bool(self.runner_key_exists(runner_id))

        try:
            from app.modules.dev_runner.services.redis_connection import RedisConnection, RUNNER_KEY_PREFIX

            client = RedisConnection().redis_client
            for _ in client.scan_iter(f"{RUNNER_KEY_PREFIX}:{runner_id}:*"):
                return True
            return False
        except Exception as exc:
            logger.warning("[orphan-worktree] runner key 조회 실패 (%s): %s", runner_id, exc)
            return False

    def _list_test_worktree_branches(self) -> list[str]:
        from app.modules.dev_runner.services.worktree_service import is_test_branch

        branches: list[str] = []
        for item in self._iter_git_worktrees():
            branch = str(item.get("branch") or "")
            if branch and is_test_branch(branch):
                branches.append(branch)
        return sorted(set(branches))

    async def detect_orphan_test_worktrees(self) -> list[str]:
        """잔류 test worktree 후보 branch 목록을 반환한다."""
        from app.modules.dev_runner.services.worktree_service import is_test_branch

        now = time.time()
        branches: list[str] = []
        for item in self._iter_git_worktrees():
            branch = str(item.get("branch") or "")
            if not branch or not is_test_branch(branch):
                continue

            worktree_path = Path(str(item.get("worktree_path") or ""))
            if not worktree_path.exists():
                continue

            age_seconds = now - worktree_path.stat().st_mtime
            if age_seconds < self.test_worktree_grace_period_seconds:
                continue

            if branch.startswith("runner/"):
                runner_id = branch.split("/", 1)[1]
                if self._runner_keys_exist(runner_id):
                    continue

            branches.append(branch)

        return branches

    async def cleanup_orphan_test_worktrees(self, branches: list[str]) -> object | None:
        if not branches:
            return None

        if self.cleanup_callback is not None:
            return await self.cleanup_callback(branches)

        from app.modules.dev_runner.services.worktree_service import cleanup_worktrees

        return await cleanup_worktrees(branches, dry_run=False, repo_root=self.repo_root)

    async def cleanup(self, orphans: list[dict], force: bool = False) -> list[dict]:
        """고아 프로세스를 정리한다.

        Args:
            orphans: scan()에서 반환된 고아 프로세스 리스트
            force: True면 grace period 무시하고 즉시 정리

        Returns:
            실제로 정리된 프로세스 정보 리스트
        """
        # 순환 import 방지를 위해 지연 임포트
        from scripts.services.service_utils import kill_pid  # type: ignore

        cleaned: list[dict] = []
        now = time.time()

        for entry in orphans:
            try:
                pid = int(entry.get("pid", 0))
            except (ValueError, TypeError):
                continue

            first_seen = self._orphan_first_seen.get(pid)
            if first_seen is None:
                # 처음 발견 — 기록만
                self._orphan_first_seen[pid] = now
                continue

            if not force and (now - first_seen) < self.grace_period:
                # Grace period 미경과 → 스킵
                continue

            # watchdog/listener 역할 프로세스는 cleanup 대상에서 제외
            # (browser_workers.py facade 재시작 시 ppid가 바뀌어 오판될 수 있음)
            role = entry.get("role", "")
            _WATCHDOG_ROLES = {
                "watchdog", "claude_watchdog", "cmd_listener_watchdog",
                "chat_executor_watchdog", "dev_listener", "api_watchdog",
            }
            if role in _WATCHDOG_ROLES:
                logger.debug("워치독/리스너 프로세스는 orphan cleanup 제외: pid=%s role=%s", pid, role)
                continue

            # 정리
            name = entry.get("name", "unknown")
            logger.info("고아 프로세스 종료: pid=%s name=%s", pid, name)
            kill_pid(pid)
            await self.registry.unregister(pid)
            self._orphan_first_seen.pop(pid, None)
            cleaned.append(entry)

            # 스냅샷 기록 (순환 import 방지를 위해 지연 임포트)
            try:
                from app.shared.process.snapshot_writer import SnapshotWriter
                SnapshotWriter(self.registry).record_orphan_action(pid, name, "terminated")
            except Exception as exc:
                logger.debug("record_orphan_action 실패: %s", exc)

        return cleaned

    async def run_periodic(
        self,
        interval: float = 60,
        memory_check_interval: float | None = None,
    ) -> None:
        """주기적으로 고아 프로세스를 스캔/정리하고 메모리 압박을 체크한다.

        Args:
            interval: 프로세스 스캔/정리 주기 (초)
            memory_check_interval: 메모리 압박 체크 주기 (초). None이면 설정값 사용
        """
        # MemoryPressureResponder는 지연 임포트 (순환 방지)
        from app.shared.process.memory_pressure import MemoryPressureResponder

        pressure = MemoryPressureResponder(self)
        scan_interval = max(0.1, float(interval))
        _configured_memory_interval = (
            float(getattr(settings, "MEMORY_PRESSURE_CHECK_INTERVAL", scan_interval))
            if memory_check_interval is None
            else float(memory_check_interval)
        )
        memory_interval = max(0.1, _configured_memory_interval)

        loop_count = 0
        capture_every_loops = max(1, int(getattr(settings, "PROCESS_WATCH_CAPTURE_EVERY_LOOPS", 1)))
        capture_timeout = max(1, int(getattr(settings, "PROCESS_WATCH_CAPTURE_TIMEOUT_SEC", 10)))
        capture_limit = max(1, int(getattr(settings, "PROCESS_WATCH_CAPTURE_LIMIT", 200)))
        next_scan_at = time.monotonic()
        next_memory_check_at = next_scan_at

        while True:
            try:
                now = time.monotonic()
                if now >= next_scan_at:
                    loop_count += 1
                    if loop_count % capture_every_loops == 0:
                        try:
                            from app.shared.process.snapshot_writer import SnapshotWriter

                            writer = SnapshotWriter(self.registry)
                            captured = await asyncio.wait_for(
                                writer.capture_python_processes(
                                    min_memory_mb=0.0,
                                    limit=capture_limit,
                                    captured_by="periodic",
                                ),
                                timeout=capture_timeout,
                            )
                            logger.debug(
                                "[process-watch] periodic capture complete: count=%s loop=%s",
                                captured,
                                loop_count,
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                "[process-watch] periodic capture timeout after %ss", capture_timeout
                            )
                        except Exception as capture_exc:
                            logger.warning(
                                "[process-watch] periodic capture failed: %s", capture_exc
                            )

                    orphans = await self.scan()
                    await self.cleanup(orphans)
                    stale_test_branches = await self.detect_orphan_test_worktrees()
                    if stale_test_branches:
                        await self.cleanup_orphan_test_worktrees(stale_test_branches)
                        WorktreeResidueMonitor.record_cleanup(
                            event_type="orphan_cleanup",
                            branches=stale_test_branches,
                            source="orphan_detector",
                        )
                        logger.info(
                            "[orphan-worktree] cleaned %d stale test worktrees: %s",
                            len(stale_test_branches),
                            ", ".join(stale_test_branches),
                        )
                    WorktreeResidueMonitor.record_scan(
                        self._list_test_worktree_branches(),
                        source="orphan_detector",
                    )
                    next_scan_at = time.monotonic() + scan_interval

                now = time.monotonic()
                if now >= next_memory_check_at:
                    await pressure.check()
                    next_memory_check_at = time.monotonic() + memory_interval
            except asyncio.CancelledError:
                logger.info("OrphanDetector 루프 취소됨")
                raise
            except Exception as exc:
                logger.error("OrphanDetector 루프 오류: %s", exc, exc_info=True)

            sleep_until = min(next_scan_at, next_memory_check_at)
            sleep_for = max(0.05, sleep_until - time.monotonic())
            await asyncio.sleep(sleep_for)
