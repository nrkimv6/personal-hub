"""event_log_tailer — F+G+H+I 도메인: tail state · dedup · 완료 추적 · 파일 폴링

EventService의 유일한 mutable state 집합을 LogTailer 클래스로 응집한다.
- F: tail state 관리 (runner별 파일 offset, inode)
- G: 로그 중복 제거 (fingerprint 기반 sliding window)
- H: 완료 추적 (TTL 기반 인메모리 dict)
- I: 파일 폴링 (LogFileResolver 위임 후 delta read)
"""
import hashlib
import logging
import time
from collections import deque
from pathlib import Path
from typing import Optional

from app.modules.dev_runner.services.completion_reason import (
    is_log_completed_payload as _is_log_completed_payload,
    parse_log_completed_payload as _parse_log_completed_payload,
)
from app.modules.dev_runner.services.event_routing import RUNNER_KEY_PREFIX
from app.modules.dev_runner.services.event_sse import build_log_line_payload as _build_log_line_payload
from app.modules.dev_runner.services.log_file_resolver import LogFileResolver
from app.modules.dev_runner.services.visibility import is_visible_runner

logger = logging.getLogger(__name__)

MAX_FALLBACK_READ_LINES = 400
MAX_FALLBACK_READ_CHARS = 65536
TAIL_STATE_TTL_SEC = 600.0
DEFAULT_DEDUP_WINDOW = 256
COMPLETED_RUNNER_TTL_SEC = 120.0


