"""메모리 압박 감지 및 단계별 대응 모듈.

시스템 가용 메모리를 주기적으로 확인하고, 임계값에 따라 알림/정리/재부팅을 수행한다.

임계값 단계:
    normal    : >= MEMORY_CAUTION_MB (4096 MB)
    caution   : >= MEMORY_WARNING_MB (2048 MB)
    warning   : >= MEMORY_CRITICAL_MB (1024 MB)
    critical  : >= MEMORY_EMERGENCY_MB (512 MB) -> history-only
    emergency : >= MEMORY_FATAL_MB (256 MB)
                >= 500 MB -> history-only
                < 500 MB  -> outbound alert
    fatal     : < MEMORY_FATAL_MB -> outbound alert 유지
"""
import json
import logging
import hashlib
import math
import subprocess
import time
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

from app.core.config import settings

if TYPE_CHECKING:
    from app.shared.process.orphan_detector import OrphanDetector

logger = logging.getLogger(__name__)

_ALERT_COOLDOWN_SEC = 600  # 10분 쿨다운
_SCRIPT_EXTENSIONS = {".py", ".ps1", ".bat", ".cmd"}
_HEAVY_TEST_PROCESS_MB_DEFAULT = 1500.0
_HEAVY_TEST_PROCESS_MB_MIN = 256.0
_PRE_FATAL_REPEAT_WINDOW_SEC = 1800
_PRE_FATAL_REPEAT_ALERT_THRESHOLD = 3
_PRE_FATAL_KILL_REASON = "memory_pressure_pre_fatal"
_MEMORY_PRESSURE_HISTORY_LEVELS = {
    "critical",
    "emergency",
    "fatal",
    "fatal_recovered",
}


def _shorten_path(path: str, max_len: int = 80) -> str:
    """경로가 max_len 초과 시 …\\부모폴더\\파일명 형태로 축약한다."""
    if len(path) <= max_len:
        return path
    p = Path(path)
    return f"…\\{p.parent.name}\\{p.name}"


def _extract_script_path(cmdline: list[str]) -> str | None:
    """python/powershell/cmd 실행 시 스크립트 파일 경로를 추출한다.

    cmdline 인자 중 .py/.ps1/.bat/.cmd 확장자를 가진 첫 번째 인자를 반환한다.
    없으면 None.
    """
    for arg in cmdline:
        try:
            ext = Path(arg).suffix.lower()
            if ext in _SCRIPT_EXTENSIONS:
                return _shorten_path(arg)
        except (ValueError, TypeError):
            continue
    return None


def _extract_test_script_path(cmdline: list[str]) -> str | None:
    """cmdline에서 test_*.py 스크립트 경로를 추출한다."""
    for arg in cmdline:
        try:
            path = Path(arg)
        except (TypeError, ValueError):
            continue
        if path.suffix.lower() == ".py" and path.name.lower().startswith("test_"):
            return str(path)
    return None


