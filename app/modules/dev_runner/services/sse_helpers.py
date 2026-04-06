"""SSE pubsub 공통 헬퍼 — Redis Pub/Sub 정리 로직 + SSE framing 유틸"""

import os
import re
from typing import Optional


async def safe_close_pubsub(pubsub) -> None:
    """Redis pubsub 안전 정리: punsubscribe → aclose, fallback close"""
    if pubsub is None:
        return
    try:
        await pubsub.unsubscribe()
        await pubsub.punsubscribe()
        await pubsub.aclose()
    except AttributeError:
        try:
            await pubsub.close()
        except Exception:
            pass
    except Exception:
        pass


# SSE framing 상수
MAX_SSE_FRAME_CHARS = 8192
MULTILINE_FRAME_ENV = "DEV_RUNNER_MULTILINE_FRAME"
_TIMESTAMP_TAG_START_RE = re.compile(r"^\s*\[\d{2}:\d{2}:\d{2}\]\s*\[[^\]]+\]\s*")
_MERGE_TAG_START_RE = re.compile(r"^\s*\[MERGE\]\[[^\]]+\]\s*")
_GENERIC_TAG_START_RE = re.compile(r"^\s*\[[A-Z][A-Z0-9_-]{1,24}\](?:\[[A-Z0-9_-]{1,24}\])?\s*")


def _is_multiline_frame_enabled() -> bool:
    raw = os.getenv(MULTILINE_FRAME_ENV)
    if raw is None:
        return True
    value = str(raw).strip().lower()
    if value in {"1", "true", "on", "yes", "y"}:
        return True
    if value in {"0", "false", "off", "no", "n"}:
        return False
    return True


def _normalize_newlines(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _truncate_sse_payload(payload: str, max_chars: int = MAX_SSE_FRAME_CHARS) -> str:
    normalized = _normalize_newlines(payload)
    if len(normalized) <= max_chars:
        return normalized
    hidden = len(normalized) - max_chars
    return f"{normalized[:max_chars]}\n… {hidden} chars truncated"


def _format_sse_data(data: str, event: Optional[str] = None) -> str:
    """멀티라인 안전 SSE 직렬화.

    SSE 규격상 data 라인이 여러 줄이면 각 줄 앞에 `data:` 접두사를 반복해야 한다.
    """
    payload = _truncate_sse_payload(data)
    lines = payload.split("\n")
    prefix = f"event: {event}\n" if event else ""
    data_block = "".join(f"data: {line}\n" for line in lines)
    return f"{prefix}{data_block}\n"


def _is_frame_start(line: str) -> bool:
    if not line:
        return False
    return bool(
        _TIMESTAMP_TAG_START_RE.match(line)
        or _MERGE_TAG_START_RE.match(line)
        or _GENERIC_TAG_START_RE.match(line)
    )


class _PollFrameBuffer:
    """파일 폴링 fallback에서 물리 라인을 논리 프레임으로 묶는다."""

    def __init__(self, max_chars: int = MAX_SSE_FRAME_CHARS):
        self._lines: list[str] = []
        self._char_count = 0
        self._max_chars = max_chars

    def push_line(self, line: str) -> tuple[list[str], bool]:
        text = (line or "").rstrip("\n")
        if not text:
            return [], False

        ready: list[str] = []
        if self._lines and _is_frame_start(text):
            flushed = self.flush()
            if flushed:
                ready.append(flushed)

        self._append(text)

        overflow = False
        if self._char_count >= self._max_chars:
            overflow = True
            flushed = self.flush()
            if flushed:
                ready.append(flushed)
        return ready, overflow

    def flush(self) -> Optional[str]:
        if not self._lines:
            return None
        msg = "\n".join(self._lines)
        self._lines = []
        self._char_count = 0
        return msg

    def _append(self, line: str) -> None:
        if self._lines:
            self._char_count += 1
        self._lines.append(line)
        self._char_count += len(line)


__all__ = [
    "safe_close_pubsub",
    "MAX_SSE_FRAME_CHARS",
    "MULTILINE_FRAME_ENV",
    "_is_multiline_frame_enabled",
    "_normalize_newlines",
    "_truncate_sse_payload",
    "_format_sse_data",
    "_is_frame_start",
    "_PollFrameBuffer",
]