class LogTailer:
    """runner별 tail state, dedup, 완료 추적, 파일 폴링을 담당하는 상태 컨테이너."""

    def __init__(
        self,
        sync_redis,
        log_file_resolver: LogFileResolver,
        dedup_window: int = DEFAULT_DEDUP_WINDOW,
        tail_state_ttl_sec: float = TAIL_STATE_TTL_SEC,
        completed_runner_ttl_sec: float = COMPLETED_RUNNER_TTL_SEC,
        file_poll_max_lines: int = MAX_FALLBACK_READ_LINES,
        file_poll_max_chars: int = MAX_FALLBACK_READ_CHARS,
    ):
        self._sync = sync_redis
        self._log_file_resolver = log_file_resolver
        self._dedup_window = dedup_window
        self._tail_state_ttl_sec = tail_state_ttl_sec
        self._completed_runner_ttl_sec = completed_runner_ttl_sec
        self._file_poll_max_lines = file_poll_max_lines
        self._file_poll_max_chars = file_poll_max_chars
        # mutable state
        self._runner_tail_state: dict[str, dict] = {}
        self._completed_runners: dict[str, float] = {}

    # ── tail state ───────────────────────────────────────────────────────

    def get_or_create_tail_state(self, runner_id: str) -> dict:
        state = self._runner_tail_state.get(runner_id)
        if state is None:
            state = {
                "path": None,
                "inode": None,
                "offset": 0,
                "recent_fingerprints": deque(maxlen=self._dedup_window),
                "last_seen": time.monotonic(),
            }
            self._runner_tail_state[runner_id] = state
        return state

    def drop_tail_state(self, runner_id: str) -> None:
        self._runner_tail_state.pop(runner_id, None)

    def ensure_tail_state_for_path(self, runner_id: str, path: Path) -> Optional[dict]:
        try:
            stat = path.stat()
        except Exception:
            self.drop_tail_state(runner_id)
            return None

        state = self.get_or_create_tail_state(runner_id)
        now = time.monotonic()
        path_str = str(path)
        inode_sig = (stat.st_dev, stat.st_ino)
        prev_path = state.get("path")
        prev_inode = state.get("inode")
        prev_offset = int(state.get("offset", 0))
        reset_reason: Optional[str] = None

        if prev_path is None and prev_inode is None:
            state["path"] = path_str
            state["inode"] = inode_sig
            state["offset"] = 0
        elif prev_path != path_str:
            state["path"] = path_str
            state["inode"] = inode_sig
            state["offset"] = 0
            state["recent_fingerprints"] = deque(maxlen=self._dedup_window)
            reset_reason = "path_changed"
        elif prev_inode != inode_sig:
            state["inode"] = inode_sig
            state["offset"] = 0
            state["recent_fingerprints"] = deque(maxlen=self._dedup_window)
            reset_reason = "rotate"
        elif stat.st_size < prev_offset:
            state["offset"] = 0
            state["recent_fingerprints"] = deque(maxlen=self._dedup_window)
            reset_reason = "truncate"

        state["last_seen"] = now
        if reset_reason:
            logger.debug(
                "[events-fallback] tail offset reset (runner=%s, reason=%s, from=%s, to=%s)",
                runner_id,
                reset_reason,
                prev_offset,
                state.get("offset"),
            )
        return state

    def cleanup_stale_state(self, visible_runner_ids: set) -> None:
        now = time.monotonic()
        for runner_id, state in list(self._runner_tail_state.items()):
            last_seen = float(state.get("last_seen", 0.0))
            if runner_id not in visible_runner_ids:
                self._runner_tail_state.pop(runner_id, None)
                continue
            if now - last_seen > self._tail_state_ttl_sec:
                self._runner_tail_state.pop(runner_id, None)
        for runner_id, marked_at in list(self._completed_runners.items()):
            if runner_id not in visible_runner_ids:
                self._completed_runners.pop(runner_id, None)
                continue
            if now - marked_at > self._completed_runner_ttl_sec:
                self._completed_runners.pop(runner_id, None)

    # ── 완료 추적 ────────────────────────────────────────────────────────

    def mark_runner_completed(self, runner_id: str) -> None:
        self._completed_runners[runner_id] = time.monotonic()
        self.drop_tail_state(runner_id)

    def is_runner_recently_completed(self, runner_id: str) -> bool:
        marked_at = self._completed_runners.get(runner_id)
        if marked_at is None:
            return False
        if time.monotonic() - marked_at > self._completed_runner_ttl_sec:
            self._completed_runners.pop(runner_id, None)
            return False
        return True

    # ── dedup ────────────────────────────────────────────────────────────

    def _fingerprint_line(self, runner_id: str, line: str) -> str:
        text = str(line or "")
        raw = f"{runner_id}\x00{text}".encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest()[:16]

    def _is_duplicate_log_line(self, runner_id: str, line: str) -> bool:
        state = self.get_or_create_tail_state(runner_id)
        state["last_seen"] = time.monotonic()
        recent = state.get("recent_fingerprints")
        if not isinstance(recent, deque):
            recent = deque(maxlen=self._dedup_window)
            state["recent_fingerprints"] = recent
        fp = self._fingerprint_line(runner_id, line)
        if fp in recent:
            return True
        recent.append(fp)
        return False

    # ── 파일 폴링 ────────────────────────────────────────────────────────

    def poll_runner_log_delta(self, runner_id: str) -> tuple:
        """delta 읽기 결과 `(events, dedup_skipped)` 반환.

        events: list[tuple[event_name, payload]]
        dedup_skipped: int
        """
        dedup_skipped = 0
        try:
            trigger = self._sync.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger")
        except Exception:
            trigger = None
        if not is_visible_runner(trigger, runner_id):
            self.drop_tail_state(runner_id)
            return [], dedup_skipped
        if self.is_runner_recently_completed(runner_id):
            return [], dedup_skipped

        path = self._log_file_resolver.find_current_log(runner_id)
        if path is None or not path.exists():
            self.drop_tail_state(runner_id)
            return [], dedup_skipped

        state = self.ensure_tail_state_for_path(runner_id, path)
        if state is None:
            return [], dedup_skipped

        max_lines = int(self._file_poll_max_lines)
        max_chars = int(self._file_poll_max_chars)
        offset = int(state.get("offset", 0))
        lines_read = 0
        chars_read = 0
        events: list = []
        completed_from_file = False

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                while lines_read < max_lines and chars_read < max_chars:
                    start_pos = handle.tell()
                    raw_line = handle.readline()
                    if raw_line == "":
                        break

                    chars_read += len(raw_line)
                    if chars_read > max_chars and lines_read > 0:
                        handle.seek(start_pos)
                        break

                    line = raw_line.rstrip("\n")
                    if not line:
                        continue
                    lines_read += 1

                    if _is_log_completed_payload(line):
                        status, reason = _parse_log_completed_payload(line)
                        payload = {"runner_id": runner_id, "status": status, "reason": reason}
                        try:
                            error = self._sync.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:error")
                        except Exception:
                            error = None
                        if error:
                            payload["error"] = error
                        events.append(("log_completed", payload))
                        completed_from_file = True
                        break

                    if self._is_duplicate_log_line(runner_id, line):
                        dedup_skipped += 1
                        continue

                    events.append(
                        (
                            "log",
                            {"runner_id": runner_id, "line": _build_log_line_payload(line)},
                        )
                    )

                new_offset = handle.tell()
        except Exception as exc:
            logger.debug("[events-fallback] file poll read failed (runner=%s): %s", runner_id, exc)
            return [], dedup_skipped

        if completed_from_file:
            self.mark_runner_completed(runner_id)
            return events, dedup_skipped

        state["offset"] = int(new_offset)
        state["last_seen"] = time.monotonic()
        if lines_read >= max_lines or chars_read >= max_chars:
            logger.debug(
                "[events-fallback] read cap reached (runner=%s, lines=%s, chars=%s)",
                runner_id,
                lines_read,
                chars_read,
            )
        return events, dedup_skipped

    async def init_offsets_for_active_runners(self, visible_runner_ids) -> None:
        """SSE 연결 시점에 활성 러너의 tail offset을 현재 파일 EOF로 초기화한다."""
        for runner_id in visible_runner_ids:
            try:
                path = self._log_file_resolver.find_current_log(runner_id)
                if path is None:
                    continue
                state = self.ensure_tail_state_for_path(runner_id, path)
                if state is None:
                    continue
                try:
                    state["offset"] = path.stat().st_size
                except Exception as e:
                    logger.warning(
                        "[events-init-offsets] stat 실패 (runner=%s, path=%s): %s",
                        runner_id,
                        path,
                        e,
                    )
            except Exception as e:
                logger.warning("[events-init-offsets] runner=%s 처리 중 예외: %s", runner_id, e)
