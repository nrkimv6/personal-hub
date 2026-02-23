"""Facebook 크롤링 스케줄러.

Instagram 스케줄러와 동일한 패턴으로 구현.
시간대별로 크롤링 빈도를 조절합니다.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time
from typing import List, Optional

logger = logging.getLogger("facebook.scheduler")


@dataclass
class TimeWindow:
    """시간 구간 정보."""
    start: time      # 시작 시간
    end: time        # 종료 시간
    interval_min: int  # 크롤링 간격 (분)
    label: str = ""    # 구간 레이블


# 기본 시간대별 스케줄
# Facebook은 Instagram보다 간격을 더 길게 설정 (IP 차단 방지)
DEFAULT_SCHEDULE: List[TimeWindow] = [
    TimeWindow(start=time(7, 0),  end=time(9, 0),  interval_min=60, label="오전 출근 시간"),
    TimeWindow(start=time(9, 0),  end=time(12, 0), interval_min=90, label="오전"),
    TimeWindow(start=time(12, 0), end=time(14, 0), interval_min=60, label="점심"),
    TimeWindow(start=time(14, 0), end=time(18, 0), interval_min=90, label="오후"),
    TimeWindow(start=time(18, 0), end=time(21, 0), interval_min=60, label="저녁"),
    TimeWindow(start=time(21, 0), end=time(23, 0), interval_min=90, label="야간"),
]


class FacebookScheduler:
    """Facebook 크롤링 스케줄러.

    시간대별로 크롤링 빈도를 조절합니다.
    Facebook의 IP 차단을 피하기 위해 충분한 간격을 둡니다.
    """

    def __init__(self, schedule: Optional[List[TimeWindow]] = None):
        """
        Args:
            schedule: 시간대별 스케줄. None이면 기본값 사용.
        """
        self.schedule = schedule or DEFAULT_SCHEDULE

    def get_current_window(self, now: Optional[datetime] = None) -> Optional[TimeWindow]:
        """현재 시간대의 TimeWindow를 반환합니다.

        Args:
            now: 현재 시간. None이면 datetime.now() 사용.

        Returns:
            현재 시간대의 TimeWindow 또는 None (스케줄 없음)
        """
        if now is None:
            now = datetime.now()

        current_time = now.time()
        for window in self.schedule:
            if window.start <= current_time < window.end:
                return window

        return None

    def get_interval_minutes(self, now: Optional[datetime] = None) -> int:
        """현재 시간대의 크롤링 간격(분)을 반환합니다.

        Args:
            now: 현재 시간. None이면 datetime.now() 사용.

        Returns:
            크롤링 간격 (분). 스케줄 외 시간이면 -1 반환.
        """
        window = self.get_current_window(now)
        if window:
            return window.interval_min
        return -1  # 크롤링 비활성 시간대

    def should_crawl_now(
        self,
        last_crawled_at: Optional[datetime] = None,
        now: Optional[datetime] = None,
    ) -> bool:
        """현재 크롤링을 실행해야 하는지 판단합니다.

        Args:
            last_crawled_at: 마지막 크롤링 시각. None이면 항상 True.
            now: 현재 시간. None이면 datetime.now() 사용.

        Returns:
            True면 크롤링 실행 필요
        """
        if now is None:
            now = datetime.now()

        interval = self.get_interval_minutes(now)
        if interval < 0:
            logger.debug("크롤링 비활성 시간대")
            return False

        if last_crawled_at is None:
            return True

        elapsed = (now - last_crawled_at).total_seconds() / 60
        should = elapsed >= interval

        if not should:
            logger.debug(
                f"크롤링 대기 중 (경과={elapsed:.0f}분, 간격={interval}분)"
            )

        return should

    def get_today_schedule(self, date: Optional[datetime] = None) -> List[dict]:
        """오늘의 크롤링 스케줄 목록을 반환합니다.

        Returns:
            스케줄 목록 [{"start": "07:00", "end": "09:00", "interval_min": 60, "label": "..."}]
        """
        return [
            {
                "start": w.start.strftime("%H:%M"),
                "end": w.end.strftime("%H:%M"),
                "interval_min": w.interval_min,
                "label": w.label,
            }
            for w in self.schedule
        ]
