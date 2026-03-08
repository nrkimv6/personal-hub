"""메모리 압박 감지 및 단계별 대응 모듈.

시스템 가용 메모리를 주기적으로 확인하고, 임계값에 따라 알림/정리/재부팅을 수행한다.

임계값 단계:
    normal    : >= MEMORY_CAUTION_MB (4096 MB)
    caution   : >= MEMORY_WARNING_MB (2048 MB)
    warning   : >= MEMORY_CRITICAL_MB (1024 MB)
    critical  : >= MEMORY_EMERGENCY_MB (512 MB)
    emergency : >= MEMORY_FATAL_MB (256 MB)
    fatal     : < MEMORY_FATAL_MB
"""
import logging
import subprocess
import time
from typing import TYPE_CHECKING

import psutil

from app.core.config import settings

if TYPE_CHECKING:
    from app.shared.process.orphan_detector import OrphanDetector

logger = logging.getLogger(__name__)

_ALERT_COOLDOWN_SEC = 600  # 10분 쿨다운


class MemoryPressureResponder:
    """시스템 메모리 압박을 감지하고 단계별 대응을 수행한다."""

    def __init__(self, orphan_detector: "OrphanDetector") -> None:
        self.orphan_detector = orphan_detector
        self._last_alert_time: dict[str, float] = {}  # 단계명 → 최종 알림 시각
        self._fatal_triggered: bool = False

    async def check(self) -> str:
        """현재 가용 메모리를 확인하고 단계를 판정하여 대응한다.

        Returns:
            단계 이름 ("normal"/"caution"/"warning"/"critical"/"emergency"/"fatal")
        """
        available_bytes = psutil.virtual_memory().available
        available_mb = available_bytes / (1024 * 1024)

        if available_mb >= settings.MEMORY_CAUTION_MB:
            return "normal"
        elif available_mb >= settings.MEMORY_WARNING_MB:
            await self._on_caution(available_mb)
            return "caution"
        elif available_mb >= settings.MEMORY_CRITICAL_MB:
            await self._on_warning(available_mb)
            return "warning"
        elif available_mb >= settings.MEMORY_EMERGENCY_MB:
            await self._on_critical(available_mb)
            return "critical"
        elif available_mb >= settings.MEMORY_FATAL_MB:
            await self._on_emergency(available_mb)
            return "emergency"
        else:
            await self._on_fatal(available_mb)
            return "fatal"

    def _should_alert(self, level: str) -> bool:
        """해당 단계의 알림을 보낼 수 있는지 확인한다 (쿨다운 적용)."""
        if level == "fatal":
            if self._fatal_triggered:
                return False
            return True

        last = self._last_alert_time.get(level, 0.0)
        if time.time() - last < _ALERT_COOLDOWN_SEC:
            return False
        return True

    def _record_alert(self, level: str) -> None:
        """알림 시각을 기록한다."""
        self._last_alert_time[level] = time.time()

    def _get_top_processes(self, n: int = 5) -> list[dict]:
        """메모리 사용량 상위 n개 프로세스를 반환한다."""
        procs = []
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                rss = proc.info["memory_info"].rss if proc.info["memory_info"] else 0
                procs.append({
                    "pid": proc.info["pid"],
                    "name": proc.info["name"],
                    "memory_mb": round(rss / (1024 * 1024), 1),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        return procs[:n]

    async def _send_telegram(self, message: str) -> None:
        """Telegram 알림을 전송한다. 실패 시 경고 로그."""
        try:
            from app.shared.notification.notification_service import NotificationService
            await NotificationService().send_telegram(message)
        except Exception as exc:
            logger.warning("Telegram 알림 전송 실패: %s", exc)

    async def _on_caution(self, available_mb: float) -> None:
        """주의 단계 대응."""
        if not self._should_alert("caution"):
            return
        top5 = self._get_top_processes(5)
        top5_str = ", ".join(f"{p['name']}({p['memory_mb']}MB)" for p in top5)
        msg = (
            f"⚠️ 시스템 메모리 주의: {available_mb/1024:.1f}GB 남음\n"
            f"상위 프로세스: {top5_str}"
        )
        logger.warning(msg)
        await self._send_telegram(msg)
        self._record_alert("caution")

    async def _on_warning(self, available_mb: float) -> None:
        """경고 단계 대응 — 고아 프로세스 정리."""
        if not self._should_alert("warning"):
            return
        top5 = self._get_top_processes(5)
        top5_str = ", ".join(f"{p['name']}({p['memory_mb']}MB)" for p in top5)
        msg = (
            f"🔶 시스템 메모리 경고: {available_mb/1024:.1f}GB 남음\n"
            f"고아 프로세스 정리 실행...\n상위: {top5_str}"
        )
        logger.warning(msg)
        await self._send_telegram(msg)
        self._record_alert("warning")

        orphans = await self.orphan_detector.scan()
        await self.orphan_detector.cleanup(orphans)

    async def _on_critical(self, available_mb: float) -> None:
        """위험 단계 대응 — 강제 고아 정리."""
        if not self._should_alert("critical"):
            return
        msg = (
            f"🔴 시스템 메모리 위험: {available_mb:.0f}MB 남음\n"
            f"강제 고아 정리 실행"
        )
        logger.error(msg)
        await self._send_telegram(msg)
        self._record_alert("critical")

        orphans = await self.orphan_detector.scan()
        await self.orphan_detector.cleanup(orphans, force=True)
        logger.error("메모리 위험 — 워커 재시작이 필요할 수 있습니다.")

    async def _on_emergency(self, available_mb: float) -> None:
        """긴급 단계 대응 — 강제 정리 + 데스크톱 알림."""
        if not self._should_alert("emergency"):
            return
        msg = f"🚨 메모리 긴급: {available_mb:.0f}MB 남음! 즉각 조치 필요"
        logger.critical(msg)
        await self._send_telegram(msg)
        self._record_alert("emergency")

        orphans = await self.orphan_detector.scan()
        await self.orphan_detector.cleanup(orphans, force=True)

        # 데스크톱 팝업
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-Command",
                    f"[System.Windows.Forms.MessageBox]::Show("
                    f"'메모리 부족 경고: {available_mb:.0f}MB 남음', "
                    f"'시스템 경고', 'OK', 'Warning')",
                ],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as exc:
            logger.warning("데스크톱 알림 실패: %s", exc)

    async def _on_fatal(self, available_mb: float) -> None:
        """치명 단계 대응 — Telegram 알림 후 강제 재부팅 (1회만)."""
        if not self._should_alert("fatal"):
            return
        msg = f"🔴 강제 재부팅: 메모리 {available_mb:.0f}MB 미만 — 30초 후 재부팅"
        logger.critical(msg)
        await self._send_telegram(msg)
        self._fatal_triggered = True

        subprocess.run(
            [
                "shutdown",
                "/r",
                "/t",
                "30",
                "/c",
                f"메모리 부족 자동 재부팅 ({available_mb:.0f}MB 미만)",
            ],
            check=False,
        )
