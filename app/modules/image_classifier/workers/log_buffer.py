"""
파이프라인 로그 링버퍼 + ETA 계산 유틸

- PipelineLogBuffer: 각 워커의 로그를 메모리에 수집 (최근 50건)
- calc_eta: 처리 속도 기반 남은 시간 추정
"""

from collections import deque
from datetime import datetime


class PipelineLogBuffer:
    """파이프라인 실행 로그를 메모리 링버퍼에 수집"""

    def __init__(self, maxlen: int = 200):
        self._buffer: deque = deque(maxlen=maxlen)

    def add(self, stage: str, message: str):
        """로그 추가"""
        self._buffer.append({
            "stage": stage,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        })

    def get_recent(self, limit: int = 20) -> list[dict]:
        """최근 로그 반환 (최신 먼저)"""
        items = list(self._buffer)
        items.reverse()
        return items[:limit]

    def clear(self):
        """버퍼 초기화"""
        self._buffer.clear()


# 전역 싱글톤
pipeline_logs = PipelineLogBuffer()


def calc_eta(started_at: str, processed: int, total: int) -> dict | None:
    """
    처리 속도 기반 남은 시간 추정

    Returns:
        {elapsed_seconds, items_per_second, eta_seconds, eta_display} or None
    """
    if processed <= 0 or total <= 0:
        return None

    try:
        start_dt = datetime.fromisoformat(started_at)
    except (ValueError, TypeError):
        return None

    elapsed = (datetime.now() - start_dt).total_seconds()
    if elapsed <= 0:
        return None

    speed = processed / elapsed
    remaining = total - processed
    eta_seconds = remaining / speed if speed > 0 else 0

    # 사람이 읽기 좋은 형태
    if eta_seconds < 60:
        eta_display = f"약 {int(eta_seconds)}초"
    elif eta_seconds < 3600:
        minutes = int(eta_seconds // 60)
        seconds = int(eta_seconds % 60)
        eta_display = f"약 {minutes}분 {seconds}초"
    else:
        hours = int(eta_seconds // 3600)
        minutes = int((eta_seconds % 3600) // 60)
        eta_display = f"약 {hours}시간 {minutes}분"

    return {
        "elapsed_seconds": round(elapsed, 1),
        "items_per_second": round(speed, 2),
        "eta_seconds": round(eta_seconds, 1),
        "eta_display": eta_display,
    }
