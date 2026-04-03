"""dev-runner 로그 멀티라인 프레이밍 공통 유틸."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple


_TIMESTAMP_TAG_START_RE = re.compile(r"^\s*\[\d{2}:\d{2}:\d{2}\]\s*\[[^\]]+\]\s*")
_MERGE_TAG_START_RE = re.compile(r"^\s*\[MERGE\]\[[^\]]+\]\s*")
_GENERIC_TAG_START_RE = re.compile(r"^\s*\[[A-Z][A-Z0-9_-]{1,24}\](?:\[[A-Z0-9_-]{1,24}\])?\s*")


def is_frame_start(line: str) -> bool:
    """새 로그 프레임 시작 라인인지 판별."""
    if not line:
        return False
    return bool(
        _TIMESTAMP_TAG_START_RE.match(line)
        or _MERGE_TAG_START_RE.match(line)
        or _GENERIC_TAG_START_RE.match(line)
    )


class MultilineFrameBuffer:
    """물리 라인을 논리 로그 프레임으로 묶는다."""

    def __init__(self, max_chars: int = 8192) -> None:
        self._lines: List[str] = []
        self._char_count = 0
        self._max_chars = max_chars

    def push_line(self, line: str) -> Tuple[List[str], bool]:
        """라인 1개를 입력하고 완성된 프레임 목록과 overflow 여부를 반환."""
        text = (line or "").rstrip("\n")
        if not text:
            return [], False

        ready: List[str] = []
        if self._lines and is_frame_start(text):
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
        """현재 누적 프레임을 반환하고 버퍼를 비운다."""
        if not self._lines:
            return None
        msg = "\n".join(self._lines)
        self._lines = []
        self._char_count = 0
        return msg

    def _append(self, line: str) -> None:
        if self._lines:
            self._char_count += 1  # "\n"
        self._lines.append(line)
        self._char_count += len(line)

