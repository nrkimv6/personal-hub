"""고아 프로세스 감지 및 정리 모듈.

부모 프로세스가 죽었지만 자식 프로세스가 살아있는 경우(고아 프로세스)를
감지하고, grace period 경과 후 자동으로 정리한다.
"""
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

from app.shared.process.registry import ProcessRegistry

if TYPE_CHECKING:
    pass

# kill_pid 동적 임포트 (scripts/service_utils.py)
def kill_pid(pid: int, timeout: int = 5) -> bool:
    """scripts.service_utils.kill_pid 위임 래퍼."""
    try:
        scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from service_utils import kill_pid as _kp  # type: ignore
        return _kp(pid, timeout)
    except Exception as exc:
        import logging as _l
        _l.getLogger(__name__).warning("kill_pid 실패 (pid=%s): %s", pid, exc)
        return False

logger = logging.getLogger(__name__)


class OrphanDetector:
    """고아 프로세스 감지 및 정리 클래스."""

    def __init__(self, registry: ProcessRegistry, grace_period: int = 30) -> None:
        """초기화.

        Args:
            registry: ProcessRegistry 인스턴스
            grace_period: 고아 감지 후 정리까지 대기 시간 (초)
        """
        self.registry = registry
        self.grace_period = grace_period
        self._orphan_first_seen: dict[int, float] = {}  # pid → 최초 감지 시각

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

    async def cleanup(self, orphans: list[dict], force: bool = False) -> list[dict]:
        """고아 프로세스를 정리한다.

        Args:
            orphans: scan()에서 반환된 고아 프로세스 리스트
            force: True면 grace period 무시하고 즉시 정리

        Returns:
            실제로 정리된 프로세스 정보 리스트
        """
        # 순환 import 방지를 위해 지연 임포트
        from scripts.service_utils import kill_pid  # type: ignore

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

    async def run_periodic(self, interval: int = 60) -> None:
        """주기적으로 고아 프로세스를 스캔하고 정리한다.

        Args:
            interval: 스캔 주기 (초)
        """
        # MemoryPressureResponder는 지연 임포트 (순환 방지)
        from app.shared.process.memory_pressure import MemoryPressureResponder

        pressure = MemoryPressureResponder(self)

        while True:
            try:
                orphans = await self.scan()
                await self.cleanup(orphans)
                await pressure.check()
            except asyncio.CancelledError:
                logger.info("OrphanDetector 루프 취소됨")
                raise
            except Exception as exc:
                logger.error("OrphanDetector 루프 오류: %s", exc, exc_info=True)

            await asyncio.sleep(interval)