def _collect_process_tree() -> dict[int, dict]:
    """시스템 전체 프로세스 정보를 수집한다.

    Returns:
        {pid: {"name", "ppid", "memory_mb", "cmdline_short"}} dict
    """
    tree: dict[int, dict] = {}
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            pid = proc.info["pid"]
            rss = proc.info["memory_info"].rss if proc.info["memory_info"] else 0
            memory_mb = round(rss / (1024 * 1024), 1)

            try:
                ppid = proc.ppid()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                ppid = 0

            try:
                cmdline = proc.cmdline()
                cmdline_short = " ".join(cmdline)[:120]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                cmdline_short = ""

            tree[pid] = {
                "name": proc.info["name"] or "",
                "ppid": ppid,
                "memory_mb": memory_mb,
                "cmdline_short": cmdline_short,
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return tree


def _format_process_tree(tree: dict[int, dict], min_memory_mb: float = 50.0) -> str:
    """프로세스 트리를 indent 텍스트로 포맷한다.

    메모리 min_memory_mb 미만이고 자식 중 해당 임계값 이상인 것이 없으면 생략.

    Args:
        tree: _collect_process_tree() 반환값
        min_memory_mb: 표시 최소 메모리 임계값 (MB)

    Returns:
        indent 기반 트리 문자열
    """
    if not tree:
        return "(프로세스 정보 없음)"

    # children 매핑 구성
    children: dict[int, list[int]] = {}
    for pid, info in tree.items():
        ppid = info["ppid"]
        children.setdefault(ppid, []).append(pid)

    # 서브트리 내 최대 메모리 캐시 (부모 표시 여부 결정용)
    def max_subtree_memory(pid: int) -> float:
        mem = tree.get(pid, {}).get("memory_mb", 0.0)
        for child_pid in children.get(pid, []):
            mem = max(mem, max_subtree_memory(child_pid))
        return mem

    lines: list[str] = []

    def visit(pid: int, depth: int) -> None:
        info = tree.get(pid)
        if info is None:
            return
        # 서브트리 최대 메모리가 임계값 미만이면 생략
        if max_subtree_memory(pid) < min_memory_mb:
            return
        indent = "  " * depth
        name = info["name"]
        mem = info["memory_mb"]
        cmd = info["cmdline_short"]
        cmd_part = f" {cmd}" if cmd and cmd != name else ""
        lines.append(f"{indent}PID={pid} {name} {mem}MB{cmd_part}")
        for child_pid in sorted(children.get(pid, [])):
            visit(child_pid, depth + 1)

    # 루트: ppid가 tree에 없는 프로세스
    roots = [pid for pid, info in tree.items() if info["ppid"] not in tree]
    for root_pid in sorted(roots):
        visit(root_pid, 0)

    return "\n".join(lines) if lines else "(50MB 이상 프로세스 없음)"


def _resolve_events_log_path() -> Path:
    """메모리 압박 이벤트 JSONL 경로를 반환한다."""
    return Path(__file__).resolve().parents[3] / "logs" / "memory_pressure_events.jsonl"


def _excerpt_process_tree(tree_text: str, max_lines: int = 80) -> str:
    """프로세스 트리 전문을 목록 화면용 excerpt로 잘라낸다."""
    if not tree_text:
        return ""
    lines = tree_text.splitlines()
    if len(lines) <= max_lines:
        return tree_text
    omitted = len(lines) - max_lines
    return "\n".join(lines[:max_lines]) + f"\n... (+{omitted} lines)"


def _normalize_history_levels(levels: list[str] | None) -> set[str] | None:
    """history 필터 값을 소문자 set으로 정규화한다."""
    if not levels:
        return None
    normalized: set[str] = set()
    for raw in levels:
        for part in str(raw).split(","):
            value = part.strip().lower()
            if value:
                normalized.add(value)
    return normalized or None


def read_persisted_history(
    limit: int,
    levels: list[str] | None = None,
    since_hours: int | None = None,
) -> dict:
    """메모리 압박 JSONL 히스토리를 newest-first 형태로 읽는다."""
    log_path = _resolve_events_log_path()
    normalized_levels = _normalize_history_levels(levels)
    cutoff = datetime.now() - timedelta(hours=since_hours) if since_hours is not None else None
    items: deque[dict] = deque(maxlen=max(1, limit))
    summary = Counter()
    total = 0

    if not log_path.exists():
        return {
            "total": 0,
            "summary": {
                "total": 0,
                "critical": 0,
                "emergency": 0,
                "fatal": 0,
                "fatal_recovered": 0,
            },
            "items": [],
        }

    with log_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            level = str(record.get("level") or "").strip().lower()
            if level not in _MEMORY_PRESSURE_HISTORY_LEVELS:
                continue
            if normalized_levels is not None and level not in normalized_levels:
                continue

            timestamp = record.get("timestamp")
            if cutoff is not None:
                try:
                    record_time = datetime.fromisoformat(str(timestamp))
                except (TypeError, ValueError):
                    continue
                if record_time < cutoff:
                    continue

            try:
                available_mb = float(record.get("available_mb") or 0.0)
            except (TypeError, ValueError):
                continue

            top_processes = record.get("top_processes")
            if not isinstance(top_processes, list):
                top_processes = []

            process_tree = record.get("process_tree")
            items.append(
                {
                    "timestamp": str(timestamp or ""),
                    "level": level,
                    "available_mb": round(available_mb, 1),
                    "top_processes": top_processes,
                    "process_tree_excerpt": _excerpt_process_tree(str(process_tree or "")),
                }
            )
            total += 1
            summary[level] += 1

    ordered_items = list(reversed(items))
    return {
        "total": total,
        "summary": {
            "total": total,
            "critical": summary.get("critical", 0),
            "emergency": summary.get("emergency", 0),
            "fatal": summary.get("fatal", 0),
            "fatal_recovered": summary.get("fatal_recovered", 0),
        },
        "items": ordered_items,
    }


class MemoryPressureResponder:
    """시스템 메모리 압박을 감지하고 단계별 대응을 수행한다."""

    def __init__(self, orphan_detector: "OrphanDetector") -> None:
        self.orphan_detector = orphan_detector
        self._last_alert_time: dict[str, float] = {}  # 단계명 → 최종 알림 시각
        self._fatal_triggered: bool = False
        self._pre_fatal_recovery_times: deque[float] = deque()

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

    def _should_notify_outbound(self, available_mb: float) -> bool:
        """500MB 미만에서만 outbound 알림을 허용한다."""
        return available_mb < float(getattr(settings, "MEMORY_PRESSURE_OUTBOUND_ALERT_MAX_MB", 500))

    def _record_alert(self, level: str) -> None:
        """알림 시각을 기록한다."""
        self._last_alert_time[level] = time.time()

    def _resolve_heavy_test_threshold_mb(self) -> float:
        """pre-fatal 완화 후보 선별 임계값을 정규화한다."""
        raw_value = settings.MEMORY_HEAVY_TEST_PROCESS_MB
        try:
            threshold_mb = float(raw_value)
        except (TypeError, ValueError):
            logger.warning(
                "[memory-pressure] event=pre_fatal_threshold_invalid raw=%r fallback=%.1f",
                raw_value,
                _HEAVY_TEST_PROCESS_MB_DEFAULT,
            )
            return _HEAVY_TEST_PROCESS_MB_DEFAULT

        if not math.isfinite(threshold_mb):
            logger.warning(
                "[memory-pressure] event=pre_fatal_threshold_invalid raw=%r fallback=%.1f",
                raw_value,
                _HEAVY_TEST_PROCESS_MB_DEFAULT,
            )
            return _HEAVY_TEST_PROCESS_MB_DEFAULT

        if threshold_mb < _HEAVY_TEST_PROCESS_MB_MIN:
            logger.warning(
                "[memory-pressure] event=pre_fatal_threshold_clamped raw=%.1f clamp=%.1f",
                threshold_mb,
                _HEAVY_TEST_PROCESS_MB_MIN,
            )
            return _HEAVY_TEST_PROCESS_MB_MIN

        return threshold_mb

    def _record_pre_fatal_action(
        self,
        *,
        target: dict,
        result: str,
        available_before_mb: float,
        available_after_mb: float | None = None,
        detail: str = "",
    ) -> None:
        """pre-fatal 완화 조치를 process-watch action 로그에 남긴다."""
        registry = getattr(self.orphan_detector, "registry", None)
        if registry is None:
            return

        try:
            from app.shared.process.snapshot_writer import PRE_FATAL_KILL_ACTION, SnapshotWriter

            writer = SnapshotWriter(registry)
            detail_parts = [
                f"available_before_mb={available_before_mb:.1f}",
                f"threshold_mb={float(target.get('threshold_mb', 0.0)):.1f}",
                f"script_path={target.get('script_path') or ''}",
            ]
            if available_after_mb is not None:
                detail_parts.append(f"available_after_mb={available_after_mb:.1f}")
            if detail:
                detail_parts.append(detail)
            writer.record_kill_action(
                action=PRE_FATAL_KILL_ACTION,
                pid=int(target["pid"]),
                cmdline_hash=str(target.get("cmdline_hash") or ""),
                reason=_PRE_FATAL_KILL_REASON,
                actor="memory_pressure",
                result=result,
                detail=" ".join(part for part in detail_parts if part),
            )
        except Exception as exc:
            logger.warning(
                "[memory-pressure] event=pre_fatal_action_log_failed pid=%s reason=%s",
                target.get("pid"),
                exc,
            )

    def _register_pre_fatal_recovery(self) -> dict[str, object]:
        """짧은 시간 내 반복되는 pre-fatal 복구 상태를 기록한다."""
        now = time.time()
        cutoff = now - _PRE_FATAL_REPEAT_WINDOW_SEC
        while self._pre_fatal_recovery_times and self._pre_fatal_recovery_times[0] < cutoff:
            self._pre_fatal_recovery_times.popleft()
        self._pre_fatal_recovery_times.append(now)

        count = len(self._pre_fatal_recovery_times)
        last_recovered_at = datetime.fromtimestamp(now).isoformat(timespec="seconds")
        if count > 1:
            logger.warning(
                "[memory-pressure] event=pre_fatal_repeat count=%s window_sec=%s last_recovered_at=%s",
                count,
                _PRE_FATAL_REPEAT_WINDOW_SEC,
                last_recovered_at,
            )
        return {
            "repeat_count": count,
            "last_recovered_at": last_recovered_at,
            "repeat_active": count >= _PRE_FATAL_REPEAT_ALERT_THRESHOLD,
        }

    def _attempt_pre_fatal_mitigation(self, available_mb: float) -> tuple[bool, float, list[dict]]:
        """fatal 직전 단일 고메모리 test_*.py 프로세스를 선제 종료한다.

        Returns:
            (recovered, available_after_mb, killed_processes)
        """
        heavy_threshold_mb = self._resolve_heavy_test_threshold_mb()
        candidates: list[dict] = []
        for proc in psutil.process_iter(["pid", "name", "memory_info", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                script_path = _extract_test_script_path(cmdline)
                if not script_path:
                    continue
                rss = proc.info["memory_info"].rss if proc.info["memory_info"] else 0
                memory_mb = round(rss / (1024 * 1024), 1)
                if memory_mb < heavy_threshold_mb:
                    continue
                candidates.append(
                    {
                        "pid": int(proc.info["pid"]),
                        "name": proc.info.get("name") or "",
                        "script_path": script_path,
                        "memory_mb": memory_mb,
                        "cmdline_hash": hashlib.sha256(
                            " ".join(str(part) for part in cmdline if part).strip().encode(
                                "utf-8",
                                errors="ignore",
                            )
                        ).hexdigest()[:32],
                        "threshold_mb": heavy_threshold_mb,
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
                continue

        if not candidates:
            return False, available_mb, []

        candidates.sort(key=lambda item: item["memory_mb"], reverse=True)
        target = candidates[0]
        target_pid = target["pid"]
        try:
            process = psutil.Process(target_pid)
            process.terminate()
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired) as exc:
            logger.warning(
                "[memory-pressure] event=pre_fatal_mitigation result=failed pid=%s reason=%s",
                target_pid,
                exc,
            )
            self._record_pre_fatal_action(
                target=target,
                result="failed",
                available_before_mb=available_mb,
                detail=f"error={exc}",
            )
            return False, available_mb, []

        # RSS 회수 지연을 감안해 짧게 대기 후 재측정
        time.sleep(1.0)
        available_after_mb = psutil.virtual_memory().available / (1024 * 1024)
        recovered = available_after_mb >= settings.MEMORY_FATAL_MB
        logger.warning(
            "[memory-pressure] event=pre_fatal_mitigation result=success pid=%s script=%s "
            "rss=%.1fMB threshold=%.1fMB available_before=%.1fMB available_after=%.1fMB recovered=%s",
            target["pid"],
            target["script_path"],
            target["memory_mb"],
            heavy_threshold_mb,
            available_mb,
            available_after_mb,
            recovered,
        )
        self._record_pre_fatal_action(
            target=target,
            result="success",
            available_before_mb=available_mb,
            available_after_mb=available_after_mb,
            detail=f"recovered={recovered}",
        )
        return recovered, available_after_mb, [target]

    def _get_top_processes(self, n: int = 5) -> list[dict]:
        """메모리 사용량 상위 n개 프로세스를 반환한다.

        반환 dict 필드:
            pid, name, memory_mb, script_path, ppid, parent_name, ppid_alive,
            grandparent_pid, grandparent_name, is_orphan
        """
        orphan_pids: set[int] = set(self.orphan_detector._orphan_first_seen.keys())

        procs = []
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                rss = proc.info["memory_info"].rss if proc.info["memory_info"] else 0
                pid = proc.info["pid"]

                # cmdline — AccessDenied 가능
                try:
                    cmdline = proc.cmdline()
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    cmdline = []

                script_path = _extract_script_path(cmdline)

                # 부모 프로세스 정보
                try:
                    ppid = proc.ppid()
                    ppid_alive = psutil.pid_exists(ppid)
                    try:
                        parent_name = psutil.Process(ppid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        parent_name = "?"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    ppid = None
                    ppid_alive = False
                    parent_name = "?"

                # 조부모 프로세스 정보
                grandparent_pid: int | None = None
                grandparent_name: str = "?"
                if ppid is not None:
                    try:
                        grandparent_pid = psutil.Process(ppid).ppid()
                        try:
                            grandparent_name = psutil.Process(grandparent_pid).name()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            grandparent_name = "?"
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        grandparent_pid = None

                is_orphan = pid in orphan_pids or (ppid is not None and not ppid_alive)

                procs.append({
                    "pid": pid,
                    "name": proc.info["name"],
                    "memory_mb": round(rss / (1024 * 1024), 1),
                    "script_path": script_path,
                    "ppid": ppid,
                    "parent_name": parent_name,
                    "ppid_alive": ppid_alive,
                    "grandparent_pid": grandparent_pid,
                    "grandparent_name": grandparent_name,
                    "is_orphan": is_orphan,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        return procs[:n]

    def _format_process_detail(self, proc: dict) -> str:
        """프로세스 정보를 한 줄 문자열로 포맷한다.

        예시:
            PID=1234 python.exe [app\\worker\\orchestrator.py] 512.0MB | parent: browser_workers.py(PID=5678, alive) ← WindowsTerminal(PID=100) | orphan: NO
        """
        name = proc.get("name", "?")
        pid = proc.get("pid", "?")
        memory_mb = proc.get("memory_mb", 0)
        script_path = proc.get("script_path")
        ppid = proc.get("ppid", "?")
        parent_name = proc.get("parent_name", "?")
        ppid_alive = proc.get("ppid_alive", False)
        grandparent_pid = proc.get("grandparent_pid")
        grandparent_name = proc.get("grandparent_name", "?")
        is_orphan = proc.get("is_orphan", False)

        name_part = f"{name} [{script_path}]" if script_path else name
        parent_alive_str = "alive" if ppid_alive else "dead"
        orphan_str = "YES" if is_orphan else "NO"

        grandparent_str = ""
        if grandparent_pid is not None:
            grandparent_str = f" ← {grandparent_name}(PID={grandparent_pid})"

        return (
            f"  PID={pid} {name_part} {memory_mb}MB"
            f" | parent: {parent_name}(PID={ppid}, {parent_alive_str}){grandparent_str}"
            f" | orphan: {orphan_str}"
        )

    def _format_top_processes(self, n: int = 5) -> str:
        """상위 n개 프로세스의 상세 정보를 줄바꿈으로 연결하여 반환한다."""
        procs = self._get_top_processes(n)
        return "\n".join(self._format_process_detail(p) for p in procs)

    def _persist_snapshot(
        self,
        level: str,
        available_mb: float,
        top_procs: list[dict],
        tree_text: str,
        extra: dict | None = None,
    ) -> None:
        """메모리 압박 스냅샷을 재부팅에도 유실되지 않는 영속 파일에 기록한다.

        파일: logs/memory_pressure_events.jsonl (JSONL append)
        예외 발생 시 경고 로그만 출력하고 절대 전파하지 않는다.
        """
        try:
            log_path = _resolve_events_log_path()
            log_dir = log_path.parent
            log_dir.mkdir(parents=True, exist_ok=True)

            record = {
                "timestamp": datetime.now().isoformat(),
                "level": level,
                "available_mb": round(available_mb, 1),
                "top_processes": top_procs,
                "process_tree": tree_text,
            }
            if extra:
                record.update(extra)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
        except Exception as exc:
            logger.warning("영속 스냅샷 기록 실패: %s", exc)

    async def _send_telegram(self, message: str) -> None:
        """Telegram 알림을 전송한다. 실패 시 경고 로그."""
        try:
            from app.shared.notification.notification_service import NotificationService
            await NotificationService().send_telegram(message)
        except Exception as exc:
            logger.warning("Telegram 알림 전송 실패: %s", exc)

    async def _on_caution(self, available_mb: float) -> None:
        """주의 단계 대응 — 로그만 (1GB 이상이므로 Telegram 알림 없음)."""
        if not self._should_alert("caution"):
            return
        top5 = self._get_top_processes(5)
        top5_str = ", ".join(f"{p['name']}({p['memory_mb']}MB)" for p in top5)
        msg = (
            f"⚠️ 시스템 메모리 주의: {available_mb/1024:.1f}GB 남음\n"
            f"상위 프로세스: {top5_str}"
        )
        logger.warning(msg)
        self._record_alert("caution")

    async def _on_warning(self, available_mb: float) -> None:
        """경고 단계 대응 — 고아 프로세스 정리 + 상세 프로세스 로그."""
        if not self._should_alert("warning"):
            return
        detail = self._format_top_processes(5)
        msg = (
            f"🔶 시스템 메모리 경고: {available_mb/1024:.1f}GB 남음\n"
            f"고아 프로세스 정리 실행...\n"
            f"상위 프로세스:\n{detail}"
        )
        logger.warning(msg)
        self._record_alert("warning")

        orphans = await self.orphan_detector.scan()
        await self.orphan_detector.cleanup(orphans)

    async def _on_critical(self, available_mb: float) -> None:
        """위험 단계 대응 — 강제 고아 정리 + 상세 프로세스 로그."""
        detail = self._format_top_processes(5)
        msg = (
            f"🔴 시스템 메모리 위험: {available_mb:.0f}MB 남음\n"
            f"강제 고아 정리 실행 (history-only)\n"
            f"상위 프로세스:\n{detail}"
        )
        logger.error(msg)
        top5 = self._get_top_processes(5)
        tree_text = _format_process_tree(_collect_process_tree())
        self._persist_snapshot("critical", available_mb, top5, tree_text)

        orphans = await self.orphan_detector.scan()
        await self.orphan_detector.cleanup(orphans, force=True)
        logger.warning(
            "[memory-pressure] outbound_suppressed level=critical available_mb=%.1f",
            available_mb,
        )
        logger.error("메모리 위험 — 워커 재시작이 필요할 수 있습니다.")

    async def _on_emergency(self, available_mb: float) -> None:
        """긴급 단계 대응 — 강제 정리 + 데스크톱 알림 + 상세 프로세스 로그."""
        detail = self._format_top_processes(5)
        msg = (
            f"🚨 메모리 긴급: {available_mb:.0f}MB 남음! 즉각 조치 필요\n"
            f"상위 프로세스:\n{detail}"
        )
        logger.critical(msg)
        top5 = self._get_top_processes(5)
        tree_text = _format_process_tree(_collect_process_tree())
        self._persist_snapshot("emergency", available_mb, top5, tree_text)

        orphans = await self.orphan_detector.scan()
        await self.orphan_detector.cleanup(orphans, force=True)

        if not self._should_notify_outbound(available_mb):
            logger.warning(
                "[memory-pressure] outbound_suppressed level=emergency available_mb=%.1f",
                available_mb,
            )
            return
        if not self._should_alert("emergency"):
            logger.warning(
                "[memory-pressure] outbound_suppressed level=emergency available_mb=%.1f reason=cooldown",
                available_mb,
            )
            return

        await self._send_telegram(msg)
        self._record_alert("emergency")

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
        """치명 단계 대응 — 프로세스 트리 기록 후 Telegram 알림 + 강제 재부팅 (1회만)."""
        if not self._should_alert("fatal"):
            return

        recovered, available_after_mb, killed = self._attempt_pre_fatal_mitigation(available_mb)
        if recovered:
            top10 = self._get_top_processes(10)
            tree = _collect_process_tree()
            tree_text = _format_process_tree(tree)
            threshold_mb = self._resolve_heavy_test_threshold_mb()
            repeat_meta = self._register_pre_fatal_recovery()
            self._persist_snapshot(
                "fatal_recovered",
                available_after_mb,
                top10,
                tree_text,
                extra={
                    "mitigation": {
                        "available_before_mb": round(available_mb, 1),
                        "available_after_mb": round(available_after_mb, 1),
                        "threshold_mb": round(threshold_mb, 1),
                        "killed_targets": killed,
                        "repeat_count": repeat_meta["repeat_count"],
                        "last_recovered_at": repeat_meta["last_recovered_at"],
                    }
                },
            )
            killed_summary = ", ".join(
                f"PID={p['pid']} {p['script_path']}({p['memory_mb']}MB)" for p in killed
            )
            repeat_notice = ""
            if repeat_meta["repeat_active"]:
                repeat_notice = (
                    f"\n반복 완화: {_PRE_FATAL_REPEAT_WINDOW_SEC // 60}분 내 "
                    f"{repeat_meta['repeat_count']}회 (최근 {repeat_meta['last_recovered_at']})"
                )
            msg = (
                f"🟠 재부팅 보류: fatal 직전 고메모리 테스트 프로세스 선제 종료 후 복구 "
                f"({available_mb:.0f}MB -> {available_after_mb:.0f}MB)\n"
                f"종료 대상: {killed_summary or '(없음)'}"
                f"{repeat_notice}"
            )
            logger.critical(msg)
            await self._send_telegram(msg)
            return

        fatal_available_mb = available_after_mb

        # 재부팅 전 프로세스 트리 수집 + 영속 기록 (먼저 실행)
        top10 = self._get_top_processes(10)
        detail = "\n".join(self._format_process_detail(p) for p in top10)
        tree = _collect_process_tree()
        tree_text = _format_process_tree(tree)
        self._persist_snapshot("fatal", fatal_available_mb, top10, tree_text)
        logger.critical("재부팅 전 상위 프로세스:\n%s", detail)
        logger.critical("프로세스 트리:\n%s", tree_text)

        msg = (
            f"🔴 강제 재부팅: 메모리 {fatal_available_mb:.0f}MB 미만 — 30초 후 재부팅\n"
            f"상위 프로세스:\n{detail}"
        )
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
                f"메모리 부족 자동 재부팅 ({fatal_available_mb:.0f}MB 미만)",
            ],
            check=False,
        )
