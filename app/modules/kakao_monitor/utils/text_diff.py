"""
텍스트 diff 감지 — 새 메시지 판별 + imagehash 최적화.

imagehash.phash로 빠른 화면 변경 감지 후 OCR 실행 여부 결정.
"""
from __future__ import annotations

import logging
from collections import deque

logger = logging.getLogger(__name__)

try:
    import imagehash  # type: ignore
except ImportError:
    imagehash = None  # type: ignore


class TextDiffDetector:
    """화면 변경 감지 + 새 텍스트 라인 추출."""

    def __init__(self, recent_cache_size: int = 30) -> None:
        # OCR 흔들림으로 같은 라인이 반복 신규로 판정되는 현상을 완화한다.
        self._recent_messages: deque[str] = deque(maxlen=recent_cache_size)

    def has_visual_change(
        self,
        prev_image: object,
        curr_image: object,
        threshold: int = 5,
    ) -> bool:
        """두 이미지의 phash 해밍 거리가 threshold 초과이면 변경 있음.

        Args:
            prev_image: PIL.Image (이전 캡처)
            curr_image: PIL.Image (현재 캡처)
            threshold: 해밍 거리 임계값 (기본 5)

        Returns:
            True if visual change detected, False otherwise.
        """
        if prev_image is None or curr_image is None:
            return True  # 비교 불가 시 변경으로 간주

        if imagehash is None:
            logger.debug("imagehash 미설치 — 항상 변경으로 간주")
            return True

        try:
            h1 = imagehash.phash(prev_image)
            h2 = imagehash.phash(curr_image)
            distance = h1 - h2
            logger.debug("phash 해밍 거리: %d (임계값: %d)", distance, threshold)
            return distance > threshold
        except Exception as exc:
            logger.warning("phash 비교 실패: %s", exc)
            return True

    def detect_new_messages(
        self,
        prev_lines: list[str],
        curr_lines: list[str],
    ) -> list[str]:
        """curr_lines에서 prev_lines에 없는 새 라인만 추출.

        단순 set diff 방식: 중복 메시지 필터링 포함.
        순서 보존: curr_lines 순서 기준.

        Args:
            prev_lines: 이전 OCR 텍스트 라인 목록
            curr_lines: 현재 OCR 텍스트 라인 목록

        Returns:
            새로 추가된 라인 목록
        """
        if not curr_lines:
            return []
        normalized_curr = [line.strip() for line in curr_lines if line and line.strip()]
        if not normalized_curr:
            return []
        if not prev_lines:
            return self._filter_recent_duplicates(normalized_curr)

        prev_set = {line.strip() for line in prev_lines if line and line.strip()}
        candidates = [line for line in normalized_curr if line not in prev_set]
        return self._filter_recent_duplicates(candidates)

    def _filter_recent_duplicates(self, lines: list[str]) -> list[str]:
        """짧은 구간의 중복 메시지를 제거한다."""
        if not lines:
            return []
        filtered: list[str] = []
        for line in lines:
            if line in self._recent_messages:
                continue
            self._recent_messages.append(line)
            filtered.append(line)
        return filtered
